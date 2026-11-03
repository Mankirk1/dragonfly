# SPDX-License-Identifier: Apache-2.0
"""Encoder, decoder and stream parser for RD-03D radar target frames.

The RD-03D reports up to three moving targets per frame over UART
(256000 baud, 8N1). A target report frame is 30 bytes::

    AA FF 03 00 | target 1 (8 B) | target 2 (8 B) | target 3 (8 B) | 55 CC

Each target is four little-endian 16-bit fields: x, y, speed and distance
resolution. x, y and speed use a sign-magnitude style encoding: when bit 15
is set the value is positive and equals raw - 0x8000; otherwise the value
is negative and equals -raw. An all-zero target slot means "no target".

ASSUMPTIONS TO VERIFY ON REAL HARDWARE (test T1):
  * x and y are in millimetres, distance resolution is in millimetres.
  * Speed is in cm/s (as most open-source drivers assume). The project report
    mentions mm/s, so the unit is a parameter: see SPEED_M_PER_LSB.
  * Positive speed means the target is moving away from the radar.
"""

from __future__ import annotations

import math
import struct
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field

HEADER = bytes((0xAA, 0xFF, 0x03, 0x00))
TAIL = bytes((0x55, 0xCC))
TARGET_SLOTS = 3
TARGET_BYTES = 8
FRAME_BYTES = len(HEADER) + TARGET_SLOTS * TARGET_BYTES + len(TAIL)  # 30

POSITION_M_PER_LSB = 0.001
RESOLUTION_M_PER_LSB = 0.001
SPEED_M_PER_LSB = 0.01  # cm/s. Verify in T1; the report suggests mm/s (0.001).

_MAG_MAX = 0x7FFF


def decode_signed(raw: int) -> int:
    """Decode a 16-bit RD-03D sign-magnitude value."""
    if not 0 <= raw <= 0xFFFF:
        raise ValueError(f"raw value out of 16-bit range: {raw}")
    return raw - 0x8000 if raw & 0x8000 else -raw


def encode_signed(value: int) -> int:
    """Encode an integer into the RD-03D sign-magnitude format."""
    if not -_MAG_MAX <= value <= _MAG_MAX:
        raise ValueError(f"value out of encodable range: {value}")
    return value + 0x8000 if value >= 0 else -value


@dataclass(frozen=True)
class Target:
    """One target slot, in SI units. Positions are in the radar frame:
    y points straight out of the antenna, x to the right when looking out."""

    x_m: float
    y_m: float
    speed_mps: float
    resolution_m: float

    @property
    def range_m(self) -> float:
        return math.hypot(self.x_m, self.y_m)

    @property
    def azimuth_deg(self) -> float:
        """Bearing from boresight, positive to the right."""
        return math.degrees(math.atan2(self.x_m, self.y_m))


@dataclass(frozen=True)
class Frame:
    """A decoded frame: only occupied slots, in slot order."""

    targets: tuple[Target, ...] = field(default_factory=tuple)


def _to_lsb(value: float, m_per_lsb: float) -> int:
    return round(value / m_per_lsb)


def encode_frame(frame: Frame, speed_m_per_lsb: float = SPEED_M_PER_LSB) -> bytes:
    """Encode a frame to its 30-byte wire form. Values are clamped to range."""
    if len(frame.targets) > TARGET_SLOTS:
        raise ValueError(f"at most {TARGET_SLOTS} targets per frame")
    out = bytearray(HEADER)

    def clamp(v: int) -> int:
        return max(-_MAG_MAX, min(_MAG_MAX, v))

    for t in frame.targets:
        out += struct.pack(
            "<HHHH",
            encode_signed(clamp(_to_lsb(t.x_m, POSITION_M_PER_LSB))),
            encode_signed(clamp(_to_lsb(t.y_m, POSITION_M_PER_LSB))),
            encode_signed(clamp(_to_lsb(t.speed_mps, speed_m_per_lsb))),
            max(0, min(0xFFFF, _to_lsb(t.resolution_m, RESOLUTION_M_PER_LSB))),
        )
    out += bytes(TARGET_BYTES * (TARGET_SLOTS - len(frame.targets)))
    out += TAIL
    return bytes(out)


def decode_frame(data: bytes, speed_m_per_lsb: float = SPEED_M_PER_LSB) -> Frame:
    """Decode exactly one 30-byte frame. Raises ValueError if malformed."""
    if len(data) != FRAME_BYTES:
        raise ValueError(f"expected {FRAME_BYTES} bytes, got {len(data)}")
    if data[: len(HEADER)] != HEADER or data[-len(TAIL) :] != TAIL:
        raise ValueError("bad header or tail")
    targets = []
    for slot in range(TARGET_SLOTS):
        start = len(HEADER) + slot * TARGET_BYTES
        raw = data[start : start + TARGET_BYTES]
        if raw == bytes(TARGET_BYTES):
            continue
        rx, ry, rs, rres = struct.unpack("<HHHH", raw)
        targets.append(
            Target(
                x_m=decode_signed(rx) * POSITION_M_PER_LSB,
                y_m=decode_signed(ry) * POSITION_M_PER_LSB,
                speed_mps=decode_signed(rs) * speed_m_per_lsb,
                resolution_m=rres * RESOLUTION_M_PER_LSB,
            )
        )
    return Frame(tuple(targets))


@dataclass
class ParserStats:
    frames: int = 0
    bytes_discarded: int = 0
    resyncs: int = 0


class StreamParser:
    """Incremental parser for a raw UART byte stream.

    Feed it arbitrary chunks; it yields complete, valid frames and skips
    garbage, partial frames and other message types (such as command ACKs).
    Memory use is bounded.
    """

    def __init__(self, speed_m_per_lsb: float = SPEED_M_PER_LSB) -> None:
        self._buf = bytearray()
        self._speed = speed_m_per_lsb
        self.stats = ParserStats()

    def feed(self, chunk: bytes) -> Iterator[Frame]:
        self._buf += chunk
        while True:
            idx = self._buf.find(HEADER)
            if idx < 0:
                # Keep a possible partial header at the end, drop the rest.
                keep = len(HEADER) - 1
                drop = max(0, len(self._buf) - keep)
                self._discard(drop)
                return
            if idx > 0:
                self._discard(idx)
            if len(self._buf) < FRAME_BYTES:
                return
            candidate = bytes(self._buf[:FRAME_BYTES])
            if candidate[-len(TAIL) :] != TAIL:
                # Header matched by chance inside other data: skip one byte.
                self._discard(1)
                continue
            del self._buf[:FRAME_BYTES]
            self.stats.frames += 1
            yield decode_frame(candidate, self._speed)

    def _discard(self, n: int) -> None:
        if n > 0:
            del self._buf[:n]
            self.stats.bytes_discarded += n
            self.stats.resyncs += 1


def parse_stream(
    chunks: Iterable[bytes], speed_m_per_lsb: float = SPEED_M_PER_LSB
) -> Iterator[Frame]:
    """Convenience wrapper: parse an iterable of byte chunks."""
    parser = StreamParser(speed_m_per_lsb)
    for chunk in chunks:
        yield from parser.feed(chunk)
