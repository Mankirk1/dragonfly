# SPDX-License-Identifier: Apache-2.0
import math

import numpy as np
import pytest

from dragonfly.analysis.tracking import evaluate
from dragonfly.io.rd03d import Frame, Target
from dragonfly.sim.rd03d import RD03DParams, RD03DSimulator
from dragonfly.sim.scenarios import SCENARIOS, s1_crossing_slow, s5_stop_and_go, s6_two_walkers
from dragonfly.track.tracker import SystemState, Tracker, TrackState

EMPTY = Frame(())


def frame(*xy):
    return Frame(tuple(Target(x, y, 0.0, 0.75) for x, y in xy))


def test_starts_in_search():
    assert Tracker().update(0.0, EMPTY).state is SystemState.SEARCH


def test_confirms_after_three_hits_and_aims():
    tr = Tracker()
    states = [tr.update(0.1 * k, frame((0.1 * k, 3.0))).state for k in range(4)]
    assert states[:2] == [SystemState.TENTATIVE, SystemState.TENTATIVE]
    assert states[2] is SystemState.LOCKED
    out = tr.update(0.4, frame((0.4, 3.0)))
    assert out.aim_xy is not None


def test_single_false_alarm_never_locks():
    tr = Tracker()
    tr.update(0.0, frame((1.0, 4.0)))
    for k in range(1, 10):
        out = tr.update(0.1 * k, EMPTY)
    assert out.state is SystemState.SEARCH
    assert not tr.tracks


def test_coast_then_hold_then_delete():
    tr = Tracker()
    for k in range(5):
        tr.update(0.1 * k, frame((0.1 * k, 3.0)))
    seen = []
    t = 0.4
    while t < 6.0:
        t += 0.1
        seen.append((round(t, 1), tr.update(t, EMPTY).state))
    states = dict(seen)
    assert states[0.5] is SystemState.COAST
    assert states[1.6] is SystemState.HOLD
    assert states[5.5] is SystemState.SEARCH
    # In HOLD the aim point does not drift.
    tr2 = Tracker()
    for k in range(5):
        tr2.update(0.1 * k, frame((0.1 * k, 3.0)))
    for k in range(5, 25):
        out = tr2.update(0.1 * k, EMPTY)
    a = out.aim_xy
    b = tr2.update(2.6, EMPTY).aim_xy
    assert a == pytest.approx(b)


def test_held_track_ignores_one_stray_measurement():
    tr = Tracker()
    for k in range(5):
        tr.update(0.1 * k, frame((0.1 * k, 3.0)))
    for k in range(5, 20):
        out = tr.update(0.1 * k, EMPTY)
    assert out.state is SystemState.HOLD
    held = out.aim_xy
    out = tr.update(2.0, frame((2.0, 3.5)))  # one clutter report nearby
    assert out.state is SystemState.HOLD
    assert out.aim_xy == pytest.approx(held, abs=0.05)


def test_two_targets_tracked_separately():
    tr = Tracker()
    for k in range(10):
        out = tr.update(0.1 * k, frame((-1.5, 3.0 + 0.05 * k), (1.5, 4.0 - 0.05 * k)))
    confirmed = [t for t in out.tracks if t.state is TrackState.LOCKED]
    assert len(confirmed) == 2


def test_primary_is_sticky():
    tr = Tracker()
    # Two targets; A nearer at first.
    for k in range(5):
        out = tr.update(0.1 * k, frame((-1.0, 3.0), (1.5, 3.3)))
    first = out.primary
    # B becomes ~0.9 m nearer, but only for 0.5 s: no switch.
    for k in range(5, 10):
        out = tr.update(0.1 * k, frame((-1.0, 3.0), (1.0, 2.0)))
    assert out.primary == first
    # After more than 1 s nearer, B takes over.
    for k in range(10, 22):
        out = tr.update(0.1 * k, frame((-1.0, 3.0), (1.0, 2.0)))
    assert out.primary != first


def test_follows_simulated_crossing_with_lock_quickly():
    tr = Tracker()
    first_lock = None
    for sf in RD03DSimulator(s1_crossing_slow(), seed=1).frames():
        out = tr.update(sf.t, sf.frame)
        if out.state is SystemState.LOCKED and first_lock is None:
            first_lock = sf.t
    assert first_lock is not None and first_lock < 0.5


def test_stop_and_go_reaches_hold_and_relocks():
    seen = set()
    tr = Tracker()
    for sf in RD03DSimulator(s5_stop_and_go(stop_s=2.5), seed=2).frames():
        seen.add(tr.update(sf.t, sf.frame).state)
    assert {SystemState.LOCKED, SystemState.COAST, SystemState.HOLD} <= seen


def test_capacity_limit():
    tr = Tracker()
    many = frame(*[(x, 4.0) for x in (-3.0, -1.5, 0.0, 1.5, 3.0)])
    tr.update(0.0, many)
    tr.update(0.1, frame((-2.5, 6.0), (2.5, 6.0)))
    assert len(tr.tracks) <= tr.cfg.max_tracks


# Simulated A/B regression thresholds (pan error in degrees, mean over 6 seeds,
# 250 ms latency). Measured when written: S1 2.0, S2 2.1, S3 2.4, S4 2.0,
# S5 3.5, S6 2.5. Thresholds leave ~25% margin; a change that breaks them has
# made tracking worse and must explain why.
RMS_LIMIT = {"S1": 2.5, "S2": 2.7, "S3": 3.0, "S4": 2.5, "S5": 4.4, "S6": 3.1}


@pytest.mark.parametrize("name", sorted(SCENARIOS))
def test_simulated_pointing_error_regression(name):
    runs = [evaluate(SCENARIOS[name](), latency_s=0.25, seed=s) for s in range(6)]
    rms = np.mean([r.filtered.rms_deg for r in runs])
    assert rms < RMS_LIMIT[name], f"{name}: {rms:.2f} deg"
    assert all(r.lock_losses == 0 for r in runs)


@pytest.mark.parametrize("name", ["S1", "S2", "S4", "S5", "S6"])
def test_filter_beats_unfiltered_baseline(name):
    runs = [evaluate(SCENARIOS[name](), latency_s=0.25, seed=s) for s in range(6)]
    f = np.mean([r.filtered.rms_deg for r in runs])
    u = np.mean([r.unfiltered.rms_deg for r in runs])
    assert f < u


def test_two_walkers_keep_one_primary_mostly():
    runs = [evaluate(s6_two_walkers(), seed=s) for s in range(6)]
    assert np.mean([r.primary_switches for r in runs]) <= 1.5


def test_tracking_is_robust_to_heavy_clutter():
    params = RD03DParams(false_alarm_rate=0.3)
    runs = [evaluate(s1_crossing_slow(), radar_params=params, seed=s) for s in range(4)]
    assert np.mean([r.filtered.rms_deg for r in runs]) < 4.0
    assert all(math.isfinite(r.time_to_lock_s) for r in runs)
