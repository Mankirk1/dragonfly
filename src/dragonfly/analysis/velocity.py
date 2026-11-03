# SPDX-License-Identifier: Apache-2.0
"""Score FFT velocity estimates against ground truth (benchmark B2, test T4).

Ground truth is the target's radial speed magnitude averaged over each FFT
frame. A frame counts as a target frame when the speed stays at or above
``min_speed_mps`` for the whole frame, and as an empty frame when it stays
below it. Frames that straddle a start or stop are left out of both, since
the right answer for them is ambiguous.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np

from dragonfly.dsp.doppler import DopplerConfig, DopplerResult, FloatArray


@dataclass(frozen=True)
class VelocityScore:
    frames: int
    target_frames: int
    detection_rate: float
    false_alarm_rate: float
    mae_mps: float
    bias_mps: float
    p95_abs_error_mps: float

    def summary(self) -> str:
        return (
            f"frames={self.frames} target_frames={self.target_frames} "
            f"Pd={self.detection_rate:.3f} Pfa={self.false_alarm_rate:.3f} "
            f"MAE={self.mae_mps:.3f} m/s bias={self.bias_mps:+.3f} m/s "
            f"p95={self.p95_abs_error_mps:.3f} m/s"
        )


def frame_truth(
    truth_mps: FloatArray, cfg: DopplerConfig
) -> tuple[FloatArray, FloatArray, FloatArray]:
    """Mean, minimum and maximum |radial speed| over each analysis frame."""
    frames = [
        np.abs(truth_mps[s : s + cfg.n_fft])
        for s in range(0, len(truth_mps) - cfg.n_fft + 1, cfg.hop)
    ]
    return (
        np.array([f.mean() for f in frames]),
        np.array([f.min() for f in frames]),
        np.array([f.max() for f in frames]),
    )


def score(
    results: Sequence[DopplerResult],
    truth_mps: FloatArray,
    cfg: DopplerConfig,
    min_speed_mps: float = 0.2,
) -> VelocityScore:
    truth, lo, hi = frame_truth(truth_mps, cfg)
    if len(truth) != len(results):
        raise ValueError("results and truth cover different numbers of frames")
    det = np.array([r.detected for r in results])
    est = np.array([r.speed_mps for r in results])
    has_target = lo >= min_speed_mps
    hits = det & has_target
    err = est[hits] - truth[hits]
    no_target = hi < min_speed_mps
    return VelocityScore(
        frames=len(results),
        target_frames=int(has_target.sum()),
        detection_rate=float(hits.sum()) / max(1, int(has_target.sum())),
        false_alarm_rate=float((det & no_target).sum()) / max(1, int(no_target.sum())),
        mae_mps=float(np.mean(np.abs(err))) if len(err) else float("nan"),
        bias_mps=float(np.mean(err)) if len(err) else float("nan"),
        p95_abs_error_mps=float(np.percentile(np.abs(err), 95)) if len(err) else float("nan"),
    )
