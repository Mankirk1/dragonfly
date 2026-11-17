# SPDX-License-Identifier: Apache-2.0
import numpy as np
import pytest

from dragonfly.classify.dataset import CLASSES, TargetClass, make_dataset
from dragonfly.classify.features import FEATURE_NAMES, extract, spectrogram
from dragonfly.classify.model import MajorityVote, bootstrap_ci, evaluate
from dragonfly.classify.report import main as report_main
from dragonfly.dsp.doppler import DopplerConfig
from dragonfly.sim.cdm324 import CDM324Params, CDM324Simulator
from dragonfly.sim.scene import PathTarget, Scene, TargetKind

QUIET = CDM324Params(noise_rms=0.002, hum_50_amplitude=0.0, hum_100_amplitude=0.0)


def features_for(kind, speed=1.2, seed=0):
    scene = Scene((PathTarget("t", ((0.0, 0.0, 5.5), (3.5, 0.0, 5.5 - 3.5 * speed)), kind=kind),))
    rec = CDM324Simulator(scene, QUIET, seed=seed).record()
    return extract(rec.volts_normalised)


@pytest.fixture(scope="module")
def small_dataset():
    return make_dataset(sessions=4, clips_per_class=2, clip_s=4.0, seed=3)


def test_feature_shape_and_names():
    x = features_for(TargetKind.WALKER)
    assert x.shape[1] == len(FEATURE_NAMES) == 8
    assert len(x) >= 3
    assert np.all(np.isfinite(x))


def test_too_short_signal_gives_no_windows():
    assert extract(np.zeros(2000)).shape == (0, 8)
    p, f = spectrogram(np.zeros(100), DopplerConfig())
    assert p.size == 0 and f.size == 0


def test_walker_features_differ_from_rigid():
    w = features_for(TargetKind.WALKER).mean(axis=0)
    r = features_for(TargetKind.RIGID).mean(axis=0)
    i = {n: k for k, n in enumerate(FEATURE_NAMES)}
    assert w[i["bandwidth_hz"]] > 2 * r[i["bandwidth_hz"]]
    assert w[i["peak_to_mean_db"]] < r[i["peak_to_mean_db"]]
    # Torso line sits near the body speed in both cases (~1.2 m/s ~ 193 Hz).
    assert w[i["peak_hz"]] == pytest.approx(193, abs=40)
    assert r[i["peak_hz"]] == pytest.approx(193, abs=10)


def test_dataset_is_grouped_by_session_and_clip(small_dataset):
    ds = small_dataset
    assert set(np.unique(ds.session)) == {0, 1, 2, 3}
    assert set(np.unique(ds.y)) == set(range(len(CLASSES)))
    # Every clip belongs to exactly one session and one class.
    for c in np.unique(ds.clip):
        assert len(np.unique(ds.session[ds.clip == c])) == 1
        assert len(np.unique(ds.y[ds.clip == c])) == 1
    assert CLASSES[0] is TargetClass.WALKER


def test_evaluation_uses_only_held_out_sessions(small_dataset):
    ev = evaluate(small_dataset, test_sessions=[3])
    assert ev.model in ev.cv_accuracy
    assert ev.confusion.sum() == int((small_dataset.session == 3).sum())
    lo, hi = ev.test_ci95
    assert 0.0 <= lo <= ev.test_accuracy <= hi <= 1.0
    # Better than chance on three classes, even on a tiny synthetic set.
    assert ev.test_accuracy > 0.5


def test_evaluation_needs_both_splits(small_dataset):
    with pytest.raises(ValueError):
        evaluate(small_dataset, test_sessions=[0, 1, 2, 3])


def test_bootstrap_ci_resamples_clips():
    y = np.array([0, 0, 1, 1])
    assert bootstrap_ci(y, y, np.array([0, 0, 1, 1]), n=50) == (1.0, 1.0)


def test_majority_vote():
    mv = MajorityVote(3)
    assert [mv.update(v) for v in (0, 1, 1, 0, 0)] == [0, 0, 1, 1, 0]
    with pytest.raises(ValueError):
        MajorityVote(0)


def test_report_runs(capsys):
    assert report_main(["--sessions", "3", "--clips-per-class", "1", "--test-sessions", "2"]) == 0
    out = capsys.readouterr().out
    assert "not a B7 result" in out
