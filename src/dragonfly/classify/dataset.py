# SPDX-License-Identifier: Apache-2.0
"""Synthetic micro-Doppler dataset that follows the real dataset plan (report 8.6).

Each clip is about 10 s of one class. Clips vary the subject (gait), speed,
direction (approach or recede), range and session (noise, hum, gain).
Every clip carries a session id so that training and testing can be split
by session, never by random window, which would leak information.

A synthetic dataset checks that the pipeline works end to end. A classifier
trained on it is not a substitute for one trained on real recordings, and
its accuracy is not the B7 result.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

import numpy as np
import numpy.typing as npt

from dragonfly.classify.features import FEATURE_NAMES, FeatureConfig, extract
from dragonfly.sim.cdm324 import CDM324Params, CDM324Simulator
from dragonfly.sim.scene import PathTarget, Scene, TargetKind


class TargetClass(Enum):
    WALKER = "walker"
    RIGID = "rigid"
    EMPTY = "empty"


CLASSES = tuple(TargetClass)


@dataclass(frozen=True)
class Dataset:
    X: npt.NDArray[np.float64]
    y: npt.NDArray[np.int64]
    """Index into CLASSES."""
    session: npt.NDArray[np.int64]
    clip: npt.NDArray[np.int64]
    feature_names: tuple[str, ...] = FEATURE_NAMES


def _clip_scene(cls: TargetClass, rng: np.random.Generator, duration: float) -> Scene:
    if cls is TargetClass.EMPTY:
        return Scene((PathTarget("still", ((0.0, 0.0, 3.0), (duration, 0.0, 3.0))),))
    speed = rng.uniform(0.6, 1.8) if cls is TargetClass.WALKER else rng.uniform(0.3, 1.5)
    # Mostly radial walks (the plan), with off-axis paths up to 60 degrees,
    # which shrink the radial speed and the micro-Doppler.
    heading = np.radians(rng.uniform(-60.0, 60.0))
    r0 = rng.uniform(2.0, 6.5)
    az0 = np.radians(rng.uniform(-30.0, 30.0))
    x0, y0 = r0 * np.sin(az0), r0 * np.cos(az0)
    toward = 1.0 if rng.random() < 0.5 else -1.0
    dx, dy = np.sin(heading) * speed, -toward * np.cos(heading) * speed
    t_end = duration
    x1, y1 = x0 + dx * t_end, y0 + dy * t_end
    if y1 < 1.0:  # stop before walking into the radar
        t_end = max(1.5, (y0 - 1.0) / max(-dy, 1e-6))
        x1, y1 = x0 + dx * t_end, y0 + dy * t_end
    kind = TargetKind.WALKER if cls is TargetClass.WALKER else TargetKind.RIGID
    path = ((0.0, float(x0), float(y0)), (float(t_end), float(x1), float(y1)))
    return Scene((PathTarget("t", path, kind=kind, rcs=rng.uniform(0.5, 1.5)),))


def make_dataset(
    sessions: int = 6,
    clips_per_class: int = 5,
    clip_s: float = 6.0,
    seed: int = 0,
    features: FeatureConfig | None = None,
) -> Dataset:
    rng = np.random.default_rng(seed)
    xs, ys, ss, cs = [], [], [], []
    clip_id = 0
    for session in range(sessions):
        # Session-level conditions: environment noise, hum, front-end gain.
        noise = rng.uniform(0.002, 0.03)
        hum = rng.uniform(0.0, 0.01)
        gain = rng.uniform(0.05, 0.35)
        for cls_i, cls in enumerate(CLASSES):
            for _ in range(clips_per_class):
                params = CDM324Params(
                    noise_rms=noise,
                    hum_50_amplitude=hum,
                    hum_100_amplitude=hum / 2,
                    signal_at_reference=gain,
                    stride_hz_per_mps=rng.uniform(0.55, 0.75),
                    limb_swing_scale=rng.uniform(0.8, 1.2),
                    limb_amplitude_scale=rng.uniform(0.7, 1.3),
                )
                scene = _clip_scene(cls, rng, clip_s)
                rec = CDM324Simulator(scene, params, seed=int(rng.integers(1 << 31))).record(
                    duration_s=max(scene.duration, 2.0)
                )
                feats = extract(rec.volts_normalised, features)
                xs.append(feats)
                ys += [cls_i] * len(feats)
                ss += [session] * len(feats)
                cs += [clip_id] * len(feats)
                clip_id += 1
    return Dataset(
        X=np.vstack(xs),
        y=np.asarray(ys, dtype=np.int64),
        session=np.asarray(ss, dtype=np.int64),
        clip=np.asarray(cs, dtype=np.int64),
    )
