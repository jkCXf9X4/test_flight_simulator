"""Offline unit tests for the per-variant aircraft SSP export CLI."""

from __future__ import annotations

import zipfile
from pathlib import Path

import export_aircraft_variants as exporter
import pyssp_sysml
import pytest


def _write_ssp(
    path: Path,
    *,
    ssd: bool = True,
    parameter_sets: tuple[str, ...] = ("variant.ssv",),
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w") as zf:
        if ssd:
            zf.writestr(exporter.SSD_ENTRY, "<ssd/>")
        for name in parameter_sets:
            zf.writestr(f"{exporter.PARAMETER_SET_PREFIX}{name}", "<ssv/>")


def _fake_generate(
    calls: list[dict],
    *,
    fail: str | None = None,
    write=_write_ssp,
):
    def generate_ssp(architecture_path, output_path, composition, **kwargs):
        calls.append(
            {
                "architecture_path": architecture_path,
                "output_path": output_path,
                "composition": composition,
                **kwargs,
            }
        )
        if composition == fail:
            raise RuntimeError(f"cannot export {composition}")
        write(output_path)
        return output_path

    return generate_ssp


def _exported_lines(text: str) -> list[str]:
    return [line for line in text.splitlines() if line.startswith("exported ")]


def test_default_variant_order(monkeypatch, tmp_path, capsys):
    calls: list[dict] = []
    monkeypatch.setattr(pyssp_sysml, "generate_ssp", _fake_generate(calls))

    rc = exporter.main(["--output-dir", str(tmp_path), "--fmu-root", str(tmp_path)])

    assert rc == 0
    assert [call["composition"] for call in calls] == list(exporter.DEFAULT_VARIANTS)
    assert exporter.DEFAULT_VARIANTS == (
        "RedInterceptor",
        "RedStriker",
        "BlueCas",
        "BlueBaseline",
    )
    assert len(_exported_lines(capsys.readouterr().out)) == len(exporter.DEFAULT_VARIANTS)


def test_variant_flags_override_the_default_list(monkeypatch, tmp_path):
    calls: list[dict] = []
    monkeypatch.setattr(pyssp_sysml, "generate_ssp", _fake_generate(calls))

    rc = exporter.main(
        [
            "--variant",
            "BlueCas",
            "--variant",
            "RedStriker",
            "--output-dir",
            str(tmp_path),
            "--fmu-root",
            str(tmp_path),
        ]
    )

    assert rc == 0
    assert [call["composition"] for call in calls] == ["BlueCas", "RedStriker"]


def test_output_path_and_generate_arguments(monkeypatch, tmp_path):
    calls: list[dict] = []
    monkeypatch.setattr(pyssp_sysml, "generate_ssp", _fake_generate(calls))
    output_dir = tmp_path / "variants"
    fmu_root = tmp_path / "fmus"

    rc = exporter.main(
        [
            "--variant",
            "RedInterceptor",
            "--output-dir",
            str(output_dir),
            "--fmu-root",
            str(fmu_root),
        ]
    )

    assert rc == 0
    call = calls[0]
    assert call["architecture_path"] == exporter.PARTICIPANTS_MODEL
    assert call["output_path"] == output_dir / "RedInterceptor.ssp"
    assert call["includes"] == exporter.resolve_includes()
    assert call["fmu_root"] == fmu_root
    assert call["validate_fmus"] is True
    assert call["allow_missing_fmus"] is False
    assert call["base_index"] == exporter.PARAMETER_BASE_INDEX


def test_fmu_flags_are_forwarded(monkeypatch, tmp_path):
    calls: list[dict] = []
    monkeypatch.setattr(pyssp_sysml, "generate_ssp", _fake_generate(calls))

    rc = exporter.main(
        [
            "--variant",
            "BlueBaseline",
            "--output-dir",
            str(tmp_path),
            "--fmu-root",
            str(tmp_path),
            "--allow-missing-fmus",
            "--no-validate-fmus",
        ]
    )

    assert rc == 0
    assert calls[0]["validate_fmus"] is False
    assert calls[0]["allow_missing_fmus"] is True


def test_failed_generate_returns_nonzero(monkeypatch, tmp_path, capsys):
    calls: list[dict] = []
    monkeypatch.setattr(
        pyssp_sysml,
        "generate_ssp",
        _fake_generate(calls, fail="BlueCas"),
    )

    rc = exporter.main(
        [
            "--variant",
            "RedInterceptor",
            "--variant",
            "BlueCas",
            "--output-dir",
            str(tmp_path),
            "--fmu-root",
            str(tmp_path),
        ]
    )

    captured = capsys.readouterr()
    assert rc == 1
    assert [call["composition"] for call in calls] == ["RedInterceptor", "BlueCas"]
    assert len(_exported_lines(captured.out)) == 1
    assert "export failed for BlueCas" in captured.err


@pytest.mark.parametrize(
    ("ssd", "parameter_sets", "expected"),
    [
        (False, ("variant.ssv",), "missing SystemStructure.ssd"),
        (True, (), "no resources/parameter_sets/*.ssv parameter sets"),
    ],
)
def test_incomplete_archive_is_rejected(
    monkeypatch, tmp_path, capsys, ssd, parameter_sets, expected
):
    calls: list[dict] = []
    monkeypatch.setattr(
        pyssp_sysml,
        "generate_ssp",
        _fake_generate(
            calls,
            write=lambda path: _write_ssp(
                path, ssd=ssd, parameter_sets=parameter_sets
            ),
        ),
    )

    rc = exporter.main(
        [
            "--variant",
            "RedInterceptor",
            "--output-dir",
            str(tmp_path),
            "--fmu-root",
            str(tmp_path),
        ]
    )

    captured = capsys.readouterr()
    assert rc == 1
    assert _exported_lines(captured.out) == []
    assert expected in captured.err


def test_stage_fmu_root_resolves_both_source_shapes(tmp_path):
    airplane = tmp_path / "airplane"
    fmu_dir = airplane / "build" / "fmus"
    fmu_dir.mkdir(parents=True)
    (fmu_dir / "Environment.fmu").write_bytes(b"env")
    (fmu_dir / "RprEntity.fmu").write_bytes(b"rpr")
    stage_dir = tmp_path / "stage"

    root = exporter.stage_fmu_root(airplane, stage_dir)

    assert root == stage_dir
    assert (root / "build" / "fmus" / "Environment.fmu").read_bytes() == b"env"
    assert (root / "RprEntity.fmu").read_bytes() == b"rpr"
    assert (root / "Environment.fmu").read_bytes() == b"env"


def test_help_exits_cleanly(capsys):
    with pytest.raises(SystemExit) as excinfo:
        exporter.main(["--help"])

    assert excinfo.value.code == 0
    assert "usage:" in capsys.readouterr().out
