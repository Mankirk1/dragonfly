# SPDX-License-Identifier: Apache-2.0
"""Parity between the Python reference and the C++ firmware core.

These tests run when DRAGONFLY_CORE_CLI points at a built ``core_cli``::

    cmake -S firmware -B build/firmware && cmake --build build/firmware
    DRAGONFLY_CORE_CLI=build/firmware/core_cli pytest tests/test_parity.py

CI always runs them. Locally they are skipped if the binary is not built.
"""

import math
import os
import subprocess  # noqa: S404
from pathlib import Path

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from dragonfly.control.interlock import Interlock, InterlockInputs
from dragonfly.io.rd03d import Frame, Target, encode_frame, parse_stream
from dragonfly.track.tracker import SystemState

CLI = os.environ.get("DRAGONFLY_CORE_CLI")
pytestmark = pytest.mark.skipif(not CLI or not Path(CLI).exists(), reason="C++ core_cli not built")

STATES = list(SystemState)  # same order as df::SystemState


def run_cli(*args: str, data: bytes) -> str:
    assert CLI is not None
    # The binary path comes from our own CI configuration, not from user input.
    out = subprocess.run([CLI, *args], input=data, capture_output=True, check=True)  # noqa: S603
    return out.stdout.decode()


targets = st.builds(
    Target,
    x_m=st.floats(-8, 8),
    y_m=st.floats(0.001, 8),
    speed_mps=st.floats(-5, 5),
    resolution_m=st.floats(0, 2),
)
chunk = st.one_of(
    st.binary(max_size=40),
    st.lists(targets, max_size=3).map(lambda ts: encode_frame(Frame(tuple(ts)))),
    st.just(bytes((0xAA, 0xFF, 0x03, 0x00))),  # stray headers
)


@settings(max_examples=300, deadline=None)
@given(st.lists(chunk, max_size=20))
def test_rd03d_parser_matches_python(chunks):
    data = b"".join(chunks)
    py = list(parse_stream([data]))
    lines = [ln.split() for ln in run_cli("rd03d", "0.01", data=data).splitlines()]
    assert len(lines) == len(py)
    for frame, fields in zip(py, lines, strict=True):
        assert int(fields[0]) == len(frame.targets)
        values = [float(v) for v in fields[1:]]
        expected = [v for t in frame.targets for v in (t.x_m, t.y_m, t.speed_mps, t.resolution_m)]
        assert values == pytest.approx(expected, abs=1e-5)


# Three-decimal values keep float32 and float64 on the same side of every limit.
num = st.one_of(
    st.decimals(-10, 10, places=3).map(float),
    st.sampled_from([math.nan, math.inf, -math.inf, 0.5, 6.0, 1.2, 60.0, -60.0]),
)
inputs = st.builds(
    InterlockInputs,
    arm_switch=st.booleans(),
    fault=st.booleans(),
    watchdog_ok=st.booleans(),
    telemetry_age_s=num,
    state=st.sampled_from(STATES),
    coast_time_s=num,
    target_range_m=num,
    pan_deg=num,
    aim_height_m=num,
    beam_height_at_target_m=num,
)


def line(i: InterlockInputs) -> str:
    vals = [
        int(i.arm_switch),
        int(i.fault),
        int(i.watchdog_ok),
        i.telemetry_age_s,
        STATES.index(i.state),
        i.coast_time_s,
        i.target_range_m,
        i.pan_deg,
        i.aim_height_m,
        i.beam_height_at_target_m,
    ]
    return " ".join(str(v) for v in vals)


@settings(max_examples=500, deadline=None)
@given(st.lists(inputs, min_size=1, max_size=40))
def test_interlock_matches_python(sequence):
    py = Interlock()
    expected = [py.evaluate(i).value for i in sequence]
    data = ("\n".join(line(i) for i in sequence) + "\n").encode()
    assert run_cli("interlock", data=data).split() == expected
