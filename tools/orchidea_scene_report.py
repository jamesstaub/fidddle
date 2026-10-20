"""Truth against estimated notes for one OrchideaSOL scene (python reference). Same scene arguments as eval_orchidea.py tracker.

  .venv/bin/python tools/orchidea_scene_report.py --instrument cello --techniques ordinario --kind lines --voices 1 --index 0 [--set k=v]
"""
import argparse
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from tools import eval_orchidea as eo
from fidddle.profile import DetectorConfig
from tools.eval_tracker import run
from tools.eval_fit import set_overrides

NAMES = "C C# D D# E F F# G G# A A# B".split()
nm = lambda m: f"{NAMES[m % 12]}{m // 12 - 1}"


def main():
    ap = argparse.ArgumentParser()
    for k, d in (("instrument", "cello"), ("kind", "lines"), ("techniques", None), ("dynamics", None)):
        ap.add_argument("--" + k, default=d)
    for k, d in (("n", 1), ("voices", 1), ("hits", 3), ("seed", 0), ("index", 0)):
        ap.add_argument("--" + k, type=int, default=d)
    ap.add_argument("--set", action="append")
    a = ap.parse_args()
    a.n = a.index + 1
    s = eo.build_scenes(a)[a.index]
    cfg = DetectorConfig.for_instrument(a.instrument, float(eo.SR))
    set_overrides(cfg, a.set)
    est, _ = run(cfg, s["mix"], eo.SR)
    rows = [(n["onset"], n["offset"], "truth", n["midi"], f"{n['technique']} {n['dynamic']} {n['file']}") for n in s["notes"]]
    rows += [(e[0], e[1], "est", e[2], "") for e in est]
    for on, off, k, m, extra in sorted(rows):
        print(f"{on:6.2f}-{off:6.2f}  {k:5s} {nm(m):4s}({m}) {extra}")


if __name__ == "__main__":
    main()
