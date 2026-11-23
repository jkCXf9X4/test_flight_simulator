"""End-to-end acceptance for the RPR broadcast -> recorder -> artifacts path.

Skipped when the airplane bundle is missing or a federation/RPR port is already
in use. The live tests are two instances and four instances, a fixed simulated
duration, the real UDP path, and the real Rerun and pyssp_vv consumers. The
per-datagram tests below run without the airplane bundle: they prove the
recorder accepts the ``rpr_entity`` FMU's wire-wrapped ``PhysicalEntity``
frames over UDP and distinguishes entities by their payload identity.
"""

from __future__ import annotations

import csv
import json
import math
import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest
import rpr_e2e
from pyfmi_interop.ir import ModelDefinition
from pyfmi_interop.wire import PayloadFormat
from pyfmi_interop.wire import encode as encode_wire_frame
from pysos_interop import EntityKey, EntityState
from pysos_interop.rpr import RprOrigin, encode_entity_state
from pysos_interop.truth import entity_slug, iter_truth

REPO_ROOT = Path(__file__).resolve().parents[1]
SCENARIO_SSP = REPO_ROOT / "build" / "ssp" / "scenario.ssp"
FEDERATION_PORTS = (*(range(5510, 5518)), rpr_e2e.RPR_UDP_PORT)
SOS_MANIFEST = REPO_ROOT / "manifests" / "aircraft_federation.manifest.json"


