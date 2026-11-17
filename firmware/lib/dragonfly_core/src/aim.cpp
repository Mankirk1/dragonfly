// SPDX-License-Identifier: Apache-2.0
#include "aim.hpp"

#include <algorithm>
#include <cmath>

namespace df {
namespace {
constexpr float kDegPerRad = 57.29577951308232f;
float clampf(float v, float lo, float hi) { return std::min(std::max(v, lo), hi); }
}  // namespace

AimSolution aim_solve(float x_m, float y_m, const AimConfig& cfg) {
    const float dx = x_m - cfg.laser_offset_x_m;
    const float dy = y_m - cfg.laser_offset_y_m;
    const float r_h = std::max(std::hypot(dx, dy), cfg.min_range_m);
    const float h = std::min(cfg.aim_height_m, cfg.max_aim_height_m);
    return AimSolution{std::atan2(dx, dy) * kDegPerRad,
                       std::atan2(h - cfg.laser_height_m, r_h) * kDegPerRad, r_h};
}

float beam_height_at(float range_m, float tilt_deg, float laser_height_m) {
    return laser_height_m + range_m * std::tan(tilt_deg / kDegPerRad);
}

ServoAxis::ServoAxis(const ServoLimits& lim, float start_deg)
    : lim_(lim), angle_(clampf(start_deg, lim.min_deg, lim.max_deg)) {}

float ServoAxis::step(float target_deg, float dt_s) {
    const float target = clampf(target_deg, lim_.min_deg, lim_.max_deg);
    if (std::fabs(target - angle_) <= lim_.deadband_deg) return angle_;
    const float desired = angle_ + (1.0f - lim_.smoothing) * (target - angle_);
    const float max_step = lim_.max_rate_deg_s * std::max(dt_s, 0.0f);
    const float delta = clampf(desired - angle_, -max_step, max_step);
    angle_ = clampf(angle_ + delta, lim_.min_deg, lim_.max_deg);
    return angle_;
}

float nominal_pulse_us(float angle_deg, float min_deg, float max_deg, float min_us,
                       float max_us) {
    const float a = clampf(angle_deg, min_deg, max_deg);
    return min_us + (a - min_deg) / (max_deg - min_deg) * (max_us - min_us);
}

}  // namespace df
