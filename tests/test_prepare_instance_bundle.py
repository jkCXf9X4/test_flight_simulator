"""Offline tests for preparing per-instance bundles from variant SSPs."""

from __future__ import annotations

import json
import zipfile
from pathlib import Path

import prepare_instance_bundle as bundle
import pytest

SSD_NS = "http://ssp-standard.org/SSP1/SystemStructureDescription"
SSV_NS = "http://ssp-standard.org/SSP1/SystemStructureParameterValues"
SSM_NS = "http://ssp-standard.org/SSP1/SystemStructureParameterMapping"


def _write_variant_ssp(path: Path, *, stop_time: float = 42.0) -> None:
    """Write a self-contained variant archive with an inline parameter set."""

    path.parent.mkdir(parents=True, exist_ok=True)
    ssd = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        f'<ssd:SystemStructureDescription xmlns:ssd="{SSD_NS}" version="1.0">'
        f'<ssd:DefaultExperiment startTime="0" stopTime="{stop_time}"/>'
        "</ssd:SystemStructureDescription>"
    )
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(bundle.SSD_MEMBER, ssd)
        archive.writestr("resources/parameter_sets/Scenario.ssv", "<ssv/>")


def _write_legacy_ssp(path: Path, *, stop_time: float = 30.0) -> None:
    """Write the minimal members the legacy rewrite path expects."""

    path.parent.mkdir(parents=True, exist_ok=True)
    ssv = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        f'<ssv:ParameterSet xmlns:ssv="{SSV_NS}" version="1.0" name="params">'
        "<ssv:Parameters>"
        '<ssv:Parameter name="initX_km"><ssv:Real value="1.0"/></ssv:Parameter>'
        '<ssv:Parameter name="initY_km"><ssv:Real value="2.0"/></ssv:Parameter>'
        "</ssv:Parameters></ssv:ParameterSet>"
    )
    ssm = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        f'<ssm:ParameterMapping xmlns:ssm="{SSM_NS}" version="1.0">'
        '<ssm:MappingEntry source="initX_km" target="environment.initX_km"/>'
        "</ssm:ParameterMapping>"
    )
    ssd = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        f'<ssd:SystemStructureDescription xmlns:ssd="{SSD_NS}" version="1.0">'
        f'<ssd:DefaultExperiment startTime="0" stopTime="{stop_time}"/>'
        "</ssd:SystemStructureDescription>"
    )
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(bundle.SSV_MEMBER, ssv)
        archive.writestr(bundle.SSM_MEMBER, ssm)
        archive.writestr(bundle.SSD_MEMBER, ssd)


def _config(instance_dir: Path) -> dict:
    return json.loads((instance_dir / "config.json").read_text(encoding="utf-8"))


def test_variant_mode_copies_archive_and_points_config_at_it(tmp_path):
    variant_dir = tmp_path / "variants"
    variant_ssp = variant_dir / "BlueCas.ssp"
    _write_variant_ssp(variant_ssp)
    out_dir = tmp_path / "instances"

    summary = bundle.prepare_instance(
        1,
        tmp_path / "unused-source.ssp",
        out_dir,
        variant="BlueCas",
        variant_dir=variant_dir,
    )

    instance_dir = out_dir / "instance-1"
    copied = instance_dir / "BlueCas.ssp"
    assert copied.read_bytes() == variant_ssp.read_bytes()
    assert _config(instance_dir)["simulation"]["ssp"] == copied.resolve().as_posix()
    assert summary["variant"] == "BlueCas"
    assert summary["ssp"] == str(copied)
    assert summary["stop_time"] == "42.0"
    assert "scenario" not in summary
    assert "init_x_km" not in summary
    assert "init_y_km" not in summary


def test_variant_mode_explicit_stop_time_reaches_the_config(tmp_path):
    variant_dir = tmp_path / "variants"
    _write_variant_ssp(variant_dir / "RedStriker.ssp")
    out_dir = tmp_path / "instances"

    summary = bundle.prepare_instance(
        2,
        tmp_path / "unused-source.ssp",
        out_dir,
        variant="RedStriker",
        variant_dir=variant_dir,
        stop_time=7.5,
    )

    assert _config(out_dir / "instance-2")["simulation"]["stop_time"] == 7.5
    assert summary["stop_time"] == "7.5"


def test_missing_variant_archive_raises_a_clear_error(tmp_path):
    with pytest.raises(SystemExit, match="Variant SSP not found"):
        bundle.prepare_instance(
            1,
            tmp_path / "unused-source.ssp",
            tmp_path / "instances",
            variant="Ghost",
            variant_dir=tmp_path / "variants",
        )


def test_legacy_mode_still_reaches_the_rewrite_path(tmp_path, monkeypatch):
    monkeypatch.setattr(bundle, "_scenario_parameter_set", lambda *args, **kwargs: {})
    monkeypatch.setattr(bundle, "_validate_ssd", lambda *args, **kwargs: None)
    source = tmp_path / "scenario.ssp"
    _write_legacy_ssp(source)

    summary = bundle.prepare_instance(1, source, tmp_path / "instances")

    dest = Path(summary["ssp"])
    assert dest.is_file()
    with zipfile.ZipFile(dest) as archive:
        ssv = archive.read(bundle.SSV_MEMBER).decode("utf-8")
    assert 'name="initX_km"' in ssv
    assert 'name="rpr_entity.bind_address"' in ssv
    assert 'value="127.0.0.1:5510"' in ssv
    assert _config(dest.parent)["simulation"]["ssp"] == dest.as_posix()
