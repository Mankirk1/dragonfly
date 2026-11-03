// SPDX-License-Identifier: Apache-2.0
#include "rd03d.hpp"

#include <cstring>

namespace df {
namespace {

constexpr std::uint8_t kHeader[4] = {0xAA, 0xFF, 0x03, 0x00};
constexpr std::uint8_t kTail[2] = {0x55, 0xCC};

std::uint16_t le16(const std::uint8_t* p) {
    return static_cast<std::uint16_t>(p[0] | (p[1] << 8));
}

// True if buf[start..len) is a prefix of the header (or contains it whole).
bool header_prefix_at(const std::uint8_t* buf, std::size_t start, std::size_t len) {
    for (std::size_t i = 0; i < sizeof(kHeader) && start + i < len; ++i) {
        if (buf[start + i] != kHeader[i]) return false;
    }
    return true;
}

}  // namespace

int32_t rd03d_decode_signed(std::uint16_t raw) {
    return (raw & 0x8000u) ? static_cast<int32_t>(raw) - 0x8000 : -static_cast<int32_t>(raw);
}

bool rd03d_decode_frame(const std::uint8_t* data, std::size_t len, float speed_m_per_lsb,
                        Frame& out) {
    if (len != kRd03dFrameBytes) return false;
    if (std::memcmp(data, kHeader, sizeof(kHeader)) != 0) return false;
    if (std::memcmp(data + len - sizeof(kTail), kTail, sizeof(kTail)) != 0) return false;
    out = Frame{};
    for (std::size_t slot = 0; slot < kRd03dSlots; ++slot) {
        const std::uint8_t* p = data + sizeof(kHeader) + slot * 8;
        bool empty = true;
        for (int i = 0; i < 8; ++i) empty = empty && p[i] == 0;
        if (empty) continue;
        Target& t = out.targets[out.count++];
        t.x_m = static_cast<float>(rd03d_decode_signed(le16(p))) * 0.001f;
        t.y_m = static_cast<float>(rd03d_decode_signed(le16(p + 2))) * 0.001f;
        t.speed_mps = static_cast<float>(rd03d_decode_signed(le16(p + 4))) * speed_m_per_lsb;
        t.resolution_m = static_cast<float>(le16(p + 6)) * 0.001f;
    }
    return true;
}

void Rd03dParser::resync_from(std::size_t start) {
    // Discard bytes before the first position that could begin a header.
    std::size_t s = start;
    while (s < len_ && !header_prefix_at(buf_, s, len_)) ++s;
    discarded_ += static_cast<std::uint32_t>(s);
    std::memmove(buf_, buf_ + s, len_ - s);
    len_ -= s;
}

bool Rd03dParser::push(std::uint8_t byte, Frame& out) {
    buf_[len_++] = byte;
    if (!header_prefix_at(buf_, 0, len_)) {
        resync_from(1);
        return false;
    }
    if (len_ < kRd03dFrameBytes) return false;
    if (rd03d_decode_frame(buf_, len_, speed_, out)) {
        len_ = 0;
        ++frames_;
        return true;
    }
    // Header matched by chance inside other data: skip one byte and rescan.
    resync_from(1);
    return false;
}

}  // namespace df
