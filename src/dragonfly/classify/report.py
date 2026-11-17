# SPDX-License-Identifier: Apache-2.0
"""Run the full classification pipeline on synthetic data and print a report.

    dragonfly-classify-sim --sessions 8 --test-sessions 6 7

This checks the pipeline end to end. The numbers describe the simulator,
not the real system: B7 is measured on real held-out recordings (test T7).
"""

from __future__ import annotations

import argparse

from dragonfly.classify.dataset import CLASSES, make_dataset
from dragonfly.classify.model import evaluate


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--sessions", type=int, default=8)
    ap.add_argument("--clips-per-class", type=int, default=4)
    ap.add_argument("--test-sessions", type=int, nargs="+", default=[6, 7])
    ap.add_argument("--seed", type=int, default=0)
    args = ap.parse_args(argv)
    ds = make_dataset(args.sessions, args.clips_per_class, seed=args.seed)
    ev = evaluate(ds, args.test_sessions, seed=args.seed)
    names = [c.value for c in CLASSES]
    print("SIMULATED DATA - pipeline check only, not a B7 result")
    print(f"windows: {len(ds.y)}, test sessions: {list(ev.test_sessions)}")
    print("cross-validated accuracy (development sessions):")
    for name, acc in sorted(ev.cv_accuracy.items(), key=lambda kv: -kv[1]):
        print(f"  {name:14s} {acc:.3f}")
    lo, hi = ev.test_ci95
    print(
        f"selected: {ev.model}; held-out accuracy {ev.test_accuracy:.3f} (95% CI {lo:.3f}-{hi:.3f})"
    )
    print("class        precision  recall")
    for n, p, r in zip(names, ev.precision, ev.recall, strict=True):
        print(f"  {n:10s} {p:9.3f} {r:7.3f}")
    print("confusion matrix (rows = true, columns = predicted):", names)
    print(ev.confusion)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
