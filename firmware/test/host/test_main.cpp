// SPDX-License-Identifier: Apache-2.0
// Host unit tests for the portable core. Kept dependency-free on purpose.
#include <cmath>
#include <cstdio>
#include <cstring>
#include <vector>

#include "aim.hpp"
#include "interlock.hpp"
#include "rd03d.hpp"

namespace {
int g_failures = 0;
int g_checks = 0;
#define CHECK(cond)                                                       \
    do {                                                                  \
        ++g_checks;                                                       \
        if (!(cond)) {                                                    \
            ++g_failures;                                                 \
            std::printf("FAIL %s:%d: %s\n", __FILE__, __LINE__, #cond);   \
        }                                                                 \
    } while (0)
#define CHECK_NEAR(a, b, tol) CHECK(std::fabs(static_cast<double>(a) - static_cast<double>(b)) <= (tol))

const std::uint8_t kExample[30] = {0xAA, 0xFF, 0x03, 0x00, 0x0E, 0x03, 0xB1, 0x86, 0x10, 0x00,
                                   0x40, 0x01, 0,    0,    0,    0,    0,    0,    0,    0,
                                   0,    0,    0,    0,    0,    0,    0,    0,    0x55, 0xCC};

void test_decode_signed() {
    CHECK(df::rd03d_decode_signed(0x8005) == 5);
    CHECK(df::rd03d_decode_signed(5) == -5);
    CHECK(df::rd03d_decode_signed(0) == 0);
}

void test_decode_example() {
    df::Frame f;
    CHECK(df::rd03d_decode_frame(kExample, 30, 0.01f, f));
    CHECK(f.count == 1);
    CHECK_NEAR(f.targets[0].x_m, -0.782, 1e-6);
    CHECK_NEAR(f.targets[0].y_m, 1.713, 1e-6);
    CHECK_NEAR(f.targets[0].speed_mps, -0.16, 1e-6);
    CHECK_NEAR(f.targets[0].resolution_m, 0.32, 1e-6);
    std::uint8_t bad[30];
    std::memcpy(bad, kExample, 30);
    bad[29] = 0;
    CHECK(!df::rd03d_decode_frame(bad, 30, 0.01f, f));
    CHECK(!df::rd03d_decode_frame(kExample, 29, 0.01f, f));
}

void test_parser_resync() {
    std::vector<std::uint8_t> s = {0x01, 0x02, 0xAA, 0xFF};
    s.insert(s.end(), kExample, kExample + 30);
    s.insert(s.end(), {'j', 'u', 'n', 'k'});
    s.insert(s.end(), kExample, kExample + 30);
    df::Rd03dParser p;
    int frames = 0;
    df::Frame f;
    for (auto b : s) frames += p.push(b, f) ? 1 : 0;
    CHECK(frames == 2);
    CHECK(p.bytes_discarded() > 0);
    // Long run of noise never overflows the fixed buffer.
    for (int i = 0; i < 100000; ++i) p.push(static_cast<std::uint8_t>(i * 37), f);
}

df::InterlockInputs good() {
    return df::InterlockInputs{true, false, true, 0.05f, df::SystemState::Locked,
                               0.0f, 3.0f,  10.0f, 1.0f, 1.0f};
}

void test_interlock() {
    df::Interlock il;
    df::InterlockInputs in = good();
    CHECK(il.evaluate(in) == df::Reason::RearmRequired);  // starts disarmed
    in.arm_switch = false;
    CHECK(il.evaluate(in) == df::Reason::NotArmed);
    in = good();
    CHECK(il.evaluate(in) == df::Reason::Ok);
    in.fault = true;
    CHECK(il.evaluate(in) == df::Reason::FaultLatched);
    in = good();
    CHECK(il.evaluate(in) == df::Reason::FaultLatched);  // stays latched
    in.arm_switch = false;
    il.evaluate(in);
    in = good();
    CHECK(il.evaluate(in) == df::Reason::Ok);
    in.target_range_m = NAN;
    CHECK(il.evaluate(in) == df::Reason::BadInput);
    in = good();
    in.beam_height_at_target_m = 1.21f;
    il = df::Interlock();
    df::InterlockInputs off = good();
    off.arm_switch = false;
    il.evaluate(off);
    CHECK(il.evaluate(in) == df::Reason::HeightCap);
    CHECK(std::strcmp(df::reason_name(df::Reason::HeightCap), "height_cap") == 0);
}

void test_aim() {
    df::AimConfig cfg;
    df::AimSolution s = df::aim_solve(1.0f, 1.0f, cfg);
    CHECK_NEAR(s.pan_deg, 45.0, 1e-4);
    cfg.laser_height_m = 0.8f;
    cfg.aim_height_m = 1.2f;
    s = df::aim_solve(0.0f, 4.0f, cfg);
    CHECK_NEAR(df::beam_height_at(s.horizontal_range_m, s.tilt_deg, 0.8f), 1.2, 1e-5);
    df::ServoAxis axis({-90.0f, 90.0f, 100.0f, 0.5f, 0.0f});
    CHECK_NEAR(axis.step(50.0f, 0.02f), 2.0, 1e-5);
    CHECK_NEAR(df::nominal_pulse_us(0.0f, -90.0f, 90.0f, 600.0f, 2400.0f), 1500.0, 1e-3);
}
}  // namespace

int main() {
    test_decode_signed();
    test_decode_example();
    test_parser_resync();
    test_interlock();
    test_aim();
    std::printf("%d checks, %d failures\n", g_checks, g_failures);
    return g_failures == 0 ? 0 : 1;
}
