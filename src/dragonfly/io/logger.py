# SPDX-License-Identifier: Apache-2.0
"""Record RD-03D output to disk for the test campaigns.

Two files are written per session:

* ``<name>.bin``: the raw UART bytes, untouched. If an assumption in the
  decoder (such as the speed unit) turns out wrong, the session can be
  decoded again later without re-running the test.
* ``<name>.csv``: one row per reported target, plus one row for each empty
  frame (so detection probability can be computed).

Usage::

    dragonfly-log --port /dev/ttyUSB0 --out data/t1/session01 --duration 60
    dragonfly-log --replay data/t1/session01.bin --out data/t1/session01_redo

Recordings belong in the git-ignored ``data/`` folder. Do not commit them.
"""

from __future__ import annotations

import argparse
import csv
import sys
import time
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import IO

from dragonfly.io.rd03d import SPEED_M_PER_LSB, Frame, StreamParser

BAUD_RATE = 256000

CSV_COLUMNS = (
    "host_time_s",
    "frame",
    "n_targets",
    "slot",
    "x_m",
    "y_m",
    "range_m",
    "azimuth_deg",
    "speed_mps",
    "resolution_m",
)


class FrameCsvWriter:
    def __init__(self, stream: IO[str]) -> None:
        self._w = csv.writer(stream)
        self._w.writerow(CSV_COLUMNS)
        self.frames = 0

    def write(self, host_time_s: float, frame: Frame) -> None:
        n = len(frame.targets)
        if n == 0:
            self._w.writerow([f"{host_time_s:.6f}", self.frames, 0, "", "", "", "", "", "", ""])
        for slot, t in enumerate(frame.targets):
            self._w.writerow(
                [
                    f"{host_time_s:.6f}",
                    self.frames,
                    n,
                    slot,
                    f"{t.x_m:.3f}",
                    f"{t.y_m:.3f}",
                    f"{t.range_m:.3f}",
                    f"{t.azimuth_deg:.2f}",
                    f"{t.speed_mps:.3f}",
                    f"{t.resolution_m:.3f}",
                ]
            )
        self.frames += 1


def record(
    chunks: Iterable[bytes],
    out_base: Path,
    clock: Callable[[], float] = time.monotonic,
    speed_m_per_lsb: float = SPEED_M_PER_LSB,
) -> int:
    """Write raw bytes and decoded CSV for every chunk. Returns frame count."""
    out_base.parent.mkdir(parents=True, exist_ok=True)
    parser = StreamParser(speed_m_per_lsb)
    t0 = clock()
    with (
        open(out_base.with_suffix(".bin"), "wb") as raw,
        open(out_base.with_suffix(".csv"), "w", newline="") as text,
    ):
        writer = FrameCsvWriter(text)
        for chunk in chunks:
            raw.write(chunk)
            now = clock() - t0
            for frame in parser.feed(chunk):
                writer.write(now, frame)
    return writer.frames


def _serial_chunks(port: str, duration_s: float | None) -> Iterable[bytes]:
    try:
        import serial
    except ImportError as exc:  # pragma: no cover - depends on optional extra
        raise SystemExit('pyserial is needed: pip install -e ".[hardware]"') from exc
    deadline = None if duration_s is None else time.monotonic() + duration_s
    with serial.Serial(port, BAUD_RATE, timeout=0.1) as ser:
        while deadline is None or time.monotonic() < deadline:
            data = ser.read(4096)
            if data:
                yield data


def _file_chunks(path: Path, size: int = 30) -> Iterable[bytes]:
    with open(path, "rb") as f:
        while chunk := f.read(size):
            yield chunk


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Record RD-03D radar output.")
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--port", help="serial port, e.g. /dev/ttyUSB0 or COM3")
    src.add_argument("--replay", type=Path, help="decode a previously saved .bin file")
    ap.add_argument("--out", type=Path, required=True, help="output path without extension")
    ap.add_argument("--duration", type=float, help="seconds to record (default: until Ctrl+C)")
    ap.add_argument(
        "--speed-unit",
        type=float,
        default=SPEED_M_PER_LSB,
        help="metres per second per speed LSB (default 0.01 = cm/s)",
    )
    args = ap.parse_args(argv)
    chunks = _serial_chunks(args.port, args.duration) if args.port else _file_chunks(args.replay)
    try:
        n = record(chunks, args.out, speed_m_per_lsb=args.speed_unit)
    except KeyboardInterrupt:
        print("stopped", file=sys.stderr)
        return 0
    print(f"{n} frames written to {args.out.with_suffix('.csv')}", file=sys.stderr)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
