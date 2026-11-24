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


def _write_variant_with_transport(
    path: Path,
    *,
    variant: str = "BlueCas",
    stop_time: float = 42.0,
    transport: str = "udp",
    bind_address: str = "127.0.0.1:5510",
    peer_address: str = "127.0.0.1:5505",
) -> None:
    """Write a minimal variant archive with an exported Transport SSV."""

    path.parent.mkdir(parents=True, exist_ok=True)
    ssd = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        f'<ssd:SystemStructureDescription xmlns:ssd="{SSD_NS}" version="1.0">'
        f'<ssd:DefaultExperiment startTime="0" stopTime="{stop_time}"/>'
        "</ssd:SystemStructureDescription>"
    )
    ssv = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        f'<ssv:ParameterSet xmlns:ssv="{SSV_NS}" version="1.0" name="{variant}Transport">'
        "<ssv:Parameters>"
        f'<ssv:Parameter name="transport"><ssv:String value="{transport}"/></ssv:Parameter>'
        f'<ssv:Parameter name="bind_address"><ssv:String value="{bind_address}"/></ssv:Parameter>'
        f'<ssv:Parameter name="peer_address"><ssv:String value="{peer_address}"/></ssv:Parameter>'
        "</ssv:Parameters></ssv:ParameterSet>"
    )
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(bundle.SSD_MEMBER, ssd)
        archive.writestr(f"resources/parameter_sets/{variant}Scenario.ssv", "<ssv/>")
        archive.writestr(f"resources/parameter_sets/{variant}Transport.ssv", ssv)
        archive.writestr("resources/opaque.bin", b"\x00\x01opaque-member\x02\x03")


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


def _clear_transport_env(monkeypatch):
    for name in (
        "PYSOS_TRANSPORT",
        "PYSOS_TELEMETRY_PATH",
        "PYSOS_CONTROL_PATH",
        "PYSOS_TELEMETRY_PORT",
    ):
        monkeypatch.delenv(name, raising=False)


def test_env_transport_defaults_to_unix(monkeypatch):
    _clear_transport_env(monkeypatch)
    assert bundle.resolve_env_transport() == ("unix", None, None)


def test_env_telemetry_port_selects_the_udp_manifest_path(monkeypatch):
    _clear_transport_env(monkeypatch)
    monkeypatch.setenv("PYSOS_TELEMETRY_PORT", "5512")
    assert bundle.resolve_env_transport() == ("udp", None, None)


def test_env_transport_wins_over_the_udp_port_hint(monkeypatch):
    monkeypatch.setenv("PYSOS_TRANSPORT", "unix")
    monkeypatch.setenv("PYSOS_TELEMETRY_PORT", "5512")
    monkeypatch.setenv("PYSOS_TELEMETRY_PATH", "/tmp/instance.sock")
    monkeypatch.setenv("PYSOS_CONTROL_PATH", "@recorder")
    assert bundle.resolve_env_transport() == (
        "unix",
        "/tmp/instance.sock",
        "@recorder",
    )


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
        transport="udp",
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
        transport="udp",
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


def test_unix_transport_rewrites_only_the_transport_member(tmp_path):
    variant_dir = tmp_path / "variants"
    variant_ssp = variant_dir / "BlueCas.ssp"
    _write_variant_with_transport(variant_ssp)
    out_dir = tmp_path / "instances"

    summary = bundle.prepare_instance(
        3,
        tmp_path / "unused-source.ssp",
        out_dir,
        variant="BlueCas",
        variant_dir=variant_dir,
        transport="unix",
        bind_address="/tmp/bluecas.sock",
        peer_address="@recorder",
    )

    dest = out_dir / "instance-3" / "BlueCas.ssp"
    member = "resources/parameter_sets/BlueCasTransport.ssv"
    with zipfile.ZipFile(variant_ssp) as source, zipfile.ZipFile(dest) as copied:
        assert copied.namelist() == source.namelist()
        for name in source.namelist():
            if name != member:
                assert copied.read(name) == source.read(name), name
        ssv = copied.read(member).decode("utf-8")
    assert 'name="transport"' in ssv and 'value="unix"' in ssv
    assert 'name="bind_address"' in ssv and 'value="/tmp/bluecas.sock"' in ssv
    assert 'name="peer_address"' in ssv and 'value="@recorder"' in ssv
    assert summary["transport"] == "unix"
    assert summary["rpr_bind_address"] == "/tmp/bluecas.sock"
    assert summary["rpr_peer_address"] == "@recorder"


