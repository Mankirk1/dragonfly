// SPDX-License-Identifier: Apache-2.0
// Command-line wrapper around the C++ core, used by tests/test_parity.py to
// check that the firmware matches the Python reference.
//
//   core_cli rd03d <speed_m_per_lsb>  < raw.bin     prints one line per frame
//   core_cli interlock                < inputs.txt  prints one reason per line
//
// Interlock input lines: arm fault watchdog_ok telemetry_age state coast range
// pan aim_height beam_height, with booleans as 0/1 and state as 0..4.
#include <cstdio>
#include <cstdlib>
#include <cstring>

#include "interlock.hpp"
#include "rd03d.hpp"

namespace {

int run_rd03d(float speed) {
    df::Rd03dParser parser(speed);
    df::Frame f;
    int c;
    while ((c = std::getchar()) != EOF) {
        if (parser.push(static_cast<std::uint8_t>(c), f)) {
            std::printf("%u", static_cast<unsigned>(f.count));
            for (std::uint8_t i = 0; i < f.count; ++i) {
                const df::Target& t = f.targets[i];
                std::printf(" %.6f %.6f %.6f %.6f", static_cast<double>(t.x_m),
                            static_cast<double>(t.y_m), static_cast<double>(t.speed_mps),
                            static_cast<double>(t.resolution_m));
            }
            std::printf("\n");
        }
    }
    return 0;
}

int run_interlock() {
    df::Interlock il;
    int arm, fault, wd, state;
    float age, coast, range, pan, aim, beam;
    char line[512];
    while (std::fgets(line, sizeof(line), stdin) != nullptr) {
        if (std::sscanf(line, "%d %d %d %f %d %f %f %f %f %f", &arm, &fault, &wd, &age, &state,
                        &coast, &range, &pan, &aim, &beam) != 10 ||
            state < 0 || state > 4) {
            std::fprintf(stderr, "bad line: %s", line);
            return 2;
        }
        const df::InterlockInputs in{arm != 0, fault != 0, wd != 0, age,
                                     static_cast<df::SystemState>(state),
                                     coast, range, pan, aim, beam};
        std::printf("%s\n", df::reason_name(il.evaluate(in)));
    }
    return 0;
}

}  // namespace

int main(int argc, char** argv) {
    if (argc >= 2 && std::strcmp(argv[1], "rd03d") == 0) {
        return run_rd03d(argc >= 3 ? std::strtof(argv[2], nullptr) : df::kDefaultSpeedMPerLsb);
    }
    if (argc >= 2 && std::strcmp(argv[1], "interlock") == 0) return run_interlock();
    std::fprintf(stderr, "usage: core_cli rd03d [speed] | core_cli interlock\n");
    return 1;
}
