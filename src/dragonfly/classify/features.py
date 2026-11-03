# SPDX-License-Identifier: Apache-2.0
"""Micro-Doppler features from the CDM324 channel (report section 8.5).

The signal is cut into the same FFT frames as the velocity estimator
(1024 points, 128 ms hop). Consecutive frames are grouped into analysis
windows (default 8 frames, about 1.15 s), and each window becomes one
feature vector:

=====================  ==================================================
peak_hz                strongest line: body (torso) speed
centroid_hz            power-weighted mean frequency
bandwidth_hz           power-weighted spread around the centroid
occupied_hz            width of the band within 20 dB of the peak
peak_to_mean_db        narrow line (rigid) versus broad spectrum (walker)
cadence_ratio          share of centroid variation at 1 to 3 Hz (gait)
energy_cv              frame-to-frame variation of total energy
strong_peaks           mean count of local peaks within 15 dB of the max
=====================  ==================================================

Spectra are normalised by a per-recording noise floor so features do not
depend on absolute signal level (range, gain).
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import numpy.typing as npt

from dragonfly.dsp.doppler import DopplerConfig

FloatArray = npt.NDArray[np.float64]

FEATURE_NAMES = (
    "peak_hz",
    "centroid_hz",
    "bandwidth_hz",
    "occupied_hz",
    "peak_to_mean_db",
    "cadence_ratio",
    "energy_cv",
    "strong_peaks",
)


@dataclass(frozen=True)
class FeatureConfig:
    doppler: DopplerConfig = DopplerConfig()
    window_frames: int = 8
    window_hop_frames: int = 4
    occupied_db: float = 20.0
    peak_db: float = 15.0


def spectrogram(samples: FloatArray, cfg: DopplerConfig) -> tuple[FloatArray, FloatArray]:
    """Power spectrogram (frames x bins) and bin frequencies, band-limited."""
    win = np.hanning(cfg.n_fft)
    starts = range(0, len(samples) - cfg.n_fft + 1, cfg.hop)
    frames = np.array([samples[s : s + cfg.n_fft] for s in starts])
    if len(frames) == 0:
        return np.zeros((0, 0)), np.zeros(0)
    frames = (frames - frames.mean(axis=1, keepdims=True)) * win
    p: FloatArray = (np.abs(np.fft.rfft(frames, axis=1)) ** 2).astype(np.float64)
    f: FloatArray = np.fft.rfftfreq(cfg.n_fft, 1.0 / cfg.fs_hz).astype(np.float64)
    band = (f >= cfg.min_hz) & (f <= cfg.max_hz)
    return p[:, band], f[band]


def _window_features(
    p: FloatArray, f: FloatArray, cfg: FeatureConfig, frame_rate: float
) -> list[float]:
    mean_p = p.mean(axis=0)
    total = mean_p.sum() + 1e-30
    k = int(np.argmax(mean_p))
    centroid = float((f * mean_p).sum() / total)
    bandwidth = float(np.sqrt(((f - centroid) ** 2 * mean_p).sum() / total))
    above = f[mean_p >= mean_p[k] * 10 ** (-cfg.occupied_db / 10)]
    occupied = float(above.max() - above.min()) if len(above) else 0.0
    peak_to_mean = float(10 * np.log10(mean_p[k] / (mean_p.mean() + 1e-30) + 1e-30))

    frame_total = p.sum(axis=1) + 1e-30
    frame_centroid = (p * f).sum(axis=1) / frame_total
    c = frame_centroid - frame_centroid.mean()
    spec = np.abs(np.fft.rfft(c * np.hanning(len(c)))) ** 2
    cf = np.fft.rfftfreq(len(c), 1.0 / frame_rate)
    cadence = float(spec[(cf >= 1.0) & (cf <= 3.0)].sum() / (spec[1:].sum() + 1e-30))
    energy_cv = float(frame_total.std() / frame_total.mean())

    peaks = []
    for row in p:
        thr = row.max() * 10 ** (-cfg.peak_db / 10)
        local = (row[1:-1] > row[:-2]) & (row[1:-1] >= row[2:]) & (row[1:-1] >= thr)
        peaks.append(int(local.sum()))
    return [
        float(f[k]),
        centroid,
        bandwidth,
        occupied,
        peak_to_mean,
        cadence,
        energy_cv,
        float(np.mean(peaks)),
    ]


def extract(samples: FloatArray, cfg: FeatureConfig | None = None) -> FloatArray:
    """Feature matrix, one row per analysis window, columns as FEATURE_NAMES."""
    cfg = cfg or FeatureConfig()
    p, f = spectrogram(samples, cfg.doppler)
    if len(p) < cfg.window_frames:
        return np.zeros((0, len(FEATURE_NAMES)))
    floor = np.median(p) + 1e-30
    p = p / floor
    frame_rate = cfg.doppler.fs_hz / cfg.doppler.hop
    rows = [
        _window_features(p[s : s + cfg.window_frames], f, cfg, frame_rate)
        for s in range(0, len(p) - cfg.window_frames + 1, cfg.window_hop_frames)
    ]
    return np.asarray(rows, dtype=np.float64)
