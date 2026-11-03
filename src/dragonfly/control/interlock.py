# SPDX-License-Identifier: Apache-2.0
"""Laser safety interlock (report section 10.2). SAFETY-CRITICAL.

This decides whether software may switch the laser on. It is one layer of
several: the physical arm switch is wired in series with the laser supply
and always has the final say, the laser must be a marked Class 2 (1 mW or
less) module, and test T9 must pass on the real unit with nobody present
before any trial with a person.

Rules (all must hold; anything else means OFF):

* the arm switch is on, and has been switched off and on again since
  start-up or since the last latched fault (so the system always starts
  disarmed, whatever position the switch is in),
* no latched fault: a fault, a watchdog problem or stale telemetry latches
  the laser off until the operator re-arms,
* the tracker is LOCKED, or in COAST for at most ``max_coast_s``,
* the target is between ``min_range_m`` and ``max_range_m``,
* the pan angle is inside the radar's field of view,
* the commanded aim height is at or below the cap, and the beam is at or
  below the cap at the target's distance.

The function never raises: bad or missing input (NaN, infinity) means OFF.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import Enum

from dragonfly.track.tracker import SystemState


class Reason(Enum):
    """Why the laser is off. ``OK`` means it may be on."""

    OK = "ok"
    NOT_ARMED = "not_armed"
    REARM_REQUIRED = "rearm_required"
    FAULT_LATCHED = "fault_latched"
    NOT_LOCKED = "not_locked"
    COAST_TOO_LONG = "coast_too_long"
    RANGE = "range"
    PAN_LIMIT = "pan_limit"
    HEIGHT_CAP = "height_cap"
    BAD_INPUT = "bad_input"


@dataclass(frozen=True)
class InterlockConfig:
    min_range_m: float = 0.5
    max_range_m: float = 6.0
    max_coast_s: float = 0.5
    max_pan_deg: float = 60.0
    max_aim_height_m: float = 1.2
    max_telemetry_age_s: float = 0.5


@dataclass(frozen=True)
class InterlockInputs:
    arm_switch: bool
    fault: bool
    watchdog_ok: bool
    telemetry_age_s: float
    state: SystemState
    coast_time_s: float
    target_range_m: float
    pan_deg: float
    aim_height_m: float
    beam_height_at_target_m: float


class Interlock:
    """Stateful wrapper: tracks arm-switch transitions and latched faults."""

    def __init__(self, config: InterlockConfig | None = None) -> None:
        self.cfg = config or InterlockConfig()
        self._rearm_needed = True  # start disarmed regardless of switch position
        self._latched = False
        self._last_switch = True  # treat the switch as "on" until seen off

    def evaluate(self, i: InterlockInputs) -> Reason:
        c = self.cfg
        numbers = (
            i.telemetry_age_s,
            i.coast_time_s,
            i.target_range_m,
            i.pan_deg,
            i.aim_height_m,
            i.beam_height_at_target_m,
        )
        bad = not all(isinstance(v, (int, float)) and math.isfinite(v) for v in numbers)
        fault_now = bad or i.fault or not i.watchdog_ok or i.telemetry_age_s > c.max_telemetry_age_s

        # Arm switch handling: an off position clears the re-arm requirement
        # and any latched fault; the next on position then arms.
        if not i.arm_switch:
            self._rearm_needed = False
            self._latched = False
        elif not self._last_switch:
            self._rearm_needed = False
        self._last_switch = i.arm_switch

        if fault_now and i.arm_switch:
            self._latched = True
            self._rearm_needed = True

        if bad:
            return Reason.BAD_INPUT
        if not i.arm_switch:
            return Reason.NOT_ARMED
        if self._latched:
            return Reason.FAULT_LATCHED
        if self._rearm_needed:
            return Reason.REARM_REQUIRED
        if i.state is SystemState.COAST:
            if i.coast_time_s > c.max_coast_s:
                return Reason.COAST_TOO_LONG
        elif i.state is not SystemState.LOCKED:
            return Reason.NOT_LOCKED
        if not c.min_range_m <= i.target_range_m <= c.max_range_m:
            return Reason.RANGE
        if abs(i.pan_deg) > c.max_pan_deg:
            return Reason.PAN_LIMIT
        if i.aim_height_m > c.max_aim_height_m or i.beam_height_at_target_m > c.max_aim_height_m:
            return Reason.HEIGHT_CAP
        return Reason.OK

    def laser_on(self, i: InterlockInputs) -> bool:
        return self.evaluate(i) is Reason.OK
