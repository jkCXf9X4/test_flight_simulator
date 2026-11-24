"""The runner validates and delegates to pysos_coordinate.Federation."""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import ClassVar

import instance_manifest
import pytest
import run_instance_process
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


def test_schema_two_unix_manifest_dry_run_is_valid(tmp_path, capsys):
    spec = instance_manifest.build_spec(
        instances=2, transport="unix", unix_dir=tmp_path / "sockets"
    )
    manifest = tmp_path / "unix.manifest.json"
    instance_manifest.write_manifest(spec, manifest)

    assert run_instances.main(["--manifest", str(manifest), "--dry-run"]) == 0
    output = capsys.readouterr().out
    assert "ok: manifest is valid; nothing launched" in output
    assert "instance-1.sock" in output


def test_default_flags_run_the_generated_manifest_through_federation(monkeypatch):
    _FakeFederation.instances.clear()
    monkeypatch.setattr(run_instances, "Federation", _FakeFederation)

    assert run_instances.main(["--python", "python3"]) == 0

    assert len(_FakeFederation.instances) == 1
    federation = _FakeFederation.instances[0]
    assert federation.ran
    assert federation.spec.schema == 2
    for index, instance in enumerate(federation.spec.instances, start=1):
        assert instance.telemetry[0].transport == "unix"
        assert instance.telemetry[0].path == f"@pysos-instance-{index}"
        assert instance.telemetry[0].port is None
        assert instance.env["PYSOS_TRANSPORT"] == "unix"


def test_default_launch_flags_are_translated_into_a_unix_spec(monkeypatch):
    _FakeFederation.instances.clear()
    monkeypatch.setattr(run_instances, "Federation", _FakeFederation)

    assert run_instances.main(["--instances", "1", "--stop-time", "10", "--realtime", "--python", "python3"]) == 0
    spec = _FakeFederation.instances[0].spec
    assert [instance.name for instance in spec.instances] == ["instance-1"]
    command = spec.instances[0].command
    assert command[:2] == ["python3", "scripts/run_instance_process.py"]
    assert command[-3:] == ["--stop-time", "10.0", "--realtime"]
    assert spec.instances[0].telemetry[0].path == "@pysos-instance-1"
    assert spec.instances[0].telemetry[0].port is None


def test_explicit_udp_launch_flags_keep_the_udp_spec(monkeypatch):
    _FakeFederation.instances.clear()
    monkeypatch.setattr(run_instances, "Federation", _FakeFederation)

    assert run_instances.main(["--transport", "udp", "--python", "python3"]) == 0
    spec = _FakeFederation.instances[0].spec
    assert spec.schema == 1
    assert [instance.telemetry[0].port for instance in spec.instances] == [5510, 5512]
    assert spec.to_json() == instance_manifest.build_spec(transport="udp").to_json()
    assert spec.to_json() != json.loads(
        instance_manifest.DEFAULT_MANIFEST.read_text(encoding="utf-8")
    )


def test_manifest_stop_time_overrides_every_instance(monkeypatch):
    _FakeFederation.instances.clear()
    monkeypatch.setattr(run_instances, "Federation", _FakeFederation)

    assert (
        run_instances.main(
            [
                "--manifest",
                str(instance_manifest.DEFAULT_MANIFEST),
                "--stop-time",
                "3",
                "--python",
                "python3",
            ]
        )
        == 0
    )

    spec = _FakeFederation.instances[0].spec
    assert spec.instances
    for instance in spec.instances:
        assert instance.command.count("--stop-time") == 1
        assert instance.command[-2:] == ["--stop-time", "3.0"]


def _capture_prepare(monkeypatch):
    captured = {}

    def _prepare(index, source, out_dir, **kwargs):
        captured["index"] = index
        captured.update(kwargs)
        return {"instance": str(index), "config": "/tmp/instance-config.json"}

    monkeypatch.setattr(run_instance_process, "prepare_instance", _prepare)
    monkeypatch.setattr(run_instance_process.os, "execvpe", lambda *args, **kwargs: None)
    return captured


def test_unix_transport_flags_reach_the_bundle_preparer(monkeypatch):
    captured = _capture_prepare(monkeypatch)

    assert (
        run_instance_process.main(
            [
                "--instance",
                "3",
                "--variant",
                "BlueCas",
                "--transport",
                "unix",
                "--bind-address",
                "/tmp/blue.sock",
                "--peer-address",
                "@recorder",
            ]
        )
        == 0
    )

    assert captured["index"] == 3
    assert captured["transport"] == "unix"
    assert captured["bind_address"] == "/tmp/blue.sock"
    assert captured["peer_address"] == "@recorder"
    assert captured["telemetry_port"] is None


def test_unix_mode_without_instance_names_the_bundle_after_the_bind_address(monkeypatch):
    monkeypatch.setenv("PYSOS_TELEMETRY_PORT", "5512")
    captured = _capture_prepare(monkeypatch)

    assert (
        run_instance_process.main(
            [
                "--variant",
                "BlueCas",
                "--transport",
                "unix",
                "--bind-address",
                "/tmp/instance-7.sock",
                "--peer-address",
                "@recorder",
            ]
        )
        == 0
    )

    assert captured["index"] == 1
    assert captured["instance_name"] == "instance-7"
    assert captured["telemetry_port"] is None


