# SPDX-License-Identifier: Apache-2.0
"""Generate a simulated RD-03D session: raw bytes plus ground truth.

Usage::

    dragonfly-sim --scenario S1 --out data/sim/s1 --seed 1

Writes ``<out>.bin`` (the byte stream the radar would send, which
``dragonfly-log --replay`` can decode) and ``<out>_truth.csv``.
"""

from __future__ import annotations

import argparse
import csv
from pathlib import Path

from dragonfly.io.rd03d import encode_frame
from dragonfly.sim.rd03d import RD03DSimulator, radial_speed
from dragonfly.sim.scenarios import SCENARIOS


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Simulate an RD-03D session.")
    ap.add_argument("--scenario", choices=sorted(SCENARIOS), required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--seed", type=int, default=0)
    args = ap.parse_args(argv)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    sim = RD03DSimulator(SCENARIOS[args.scenario](), seed=args.seed)
    truth_path = args.out.with_name(args.out.name + "_truth.csv")
    with open(args.out.with_suffix(".bin"), "wb") as raw, open(truth_path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(
            ["t_s", "frame", "name", "x_m", "y_m", "vx_mps", "vy_mps", "radial_mps", "detected"]
        )
        for i, sf in enumerate(sim.frames()):
            raw.write(encode_frame(sf.frame))
            for tt in sf.truth:
                s = tt.state
                w.writerow(
                    [
                        f"{sf.t:.4f}",
                        i,
                        tt.name,
                        f"{s.x:.4f}",
                        f"{s.y:.4f}",
                        f"{s.vx:.4f}",
                        f"{s.vy:.4f}",
                        f"{radial_speed(s):.4f}",
                        int(tt.detected),
                    ]
                )
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
