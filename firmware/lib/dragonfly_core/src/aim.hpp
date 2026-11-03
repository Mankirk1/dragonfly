// SPDX-License-Identifier: Apache-2.0
// Aim solver and servo command shaping. Port of src/dragonfly/control/aim.py.
#pragma once

namespace df {

struct AimConfig {
    float laser_offset_x_m = 0.0f;
    float laser_offset_y_m = 0.0f;
    float laser_height_m = 1.0f;
    float aim_height_m = 1.0f;
    float max_aim_height_m = 1.2f;
    float min_range_m = 0.3f;
};

struct AimSolution {
    float pan_deg;
    float tilt_deg;
    float horizontal_range_m;
};

AimSolution aim_solve(float x_m, float y_m, const AimConfig& cfg);
float beam_height_at(float range_m, float tilt_deg, float laser_height_m);

struct ServoLimits {
    float min_deg;
    float max_deg;
    float max_rate_deg_s = 300.0f;
    float deadband_deg = 0.5f;
    float smoothing = 0.5f;
};

class ServoAxis {
public:
    explicit ServoAxis(const ServoLimits& lim, float start_deg = 0.0f);
    float step(float target_deg, float dt_s);
    float angle() const { return angle_; }

private:
    ServoLimits lim_;
    float angle_;
};

// Nominal MG996R mapping, 1500 us centre and ~10 us per degree, before calibration.
float nominal_pulse_us(float angle_deg, float min_deg, float max_deg, float min_us, float max_us);

}  // namespace df