def test_unix_environment_rewrites_the_transport_ssv(tmp_path, monkeypatch):
    variant_dir = tmp_path / "variants"
    _write_variant_with_transport(variant_dir / "BlueCas.ssp")
    out_dir = tmp_path / "instances"
    monkeypatch.setenv("PYSOS_TRANSPORT", "unix")
    monkeypatch.setenv("PYSOS_TELEMETRY_PATH", "/tmp/instance-1.sock")
    monkeypatch.setenv("PYSOS_CONTROL_PATH", "@recorder")

    assert (
        bundle.main(
            [
                "--instance",
                "1",
                "--variant",
                "BlueCas",
                "--variant-dir",
                str(variant_dir),
                "--out-dir",
                str(out_dir),
            ]
        )
        == 0
    )

    dest = out_dir / "instance-1" / "BlueCas.ssp"
    member = "resources/parameter_sets/BlueCasTransport.ssv"
    with zipfile.ZipFile(dest) as copied:
        ssv = copied.read(member).decode("utf-8")
    assert 'name="transport"' in ssv and 'value="unix"' in ssv
    assert 'name="bind_address"' in ssv and 'value="/tmp/instance-1.sock"' in ssv
    assert 'name="peer_address"' in ssv and 'value="@recorder"' in ssv


def test_explicit_transport_flag_wins_over_the_environment(tmp_path, monkeypatch):
    variant_dir = tmp_path / "variants"
    _write_variant_with_transport(variant_dir / "BlueCas.ssp")
    out_dir = tmp_path / "instances"
    monkeypatch.setenv("PYSOS_TRANSPORT", "unix")
    monkeypatch.setenv("PYSOS_TELEMETRY_PATH", "/tmp/instance-1.sock")
    monkeypatch.setenv("PYSOS_CONTROL_PATH", "@recorder")

    assert (
        bundle.main(
            [
                "--instance",
                "1",
                "--variant",
                "BlueCas",
                "--variant-dir",
                str(variant_dir),
                "--out-dir",
                str(out_dir),
                "--transport",
                "udp",
            ]
        )
        == 0
    )

    dest = out_dir / "instance-1" / "BlueCas.ssp"
    member = "resources/parameter_sets/BlueCasTransport.ssv"
    with zipfile.ZipFile(dest) as copied:
        ssv = copied.read(member).decode("utf-8")
    assert 'name="transport"' in ssv and 'value="udp"' in ssv
    assert 'value="127.0.0.1:5510"' in ssv
    assert 'value="127.0.0.1:5505"' in ssv


def test_explicit_udp_address_override_rewrites_transport(tmp_path):
    variant_dir = tmp_path / "variants"
    variant_ssp = variant_dir / "BlueCas.ssp"
    _write_variant_with_transport(variant_ssp)
    out_dir = tmp_path / "instances"

    bundle.prepare_instance(
        1,
        tmp_path / "unused-source.ssp",
        out_dir,
        variant="BlueCas",
        variant_dir=variant_dir,
        transport="udp",
        bind_address="127.0.0.1:6510",
        peer_address="127.0.0.1:6505",
    )

    dest = out_dir / "instance-1" / "BlueCas.ssp"
    member = "resources/parameter_sets/BlueCasTransport.ssv"
    with zipfile.ZipFile(dest) as copied:
        ssv = copied.read(member).decode("utf-8")
    assert 'name="transport"' in ssv and 'value="udp"' in ssv
    assert 'value="127.0.0.1:6510"' in ssv
    assert 'value="127.0.0.1:6505"' in ssv


def test_explicit_instance_name_names_the_bundle(tmp_path):
    variant_dir = tmp_path / "variants"
    _write_variant_with_transport(variant_dir / "BlueCas.ssp")
    out_dir = tmp_path / "instances"

    summary = bundle.prepare_instance(
        1,
        tmp_path / "unused-source.ssp",
        out_dir,
        variant="BlueCas",
        variant_dir=variant_dir,
        instance_name="instance-fed-instance-1",
    )

    assert (out_dir / "instance-fed-instance-1" / "BlueCas.ssp").is_file()
    assert summary["instance"] == "instance-fed-instance-1"
    # Nothing explicit and no env: the unix default derives the addresses.
    assert summary["transport"] == "unix"
    assert summary["rpr_bind_address"] == "@pysos-BlueCas"
    assert summary["rpr_peer_address"] == "@pysos-recorder"


def test_default_transport_is_unix_and_derives_bind_and_peer(tmp_path):
    variant_dir = tmp_path / "variants"
    variant_ssp = variant_dir / "BlueCas.ssp"
    _write_variant_with_transport(variant_ssp)
    out_dir = tmp_path / "instances"

    summary = bundle.prepare_instance(
        3,
        tmp_path / "unused-source.ssp",
        out_dir,
        variant="BlueCas",
        variant_dir=variant_dir,
    )

    assert summary["transport"] == "unix"
    assert summary["rpr_bind_address"] == "@pysos-BlueCas"
    assert summary["rpr_peer_address"] == "@pysos-recorder"
    dest = out_dir / "instance-3" / "BlueCas.ssp"
    member = "resources/parameter_sets/BlueCasTransport.ssv"
    with zipfile.ZipFile(dest) as copied:
        ssv = copied.read(member).decode("utf-8")
    assert 'name="transport"' in ssv and 'value="unix"' in ssv
    assert 'name="bind_address"' in ssv and 'value="@pysos-BlueCas"' in ssv
    assert 'name="peer_address"' in ssv and 'value="@pysos-recorder"' in ssv


