// SPDX-License-Identifier: Apache-2.0
// Laser safety interlock. SAFETY-CRITICAL.
// Port of src/dragonfly/control/interlock.py; behaviour must match it exactly
// (tests/test_parity.py). See docs/safety/laser-interlock.md. The hardware arm
// switch in series with the laser supply always has the final say.
#pragma once

#include <cstdint>

namespace df {

enum class SystemState : std::uint8_t { Search, Tentative, Locked, Coast, Hold };

enum class Reason : std::uint8_t {
    Ok,
    NotArmed,
    RearmRequired,
    FaultLatched,
    NotLocked,
    CoastTooLong,
    Range,
    PanLimit,
    HeightCap,
    BadInput,
};

const char* reason_name(Reason r);

struct InterlockConfig {
    float min_range_m = 0.5f;
    float max_range_m = 6.0f;
    float max_coast_s = 0.5f;
    float max_pan_deg = 60.0f;
    float max_aim_height_m = 1.2f;
    float max_telemetry_age_s = 0.5f;
};

struct InterlockInputs {
    bool arm_switch;
    bool fault;
    bool watchdog_ok;
    float telemetry_age_s;
    SystemState state;
    float coast_time_s;
    float target_range_m;
    float pan_deg;
    float aim_height_m;
    float beam_height_at_target_m;
};

class Interlock {
public:
    explicit Interlock(const InterlockConfig& cfg = InterlockConfig{}) : cfg_(cfg) {}
    Reason evaluate(const InterlockInputs& in);
    bool laser_on(const InterlockInputs& in) { return evaluate(in) == Reason::Ok; }

private:
    InterlockConfig cfg_;
    bool rearm_needed_ = true;  // start disarmed whatever the switch position
    bool latched_ = false;
    bool last_switch_ = true;
};

}  // namespace df
