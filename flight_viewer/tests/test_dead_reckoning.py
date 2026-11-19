"""Tests for the dead-reckoning behaviour exposed through the shared model."""

import math

import pytest

from flight_viewer.dead_reckoning import dead_reckon, is_stale
from flight_viewer.model import EntityKey, EntityState

KEY = EntityKey(1, 1, 7)
START_S = 10.0
DT_S = 4.5
POSITION = (100.0, -50.0, 25.0)
ORIENTATION_DEG = (5.0, 10.0, 15.0)
ORIENTATION = tuple(math.radians(value) for value in ORIENTATION_DEG)
VELOCITY = (3.0, -4.0, 2.0)


def make_state(**changes):
    fields = {
        "key": KEY,
        "timestamp": START_S,
        "position_enu_m": POSITION,
        "orientation_rps": ORIENTATION,
        "velocity_enu_mps": VELOCITY,
        "angular_velocity_rps": (0.0, 0.0, 0.0),
        "marking": "AC-7",
    }
    fields.update(changes)
    return EntityState(**fields)


@pytest.mark.parametrize("algorithm", [2, 4])
def test_linear_motion_matches_closed_form(algorithm):
    state = make_state()
    out = dead_reckon(state, DT_S, algorithm)

    expected = tuple(p + v * DT_S for p, v in zip(POSITION, VELOCITY))
    assert out.timestamp == pytest.approx(START_S + DT_S)
    assert out.position_enu_m == pytest.approx(expected)
    assert out.velocity_enu_mps == pytest.approx(VELOCITY)
    assert out.orientation_rps == pytest.approx(ORIENTATION)


def test_algorithm_one_is_static():
    state = make_state()
    out = dead_reckon(state, 999.0, 1)

    assert out is not state
    assert out.timestamp == pytest.approx(START_S + 999.0)
    assert out.position_enu_m == pytest.approx(POSITION)
    assert out.orientation_rps == pytest.approx(ORIENTATION)
    assert out.velocity_enu_mps == pytest.approx(VELOCITY)


@pytest.mark.parametrize("algorithm", [0, 3, 5, 7, 8, 42])
def test_unsupported_algorithm_raises(algorithm):
    with pytest.raises(ValueError):
        dead_reckon(make_state(), DT_S, algorithm)


def test_is_stale_uses_strict_threshold():
    assert is_stale(make_state(timestamp=10.0), 15.0, 5.0) is False
    assert is_stale(make_state(timestamp=9.999), 15.0, 5.0) is True


def test_algorithm_four_integrates_orientation_and_position():
    euler_rates = (
        math.radians(10.0),
        math.radians(-5.0),
        math.radians(30.0),
    )
    from pysos_interop.rates import euler_rates_to_body_rates

    state = make_state(
        angular_velocity_rps=euler_rates_to_body_rates(ORIENTATION, euler_rates)
    )

    out = dead_reckon(state, DT_S, 4)

    expected_position = tuple(p + v * DT_S for p, v in zip(POSITION, VELOCITY))
    expected_orientation = tuple(
        angle + rate * DT_S for angle, rate in zip(ORIENTATION, euler_rates)
    )
    assert out.position_enu_m == pytest.approx(expected_position)
    assert out.orientation_rps == pytest.approx(expected_orientation)


def test_zero_angular_velocity_leaves_orientation_alone():
    state = make_state(angular_velocity_rps=(0.0, 0.0, 0.0))

    out = dead_reckon(state, 100.0, 4)

    assert out.orientation_rps == pytest.approx(ORIENTATION)


def test_linear_algorithm_does_not_rotate():
    state = make_state(angular_velocity_rps=(0.0, 0.0, math.pi / 2.0))

    out = dead_reckon(state, 2.0, 2)

    assert out.orientation_rps == pytest.approx(ORIENTATION)


def test_input_state_is_not_mutated():
    state = make_state()
    snapshot = (
        state.timestamp,
        state.position_enu_m,
        state.orientation_rps,
        state.velocity_enu_mps,
        state.angular_velocity_rps,
    )

    for algorithm in (1, 2, 4):
        dead_reckon(state, 999.0, algorithm)

    assert (
        state.timestamp,
        state.position_enu_m,
        state.orientation_rps,
        state.velocity_enu_mps,
        state.angular_velocity_rps,
    ) == snapshot
