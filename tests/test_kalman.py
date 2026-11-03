# SPDX-License-Identifier: Apache-2.0
import math

import numpy as np
import pytest

from dragonfly.track.kalman import (
    H,
    KalmanCV,
    polar_measurement_noise,
    process_noise,
    transition,
)


def test_transition_moves_position_by_velocity():
    x = transition(0.5) @ np.array([1.0, 2.0, 2.0, -4.0])
    assert x == pytest.approx([2.0, 0.0, 2.0, -4.0])


def test_process_noise_matches_appendix_a():
    q = process_noise(0.1, 1.0)
    assert q[0, 0] == pytest.approx(0.1**4 / 4)
    assert q[0, 2] == pytest.approx(0.1**3 / 2)
    assert q[2, 2] == pytest.approx(0.1**2)
    assert np.allclose(q, q.T)


def test_polar_noise_is_radial_and_cross_range():
    r = polar_measurement_noise(0.0, 4.0, 0.15, math.radians(2.0))
    assert r[1, 1] == pytest.approx(0.15**2)  # along the line of sight
    assert r[0, 0] == pytest.approx((4.0 * math.radians(2.0)) ** 2)  # cross-range
    assert r[0, 1] == pytest.approx(0.0, abs=1e-12)
    r45 = polar_measurement_noise(3.0, 3.0, 0.15, math.radians(2.0))
    assert np.all(np.linalg.eigvalsh(r45) > 0)


def test_rejects_bad_shapes_and_negative_dt():
    with pytest.raises(ValueError):
        KalmanCV(np.zeros(3), np.eye(4))
    kf = KalmanCV(np.zeros(4), np.eye(4))
    with pytest.raises(ValueError):
        kf.predict(-0.1, 1.0)


def test_converges_on_constant_velocity_target_and_is_consistent():
    rng = np.random.default_rng(0)
    truth = np.array([-2.0, 3.0, 1.0, 0.2])
    kf = KalmanCV(np.array([-2.0, 3.0, 0.0, 0.0]), np.diag([0.1, 0.1, 4.0, 4.0]))
    r = np.diag([0.04, 0.04])
    nees = []
    q = process_noise(0.1, 0.5)
    for k in range(400):
        truth = transition(0.1) @ truth + rng.multivariate_normal(np.zeros(4), q)
        kf.predict(0.1, 0.5)
        z = H @ truth + rng.multivariate_normal([0, 0], r)
        kf.update(z, r)
        if k > 50:
            e = truth - kf.x
            nees.append(e @ np.linalg.solve(kf.P, e))
    assert kf.x[2:] == pytest.approx(truth[2:], abs=0.5)
    # Average NEES of a consistent 4-state filter is about 4.
    assert 2.5 < np.mean(nees) < 6.0
    assert np.allclose(kf.P, kf.P.T)
    assert np.all(np.linalg.eigvalsh(kf.P) > 0)


def test_predicted_position_leads_by_velocity():
    kf = KalmanCV(np.array([1.0, 2.0, 1.0, -1.0]), np.eye(4))
    assert kf.predicted_position(0.25) == pytest.approx((1.25, 1.75))
