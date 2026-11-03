# SPDX-License-Identifier: Apache-2.0
import math

import numpy as np
import pytest

from dragonfly.io.rd03d import decode_frame, encode_frame
from dragonfly.sim.rd03d import RD03DParams, RD03DSimulator, radial_speed
from dragonfly.sim.scenarios import SCENARIOS, rigid_roll, s5_stop_and_go, t1_walker
from dragonfly.sim.scene import PathTarget, Scene, State


def test_path_interpolation_and_velocity():
    p = PathTarget("w", ((0.0, 0.0, 1.0), (2.0, 2.0, 1.0)))
    s = p.state(1.0)
    assert s == State(1.0, 1.0, 1.0, 0.0)
    assert p.state(-0.1) is None
    assert p.state(2.1) is None


@pytest.mark.parametrize("wps", [((0.0, 0.0, 1.0),), ((0.0, 0.0, 1.0), (0.0, 1.0, 1.0))])
def test_path_validation(wps):
    with pytest.raises(ValueError):
        PathTarget("w", wps)


def test_radial_speed_sign():
    assert radial_speed(State(0, 2, 0, 1)) == pytest.approx(1.0)  # receding
    assert radial_speed(State(0, 2, 0, -1)) == pytest.approx(-1.0)  # approaching
    assert radial_speed(State(0, 2, 1, 0)) == pytest.approx(0.0)  # tangential
    assert radial_speed(State(0, 0, 1, 0)) == 0.0


@pytest.mark.parametrize("name", sorted(SCENARIOS))
def test_scenarios_build_and_run(name):
    frames = list(RD03DSimulator(SCENARIOS[name](), seed=1).frames())
    assert len(frames) > 20
    for sf in frames:
        assert len(sf.frame.targets) <= 3
        # Every frame survives the wire format.
        assert len(decode_frame(encode_frame(sf.frame)).targets) == len(sf.frame.targets)


def test_simulator_is_deterministic():
    a = [sf.frame for sf in RD03DSimulator(SCENARIOS["S1"](), seed=7).frames()]
    b = [sf.frame for sf in RD03DSimulator(SCENARIOS["S1"](), seed=7).frames()]
    assert a == b


def test_range_noise_matches_datasheet_sigma():
    params = RD03DParams(false_alarm_rate=0.0, azimuth_sigma_deg=0.0)
    scene = t1_walker(3.0, 0.0, repeats=200)
    errors = []
    for sf in RD03DSimulator(scene, params, seed=3).frames():
        if sf.frame.targets and sf.truth:
            s = sf.truth[0].state
            errors.append(sf.frame.targets[0].range_m - math.hypot(s.x, s.y))
    errors_arr = np.array(errors)
    assert len(errors_arr) > 500
    assert abs(errors_arr.mean()) < 0.03
    assert errors_arr.std() == pytest.approx(0.15, rel=0.15)


def test_stationary_target_disappears():
    params = RD03DParams(false_alarm_rate=0.0)
    for sf in RD03DSimulator(s5_stop_and_go(), params, seed=2).frames():
        for tt in sf.truth:
            if math.hypot(tt.state.vx, tt.state.vy) == 0.0:
                assert not tt.detected
                assert not sf.frame.targets


def test_outside_field_of_view_not_detected():
    params = RD03DParams(false_alarm_rate=0.0)
    scene = t1_walker(3.0, 75.0)
    assert not any(sf.frame.targets for sf in RD03DSimulator(scene, params).frames())


def test_detection_probability_falls_with_range():
    params = RD03DParams(false_alarm_rate=0.0)

    def rate(r):
        frames = list(RD03DSimulator(t1_walker(r, 0.0, repeats=40), params, seed=5).frames())
        return sum(bool(sf.frame.targets) for sf in frames) / len(frames)

    assert rate(3.0) > 0.9
    assert rate(7.5) < rate(3.0)
    assert rate(9.5) == 0.0


def test_close_targets_merge():
    params = RD03DParams(false_alarm_rate=0.0, p_detect_reliable=1.0)
    a = PathTarget("a", ((0.0, 0.0, 3.0), (5.0, 0.0, 1.0)))
    b = PathTarget("b", ((0.0, 0.1, 3.3), (5.0, 0.1, 1.3)))
    frames = list(RD03DSimulator(Scene((a, b)), params, seed=0).frames())
    assert all(len(sf.frame.targets) <= 1 for sf in frames)


def test_false_alarms_appear_at_expected_rate():
    params = RD03DParams(false_alarm_rate=0.5)
    scene = t1_walker(9.5, 0.0, repeats=100)  # real target out of range
    frames = list(RD03DSimulator(scene, params, seed=4).frames())
    mean = np.mean([len(sf.frame.targets) for sf in frames])
    assert mean == pytest.approx(0.5, rel=0.2)


def test_rigid_scene():
    frames = list(RD03DSimulator(rigid_roll(), seed=0).frames())
    assert any(sf.frame.targets for sf in frames)
