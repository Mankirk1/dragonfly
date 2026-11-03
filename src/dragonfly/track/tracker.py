# SPDX-License-Identifier: Apache-2.0
"""Multi-target tracker with the track states from report section 9.3.

Per track::

    TENTATIVE --3 hits in 5 frames--> LOCKED
    TENTATIVE --2 misses in a row---> deleted
    LOCKED    --miss----------------> COAST
    COAST     --hit-----------------> LOCKED
    COAST     --1.0 s without hit---> HOLD   (target presumed stopped)
    HOLD      --3.0 s more----------> deleted

A target that starts moving again after HOLD is picked up by a new
tentative track, which must be confirmed (3 hits in 5 frames) before it
takes over. A held track never jumps to a single new measurement, so one
clutter report cannot swing the laser while the target stands still.

The system state is SEARCH when there is no primary track, otherwise the
primary track's state. The primary is the nearest confirmed track, and the
choice is sticky: it only moves to another track that has been at least
0.5 m nearer for at least 1 s, or immediately when the primary is not
currently seen (COAST or HOLD) and another confirmed track is.

Two adaptations handle the RD-03D's quirks. A surprising measurement
(normalised innovation above ``maneuver_nis``) raises the process noise for a
few frames so the filter follows turns and stops quickly. And because the
radar mostly loses a target when it stops moving, the velocity estimate
decays while coasting, so the aim point does not run ahead of a person who
has just stopped.

Association is global nearest neighbour: an optimal one-to-one assignment
of measurements to tracks, using Mahalanobis distance, gated at
d^2 <= 9.21 (99% for 2 degrees of freedom).
"""

from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass, field
from enum import Enum

import numpy as np
from scipy.optimize import linear_sum_assignment

from dragonfly.io.rd03d import Frame
from dragonfly.track.kalman import Array, KalmanCV, polar_measurement_noise


class TrackState(Enum):
    TENTATIVE = "tentative"
    LOCKED = "locked"
    COAST = "coast"
    HOLD = "hold"


class SystemState(Enum):
    SEARCH = "search"
    TENTATIVE = "tentative"
    LOCKED = "locked"
    COAST = "coast"
    HOLD = "hold"


@dataclass(frozen=True)
class TrackerConfig:
    sigma_a: float = 1.0  # m/s^2 process noise (report: tune 0.5 to 2)
    sigma_r: float = 0.15  # m, datasheet ranging accuracy
    sigma_az_deg: float = 2.0  # ASSUMPTION until T1 measures it
    initial_speed_sigma: float = 2.0  # m/s, velocity uncertainty of a new track
    gate_d2: float = 9.21
    confirm_hits: int = 3
    confirm_window: int = 5
    tentative_max_misses: int = 2
    coast_timeout_s: float = 1.0
    hold_timeout_s: float = 3.0
    max_tracks: int = 5
    duplicate_distance_m: float = 0.75  # one radar resolution cell
    switch_margin_m: float = 0.5
    switch_time_s: float = 1.0
    lead_s: float = 0.25  # aim lead time; set to the measured latency (T5)
    # Maneuver adaptation: a surprising measurement (NIS above the threshold)
    # temporarily raises the process noise so the filter catches up quickly.
    maneuver_nis: float = 6.0
    maneuver_q_scale: float = 10.0
    maneuver_decay: float = 0.7
    # The RD-03D loses a target mostly because it stopped, so while coasting
    # the estimated velocity decays with this time constant.
    coast_velocity_tau_s: float = 0.3


@dataclass
class Track:
    id: int
    kf: KalmanCV
    state: TrackState
    last_hit_t: float
    hits: deque[bool] = field(default_factory=lambda: deque(maxlen=5))
    consecutive_misses: int = 0
    last_nis: float = float("nan")
    q_scale: float = 1.0

    @property
    def range_m(self) -> float:
        return math.hypot(self.kf.x[0], self.kf.x[1])

    @property
    def confirmed(self) -> bool:
        return self.state is not TrackState.TENTATIVE


