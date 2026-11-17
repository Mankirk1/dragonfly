# SPDX-License-Identifier: Apache-2.0
"""Standard test scenes from the validation plan.

S1 to S6 mirror the closed-loop A/B scenarios. ``t1_walker`` builds one
cell of the T1 radar characterisation grid. Distances are metres, speeds
are m/s, angles are degrees from boresight (positive to the right).
"""

from __future__ import annotations

import math

from dragonfly.sim.scene import PathTarget, Scene, TargetKind


def _polar(range_m: float, azimuth_deg: float) -> tuple[float, float]:
    a = math.radians(azimuth_deg)
    return range_m * math.sin(a), range_m * math.cos(a)


def crossing(speed_mps: float, range_m: float = 3.0, half_width_m: float = 3.0) -> Scene:
    """Walk across the field of view at a fixed distance in front of the radar."""
    duration = 2 * half_width_m / speed_mps
    path = ((0.0, -half_width_m, range_m), (duration, half_width_m, range_m))
    return Scene((PathTarget("walker", path),))


def s1_crossing_slow() -> Scene:
    return crossing(1.0)


def s2_crossing_fast() -> Scene:
    return crossing(1.5)


def s3_approach_recede(speed_mps: float = 1.0, far_m: float = 5.0, near_m: float = 1.0) -> Scene:
    leg = (far_m - near_m) / speed_mps
    path = ((0.0, 0.0, far_m), (leg, 0.0, near_m), (2 * leg, 0.0, far_m))
    return Scene((PathTarget("walker", path),))


def s4_arc(
    range_m: float = 4.0,
    from_deg: float = -40.0,
    to_deg: float = 40.0,
    speed_mps: float = 1.0,
    steps: int = 16,
) -> Scene:
    """Walk an arc at constant range, sweeping the azimuth."""
    arc_len = range_m * math.radians(abs(to_deg - from_deg))
    duration = arc_len / speed_mps
    path = tuple(
        (duration * k / steps, *_polar(range_m, from_deg + (to_deg - from_deg) * k / steps))
        for k in range(steps + 1)
    )
    return Scene((PathTarget("walker", path),))


def s5_stop_and_go(
    range_m: float = 3.0,
    speed_mps: float = 1.0,
    walk_s: float = 2.0,
    stop_s: float = 2.0,
    legs: int = 3,
) -> Scene:
    x = -walk_s * speed_mps * legs / 2
    t = 0.0
    path = [(t, x, range_m)]
    for leg in range(legs):
        t += walk_s
        x += walk_s * speed_mps
        path.append((t, x, range_m))
        if leg < legs - 1:
            t += stop_s
            path.append((t, x, range_m))
    return Scene((PathTarget("walker", tuple(path)),))


def s6_two_walkers(duration_s: float = 5.0) -> Scene:
    a = PathTarget("walker_a", ((0.0, -2.5, 3.0), (duration_s, 2.5, 4.0)))
    b = PathTarget("walker_b", ((0.0, 2.5, 3.0), (duration_s, -2.5, 4.0)))
    return Scene((a, b))


def t1_walker(
    range_m: float,
    azimuth_deg: float,
    pace_m: float = 0.5,
    speed_mps: float = 0.8,
    repeats: int = 5,
) -> Scene:
    """Walker pacing radially back and forth around one marked grid point."""
    near = _polar(range_m - pace_m / 2, azimuth_deg)
    far = _polar(range_m + pace_m / 2, azimuth_deg)
    leg = pace_m / speed_mps
    path = tuple((k * leg, *(near if k % 2 == 0 else far)) for k in range(2 * repeats + 1))
    return Scene((PathTarget("walker", path),))


def rigid_roll(
    range_start_m: float = 5.0, range_end_m: float = 1.5, speed_mps: float = 0.8
) -> Scene:
    """A rolling object moving straight toward the radar."""
    duration = (range_start_m - range_end_m) / speed_mps
    path = ((0.0, 0.0, range_start_m), (duration, 0.0, range_end_m))
    return Scene((PathTarget("cart", path, kind=TargetKind.RIGID, rcs=0.5),))


SCENARIOS = {
    "S1": s1_crossing_slow,
    "S2": s2_crossing_fast,
    "S3": s3_approach_recede,
    "S4": s4_arc,
    "S5": s5_stop_and_go,
    "S6": s6_two_walkers,
}
