# SPDX-License-Identifier: Apache-2.0
import csv
import itertools

from dragonfly.io.logger import main as log_main
from dragonfly.io.logger import record
from dragonfly.io.rd03d import FRAME_BYTES, Frame, Target, encode_frame
from dragonfly.sim.cli import main as sim_main


def test_record_writes_raw_and_csv(tmp_path):
    frames = [
        Frame((Target(0.5, 2.0, -0.5, 0.75),)),
        Frame(()),
        Frame((Target(-1.0, 3.0, 1.0, 0.75), Target(1.0, 4.0, 0.2, 0.75))),
    ]
    data = b"".join(encode_frame(f) for f in frames)
    chunks = [data[i : i + 7] for i in range(0, len(data), 7)]
    tick = itertools.count()
    n = record(chunks, tmp_path / "s", clock=lambda: float(next(tick)))
    assert n == 3
    assert (tmp_path / "s.bin").read_bytes() == data
    rows = list(csv.DictReader(open(tmp_path / "s.csv")))
    assert [r["n_targets"] for r in rows] == ["1", "0", "2", "2"]
    assert rows[1]["slot"] == ""
    assert float(rows[2]["azimuth_deg"]) < 0


def test_sim_then_replay_end_to_end(tmp_path):
    assert sim_main(["--scenario", "S1", "--out", str(tmp_path / "s1"), "--seed", "1"]) == 0
    assert (tmp_path / "s1_truth.csv").exists()
    assert log_main(["--replay", str(tmp_path / "s1.bin"), "--out", str(tmp_path / "s1_log")]) == 0
    rows = list(csv.DictReader(open(tmp_path / "s1_log.csv")))
    frames = {r["frame"] for r in rows}
    # Every frame the simulator sent is decoded, including empty ones.
    assert len(frames) == (tmp_path / "s1.bin").stat().st_size // FRAME_BYTES
