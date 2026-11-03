# SPDX-License-Identifier: Apache-2.0
import pytest
from hypothesis import given
from hypothesis import strategies as st

from dragonfly.io.rd03d import (
    FRAME_BYTES,
    HEADER,
    TAIL,
    Frame,
    StreamParser,
    Target,
    decode_frame,
    decode_signed,
    encode_frame,
    encode_signed,
    parse_stream,
)

# A frame captured from vendor documentation style example: one target at
# x = -782 mm, y = 1713 mm, speed = -16 (LSB), resolution 320 mm.
EXAMPLE = bytes.fromhex("AAFF0300 0E03 B186 1000 4001" + "00" * 16 + "55CC")


def test_example_frame_decodes():
    frame = decode_frame(EXAMPLE)
    assert len(frame.targets) == 1
    t = frame.targets[0]
    assert t.x_m == pytest.approx(-0.782)
    assert t.y_m == pytest.approx(1.713)
    assert t.speed_mps == pytest.approx(-0.16)
    assert t.resolution_m == pytest.approx(0.320)


def test_signed_encoding_examples():
    assert decode_signed(0x8000 + 5) == 5
    assert decode_signed(5) == -5
    assert decode_signed(0) == 0
    assert encode_signed(-5) == 5
    assert encode_signed(5) == 0x8005


@given(st.integers(-0x7FFF, 0x7FFF))
def test_signed_roundtrip(v):
    assert decode_signed(encode_signed(v)) == v


@pytest.mark.parametrize("bad", [-1, 0x10000])
def test_decode_signed_rejects_out_of_range(bad):
    with pytest.raises(ValueError):
        decode_signed(bad)


def test_encode_signed_rejects_out_of_range():
    with pytest.raises(ValueError):
        encode_signed(0x8000)


targets = st.builds(
    Target,
    x_m=st.floats(-8, 8),
    y_m=st.floats(0.001, 8),
    speed_mps=st.floats(-5, 5),
    resolution_m=st.floats(0, 2),
)


@given(st.lists(targets, max_size=3))
def test_frame_roundtrip_within_quantisation(ts):
    frame = Frame(tuple(ts))
    data = encode_frame(frame)
    assert len(data) == FRAME_BYTES
    decoded = decode_frame(data)
    assert len(decoded.targets) == len(ts)
    for a, b in zip(ts, decoded.targets, strict=True):
        assert b.x_m == pytest.approx(a.x_m, abs=0.0006)
        assert b.y_m == pytest.approx(a.y_m, abs=0.0006)
        assert b.speed_mps == pytest.approx(a.speed_mps, abs=0.006)


def test_too_many_targets_rejected():
    t = Target(0.0, 1.0, 0.0, 0.0)
    with pytest.raises(ValueError):
        encode_frame(Frame((t, t, t, t)))


@pytest.mark.parametrize(
    "data",
    [EXAMPLE[:-1], b"\x00" + EXAMPLE[1:], EXAMPLE[:-2] + b"\x00\x00"],
)
def test_malformed_frames_rejected(data):
    with pytest.raises(ValueError):
        decode_frame(data)


def test_parser_handles_garbage_and_split_chunks():
    stream = b"\x01\x02\xaa\xff" + EXAMPLE + b"junk" + EXAMPLE
    parser = StreamParser()
    frames = []
    for i in range(len(stream)):
        frames += list(parser.feed(stream[i : i + 1]))
    assert len(frames) == 2
    assert parser.stats.frames == 2
    assert parser.stats.bytes_discarded > 0


def test_parser_skips_false_header():
    # A header followed by data that is not a full frame, then a real frame.
    stream = HEADER + b"\x00" * 10 + EXAMPLE
    assert len(list(parse_stream([stream]))) == 1


def test_parser_memory_is_bounded():
    parser = StreamParser()
    for _ in range(1000):
        list(parser.feed(b"\x00" * 1000))
    assert len(parser._buf) < len(HEADER)


@given(st.binary(max_size=500), st.lists(targets, max_size=3), st.binary(max_size=500))
def test_parser_finds_frame_in_random_noise(prefix, ts, suffix):
    frame_bytes = encode_frame(Frame(tuple(ts)))
    frames = list(parse_stream([prefix, frame_bytes, suffix]))
    # Random noise can contain a real-looking frame, but ours must be found.
    assert any(len(f.targets) == len(ts) for f in frames)


@given(st.binary(max_size=2000))
def test_parser_never_crashes_on_noise(data):
    list(parse_stream([data]))


def test_tail_constant():
    assert TAIL == b"\x55\xcc"
