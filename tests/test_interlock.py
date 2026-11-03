# SPDX-License-Identifier: Apache-2.0
"""Tests for the laser interlock. This module is safety-critical: every rule
has a direct test, and property tests check that OK never appears unless
every rule holds."""

import dataclasses
import itertools
import math

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from dragonfly.control.interlock import Interlock, InterlockConfig, InterlockInputs, Reason
from dragonfly.track.tracker import SystemState

CFG = InterlockConfig()

GOOD = InterlockInputs(
    arm_switch=True,
    fault=False,
    watchdog_ok=True,
    telemetry_age_s=0.05,
    state=SystemState.LOCKED,
    coast_time_s=0.0,
    target_range_m=3.0,
    pan_deg=10.0,
    aim_height_m=1.0,
    beam_height_at_target_m=1.0,
)


def armed() -> Interlock:
    il = Interlock()
    il.evaluate(dataclasses.replace(GOOD, arm_switch=False))
    assert il.evaluate(GOOD) is Reason.OK
    return il


def with_(**kw):
    return dataclasses.replace(GOOD, **kw)


def test_starts_disarmed_even_with_switch_on():
    il = Interlock()
    assert il.evaluate(GOOD) is Reason.REARM_REQUIRED
    assert il.evaluate(GOOD) is Reason.REARM_REQUIRED


def test_off_then_on_arms():
    armed()


def test_switch_off_turns_laser_off():
    il = armed()
    assert il.evaluate(with_(arm_switch=False)) is Reason.NOT_ARMED


@pytest.mark.parametrize(
    "kw,reason",
    [
        ({"state": SystemState.SEARCH}, Reason.NOT_LOCKED),
        ({"state": SystemState.TENTATIVE}, Reason.NOT_LOCKED),
        ({"state": SystemState.HOLD}, Reason.NOT_LOCKED),
        ({"state": SystemState.COAST, "coast_time_s": 0.51}, Reason.COAST_TOO_LONG),
        ({"target_range_m": 0.49}, Reason.RANGE),
        ({"target_range_m": 6.01}, Reason.RANGE),
        ({"pan_deg": 60.1}, Reason.PAN_LIMIT),
        ({"pan_deg": -60.1}, Reason.PAN_LIMIT),
        ({"aim_height_m": 1.21}, Reason.HEIGHT_CAP),
        ({"beam_height_at_target_m": 1.21}, Reason.HEIGHT_CAP),
    ],
)
def test_each_condition_turns_laser_off(kw, reason):
    il = armed()
    assert il.evaluate(with_(**kw)) is reason
    # These are not faults: the laser comes back when the condition clears.
    assert il.evaluate(GOOD) is Reason.OK


def test_short_coast_allowed():
    il = armed()
    assert il.evaluate(with_(state=SystemState.COAST, coast_time_s=0.5)) is Reason.OK


@pytest.mark.parametrize(
    "kw",
    [{"fault": True}, {"watchdog_ok": False}, {"telemetry_age_s": 0.51}],
)
def test_faults_latch_until_rearmed(kw):
    il = armed()
    assert il.evaluate(with_(**kw)) is Reason.FAULT_LATCHED
    # Fault clears, but the laser stays off until the operator re-arms.
    assert il.evaluate(GOOD) is Reason.FAULT_LATCHED
    assert il.evaluate(with_(arm_switch=False)) is Reason.NOT_ARMED
    assert il.evaluate(GOOD) is Reason.OK


def test_fault_present_when_rearming_latches_again():
    il = armed()
    il.evaluate(with_(fault=True))
    il.evaluate(with_(arm_switch=False, fault=True))
    assert il.evaluate(with_(fault=True)) is Reason.FAULT_LATCHED
    assert il.evaluate(GOOD) is Reason.FAULT_LATCHED


