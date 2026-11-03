# SPDX-License-Identifier: Apache-2.0
"""Aim solver and servo command shaping (report sections 6.6 and 9.5).

The radar reports targets in its horizontal plane only. The aim solver:

1. subtracts the laser's mounting offset from the target position
   (parallax correction),
2. computes pan from the corrected x and y,
3. computes tilt from the horizontal range and a configured aim height,
   which is capped below adult shoulder height.

Angles are degrees. Pan is positive to the right of boresight, tilt is
positive upward.
"""

from __future__ import annotations

import bisect
import math
from dataclasses import dataclass


@dataclass(frozen=True)
class AimConfig:
    laser_offset_x_m: float = 0.0  # laser pivot relative to the radar, radar frame
    laser_offset_y_m: float = 0.0
    laser_height_m: float = 1.0  # height of the laser pivot above the floor
    aim_height_m: float = 1.0  # height on the target to aim at
    max_aim_height_m: float = 1.2  # safety cap, report section 10.2
    min_range_m: float = 0.3

    def __post_init__(self) -> None:
        if self.aim_height_m > self.max_aim_height_m:
            raise ValueError("aim height must not exceed the safety cap")


@dataclass(frozen=True)
class AimSolution:
    pan_deg: float
    tilt_deg: float
    horizontal_range_m: float


def solve(x_m: float, y_m: float, cfg: AimConfig) -> AimSolution:
    dx = x_m - cfg.laser_offset_x_m
    dy = y_m - cfg.laser_offset_y_m
    r_h = max(math.hypot(dx, dy), cfg.min_range_m)
    pan = math.degrees(math.atan2(dx, dy))
    h = min(cfg.aim_height_m, cfg.max_aim_height_m)
    tilt = math.degrees(math.atan2(h - cfg.laser_height_m, r_h))
    return AimSolution(pan, tilt, r_h)


def beam_height_at(range_m: float, tilt_deg: float, laser_height_m: float) -> float:
    """Height of the beam above the floor at a horizontal distance."""
    return laser_height_m + range_m * math.tan(math.radians(tilt_deg))


@dataclass(frozen=True)
class ServoCalibration:
    """Piecewise-linear map from angle (degrees) to pulse width (microseconds),
    recorded with the calibration procedure in report section 9.5."""

    angles_deg: tuple[float, ...]
    pulses_us: tuple[float, ...]

    def __post_init__(self) -> None:
        a, p = self.angles_deg, self.pulses_us
        if len(a) != len(p) or len(a) < 2:
            raise ValueError("need at least two matching calibration points")
        if any(b <= x for x, b in zip(a, a[1:], strict=False)):
            raise ValueError("calibration angles must be strictly increasing")
        inc = all(b > x for x, b in zip(p, p[1:], strict=False))
        dec = all(b < x for x, b in zip(p, p[1:], strict=False))
        if not (inc or dec):
            raise ValueError("calibration pulses must be strictly monotonic")
        if min(p) < 500 or max(p) > 2500:
            raise ValueError("pulse widths must be within 500 to 2500 us")

    @property
    def min_deg(self) -> float:
        return self.angles_deg[0]

    @property
    def max_deg(self) -> float:
        return self.angles_deg[-1]

    def pulse_us(self, angle_deg: float) -> float:
        """Pulse for an angle, clamped to the calibrated range."""
        a, p = self.angles_deg, self.pulses_us
        angle = min(max(angle_deg, a[0]), a[-1])
        i = min(max(bisect.bisect_right(a, angle) - 1, 0), len(a) - 2)
        frac = (angle - a[i]) / (a[i + 1] - a[i])
        return p[i] + frac * (p[i + 1] - p[i])


# Nominal MG996R mapping before calibration: 1500 us centre, ~10 us/degree.
DEFAULT_PAN = ServoCalibration((-90.0, 0.0, 90.0), (600.0, 1500.0, 2400.0))
DEFAULT_TILT = ServoCalibration((-45.0, 0.0, 45.0), (1050.0, 1500.0, 1950.0))


@dataclass(frozen=True)
class ServoLimits:
    min_deg: float
    max_deg: float
    max_rate_deg_s: float = 300.0  # MG996R: ~60 deg in 0.14 to 0.17 s unloaded
    deadband_deg: float = 0.5
    smoothing: float = 0.5  # 0 = no smoothing, closer to 1 = heavier


class ServoAxis:
    """Shapes a target angle into a safe servo command: clamp to travel,
    dead band (to stop hunting), light smoothing, then a rate limit."""

    def __init__(self, limits: ServoLimits, start_deg: float = 0.0) -> None:
        if not limits.min_deg < limits.max_deg:
            raise ValueError("min_deg must be below max_deg")
        if not 0.0 <= limits.smoothing < 1.0:
            raise ValueError("smoothing must be in [0, 1)")
        self.lim = limits
        self.angle = min(max(start_deg, limits.min_deg), limits.max_deg)

    def step(self, target_deg: float, dt: float) -> float:
        lim = self.lim
        target = min(max(target_deg, lim.min_deg), lim.max_deg)
        if abs(target - self.angle) <= lim.deadband_deg:
            return self.angle
        desired = self.angle + (1.0 - lim.smoothing) * (target - self.angle)
        max_step = lim.max_rate_deg_s * max(dt, 0.0)
        delta = min(max(desired - self.angle, -max_step), max_step)
        self.angle = min(max(self.angle + delta, lim.min_deg), lim.max_deg)
        return self.angle
