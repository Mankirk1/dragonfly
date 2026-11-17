# SPDX-License-Identifier: Apache-2.0
import math

import pytest
from hypothesis import given
from hypothesis import strategies as st

from dragonfly.control.aim import (
    DEFAULT_PAN,
    DEFAULT_TILT,
    AimConfig,
    ServoAxis,
    ServoCalibration,
    ServoLimits,
    beam_height_at,
    solve,
)


def test_straight_ahead_is_zero_pan():
    s = solve(0.0, 3.0, AimConfig())
    assert s.pan_deg == pytest.approx(0.0)
    assert s.tilt_deg == pytest.approx(0.0)


def test_pan_sign_and_parallax_correction():
    assert solve(1.0, 1.0, AimConfig()).pan_deg == pytest.approx(45.0)
    # Laser mounted 0.2 m right of the radar: a target straight ahead of the
    # radar is to the laser's left.
    s = solve(0.0, 3.0, AimConfig(laser_offset_x_m=0.2))
    assert s.pan_deg == pytest.approx(-math.degrees(math.atan2(0.2, 3.0)))


def test_tilt_from_aim_height():
    s = solve(0.0, 4.0, AimConfig(laser_height_m=0.8, aim_height_m=1.2))
    assert s.tilt_deg == pytest.approx(math.degrees(math.atan2(0.4, 4.0)))
    assert beam_height_at(4.0, s.tilt_deg, 0.8) == pytest.approx(1.2)


def test_aim_height_above_cap_rejected():
    with pytest.raises(ValueError):
        AimConfig(aim_height_m=1.5)


@given(st.floats(-8, 8), st.floats(0.01, 8), st.floats(0.3, 1.2), st.floats(0.3, 1.2))
def test_beam_never_above_cap_at_target(x, y, laser_h, aim_h):
    cfg = AimConfig(laser_height_m=laser_h, aim_height_m=min(aim_h, 1.2))
    s = solve(x, y, cfg)
    assert beam_height_at(s.horizontal_range_m, s.tilt_deg, laser_h) <= 1.2 + 1e-9


def test_calibration_interpolates_and_clamps():
    assert DEFAULT_PAN.pulse_us(0.0) == 1500.0
    assert DEFAULT_PAN.pulse_us(45.0) == pytest.approx(1950.0)
    assert DEFAULT_PAN.pulse_us(200.0) == 2400.0
    assert DEFAULT_TILT.pulse_us(-90.0) == 1050.0
    reversed_cal = ServoCalibration((-10.0, 10.0), (1600.0, 1400.0))
    assert reversed_cal.pulse_us(5.0) == pytest.approx(1450.0)


@pytest.mark.parametrize(
    "angles,pulses",
    [
        ((0.0,), (1500.0,)),
        ((0.0, 0.0), (1000.0, 2000.0)),
        ((0.0, 1.0), (1000.0, 1000.0)),
        ((0.0, 1.0, 2.0), (1000.0, 1500.0, 1200.0)),
        ((0.0, 1.0), (100.0, 2000.0)),
    ],
)
def test_bad_calibration_rejected(angles, pulses):
    with pytest.raises(ValueError):
        ServoCalibration(angles, pulses)


def test_servo_rate_limit_and_deadband():
    axis = ServoAxis(ServoLimits(-90, 90, max_rate_deg_s=100, deadband_deg=0.5, smoothing=0.0))
    assert axis.step(50.0, 0.02) == pytest.approx(2.0)  # 100 deg/s * 20 ms
    for _ in range(100):
        axis.step(50.0, 0.02)
    assert axis.angle == pytest.approx(50.0)
    assert axis.step(50.3, 0.02) == pytest.approx(50.0)  # inside dead band


def test_servo_clamps_to_travel():
    axis = ServoAxis(ServoLimits(-45, 45, max_rate_deg_s=1e6, smoothing=0.0))
    assert axis.step(90.0, 0.02) == 45.0
    assert axis.step(-90.0, 0.02) == -45.0


@given(st.lists(st.floats(-1000, 1000), min_size=1, max_size=50), st.floats(0.001, 0.1))
def test_servo_never_exceeds_limits_or_rate(targets, dt):
    lim = ServoLimits(-90, 90, max_rate_deg_s=300)
    axis = ServoAxis(lim)
    prev = axis.angle
    for t in targets:
        a = axis.step(t, dt)
        assert lim.min_deg <= a <= lim.max_deg
        assert abs(a - prev) <= lim.max_rate_deg_s * dt + 1e-9
        prev = a


@pytest.mark.parametrize("bad", [{"min_deg": 10, "max_deg": 0}, {"smoothing": 1.0}])
def test_bad_servo_limits_rejected(bad):
    kw = {"min_deg": -90.0, "max_deg": 90.0, **bad}
    with pytest.raises(ValueError):
        ServoAxis(ServoLimits(**kw))


def test_calibration_range():
    assert (DEFAULT_PAN.min_deg, DEFAULT_PAN.max_deg) == (-90.0, 90.0)
