# SPDX-License-Identifier: Apache-2.0
"""FFT velocity estimation for the CDM324 Doppler channel (report section 7.2).

This is the reference implementation. The ESP32 firmware must produce the
same results on the same input, within a stated tolerance.

Per frame of N samples (default 1024 at 4 kHz, hop 512 = 128 ms):

1. Remove the mean and apply a Hann window.
2. Real FFT; power spectrum P[k].
3. Compare each bin with a per-bin background level learned over time. The
   background soaks up steady interference such as 50 and 100 Hz mains hum,
   so hum does not trigger detections, yet a real target at the same
   frequency still stands out once it is much stronger than the hum.
4. Of the in-band bins above ``threshold_ratio`` times their background, the
   one with the most power is the detection. (Choosing by power rather than
   by ratio keeps harmonics from a clipped signal from winning.) Its
   frequency is refined by log-parabolic interpolation, then converted to
   speed with v = f * c / (2 * f0).
5. Optionally, ``SpeedSmoother`` turns per-frame torso speed into walking
   speed with a one-second running median.

The CDM324 has a single IF output, so the speed is a magnitude only. The
sign (approach or recede) comes from the RD-03D.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass

import numpy as np
import numpy.typing as npt

from dragonfly.sim.cdm324 import F0_HZ, C

FloatArray = npt.NDArray[np.float64]


@dataclass(frozen=True)
class DopplerConfig:
    fs_hz: float = 4000.0
    n_fft: int = 1024
    hop: int = 512
    f0_hz: float = F0_HZ
    min_hz: float = 25.0  # just above the 20 Hz high-pass corner
    max_hz: float = 1000.0  # 6.2 m/s; the anti-alias filter starts at 1.2 kHz
    threshold_ratio: float = 16.0  # power over background, 12 dB: ~1e-4 false alarms/frame
    guard_bins: int = 3  # bins around a detection that do not learn
    background_alpha: float = 0.05  # background learning rate per frame
    warmup_frames: int = 4

    @property
    def bin_hz(self) -> float:
        return self.fs_hz / self.n_fft

    @property
    def hz_per_mps(self) -> float:
        return 2.0 * self.f0_hz / C


@dataclass(frozen=True)
class DopplerResult:
    t_s: float
    """Time of the frame centre, seconds from the first sample."""
    detected: bool
    peak_hz: float
    speed_mps: float
    snr_db: float


class DopplerEstimator:
    """Frame-by-frame velocity estimator with a learned background."""

    def __init__(self, config: DopplerConfig | None = None) -> None:
        self.cfg = config or DopplerConfig()
        c = self.cfg
        if c.n_fft & (c.n_fft - 1):
            raise ValueError("n_fft must be a power of two")
        if not 0 < c.hop <= c.n_fft:
            raise ValueError("hop must be between 1 and n_fft")
        self.window = np.hanning(c.n_fft)
        freqs = np.fft.rfftfreq(c.n_fft, 1.0 / c.fs_hz)
        self.band = (freqs >= c.min_hz) & (freqs <= c.max_hz)
        self.background: FloatArray | None = None
        self.frames_seen = 0

    def spectrum(self, frame: FloatArray) -> FloatArray:
        x = (frame - frame.mean()) * self.window
        p: FloatArray = np.abs(np.fft.rfft(x)) ** 2
        return p

    def process(self, frame: FloatArray, t_s: float = 0.0) -> DopplerResult:
        c = self.cfg
        if len(frame) != c.n_fft:
            raise ValueError(f"frame must have {c.n_fft} samples")
        p = self.spectrum(frame)
        floor = float(np.median(p[self.band])) + 1e-30
        if self.background is None:
            self.background = np.full_like(p, floor)
        bg = np.maximum(self.background, floor)
        ratio = np.where(self.band, p / bg, 0.0)
        above = ratio > c.threshold_ratio
        warm = self.frames_seen >= c.warmup_frames
        detected = bool(warm and above.any())
        k = int(np.argmax(np.where(above, p, 0.0))) if detected else int(np.argmax(ratio))
        # Learn the background. During warm-up every bin is learned, so steady
        # interference present from the start (hum) is absorbed. After that,
        # bins next to the detection are frozen so a steady target does not
        # erase itself, and other bins above threshold learn ten times slower
        # so a new steady interferer is absorbed within tens of seconds.
        if warm:
            a = np.where(above, 0.1 * c.background_alpha, c.background_alpha)
            if detected:
                a[max(0, k - c.guard_bins) : k + c.guard_bins + 1] = 0.0
        else:
            a = np.full_like(p, 0.5)
        self.background = (1 - a) * self.background + a * p
        self.frames_seen += 1
        if not detected:
            return DopplerResult(t_s, False, 0.0, 0.0, 10 * np.log10(ratio[k] + 1e-30))
        peak_bin = k + self._interpolate(p, k)
        peak_hz = peak_bin * c.bin_hz
        return DopplerResult(
            t_s=t_s,
            detected=True,
            peak_hz=peak_hz,
            speed_mps=peak_hz / c.hz_per_mps,
            snr_db=float(10 * np.log10(ratio[k])),
        )

    @staticmethod
    def _interpolate(p: FloatArray, k: int) -> float:
        """Log-parabolic peak offset in bins, in -0.5..0.5."""
        if k <= 0 or k >= len(p) - 1:
            return 0.0
        a, b, g = np.log(p[k - 1 : k + 2] + 1e-30)
        denom = a - 2 * b + g
        if denom >= 0:  # not a local maximum
            return 0.0
        return float(np.clip(0.5 * (a - g) / denom, -0.5, 0.5))

    def run(self, samples: FloatArray) -> Iterator[DopplerResult]:
        """Process a whole recording, frame by frame."""
        c = self.cfg
        for start in range(0, len(samples) - c.n_fft + 1, c.hop):
            t_mid = (start + c.n_fft / 2) / c.fs_hz
            yield self.process(samples[start : start + c.n_fft], t_mid)


class SpeedSmoother:
    """Running median of the last ``n`` detected speeds.

    A walker's torso speeds up and slows down with every step, so a single
    128 ms frame measures the instantaneous speed, not the walking speed.
    A median over about one second (8 frames, two to three steps) estimates
    the walking speed, which is what test T4 measures against. The history
    is cleared after ``max_gap`` frames without a detection.
    """

    def __init__(self, n: int = 8, max_gap: int = 3) -> None:
        if n < 1:
            raise ValueError("n must be at least 1")
        self.n = n
        self.max_gap = max_gap
        self._history: list[float] = []
        self._gap = 0

    def update(self, result: DopplerResult) -> DopplerResult:
        if not result.detected:
            self._gap += 1
            if self._gap > self.max_gap:
                self._history.clear()
            return result
        self._gap = 0
        self._history.append(result.speed_mps)
        del self._history[: -self.n]
        speed = float(np.median(self._history))
        return DopplerResult(
            t_s=result.t_s,
            detected=True,
            peak_hz=result.peak_hz,
            speed_mps=speed,
            snr_db=result.snr_db,
        )