def test_unix_transport_fills_a_missing_peer_with_the_default_recorder(tmp_path):
    variant_dir = tmp_path / "variants"
    _write_variant_with_transport(variant_dir / "BlueCas.ssp")

    summary = bundle.prepare_instance(
        1,
        tmp_path / "unused-source.ssp",
        tmp_path / "instances",
        variant="BlueCas",
        variant_dir=variant_dir,
        transport="unix",
        bind_address="/tmp/bluecas.sock",
    )

    assert summary["rpr_bind_address"] == "/tmp/bluecas.sock"
    assert summary["rpr_peer_address"] == "@pysos-recorder"


def test_unix_scheme_is_rejected_with_the_bare_form(tmp_path):
    variant_dir = tmp_path / "variants"
    _write_variant_with_transport(variant_dir / "BlueCas.ssp")

    with pytest.raises(SystemExit, match="bare address"):
        bundle.prepare_instance(
            1,
            tmp_path / "unused-source.ssp",
            tmp_path / "instances",
            variant="BlueCas",
            variant_dir=variant_dir,
            transport="unix",
            bind_address="unix:///tmp/bluecas.sock",
            peer_address="@recorder",
        )


def test_unix_relative_bind_path_is_rejected(tmp_path):
    variant_dir = tmp_path / "variants"
    _write_variant_with_transport(variant_dir / "BlueCas.ssp")

    with pytest.raises(SystemExit, match="absolute socket path"):
        bundle.prepare_instance(
            1,
            tmp_path / "unused-source.ssp",
            tmp_path / "instances",
            variant="BlueCas",
            variant_dir=variant_dir,
            transport="unix",
            bind_address="bluecas.sock",
            peer_address="@recorder",
        )


def test_legacy_mode_supports_unix_transport(tmp_path, monkeypatch):
    monkeypatch.setattr(bundle, "_scenario_parameter_set", lambda *args, **kwargs: {})
    monkeypatch.setattr(bundle, "_validate_ssd", lambda *args, **kwargs: None)
    source = tmp_path / "scenario.ssp"
    _write_legacy_ssp(source)

    summary = bundle.prepare_instance(
        2,
        source,
        tmp_path / "instances",
        transport="unix",
        bind_address="/tmp/legacy.sock",
        peer_address="@recorder",
    )

    dest = Path(summary["ssp"])
    with zipfile.ZipFile(dest) as archive:
        ssv = archive.read(bundle.SSV_MEMBER).decode("utf-8")
    assert 'name="rpr_entity.transport"' in ssv and 'value="unix"' in ssv
    assert 'name="rpr_entity.bind_address"' in ssv and 'value="/tmp/legacy.sock"' in ssv
    assert 'name="rpr_entity.peer_address"' in ssv and 'value="@recorder"' in ssv
    assert summary["transport"] == "unix"
    assert summary["rpr_bind_address"] == "/tmp/legacy.sock"


def test_legacy_mode_still_reaches_the_rewrite_path(tmp_path, monkeypatch):
    monkeypatch.setattr(bundle, "_scenario_parameter_set", lambda *args, **kwargs: {})
    monkeypatch.setattr(bundle, "_validate_ssd", lambda *args, **kwargs: None)
    source = tmp_path / "scenario.ssp"
    _write_legacy_ssp(source)

    summary = bundle.prepare_instance(
        1, source, tmp_path / "instances", transport="udp"
    )

    dest = Path(summary["ssp"])
    assert dest.is_file()
    with zipfile.ZipFile(dest) as archive:
        ssv = archive.read(bundle.SSV_MEMBER).decode("utf-8")
    assert 'name="initX_km"' in ssv
    assert 'name="rpr_entity.bind_address"' in ssv
    assert 'value="127.0.0.1:5510"' in ssv
    assert _config(dest.parent)["simulation"]["ssp"] == dest.as_posix()


def test_legacy_mode_defaults_to_unix(tmp_path, monkeypatch):
    monkeypatch.setattr(bundle, "_scenario_parameter_set", lambda *args, **kwargs: {})
    monkeypatch.setattr(bundle, "_validate_ssd", lambda *args, **kwargs: None)
    source = tmp_path / "scenario.ssp"
    _write_legacy_ssp(source)

    summary = bundle.prepare_instance(2, source, tmp_path / "instances")

    dest = Path(summary["ssp"])
    with zipfile.ZipFile(dest) as archive:
        ssv = archive.read(bundle.SSV_MEMBER).decode("utf-8")
    assert 'name="rpr_entity.transport"' in ssv and 'value="unix"' in ssv
    assert 'name="rpr_entity.bind_address"' in ssv
    assert 'value="@pysos-instance-2"' in ssv
    assert 'name="rpr_entity.peer_address"' in ssv
    assert 'value="@pysos-recorder"' in ssv
    assert summary["transport"] == "unix"
