# SPDX-License-Identifier: Apache-2.0
"""Simulated A/B evaluation of tracking and aiming (benchmarks B5, B6, B8).

For each radar frame the laser is commanded at time t and arrives at
t + latency. The pointing error is the difference in bearing (pan angle)
between the commanded aim point and where the true target actually is at
t + latency. Two aiming strategies are compared, as in test T6:

* **unfiltered**: aim at the latest raw measurement nearest the target
* **filtered**: aim at the tracker's predicted position at t + lead

Results from simulation show whether the method works and how to tune it.
They are not the B5 or B8 result: those come from T6 on the real system.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from dragonfly.sim.rd03d import RD03DParams, RD03DSimulator
from dragonfly.sim.scene import Scene
from dragonfly.track.tracker import SystemState, Tracker, TrackerConfig

AIMING = (SystemState.LOCKED, SystemState.COAST)


def _wrap_deg(a: float) -> float:
    return (a + 180.0) % 360.0 - 180.0


def bearing_deg(x: float, y: float) -> float:
    return math.degrees(math.atan2(x, y))


@dataclass(frozen=True)
class AimScore:
    frames: int
    aiming_frames: int
    rms_deg: float
    p95_deg: float
    jitter_deg_s: float
    """Standard deviation of the frame-to-frame aim change, per second."""

    def summary(self) -> str:
        return (
            f"aiming {self.aiming_frames}/{self.frames} frames, RMS {self.rms_deg:.2f} deg, "
            f"p95 {self.p95_deg:.2f} deg, jitter {self.jitter_deg_s:.1f} deg/s"
        )


@dataclass(frozen=True)
class TrackingRun:
    filtered: AimScore
    unfiltered: AimScore
    time_to_lock_s: float
    lock_losses: int
    primary_switches: int
    mean_nees: float


def _score(errors: list[float], aims: list[tuple[float, float]], frames: int) -> AimScore:
    e = np.abs(np.array(errors)) if errors else np.array([np.nan])
    rates = [
        (b - a) / (tb - ta)
        for (ta, a), (tb, b) in zip(aims, aims[1:], strict=False)
        if 0 < tb - ta < 0.5
    ]
    return AimScore(
        frames=frames,
        aiming_frames=len(errors),
        rms_deg=float(np.sqrt(np.mean(e**2))),
        p95_deg=float(np.percentile(e, 95)),
        jitter_deg_s=float(np.std(rates)) if len(rates) > 1 else float("nan"),
    )


def evaluate(
    scene: Scene,
    latency_s: float = 0.25,
    tracker_config: TrackerConfig | None = None,
    radar_params: RD03DParams | None = None,
    seed: int = 0,
) -> TrackingRun:
    cfg = tracker_config or TrackerConfig(lead_s=latency_s)
    tracker = Tracker(cfg)
    sim = RD03DSimulator(scene, radar_params, seed=seed)
    f_err: list[float] = []
    u_err: list[float] = []
    f_aims: list[tuple[float, float]] = []
    u_aims: list[tuple[float, float]] = []
    nees: list[float] = []
    frames = 0
    first_visible: float | None = None
    first_lock: float | None = None
    was_aiming = False
    losses = 0
    switches = 0
    last_primary: int | None = None

    for sf in sim.frames():
        frames += 1
        out = tracker.update(sf.t, sf.frame)
        detected_truth = [tt for tt in sf.truth if tt.detected]
        if first_visible is None and detected_truth:
            first_visible = sf.t
        aiming = out.state in AIMING and out.aim_xy is not None
        if aiming and first_lock is None:
            first_lock = sf.t
        if (
            was_aiming
            and not aiming
            and any(math.hypot(tt.state.vx, tt.state.vy) > 0 for tt in sf.truth)
        ):
            losses += 1
        was_aiming = aiming
        if out.primary is not None and last_primary is not None and out.primary != last_primary:
            switches += 1
        last_primary = out.primary if out.primary is not None else last_primary

        future = [s for tg in scene.targets if (s := tg.state(sf.t + latency_s)) is not None]
        if not aiming or not future or out.aim_xy is None:
            continue
        ax, ay = out.aim_xy
        truth = min(future, key=lambda s: math.hypot(s.x - ax, s.y - ay))
        true_bearing = bearing_deg(truth.x, truth.y)
        f_bearing = bearing_deg(ax, ay)
        f_err.append(_wrap_deg(f_bearing - true_bearing))
        f_aims.append((sf.t, f_bearing))
        if sf.frame.targets:
            m = min(sf.frame.targets, key=lambda tg: math.hypot(tg.x_m - ax, tg.y_m - ay))
            u_bearing = bearing_deg(m.x_m, m.y_m)
            u_err.append(_wrap_deg(u_bearing - true_bearing))
            u_aims.append((sf.t, u_bearing))
        prim = next(tr for tr in tracker.tracks if tr.id == out.primary)
        now = [s for tg in scene.targets if (s := tg.state(sf.t)) is not None]
        if now and prim.state.value == "locked":
            s = min(now, key=lambda s: math.hypot(s.x - prim.kf.x[0], s.y - prim.kf.x[1]))
            err = np.array([s.x, s.y, s.vx, s.vy]) - prim.kf.x
            nees.append(float(err @ np.linalg.solve(prim.kf.P, err)))

    return TrackingRun(
        filtered=_score(f_err, f_aims, frames),
        unfiltered=_score(u_err, u_aims, frames),
        time_to_lock_s=(first_lock - first_visible)
        if first_lock is not None and first_visible is not None
        else float("nan"),
        lock_losses=losses,
        primary_switches=switches,
        mean_nees=float(np.mean(nees)) if nees else float("nan"),
    )