def _port_available(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind(("127.0.0.1", port))
        except OSError:
            return False
    return True


def _skip_reason() -> str | None:
    if not SCENARIO_SSP.is_file():
        return f"missing prepared bundle: {SCENARIO_SSP}"
    try:
        import pyfmi_interop  # noqa: F401
        import pysos_rpr  # noqa: F401
        import pyssp_vv  # noqa: F401
        import rerun  # noqa: F401
    except ImportError as exc:  # pragma: no cover - environment-specific
        return f"missing optional dependency: {exc}"
    busy = [port for port in FEDERATION_PORTS if not _port_available(port)]
    if busy:
        return f"ports already in use: {busy}"
    return None


SKIP_REASON = _skip_reason()


@pytest.mark.skipif(SKIP_REASON is not None, reason=SKIP_REASON or "")
def _label_texts(rrd_path):
    """Read the logged label text per entity from an ``.rrd`` recording."""

    from rerun.chunk import RrdReader

    texts = {}
    for chunk in RrdReader(str(rrd_path)).store().stream():
        if not chunk.entity_path.endswith("/label"):
            continue
        batch = chunk.to_record_batch()
        if "TextDocument:text" not in batch.schema.names:
            continue
        slug = chunk.entity_path.lstrip("/").split("/")[2]
        values = batch.column("TextDocument:text").to_pylist()
        texts[slug] = values[0][0] if values else None
    return texts


@pytest.mark.skipif(SKIP_REASON is not None, reason=SKIP_REASON or "")
def test_e2e_rpr_acceptance(tmp_path):
    result = rpr_e2e.run_e2e(run_dir=tmp_path / "run", stop_time=6.0)

    assert result.exit_codes == {"instance-1": 0, "instance-2": 0}
    assert not result.timed_out

    for path in (
        result.truth_jsonl,
        result.metadata_json,
        result.measure_csv,
        result.rrd_path,
        result.comparison_csv,
        result.separation_csv,
        result.run_json,
        result.run_dir / "logs" / "instance-1.stdout.log",
        result.run_dir / "logs" / "instance-2.stdout.log",
    ):
        assert path.is_file(), path
        assert path.stat().st_size > 0, path
    assert result.rrd_path.stat().st_size > 1024

    metadata = json.loads(result.metadata_json.read_text(encoding="utf-8"))
    assert metadata["format_version"] == "1"
    assert {entity["entity"] for entity in metadata["entities"]} == {"1_1_1", "1_1_2"}
    assert metadata["sample_count"] == result.samples

    with result.measure_csv.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    assert len(rows) >= 50
    assert "1_1_1.position_east_m" in rows[0]
    assert "1_1_2.position_east_m" in rows[0]

    first, last = rpr_e2e.truth_time_span(result.truth_jsonl)
    assert last - first >= 5.0
    assert result.instance_sim_durations
    assert min(result.instance_sim_durations.values()) >= 5.0

    separation = result.separation_m
    print(
        "measured separation: "
        f"{separation['min_m']:.1f} .. {separation['max_m']:.1f} m "
        f"(mean {separation['mean_m']:.1f} m over {separation['samples']} samples; "
        f"startup t=0 sample {separation['startup_m']} m)"
    )
    assert 4500.0 <= separation["mean_m"] <= 5500.0
    assert 4900.0 <= separation["min_m"] <= 5100.0
    assert 4900.0 <= separation["max_m"] <= 5100.0
    assert separation["samples"] >= 50
    with result.separation_csv.open(newline="", encoding="utf-8") as handle:
        separation_rows = list(csv.DictReader(handle))
    assert len(separation_rows) >= 50
    assert {"time", "min_separation_m", "nearest_a", "nearest_b"} == set(separation_rows[0])

    # The Rerun load check is the viewer-side exit code for the recording.
    verify = subprocess.run(
        [sys.executable, "-m", "rerun", "rrd", "verify", str(result.rrd_path)],
        check=False,
        capture_output=True,
        text=True,
        timeout=120,
    )
    print(f"rerun rrd verify exit code: {verify.returncode}")
    assert verify.returncode == 0, verify.stderr

    comparison = result.comparison
    self_east = comparison["self"]["1_1_1"]["signals"]["position_east_m"]
    cross = next(
        item
        for item in comparison["cross"]
        if (item["reference"], item["candidate"]) == ("1_1_1", "1_1_2")
    )
    cross_east = cross["signals"]["position_east_m"]
    print(
        "pyssp_vv compare: self max_abs_error="
        f"{self_east['max_abs_error']:.3f} m, entity 1 vs 2 east max_abs_error="
        f"{cross_east['max_abs_error']:.1f} m"
    )
    assert self_east["coverage"] == 1.0
    assert self_east["max_abs_error"] == pytest.approx(0.0, abs=1e-9)
    assert 4500.0 <= cross_east["max_abs_error"] <= 5500.0


@pytest.mark.skipif(SKIP_REASON is not None, reason=SKIP_REASON or "")
def test_four_aircraft_federation_runs_distinct_scenarios(tmp_path):
    result = rpr_e2e.run_e2e(
        run_dir=tmp_path / "sos4",
        stop_time=3.0,
        manifest_path=SOS_MANIFEST,
    )

    assert result.exit_codes == {
        "red_interceptor": 0,
        "red_striker": 0,
        "blue_cas": 0,
        "blue_baseline": 0,
    }
    assert not result.timed_out
    slugs = {"1_1_1", "1_1_2", "1_1_3", "1_1_4"}

    metadata = json.loads(result.metadata_json.read_text(encoding="utf-8"))
    assert {entity["entity"] for entity in metadata["entities"]} == slugs
    assert {entity["marking"] for entity in metadata["entities"]} == {
        "RED-1",
        "RED-2",
        "BLUE-1",
        "BLUE-2",
    }
    assert metadata["sample_count"] == result.samples

    labels = _label_texts(result.rrd_path)
    assert set(labels) == slugs
    assert labels == {
        slug: item["label"] for slug, item in result.entities.items()
    }
    assert labels["1_1_1"] == "RED-1 · high_altitude_intercept"
    assert labels["1_1_2"] == "RED-2 · deep_strike_penetration"
    assert labels["1_1_3"] == "BLUE-1 · cas_multi_store_support"
    assert labels["1_1_4"] == "BLUE-2 · test_scenario"
    assert len(set(labels.values())) == 4

    finite_pairs = {
        key: stats
        for key, stats in result.pairs.items()
        if math.isfinite(stats["min_m"]) and math.isfinite(stats["max_m"])
    }
    assert len(finite_pairs) >= 2
    assert len(finite_pairs) == 6

    summary = json.loads(result.run_json.read_text(encoding="utf-8"))
    transport = summary["transport"]
    assert transport["recorder"]["error"] is None
    assert transport["recorder"]["decode_errors"] == 0
    assert transport["recorder"]["datagrams"] >= sum(
        transport["recorder"]["frames"].values()
    )
    assert set(transport["recorder"]["frames"]) == slugs
    assert {"InDatagrams", "RcvbufErrors"} <= set(transport["kernel_udp"])
    assert set(summary["ports"]["instance_bind"]) == {
        "red_interceptor",
        "red_striker",
        "blue_cas",
        "blue_baseline",
    }
    assert summary["ports"]["rpr"] == rpr_e2e.RPR_UDP_PORT

    lengths = [item["path_length_m"] for item in result.entities.values()]
    assert all(length > 100.0 for length in lengths)
    assert len({round(length, 3) for length in lengths}) == 4


ORIGIN = RprOrigin(latitude_deg=0.0, longitude_deg=0.0, altitude_m=0.0)
ADAPTER_MODEL = ModelDefinition(
    name="rpr_entity",
    guid="0123456789abcdef0123456789abcdef",
    step_size_s=0.1,
)


def _state(entity: int, *, east_m: float = 0.0, marking: str = "") -> EntityState:
    """One entity state to encode as the FMU would broadcast it."""

    return EntityState(
        key=EntityKey(1, 1, entity),
        timestamp=0.0,
        position_enu_m=(east_m, 0.0, 1000.0),
        velocity_enu_mps=(0.0, 0.0, 0.0),
        orientation_rps=(0.0, 0.0, 0.0),
        angular_velocity_rps=(0.0, 0.0, 0.0),
        marking=marking or f"AC-{entity}",
    )


def _fmu_frame(
    state: EntityState,
    *,
    instance: int = 1,
    sequence: int = 0,
    payload_format: PayloadFormat = PayloadFormat.PROTOBUF,
) -> bytes:
    """Encode one ``rpr_entity`` FMU datagram: v2 envelope + PhysicalEntity."""

    return encode_wire_frame(
        ADAPTER_MODEL,
        encode_entity_state(state, origin=ORIGIN),
        instance=instance,
        sequence=sequence,
        timestamp_ns=0,
        payload_format=payload_format,
    )


def test_decode_rpr_datagram_unwraps_fmu_wire_envelope():
    frame = _fmu_frame(_state(3, east_m=12.5, marking="RED-1"))

    decoded = rpr_e2e.decode_rpr_datagram(frame, origin=ORIGIN)

    assert decoded.state.key == EntityKey(1, 1, 3)
    assert decoded.state.marking == "RED-1"
    assert decoded.state.position_enu_m == pytest.approx((12.5, 0.0, 1000.0))


def test_decode_rpr_datagram_rejects_non_protobuf_payload():
    frame = _fmu_frame(_state(1), payload_format=PayloadFormat.OPAQUE)

    with pytest.raises(ValueError, match="not protobuf"):
        rpr_e2e.decode_rpr_datagram(frame, origin=ORIGIN)


def test_recorder_reads_wire_frames_from_two_broadcasters(tmp_path):
    """Two entities, one socket: payload identity separates them."""

    truth_path = tmp_path / "truth.jsonl"
    expected = {
        entity_slug(key): key for key in (EntityKey(1, 1, 1), EntityKey(1, 1, 2))
    }
    recorder = rpr_e2e.RprTruthRecorder(
        host="127.0.0.1",
        port=0,
        origin=ORIGIN,
        expected_keys=expected,
        truth_path=truth_path,
        run_id="wire-test",
        sample_period_s=0.02,
        watchdog_s=0.05,
    )
    sender = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        recorder.start()
        assert recorder.ready.wait(timeout=3.0)
        assert recorder.error is None
        assert recorder.bound_port is not None
        for sequence in range(3):
            sender.sendto(
                _fmu_frame(_state(1, east_m=sequence), instance=1, sequence=sequence),
                ("127.0.0.1", recorder.bound_port),
            )
            sender.sendto(
                _fmu_frame(_state(2, east_m=sequence), instance=2, sequence=sequence),
                ("127.0.0.1", recorder.bound_port),
            )
        time.sleep(0.1)
    finally:
        recorder.stop_event.set()
        recorder.join(timeout=5.0)
        sender.close()

    assert recorder.error is None, recorder.error_traceback
    assert recorder.datagrams == 6
    assert recorder.decode_errors == 0
    assert dict(recorder.frames) == {"1_1_1": 3, "1_1_2": 3}
    assert recorder.samples == 3

    states = list(iter_truth(truth_path))
    assert len(states) == 6
    assert {(state.key.site, state.key.application, state.key.entity) for state in states} == {
        (1, 1, 1),
        (1, 1, 2),
    }
    assert {state.timestamp for state in states} == {0.0, 0.02, 0.04}
    assert {state.marking for state in states} == {"AC-1", "AC-2"}

    metadata = json.loads(truth_path.with_suffix(".meta.json").read_text(encoding="utf-8"))
    assert metadata["sample_count"] == recorder.samples
    assert {entity["entity"] for entity in metadata["entities"]} == set(expected)


def test_drain_burst_returns_every_queued_datagram():
    """The receive path empties the kernel queue before doing per-packet work.

    Regression for the batch-mode overflow: the consumers used to parse and
    protobuf-encode/decode one datagram between receives, so a fast simulator
    burst could fill the default 208 KiB receive buffer and the kernel dropped
    packets. ``_drain_burst`` must return the datagram that blocked plus every
    datagram already queued behind it, in order.
    """

    receiver = rpr_e2e._open_receiver("127.0.0.1", 0)
    sender = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        port = receiver.getsockname()[1]
        payloads = [f"telemetry-{index:04d}".encode() for index in range(64)]
        for payload in payloads:
            sender.sendto(payload, ("127.0.0.1", port))
        first, _ = receiver.recvfrom(65535)
        burst = rpr_e2e._drain_burst(receiver, first)
    finally:
        sender.close()
        receiver.close()

    assert burst == payloads
