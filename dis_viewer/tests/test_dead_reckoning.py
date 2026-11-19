"""Tests for dead reckoning between sparse entity updates."""

import math

import pytest

from dis_viewer.dead_reckoning import extrapolate, mark_stale, predicted_position
from dis_viewer.model import EntityKey, EntityState

KEY = EntityKey(1, 1, 7)
START_S = 10.0
DT_S = 4.5
POSITION = (100.0, -50.0, 25.0)
ORIENTATION = (5.0, 10.0, 15.0)
VELOCITY = (3.0, -4.0, 2.0)


def make_state(**changes):
    fields = {
        "key": KEY,
        "t_s": START_S,
        "position_enu_m": POSITION,
        "orientation_deg": ORIENTATION,
        "velocity_enu_mps": VELOCITY,
    }
    fields.update(changes)
    return EntityState(**fields)


@pytest.mark.parametrize("algorithm", [2, 3, 4, 7, 8])
def test_linear_motion_matches_closed_form(algorithm):
    state = make_state()
    out = extrapolate(state, START_S + DT_S, algorithm)

    expected = tuple(p + v * DT_S for p, v in zip(POSITION, VELOCITY))
    assert out.t_s == pytest.approx(START_S + DT_S)
    assert out.position_enu_m == pytest.approx(expected)
    assert out.velocity_enu_mps == pytest.approx(VELOCITY)
    # Phase 1 has no angular velocity, so orientation is static.
    assert out.orientation_deg == pytest.approx(ORIENTATION)


def test_predicted_position_helper():
    state = make_state()
    expected = tuple(p + v * DT_S for p, v in zip(POSITION, VELOCITY))
    assert predicted_position(state, START_S + DT_S, 2) == pytest.approx(expected)


@pytest.mark.parametrize("algorithm", [1, 2, 3, 4, 7, 8])
def test_zero_velocity_keeps_position(algorithm):
    state = make_state(velocity_enu_mps=(0.0, 0.0, 0.0))
    out = extrapolate(state, START_S + 100.0, algorithm)

    assert out.position_enu_m == pytest.approx(POSITION)
    assert out.orientation_deg == pytest.approx(ORIENTATION)


def test_algorithm_one_is_static():
    state = make_state()
    out = extrapolate(state, 999.0, 1)

    assert out is not state
    assert out.t_s == pytest.approx(999.0)
    assert out.position_enu_m == pytest.approx(POSITION)
    assert out.orientation_deg == pytest.approx(ORIENTATION)
    assert out.velocity_enu_mps == pytest.approx(VELOCITY)


@pytest.mark.parametrize("algorithm", [0, 5, 6, 9, 42])
def test_unknown_algorithm_passes_state_through(algorithm):
    state = make_state()
    out = extrapolate(state, 999.0, algorithm)

    assert out is state
    assert out == state


def test_mark_stale_uses_strict_threshold_and_copies():
    fresh = make_state(key=EntityKey(1, 1, 1), t_s=13.0)
    boundary = make_state(key=EntityKey(1, 1, 2), t_s=10.0)
    old = make_state(key=EntityKey(1, 1, 3), t_s=9.999)
    already_stale = make_state(key=EntityKey(1, 1, 4), t_s=14.0, stale=True)

    result = mark_stale([fresh, boundary, old, already_stale], 15.0, 5.0)

    assert [state.stale for state in result] == [False, False, True, True]
    assert all(copy is not source for copy, source in zip(result, [fresh, boundary, old, already_stale]))
    assert [state.stale for state in (fresh, boundary, old)] == [False, False, False]


@pytest.mark.parametrize("algorithm", [3, 4, 7, 8])
def test_optional_angular_velocity_is_integrated(algorithm):
    state = make_state()
    state.angular_velocity_rps = (0.0, 0.0, math.pi / 2.0)  # optional attribute

    out = extrapolate(state, START_S + 2.0, algorithm)

    assert out.orientation_deg == pytest.approx((5.0, 10.0, 195.0), abs=1e-9)


def test_linear_algorithm_does_not_rotate():
    state = make_state()
    state.angular_velocity_rps = (0.0, 0.0, math.pi / 2.0)

    out = extrapolate(state, START_S + 2.0, 2)

    assert out.orientation_deg == pytest.approx(ORIENTATION)


def test_input_state_is_not_mutated():
    state = make_state()
    snapshot = (
        state.t_s,
        state.position_enu_m,
        state.orientation_deg,
        state.velocity_enu_mps,
        state.stale,
    )

    for algorithm in (1, 2, 3, 4, 7, 8, 42):
        extrapolate(state, 999.0, algorithm)
    mark_stale([state], 999.0, 5.0)

    assert (
        state.t_s,
        state.position_enu_m,
        state.orientation_deg,
        state.velocity_enu_mps,
        state.stale,
    ) == snapshot
