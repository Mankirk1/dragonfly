# SPDX-License-Identifier: Apache-2.0
"""Constant-velocity Kalman filter in the radar's horizontal plane.

State ``[x, y, vx, vy]`` (metres, m/s), measurement ``[x, y]``. Matrices
follow Appendix A of the project report. The process noise is the discrete
white-noise-acceleration model with spectral density ``sigma_a**2``.

Measurement noise comes from the radar's polar errors: range error
``sigma_r`` and bearing error ``sigma_az``, rotated into x/y. This makes the
cross-range error grow with distance, as it does on the real sensor.
"""

from __future__ import annotations

import math

import numpy as np
import numpy.typing as npt

Array = npt.NDArray[np.float64]

H = np.array([[1.0, 0.0, 0.0, 0.0], [0.0, 1.0, 0.0, 0.0]])


def transition(dt: float) -> Array:
    return np.array(
        [[1.0, 0.0, dt, 0.0], [0.0, 1.0, 0.0, dt], [0.0, 0.0, 1.0, 0.0], [0.0, 0.0, 0.0, 1.0]]
    )


def process_noise(dt: float, sigma_a: float) -> Array:
    q4, q3, q2 = dt**4 / 4, dt**3 / 2, dt**2
    return sigma_a**2 * np.array(
        [[q4, 0.0, q3, 0.0], [0.0, q4, 0.0, q3], [q3, 0.0, q2, 0.0], [0.0, q3, 0.0, q2]]
    )


def polar_measurement_noise(x: float, y: float, sigma_r: float, sigma_az_rad: float) -> Array:
    """Cartesian covariance of a measurement with polar range/bearing errors."""
    r = max(math.hypot(x, y), 1e-3)
    az = math.atan2(x, y)
    # Unit vectors: radial (along line of sight) and cross-range.
    ur = np.array([math.sin(az), math.cos(az)])
    uc = np.array([math.cos(az), -math.sin(az)])
    out: Array = sigma_r**2 * np.outer(ur, ur) + (r * sigma_az_rad) ** 2 * np.outer(uc, uc)
    return out


class KalmanCV:
    def __init__(self, x0: Array, p0: Array) -> None:
        if x0.shape != (4,) or p0.shape != (4, 4):
            raise ValueError("state must be shape (4,) and covariance (4, 4)")
        self.x = x0.astype(np.float64).copy()
        self.P = p0.astype(np.float64).copy()

    def predict(self, dt: float, sigma_a: float) -> None:
        if dt < 0:
            raise ValueError("dt must be non-negative")
        f = transition(dt)
        self.x = f @ self.x
        self.P = f @ self.P @ f.T + process_noise(dt, sigma_a)

    def innovation(self, z: Array, r: Array) -> tuple[Array, Array]:
        y = z - H @ self.x
        s = H @ self.P @ H.T + r
        return y, s

    def mahalanobis2(self, z: Array, r: Array) -> float:
        y, s = self.innovation(z, r)
        return float(y @ np.linalg.solve(s, y))

    def update(self, z: Array, r: Array) -> float:
        """Apply a measurement; returns the normalised innovation squared."""
        y, s = self.innovation(z, r)
        k = self.P @ H.T @ np.linalg.inv(s)
        self.x = self.x + k @ y
        # Joseph form: keeps P symmetric and positive definite.
        i_kh = np.eye(4) - k @ H
        self.P = i_kh @ self.P @ i_kh.T + k @ r @ k.T
        return float(y @ np.linalg.solve(s, y))

    def predicted_position(self, lead_s: float) -> tuple[float, float]:
        return float(self.x[0] + self.x[2] * lead_s), float(self.x[1] + self.x[3] * lead_s)