@pytest.mark.parametrize(
    "field",
    [
        "telemetry_age_s",
        "coast_time_s",
        "target_range_m",
        "pan_deg",
        "aim_height_m",
        "beam_height_at_target_m",
    ],
)
@pytest.mark.parametrize("value", [math.nan, math.inf, -math.inf])
def test_non_finite_input_is_off_and_latches(field, value):
    il = armed()
    assert il.evaluate(with_(**{field: value})) is Reason.BAD_INPUT
    assert il.evaluate(GOOD) is Reason.FAULT_LATCHED


def test_every_state_combination_of_booleans():
    # Exhaustive over the boolean inputs and tracker states.
    for arm, fault, wd, state in itertools.product(
        [False, True], [False, True], [False, True], list(SystemState)
    ):
        il = armed()
        r = il.evaluate(with_(arm_switch=arm, fault=fault, watchdog_ok=wd, state=state))
        aiming = state in (SystemState.LOCKED, SystemState.COAST)  # coast_time_s is 0 here
        expected_ok = arm and not fault and wd and aiming
        assert (r is Reason.OK) == expected_ok, (arm, fault, wd, state, r)


finite = st.floats(allow_nan=True, allow_infinity=True, width=64)
inputs = st.builds(
    InterlockInputs,
    arm_switch=st.booleans(),
    fault=st.booleans(),
    watchdog_ok=st.booleans(),
    telemetry_age_s=finite,
    state=st.sampled_from(list(SystemState)),
    coast_time_s=finite,
    target_range_m=finite,
    pan_deg=finite,
    aim_height_m=finite,
    beam_height_at_target_m=finite,
)


def rules_hold(i: InterlockInputs) -> bool:
    c = CFG
    nums = [
        i.telemetry_age_s,
        i.coast_time_s,
        i.target_range_m,
        i.pan_deg,
        i.aim_height_m,
        i.beam_height_at_target_m,
    ]
    return (
        all(math.isfinite(v) for v in nums)
        and i.arm_switch
        and not i.fault
        and i.watchdog_ok
        and i.telemetry_age_s <= c.max_telemetry_age_s
        and (
            i.state is SystemState.LOCKED
            or (i.state is SystemState.COAST and i.coast_time_s <= c.max_coast_s)
        )
        and c.min_range_m <= i.target_range_m <= c.max_range_m
        and abs(i.pan_deg) <= c.max_pan_deg
        and i.aim_height_m <= c.max_aim_height_m
        and i.beam_height_at_target_m <= c.max_aim_height_m
    )


@settings(max_examples=2000)
@given(st.lists(inputs, min_size=1, max_size=30))
def test_ok_implies_every_rule_holds(sequence):
    il = Interlock()
    for i in sequence:
        if il.evaluate(i) is Reason.OK:
            assert rules_hold(i)


@settings(max_examples=500)
@given(st.lists(inputs, min_size=1, max_size=30))
def test_never_ok_without_seeing_switch_off(sequence):
    il = Interlock()
    seen_off = False
    for i in sequence:
        seen_off |= not i.arm_switch
        if il.evaluate(i) is Reason.OK:
            assert seen_off


@settings(max_examples=500)
@given(st.lists(inputs, min_size=1, max_size=30))
def test_never_ok_after_fault_without_rearm(sequence):
    il = Interlock()
    must_rearm = True
    for i in sequence:
        if not i.arm_switch:
            must_rearm = False
        r = il.evaluate(i)
        if (
            not rules_hold(i)
            and i.arm_switch
            and (
                i.fault
                or not i.watchdog_ok
                or not all(
                    math.isfinite(v)
                    for v in (
                        i.telemetry_age_s,
                        i.coast_time_s,
                        i.target_range_m,
                        i.pan_deg,
                        i.aim_height_m,
                        i.beam_height_at_target_m,
                    )
                )
                or i.telemetry_age_s > CFG.max_telemetry_age_s
            )
        ):
            must_rearm = True
        if r is Reason.OK:
            assert not must_rearm


def test_laser_on_matches_evaluate():
    il = Interlock()
    assert not il.laser_on(GOOD)
    il.laser_on(with_(arm_switch=False))
    assert il.laser_on(GOOD)
