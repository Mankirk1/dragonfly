// SPDX-License-Identifier: Apache-2.0
// RD-03D target frame decoder and byte-stream parser.
// Port of src/dragonfly/io/rd03d.py; behaviour must match it (tests/test_parity.py).
#pragma once

#include <cstddef>
#include <cstdint>

namespace df {

constexpr std::size_t kRd03dFrameBytes = 30;
constexpr std::size_t kRd03dSlots = 3;
constexpr float kDefaultSpeedMPerLsb = 0.01f;  // cm/s; verify in T1

struct Target {
    float x_m;
    float y_m;
    float speed_mps;
    float resolution_m;
};

struct Frame {
    std::uint8_t count = 0;
    Target targets[kRd03dSlots] = {};
};

// Decode a 16-bit RD-03D sign-magnitude value.
int32_t rd03d_decode_signed(std::uint16_t raw);

// Decode one complete 30-byte frame. Returns false if the header or tail is wrong.
bool rd03d_decode_frame(const std::uint8_t* data, std::size_t len, float speed_m_per_lsb,
                        Frame& out);

// Byte-at-a-time parser with a fixed 30-byte buffer. Skips garbage, partial
// frames and other message types, exactly like the Python StreamParser.
class Rd03dParser {
public:
    explicit Rd03dParser(float speed_m_per_lsb = kDefaultSpeedMPerLsb)
        : speed_(speed_m_per_lsb) {}

    // Push one byte. Returns true and fills `out` when a frame completes.
    bool push(std::uint8_t byte, Frame& out);

    std::uint32_t frames() const { return frames_; }
    std::uint32_t bytes_discarded() const { return discarded_; }

private:
    void resync_from(std::size_t start);

    float speed_;
    std::uint8_t buf_[kRd03dFrameBytes] = {};
    std::size_t len_ = 0;
    std::uint32_t frames_ = 0;
    std::uint32_t discarded_ = 0;
};

}  // namespace df
