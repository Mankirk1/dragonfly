// SPDX-License-Identifier: Apache-2.0
#include "interlock.hpp"

#include <cmath>

namespace df {

const char* reason_name(Reason r) {
    switch (r) {
        case Reason::Ok: return "ok";
        case Reason::NotArmed: return "not_armed";
        case Reason::RearmRequired: return "rearm_required";
        case Reason::FaultLatched: return "fault_latched";
        case Reason::NotLocked: return "not_locked";
        case Reason::CoastTooLong: return "coast_too_long";
        case Reason::Range: return "range";
        case Reason::PanLimit: return "pan_limit";
        case Reason::HeightCap: return "height_cap";
        case Reason::BadInput: return "bad_input";
    }
    return "bad_input";
}

Reason Interlock::evaluate(const InterlockInputs& in) {
    const InterlockConfig& c = cfg_;
    const float nums[] = {in.telemetry_age_s, in.coast_time_s, in.target_range_m,
                          in.pan_deg,         in.aim_height_m, in.beam_height_at_target_m};
    bool bad = false;
    for (float v : nums) bad = bad || !std::isfinite(v);
    const bool fault_now =
        bad || in.fault || !in.watchdog_ok || in.telemetry_age_s > c.max_telemetry_age_s;

    if (!in.arm_switch) {
        rearm_needed_ = false;
        latched_ = false;
    } else if (!last_switch_) {
        rearm_needed_ = false;
    }
    last_switch_ = in.arm_switch;

    if (fault_now && in.arm_switch) {
        latched_ = true;
        rearm_needed_ = true;
    }

    if (bad) return Reason::BadInput;
    if (!in.arm_switch) return Reason::NotArmed;
    if (latched_) return Reason::FaultLatched;
    if (rearm_needed_) return Reason::RearmRequired;
    if (in.state == SystemState::Coast) {
        if (in.coast_time_s > c.max_coast_s) return Reason::CoastTooLong;
    } else if (in.state != SystemState::Locked) {
        return Reason::NotLocked;
    }
    if (!(c.min_range_m <= in.target_range_m && in.target_range_m <= c.max_range_m)) {
        return Reason::Range;
    }
    if (std::fabs(in.pan_deg) > c.max_pan_deg) return Reason::PanLimit;
    if (in.aim_height_m > c.max_aim_height_m || in.beam_height_at_target_m > c.max_aim_height_m) {
        return Reason::HeightCap;
    }
    return Reason::Ok;
}

}  // namespace df
