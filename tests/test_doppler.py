# SPDX-License-Identifier: Apache-2.0
import numpy as np
import pytest

from dragonfly.analysis.velocity import score
from dragonfly.dsp.doppler import DopplerConfig, DopplerEstimator, DopplerResult, SpeedSmoother
from dragonfly.sim.cdm324 import CDM324Params, CDM324Simulator
from dragonfly.sim.scene import PathTarget, Scene, TargetKind

CFG = DopplerConfig()


def radial(speed, kind=TargetKind.WALKER, duration=6.0, start=None, lead_in=1.0):
    """Empty room for ``lead_in`` seconds, then a target moving toward the radar."""
    start = start if start is not None else 1.0 + speed * duration
    end = start - speed * duration
    wps = ((lead_in, 0.0, start), (lead_in + duration, 0.0, end))
    return Scene((PathTarget("t", wps, kind=kind),))


def run(scene, params=None, seed=0, smooth=False):
    rec = CDM324Simulator(scene, params, seed=seed).record(duration_s=scene.duration + 0.5)
    results = list(DopplerEstimator(CFG).run(rec.volts_normalised))
    if smooth:
        sm = SpeedSmoother()
        results = [sm.update(r) for r in results]
    truth = rec.radial_mps["t"]
    return results, score(results, truth, CFG)


def test_bin_spacing_matches_report():
    assert CFG.bin_hz == pytest.approx(3.906, abs=0.001)
    assert CFG.hop / CFG.fs_hz == pytest.approx(0.128)


@pytest.mark.parametrize("speed", [0.2, 0.5, 1.0, 1.4, 2.0, 3.0, 5.0])
def test_rigid_target_speed_accuracy(speed):
    duration = min(6.0, 7.0 / speed)
    _, s = run(radial(speed, TargetKind.RIGID, duration=duration, start=1.0 + speed * duration))
    assert s.detection_rate > 0.9, s.summary()
    assert s.mae_mps < 0.03, s.summary()


@pytest.mark.parametrize("speed", [0.5, 1.0, 1.4, 2.0, 3.0])
@pytest.mark.parametrize("seed", [0, 1, 2])
def test_smoothed_walker_speed_meets_proposed_t4_tolerance(speed, seed):
    # Proposed T4 tolerance: mean absolute error <= 0.2 m/s against walking speed.
    d = min(8.0, 9.0 / speed)
    _, s = run(radial(speed, duration=d, start=1.0 + speed * d), seed=seed, smooth=True)
    assert s.detection_rate > 0.85, s.summary()
    assert s.mae_mps < 0.15, s.summary()


def test_smoothing_reduces_walker_error():
    scene = radial(2.0, duration=4.0, start=9.0)
    _, raw = run(scene, seed=4)
    _, smooth = run(scene, seed=4, smooth=True)
    assert smooth.mae_mps < 0.7 * raw.mae_mps


def test_smoother_median_and_reset():
    sm = SpeedSmoother(n=3, max_gap=1)
    hit = lambda v: DopplerResult(0.0, True, 0.0, v, 20.0)  # noqa: E731
    miss = DopplerResult(0.0, False, 0.0, 0.0, 0.0)
    assert [sm.update(hit(v)).speed_mps for v in (1.0, 3.0, 2.0, 10.0)] == [1.0, 2.0, 2.0, 3.0]
    assert sm.update(miss) is miss
    sm.update(miss)  # second miss exceeds max_gap: history cleared
    assert sm.update(hit(5.0)).speed_mps == 5.0
    with pytest.raises(ValueError):
        SpeedSmoother(n=0)


def test_empty_room_with_hum_gives_few_false_alarms():
    scene = Scene((PathTarget("t", ((0.0, 0.0, 3.0), (20.0, 0.0, 3.0))),))  # never moves
    rec = CDM324Simulator(scene, CDM324Params(hum_50_amplitude=0.02), seed=1).record()
    results = list(DopplerEstimator(CFG).run(rec.volts_normalised))
    fa = np.mean([r.detected for r in results])
    assert fa < 0.02


def test_target_at_hum_frequency_still_detected():
    # 50 Hz hum equals ~0.31 m/s. A real target at that speed must still be seen.
    speed = 50.0 / CFG.hz_per_mps
    _, s = run(radial(speed, TargetKind.RIGID, duration=6.0, start=3.5), seed=2)
    assert s.detection_rate > 0.8, s.summary()
    assert s.mae_mps < 0.03, s.summary()


def test_interpolation_beats_bin_resolution():
    fs, n = CFG.fs_hz, CFG.n_fft
    est = DopplerEstimator(CFG)
    t = np.arange(n) / fs
    noise = np.random.default_rng(0).normal(0, 1e-3, n)
    for _ in range(CFG.warmup_frames):
        est.process(noise)
    f_true = 161.7  # between bins
    r = est.process(0.3 * np.cos(2 * np.pi * f_true * t) + noise)
    assert r.detected
    assert abs(r.peak_hz - f_true) < 0.2 * CFG.bin_hz


def test_no_detection_during_warmup():
    est = DopplerEstimator(CFG)
    t = np.arange(CFG.n_fft) / CFG.fs_hz
    r = est.process(np.cos(2 * np.pi * 200 * t))
    assert not r.detected


@pytest.mark.parametrize("bad", [{"n_fft": 1000}, {"hop": 0}, {"hop": 2048}])
def test_invalid_config_rejected(bad):
    with pytest.raises(ValueError):
        DopplerEstimator(DopplerConfig(**bad))


def test_wrong_frame_length_rejected():
    with pytest.raises(ValueError):
        DopplerEstimator(CFG).process(np.zeros(10))


def test_score_rejects_mismatched_lengths():
    with pytest.raises(ValueError):
        score([], np.zeros(CFG.n_fft * 3), CFG)