@dataclass(frozen=True)
class TrackReport:
    id: int
    state: TrackState
    x: float
    y: float
    vx: float
    vy: float


@dataclass(frozen=True)
class TrackerOutput:
    t: float
    state: SystemState
    primary: int | None
    tracks: tuple[TrackReport, ...]
    aim_xy: tuple[float, float] | None
    """Where to point: the primary's predicted position at t + lead_s. In HOLD
    this is the last position. None in SEARCH and TENTATIVE."""


class Tracker:
    def __init__(self, config: TrackerConfig | None = None) -> None:
        self.cfg = config or TrackerConfig()
        self.tracks: list[Track] = []
        self.primary: int | None = None
        self._next_id = 1
        self._t: float | None = None
        self._challenger: int | None = None
        self._challenger_since: float = 0.0

    def _r(self, x: float, y: float) -> Array:
        return polar_measurement_noise(x, y, self.cfg.sigma_r, math.radians(self.cfg.sigma_az_deg))

    def _new_track(self, z: Array, t: float) -> Track:
        c = self.cfg
        r = self._r(float(z[0]), float(z[1]))
        p0 = np.zeros((4, 4))
        p0[:2, :2] = r
        p0[2, 2] = p0[3, 3] = c.initial_speed_sigma**2
        tr = Track(
            self._next_id,
            KalmanCV(np.array([z[0], z[1], 0.0, 0.0]), p0),
            TrackState.TENTATIVE,
            t,
            deque([True], maxlen=c.confirm_window),
        )
        self._next_id += 1
        return tr

    @staticmethod
    def _distance(a: Track, b: Track) -> float:
        return math.hypot(a.kf.x[0] - b.kf.x[0], a.kf.x[1] - b.kf.x[1])

    def _decay_velocity(self, tr: Track, d: float) -> None:
        """Shrink the velocity estimate by factor ``d`` and grow its
        uncertainty toward the prior, as for a mean-reverting velocity."""
        prior = self.cfg.initial_speed_sigma**2
        p = tr.kf.P
        tr.kf.x[2:] *= d
        p[2:, 2:] = d * d * p[2:, 2:] + (1 - d * d) * prior * np.eye(2)
        p[:2, 2:] *= d
        p[2:, :2] *= d

    def update(self, t: float, frame: Frame) -> TrackerOutput:
        c = self.cfg
        dt = 0.0 if self._t is None else max(0.0, t - self._t)
        self._t = t
        for tr in self.tracks:
            if tr.state is TrackState.HOLD:
                self._decay_velocity(tr, 0.0)  # stopped: no drift, any restart direction
            elif tr.state is TrackState.COAST:
                self._decay_velocity(tr, math.exp(-dt / c.coast_velocity_tau_s))
            tr.kf.predict(dt, c.sigma_a * math.sqrt(tr.q_scale))

        zs = [np.array([tg.x_m, tg.y_m]) for tg in frame.targets]
        assigned: dict[int, int] = {}
        if self.tracks and zs:
            cost = np.full((len(self.tracks), len(zs)), 1e6)
            for i, tr in enumerate(self.tracks):
                if tr.state is TrackState.HOLD:
                    continue  # re-acquired through a fresh tentative track, see below
                for j, z in enumerate(zs):
                    d2 = tr.kf.mahalanobis2(z, self._r(float(z[0]), float(z[1])))
                    if d2 <= c.gate_d2:
                        cost[i, j] = d2
            rows, cols = linear_sum_assignment(cost)
            assigned = {int(i): int(j) for i, j in zip(rows, cols, strict=True) if cost[i, j] < 1e6}

        for i, tr in enumerate(self.tracks):
            if i in assigned:
                z = zs[assigned[i]]
                tr.last_nis = tr.kf.update(z, self._r(float(z[0]), float(z[1])))
                if tr.last_nis > c.maneuver_nis:
                    tr.q_scale = c.maneuver_q_scale
                else:
                    tr.q_scale = max(1.0, tr.q_scale * c.maneuver_decay)
                tr.hits.append(True)
                tr.consecutive_misses = 0
                tr.last_hit_t = t
                if tr.state is TrackState.TENTATIVE:
                    if sum(tr.hits) >= c.confirm_hits:
                        tr.state = TrackState.LOCKED
                else:
                    tr.state = TrackState.LOCKED
            else:
                tr.hits.append(False)
                tr.consecutive_misses += 1
                since = t - tr.last_hit_t
                if tr.state is TrackState.LOCKED:
                    tr.state = TrackState.COAST
                if tr.state is TrackState.COAST and since > c.coast_timeout_s:
                    tr.state = TrackState.HOLD
                    self._decay_velocity(tr, 0.0)

        self.tracks = [
            tr
            for tr in self.tracks
            if not (
                tr.state is TrackState.TENTATIVE and tr.consecutive_misses >= c.tentative_max_misses
            )
            and not (
                tr.state is TrackState.HOLD
                and t - tr.last_hit_t > c.coast_timeout_s + c.hold_timeout_s
            )
        ]

        # The radar cannot separate targets closer than one resolution cell,
        # so two tracks that close are the same target. Keep, in order of
        # preference: a track being seen over one in HOLD, a confirmed track
        # over a tentative one, the primary, then the older track.
        keep: list[Track] = []
        order = sorted(
            self.tracks,
            key=lambda tr: (
                tr.state is TrackState.HOLD,
                not tr.confirmed,
                tr.id != self.primary,
                tr.id,
            ),
        )
        for tr in order:
            if all(self._distance(tr, k) >= c.duplicate_distance_m for k in keep):
                keep.append(tr)
        self.tracks = sorted(keep, key=lambda tr: tr.id)

        used = set(assigned.values())
        for j, z in enumerate(zs):
            if j in used or len(self.tracks) >= c.max_tracks:
                continue
            near = any(
                math.hypot(tr.kf.x[0] - z[0], tr.kf.x[1] - z[1]) < c.duplicate_distance_m
                for tr in self.tracks
                if tr.state is not TrackState.HOLD
            )
            if not near:
                self.tracks.append(self._new_track(z, t))

        self._select_primary(t)
        return self._output(t)

    def _select_primary(self, t: float) -> None:
        c = self.cfg
        confirmed = [tr for tr in self.tracks if tr.confirmed]
        by_id = {tr.id: tr for tr in confirmed}
        if self.primary not in by_id:
            self.primary = min(confirmed, key=lambda tr: tr.range_m).id if confirmed else None
            self._challenger = None
            return
        current = by_id[self.primary]
        # Only targets the radar is actually seeing can take over.
        live = [tr for tr in confirmed if tr.state is TrackState.LOCKED and tr.id != current.id]
        nearest = min(live, key=lambda tr: tr.range_m, default=None)
        if nearest is not None and current.state is not TrackState.LOCKED:
            # The primary is not being seen; a target that is takes over at once.
            self.primary, self._challenger = nearest.id, None
            return
        if nearest is None or nearest.range_m > current.range_m - c.switch_margin_m:
            self._challenger = None
            return
        if self._challenger != nearest.id:
            self._challenger, self._challenger_since = nearest.id, t
        elif t - self._challenger_since >= c.switch_time_s:
            self.primary, self._challenger = nearest.id, None

    def _output(self, t: float) -> TrackerOutput:
        reports = tuple(
            TrackReport(tr.id, tr.state, *(float(v) for v in tr.kf.x)) for tr in self.tracks
        )
        prim = next((tr for tr in self.tracks if tr.id == self.primary), None)
        if prim is None:
            tentative = any(tr.state is TrackState.TENTATIVE for tr in self.tracks)
            state = SystemState.TENTATIVE if tentative else SystemState.SEARCH
            return TrackerOutput(t, state, None, reports, None)
        lead = 0.0 if prim.state is TrackState.HOLD else self.cfg.lead_s
        return TrackerOutput(
            t, SystemState(prim.state.value), prim.id, reports, prim.kf.predicted_position(lead)
        )
