"""End-to-end acceptance for the telemetry -> RPR -> recorder -> artifacts path.

Skipped when the airplane bundle is missing or a federation/RPR port is already
in use. The test is otherwise a live run: two instances, a fixed simulated
duration, the real UDP path, and the real Rerun and pyssp_vv consumers.
"""

from __future__ import annotations

import csv
import json
import socket
import subprocess
import sys
from pathlib import Path

import pytest
import rpr_e2e

REPO_ROOT = Path(__file__).resolve().parents[1]
SCENARIO_SSP = REPO_ROOT / "build" / "ssp" / "scenario.ssp"
FEDERATION_PORTS = (5501, 5502, 5503, 5504, rpr_e2e.RPR_UDP_PORT)


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
    self_east = comparison["self"]["signals"]["position_east_m"]
    cross_east = comparison["cross"]["signals"]["position_east_m"]
    print(
        "pyssp_vv compare: self max_abs_error="
        f"{self_east['max_abs_error']:.3f} m, entity 1 vs 2 east max_abs_error="
        f"{cross_east['max_abs_error']:.1f} m"
    )
    assert self_east["coverage"] == 1.0
    assert self_east["max_abs_error"] == pytest.approx(0.0, abs=1e-9)
    assert 4500.0 <= cross_east["max_abs_error"] <= 5500.0