def test_unix_without_instance_requires_a_variant(monkeypatch):
    with pytest.raises(SystemExit, match="requires --variant"):
        run_instance_process.main(
            [
                "--transport",
                "unix",
                "--bind-address",
                "/tmp/a.sock",
                "--peer-address",
                "@recorder",
            ]
        )


def test_udp_manifest_port_env_still_selects_udp_and_derives_the_index(monkeypatch):
    _clear_transport_env(monkeypatch)
    monkeypatch.setenv("PYSOS_TELEMETRY_PORT", "5512")
    captured = _capture_prepare(monkeypatch)

    assert run_instance_process.main(["--variant", "BlueCas"]) == 0

    assert captured["index"] == 2
    assert captured["telemetry_port"] == 5512
    assert captured["transport"] == "udp"


def test_explicit_udp_flag_wins_without_a_telemetry_port(monkeypatch):
    _clear_transport_env(monkeypatch)
    captured = _capture_prepare(monkeypatch)

    assert run_instance_process.main(["--instance", "2", "--transport", "udp"]) == 0

    assert captured["transport"] == "udp"
    assert captured["telemetry_port"] is None
    assert captured["bind_address"] is None
    assert captured["peer_address"] is None


def _clear_transport_env(monkeypatch):
    for name in (
        "PYSOS_TRANSPORT",
        "PYSOS_TELEMETRY_PATH",
        "PYSOS_CONTROL_PATH",
        "PYSOS_TELEMETRY_PORT",
    ):
        monkeypatch.delenv(name, raising=False)


def test_default_transport_is_unix_without_any_env(monkeypatch):
    _clear_transport_env(monkeypatch)
    captured = _capture_prepare(monkeypatch)

    assert run_instance_process.main(["--instance", "2"]) == 0

    assert captured["transport"] == "unix"
    assert captured["telemetry_port"] is None
    # prepare_instance derives the deterministic bind/peer defaults.
    assert captured["bind_address"] is None
    assert captured["peer_address"] is None


def test_unix_without_instance_derives_bind_and_peer_from_the_variant(monkeypatch):
    _clear_transport_env(monkeypatch)
    captured = _capture_prepare(monkeypatch)

    assert run_instance_process.main(["--variant", "BlueCas"]) == 0

    assert captured["transport"] == "unix"
    assert captured["bind_address"] == "@pysos-BlueCas"
    assert captured["peer_address"] == "@pysos-recorder"
    assert captured["instance_name"] == "instance-pysos-BlueCas"


def test_unix_environment_reaches_the_bundle_preparer(monkeypatch):
    monkeypatch.setenv("PYSOS_TELEMETRY_PORT", "5512")
    monkeypatch.setenv("PYSOS_TRANSPORT", "unix")
    monkeypatch.setenv("PYSOS_TELEMETRY_PATH", "/tmp/instance-7.sock")
    monkeypatch.setenv("PYSOS_CONTROL_PATH", "@recorder")
    captured = _capture_prepare(monkeypatch)

    assert run_instance_process.main(["--variant", "BlueCas"]) == 0

    assert captured["instance_name"] == "instance-7"
    assert captured["transport"] == "unix"
    assert captured["bind_address"] == "/tmp/instance-7.sock"
    assert captured["peer_address"] == "@recorder"
    assert captured["telemetry_port"] is None


def test_explicit_flags_win_over_the_unix_environment(monkeypatch):
    monkeypatch.setenv("PYSOS_TRANSPORT", "unix")
    monkeypatch.setenv("PYSOS_TELEMETRY_PATH", "/tmp/env.sock")
    monkeypatch.setenv("PYSOS_CONTROL_PATH", "@recorder")
    captured = _capture_prepare(monkeypatch)

    assert (
        run_instance_process.main(
            ["--instance", "3", "--transport", "udp", "--telemetry-port", "5530"]
        )
        == 0
    )

    assert captured["transport"] == "udp"
    assert captured["bind_address"] is None
    assert captured["peer_address"] is None
    assert captured["telemetry_port"] == 5530


@pytest.mark.parametrize("flag", ["--control-port", "--bridge-input"])
def test_bridge_control_flags_are_gone(flag):
    """The JSON bridge is gone, so the launcher no longer accepts its flags."""

    with pytest.raises(SystemExit):
        run_instance_process.parse_args([flag, "1"])


def test_invalid_manifest_returns_one(tmp_path, capsys):
    data = json.loads(instance_manifest.DEFAULT_MANIFEST.read_text(encoding="utf-8"))
    data["schema"] = 99
    bad = tmp_path / "bad.manifest.json"
    bad.write_text(json.dumps(data), encoding="utf-8")

    assert run_instances.main(["--manifest", str(bad), "--dry-run"]) == 1
    assert "invalid:" in capsys.readouterr().err
