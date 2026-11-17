# SPDX-License-Identifier: Apache-2.0
"""Moving targets on piecewise-linear paths in the radar frame.

Coordinates are metres in the radar frame: y points straight out of the
antenna, x to the right when looking out. Time is in seconds.
"""

from __future__ import annotations

import bisect
from dataclasses import dataclass
from enum import Enum

import numpy as np
import numpy.typing as npt

FloatArray = npt.NDArray[np.float64]


class TargetKind(Enum):
    WALKER = "walker"
    RIGID = "rigid"


@dataclass(frozen=True)
class State:
    x: float
    y: float
    vx: float
    vy: float


@dataclass(frozen=True)
class PathTarget:
    """A target that moves in straight lines between timed waypoints.

    Waypoints are (t, x, y) with strictly increasing t. The target
    exists only between the first and last waypoint. Repeat a position to
    make the target stand still (useful for stop-and-go scenarios).
    """

    name: str
    waypoints: tuple[tuple[float, float, float], ...]
    kind: TargetKind = TargetKind.WALKER
    rcs: float = 1.0  # relative reflectivity, 1.0 = adult walker

    def __post_init__(self) -> None:
        if len(self.waypoints) < 2:
            raise ValueError("a path needs at least two waypoints")
        times = [w[0] for w in self.waypoints]
        if any(b <= a for a, b in zip(times, times[1:], strict=False)):
            raise ValueError("waypoint times must be strictly increasing")

    @property
    def t_start(self) -> float:
        return self.waypoints[0][0]

    @property
    def t_end(self) -> float:
        return self.waypoints[-1][0]

    def state(self, t: float) -> State | None:
        """Position and velocity at time t, or None if not present."""
        if t < self.t_start or t > self.t_end:
            return None
        times = [w[0] for w in self.waypoints]
        i = min(max(bisect.bisect_right(times, t) - 1, 0), len(times) - 2)
        t0, x0, y0 = self.waypoints[i]
        t1, x1, y1 = self.waypoints[i + 1]
        frac = (t - t0) / (t1 - t0)
        vx = (x1 - x0) / (t1 - t0)
        vy = (y1 - y0) / (t1 - t0)
        return State(x0 + frac * (x1 - x0), y0 + frac * (y1 - y0), vx, vy)

    def sample(
        self, t: FloatArray
    ) -> tuple[FloatArray, FloatArray, FloatArray, FloatArray, FloatArray]:
        """Vectorised state at many times: (present, x, y, vx, vy).

        ``present`` is 1.0 where the target exists and 0.0 elsewhere; the
        other arrays hold the clamped end positions and zero velocity there.
        """
        wp = np.asarray(self.waypoints, dtype=np.float64)
        tw, xw, yw = wp[:, 0], wp[:, 1], wp[:, 2]
        x = np.interp(t, tw, xw)
        y = np.interp(t, tw, yw)
        seg = np.clip(np.searchsorted(tw, t, side="right") - 1, 0, len(tw) - 2)
        dt = tw[seg + 1] - tw[seg]
        present = ((t >= tw[0]) & (t <= tw[-1])).astype(np.float64)
        vx = (xw[seg + 1] - xw[seg]) / dt * present
        vy = (yw[seg + 1] - yw[seg]) / dt * present
        return present, x, y, vx, vy


@dataclass(frozen=True)
class Scene:
    targets: tuple[PathTarget, ...]

    @property
    def duration(self) -> float:
        return max(t.t_end for t in self.targets)
