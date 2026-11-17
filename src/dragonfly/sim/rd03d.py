# SPDX-License-Identifier: Apache-2.0
"""Statistical model of the RD-03D FMCW radar's target reports.

The model reproduces the limits listed in the datasheet and the project's
design review, so tracking code can be tested against known ground truth:

* +/-60 degree azimuth field of view and a maximum range
* motion-only detection: targets slower than a threshold disappear
* range noise (datasheet ranging accuracy 0.15 m) and azimuth noise
* range-resolution merging: targets closer than ~0.75 m in range and at a
  similar bearing are reported as one
* detection probability that falls off beyond the reliable range
* occasional false targets from clutter
* at most three reported targets per frame
* frame timing jitter

Every number marked ASSUMPTION is a starting guess. Calibrate them from
test T1 recordings before trusting simulated performance figures.
"""

from __future__ import annotations

import math
from collections.abc import Iterator
from dataclasses import dataclass

import numpy as np

from dragonfly.io.rd03d import TARGET_SLOTS, Frame, Target
from dragonfly.sim.scene import Scene, State


@dataclass(frozen=True)
class RD03DParams:
    frame_rate_hz: float = 10.0  # ASSUMPTION
    frame_jitter_s: float = 0.005  # ASSUMPTION
    fov_azimuth_deg: float = 60.0  # datasheet
    max_range_m: float = 8.0  # datasheet, open field
    min_range_m: float = 0.3  # ASSUMPTION
    reliable_range_m: float = 5.0  # report: 3-5 m reliable indoors
    p_detect_reliable: float = 0.97  # ASSUMPTION
    p_detect_max_range: float = 0.5  # ASSUMPTION
    range_sigma_m: float = 0.15  # datasheet ranging accuracy
    azimuth_sigma_deg: float = 2.0  # ASSUMPTION, measure in T1
    speed_sigma_mps: float = 0.05  # ASSUMPTION
    min_speed_mps: float = 0.1  # ASSUMPTION: motion-only detection threshold
    range_resolution_m: float = 0.75  # datasheet
    merge_azimuth_deg: float = 10.0  # ASSUMPTION
    false_alarm_rate: float = 0.02  # ASSUMPTION: expected false targets per frame
    max_targets: int = TARGET_SLOTS


@dataclass(frozen=True)
class TruthTarget:
    name: str
    state: State
    detected: bool


@dataclass(frozen=True)
class SimFrame:
    t: float
    frame: Frame
    truth: tuple[TruthTarget, ...]


def radial_speed(s: State) -> float:
    """Radial speed, positive moving away from the radar."""
    r = math.hypot(s.x, s.y)
    if r == 0.0:
        return 0.0
    return (s.x * s.vx + s.y * s.vy) / r


class RD03DSimulator:
    def __init__(self, scene: Scene, params: RD03DParams | None = None, seed: int = 0) -> None:
        self.scene = scene
        self.p = params or RD03DParams()
        self.rng = np.random.default_rng(seed)

    def p_detect(self, range_m: float) -> float:
        p = self.p
        if range_m < p.min_range_m or range_m > p.max_range_m:
            return 0.0
        if range_m <= p.reliable_range_m:
            return p.p_detect_reliable
        frac = (range_m - p.reliable_range_m) / (p.max_range_m - p.reliable_range_m)
        return p.p_detect_reliable + frac * (p.p_detect_max_range - p.p_detect_reliable)

    def _visible(self, s: State) -> bool:
        az = math.degrees(math.atan2(s.x, s.y))
        return s.y > 0 and abs(az) <= self.p.fov_azimuth_deg

    def _measure(self, s: State) -> Target:
        p, rng = self.p, self.rng
        r = math.hypot(s.x, s.y) + rng.normal(0.0, p.range_sigma_m)
        az = math.atan2(s.x, s.y) + math.radians(rng.normal(0.0, p.azimuth_sigma_deg))
        r = max(r, 0.0)
        return Target(
            x_m=r * math.sin(az),
            y_m=r * math.cos(az),
            speed_mps=radial_speed(s) + rng.normal(0.0, p.speed_sigma_mps),
            resolution_m=p.range_resolution_m,
        )

    def _false_target(self) -> Target:
        p, rng = self.p, self.rng
        r = rng.uniform(p.min_range_m, p.max_range_m)
        az = math.radians(rng.uniform(-p.fov_azimuth_deg, p.fov_azimuth_deg))
        return Target(
            x_m=r * math.sin(az),
            y_m=r * math.cos(az),
            speed_mps=rng.normal(0.0, 0.3),
            resolution_m=p.range_resolution_m,
        )

    def _merge(self, candidates: list[tuple[str, State]]) -> list[tuple[str, State]]:
        """Drop targets hidden by a nearer target within the resolution cell."""
        kept: list[tuple[str, State]] = []
        for name, s in sorted(candidates, key=lambda c: math.hypot(c[1].x, c[1].y)):
            r = math.hypot(s.x, s.y)
            az = math.degrees(math.atan2(s.x, s.y))
            hidden = any(
                abs(r - math.hypot(k.x, k.y)) < self.p.range_resolution_m
                and abs(az - math.degrees(math.atan2(k.x, k.y))) < self.p.merge_azimuth_deg
                for _, k in kept
            )
            if not hidden:
                kept.append((name, s))
        return kept

    def frames(self) -> Iterator[SimFrame]:
        p, rng = self.p, self.rng
        period = 1.0 / p.frame_rate_hz
        n_frames = int(self.scene.duration * p.frame_rate_hz) + 1
        for i in range(n_frames):
            t = max(0.0, i * period + rng.normal(0.0, p.frame_jitter_s))
            present = [(tg.name, s) for tg in self.scene.targets if (s := tg.state(t)) is not None]
            # Motion-only detection: the radar sees nothing that stands still.
            moving = [
                (n, s)
                for n, s in present
                if self._visible(s) and math.hypot(s.vx, s.vy) >= p.min_speed_mps
            ]
            reports: list[tuple[str | None, Target]] = []
            for name, s in self._merge(moving):
                if rng.random() < self.p_detect(math.hypot(s.x, s.y)):
                    reports.append((name, self._measure(s)))
            for _ in range(rng.poisson(p.false_alarm_rate)):
                reports.append((None, self._false_target()))
            reports.sort(key=lambda nt: nt[1].range_m)
            reports = reports[: p.max_targets]
            detected_names = {n for n, _ in reports if n is not None}
            truth = tuple(TruthTarget(n, s, n in detected_names) for n, s in present)
            yield SimFrame(t=t, frame=Frame(tuple(tg for _, tg in reports)), truth=truth)
