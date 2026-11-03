# SPDX-License-Identifier: Apache-2.0
import numpy as np
import pytest

from dragonfly.sim.cdm324 import HZ_PER_MPS, CDM324Params, CDM324Simulator
from dragonfly.sim.scenarios import rigid_roll, s3_approach_recede
from dragonfly.sim.scene import PathTarget, Scene, TargetKind

QUIET = CDM324Params(noise_rms=0.0, hum_50_amplitude=0.0, hum_100_amplitude=0.0)


def radial_walk(speed, kind=TargetKind.WALKER, duration=8.0, start=6.0):
    end = start - speed * duration
    return Scene((PathTarget("t", ((0.0, 0.0, start), (duration, 0.0, end)), kind=kind),))


def spectrum(x, fs):
    w = np.hanning(len(x))
    mag = np.abs(np.fft.rfft((x - x.mean()) * w))
    return np.fft.rfftfreq(len(x), 1 / fs), mag


def test_hz_per_mps_matches_report():
    assert HZ_PER_MPS == pytest.approx(160.8, abs=0.3)


def test_vectorised_sampling_matches_scalar_state():
    p = PathTarget("w", ((0.0, 0.0, 1.0), (2.0, 2.0, 1.0), (3.0, 2.0, 3.0)))
    t = np.array([0.0, 0.5, 1.9, 2.5, 3.0, 4.0])
    present, x, y, vx, vy = p.sample(t)
    for i, ti in enumerate(t):
        s = p.state(float(ti))
        if s is None:
            assert present[i] == 0.0
        else:
            assert (x[i], y[i]) == pytest.approx((s.x, s.y))
            if ti not in (2.0, 3.0):  # velocity at a waypoint is one-sided
                assert (vx[i], vy[i]) == pytest.approx((s.vx, s.vy))


@pytest.mark.parametrize("speed", [0.3, 1.0, 2.0, 4.0])
def test_rigid_target_peak_at_doppler_frequency(speed):
    rec = CDM324Simulator(
        radial_walk(speed, TargetKind.RIGID, duration=1.0, start=3.0 + speed), QUIET
    ).record()
    f, mag = spectrum(rec.volts_normalised, rec.fs_hz)
    assert f[np.argmax(mag)] == pytest.approx(speed * HZ_PER_MPS, abs=4.0)


def test_walker_spectrum_is_wider_than_rigid():
    def bandwidth(kind):
        rec = CDM324Simulator(radial_walk(1.2, kind, duration=3.0, start=5.0), QUIET).record()
        f, mag = spectrum(rec.volts_normalised, rec.fs_hz)
        p = mag**2
        centroid = (f * p).sum() / p.sum()
        return np.sqrt(((f - centroid) ** 2 * p).sum() / p.sum())

    assert bandwidth(TargetKind.WALKER) > 3 * bandwidth(TargetKind.RIGID)


def test_hum_lines_present_without_targets():
    params = CDM324Params(noise_rms=0.0)
    scene = Scene((PathTarget("still", ((0.0, 0.0, 3.0), (4.0, 0.0, 3.0))),))
    rec = CDM324Simulator(scene, params).record()
    f, mag = spectrum(rec.volts_normalised, rec.fs_hz)
    peak = f[np.argmax(mag)]
    assert peak == pytest.approx(50.0, abs=2.0)


def test_stationary_target_gives_no_doppler_line():
    scene = Scene((PathTarget("still", ((0.0, 0.0, 2.0), (4.0, 0.0, 2.0))),))
    rec = CDM324Simulator(scene, QUIET).record()
    settled = rec.volts_normalised[2000:]
    assert np.abs(settled).max() < 2.0 / 2048  # quantisation level only


def test_adc_codes_in_range_and_clip():
    loud = CDM324Params(signal_at_reference=5.0)
    rec = CDM324Simulator(radial_walk(1.0, start=2.0, duration=1.0), loud).record()
    assert rec.adc.min() >= 0
    assert rec.adc.max() <= 4095
    assert (rec.adc == 4095).any()


def test_signal_falls_with_range():
    def rms(start):
        rec = CDM324Simulator(radial_walk(0.5, TargetKind.RIGID, 1.0, start), QUIET).record()
        return rec.volts_normalised.std()

    assert rms(2.0) > 3 * rms(4.5)


def test_deterministic_and_truth_reported():
    a = CDM324Simulator(s3_approach_recede(), seed=3).record()
    b = CDM324Simulator(s3_approach_recede(), seed=3).record()
    assert np.array_equal(a.adc, b.adc)
    v = a.radial_mps["walker"]
    assert v[: len(v) // 3].mean() == pytest.approx(-1.0, abs=0.01)  # approaching
    assert len(a.t) == len(a.adc) == len(v)


def test_rigid_roll_scene_runs():
    rec = CDM324Simulator(rigid_roll(), seed=1).record()
    assert rec.adc.std() > 10
