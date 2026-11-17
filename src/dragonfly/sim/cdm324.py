# SPDX-License-Identifier: Apache-2.0
"""Model of the CDM324 continuous-wave Doppler channel, from target to ADC.

Chain: moving scatterers -> Doppler IF signal -> analog front end (band-pass
and gain) -> 12-bit ADC samples, exactly as the ESP32 would read them.

A CW radar at carrier f0 sees a target with radial speed v as a tone at
f_d = 2 * v * f0 / c (about 160.9 Hz per m/s at 24.125 GHz). The board has a
single real IF output, so the sign of v is lost: approach and recede give
the same spectrum.

Walkers are modelled as a torso plus four limbs whose speed swings around the
body speed at the stride rate, following the classic point-scatterer gait
models used in the micro-Doppler literature (for example V. C. Chen,
"The Micro-Doppler Effect in Radar", Artech House). Rigid objects are a
single scatterer. Mains hum (50 and 100 Hz), white noise and ADC
quantisation and clipping are added.

Numbers marked ASSUMPTION are starting guesses. Calibrate them from the
analog front-end bench test (T3) and real recordings before relying on them.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import numpy.typing as npt
from scipy import signal

from dragonfly.sim.scene import FloatArray, PathTarget, Scene, TargetKind

C = 299_792_458.0
F0_HZ = 24.125e9
HZ_PER_MPS = 2.0 * F0_HZ / C  # ~160.9 Hz per m/s


@dataclass(frozen=True)
class Scatterer:
    """One body part: reflectivity, speed-swing amplitude (fraction of body
    speed) and phase (in cycles of the stride)."""

    amplitude: float
    swing: float
    phase: float


# ASSUMPTION: simplified gait. Legs swing hardest, arms less, in antiphase.
WALKER_PARTS: tuple[Scatterer, ...] = (
    Scatterer(1.00, 0.0, 0.0),  # torso
    Scatterer(0.30, 1.2, 0.0),  # left leg
    Scatterer(0.30, 1.2, 0.5),  # right leg
    Scatterer(0.12, 0.6, 0.5),  # left arm
    Scatterer(0.12, 0.6, 0.0),  # right arm
)
RIGID_PARTS: tuple[Scatterer, ...] = (Scatterer(1.0, 0.0, 0.0),)


@dataclass(frozen=True)
class CDM324Params:
    fs_hz: float = 4000.0
    f0_hz: float = F0_HZ
    beam_half_power_deg: float = 40.0  # ASSUMPTION
    stride_hz_per_mps: float = 0.65  # ASSUMPTION: ~0.9 Hz stride at 1.4 m/s
    reference_range_m: float = 3.0
    signal_at_reference: float = 0.25  # ASSUMPTION: fraction of ADC full scale
    noise_rms: float = 0.004  # ASSUMPTION: fraction of full scale
    hum_50_amplitude: float = 0.003  # ASSUMPTION
    hum_100_amplitude: float = 0.0015  # ASSUMPTION
    highpass_hz: float = 20.0  # report section 7.1
    lowpass_hz: float = 1200.0  # report section 7.1
    adc_bits: int = 12
    min_range_m: float = 0.3


@dataclass(frozen=True)
class CDM324Recording:
    fs_hz: float
    t: FloatArray
    adc: npt.NDArray[np.int16]
    """Raw ADC codes, 0 to 2**bits - 1, centred on mid-scale."""
    adc_bits: int = 12
    radial_mps: dict[str, FloatArray] = field(default_factory=dict)
    """Ground-truth body radial speed per target (positive = receding)."""

    @property
    def volts_normalised(self) -> FloatArray:
        """ADC codes mapped to -1..1 around mid-scale."""
        half = float(2 ** (self.adc_bits - 1))
        out: FloatArray = (self.adc.astype(np.float64) - half) / half
        return out


class CDM324Simulator:
    def __init__(self, scene: Scene, params: CDM324Params | None = None, seed: int = 0) -> None:
        self.scene = scene
        self.p = params or CDM324Params()
        self.rng = np.random.default_rng(seed)

    def _target_if(self, tg: PathTarget, t: FloatArray) -> tuple[FloatArray, FloatArray]:
        p = self.p
        present, x, y, vx, vy = tg.sample(t)
        r = np.maximum(np.hypot(x, y), p.min_range_m)
        speed = np.hypot(vx, vy)
        v_r = (x * vx + y * vy) / r
        # Fraction of along-track motion that is radial: limbs swing along track.
        aspect = np.divide(v_r, speed, out=np.zeros_like(v_r), where=speed > 1e-9)
        az = np.degrees(np.arctan2(x, y))
        beam = np.exp(-np.log(2.0) * (az / p.beam_half_power_deg) ** 2) * (y > 0)
        gain = p.signal_at_reference * (p.reference_range_m / r) ** 2 * np.sqrt(tg.rcs) * beam
        parts = WALKER_PARTS if tg.kind is TargetKind.WALKER else RIGID_PARTS
        stride_phase = 2 * np.pi * np.cumsum(p.stride_hz_per_mps * speed) / p.fs_hz
        k = 2.0 * p.f0_hz / C
        out = np.zeros_like(t)
        start_phase = self.rng.uniform(0, 2 * np.pi, size=len(parts))
        for part, phi0 in zip(parts, start_phase, strict=True):
            v_part = v_r + part.swing * speed * aspect * np.sin(
                stride_phase + 2 * np.pi * part.phase
            )
            phase = 2 * np.pi * k * np.cumsum(v_part) / p.fs_hz + phi0
            out += part.amplitude * np.cos(phase)
        return out * gain * present, v_r * present

    def record(self, duration_s: float | None = None) -> CDM324Recording:
        p = self.p
        duration = self.scene.duration if duration_s is None else duration_s
        n = int(round(duration * p.fs_hz))
        t = np.arange(n) / p.fs_hz
        x = np.zeros(n)
        truth: dict[str, FloatArray] = {}
        for tg in self.scene.targets:
            contrib, v_r = self._target_if(tg, t)
            x += contrib
            truth[tg.name] = v_r
        hum_phase = self.rng.uniform(0, 2 * np.pi, size=2)
        x += p.hum_50_amplitude * np.sin(2 * np.pi * 50 * t + hum_phase[0])
        x += p.hum_100_amplitude * np.sin(2 * np.pi * 100 * t + hum_phase[1])
        x += self.rng.normal(0.0, p.noise_rms, size=n)
        sos = signal.butter(
            2, [p.highpass_hz, p.lowpass_hz], btype="bandpass", fs=p.fs_hz, output="sos"
        )
        x = signal.sosfilt(sos, x)
        full = 2**p.adc_bits
        codes = np.clip(np.round(full / 2 + x * full / 2), 0, full - 1).astype(np.int16)
        return CDM324Recording(fs_hz=p.fs_hz, t=t, adc=codes, adc_bits=p.adc_bits, radial_mps=truth)
