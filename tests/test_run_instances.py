"""The runner validates and delegates to pysos_coordinate.Federation."""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import ClassVar

import instance_manifest
import run_instances


class _FakeFederation:
    instances: ClassVar[list[_FakeFederation]] = []

    def __init__(self, spec, *, log_dir=None):
        self.spec = spec
        self.log_dir = log_dir
        self.ran = False
        _FakeFederation.instances.append(self)

    def run(self):
        self.ran = True
        codes = {instance.name: 0 for instance in self.spec.instances}
        return SimpleNamespace(
            ok=True,
            timed_out=False,
            exit_codes=codes,
            duration_s=0.0,
            statuses=(),
            log_dir=self.log_dir,
        )



def test_dry_run_validates_without_spawning(monkeypatch, capsys):

    def _no_federation(*args, **kwargs):
        raise AssertionError("dry-run must not construct a supervisor")

    monkeypatch.setattr(run_instances, "Federation", _no_federation)
    assert run_instances.main(["--dry-run"]) == 0
    output = capsys.readouterr().out
    assert "ok: manifest is valid; nothing launched" in output
    assert "federation: high_altitude_intercept" in output


def test_checked_in_manifest_dry_run_is_valid(capsys):
    assert run_instances.main(["--manifest", str(instance_manifest.DEFAULT_MANIFEST), "--dry-run"]) == 0
    assert "federation: high_altitude_intercept (2 instance(s)" in capsys.readouterr().out


def test_default_flags_run_the_generated_manifest_through_federation(monkeypatch):
    _FakeFederation.instances.clear()
    monkeypatch.setattr(run_instances, "Federation", _FakeFederation)

    assert run_instances.main(["--python", "python3"]) == 0

    assert len(_FakeFederation.instances) == 1
    federation = _FakeFederation.instances[0]
    assert federation.ran
    assert federation.spec.to_json() == json.loads(
        instance_manifest.DEFAULT_MANIFEST.read_text(encoding="utf-8")
    )


def test_launch_flags_are_translated_into_the_spec(monkeypatch):
    _FakeFederation.instances.clear()
    monkeypatch.setattr(run_instances, "Federation", _FakeFederation)

    assert run_instances.main(["--instances", "1", "--stop-time", "10", "--realtime", "--python", "python3"]) == 0
    spec = _FakeFederation.instances[0].spec
    assert [instance.name for instance in spec.instances] == ["instance-1"]
    command = spec.instances[0].command
    assert command[:2] == ["python3", "scripts/run_instance_process.py"]
    assert command[-3:] == ["--stop-time", "10.0", "--realtime"]
    assert spec.instances[0].telemetry[0].port == 5501


def test_invalid_manifest_returns_one(tmp_path, capsys):
    data = json.loads(instance_manifest.DEFAULT_MANIFEST.read_text(encoding="utf-8"))
    data["schema"] = 2
    bad = tmp_path / "bad.manifest.json"
    bad.write_text(json.dumps(data), encoding="utf-8")

    assert run_instances.main(["--manifest", str(bad), "--dry-run"]) == 1
    assert "invalid:" in capsys.readouterr().err
