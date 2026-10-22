"""Sanity check: does per-instrument calibration (B, weights, string values) beat a robust default across tasks?

Variants on OrchideaSOL scenes of stopped notes (plucked guitar; plucked and bowed contrabass): the profile default (B = 0), a flat small B
(3e-5), a larger one (1e-4), and the calibration learned from that library's open-string notes. Note-level P/R/F1 (exact pitch, onset +-0.15 s) per scene kind.

  .venv/bin/python tools/eval_defaults.py guitar|contrabass [--technique pizzicato_secco] [--n 6] [--voices 3]
"""
import argparse
import sys
from argparse import Namespace
from multiprocessing import Pool
from pathlib import Path
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from fidddle.analyzer import Analyzer
from fidddle.calibrate import Calibrator
from fidddle.profile import DetectorConfig
from tools import eval_orchidea as eo
from tools.eval_physics import OPEN
from tools.eval_tracker import events_to_notes, score
from tools.orchidea import catalog, mix as omix


def learn(inst, tech):
    sounds = []
    for dyn in ("mf", "ff"):
        for st, midi in enumerate(OPEN[inst], 1):
            sounds += [s for s in catalog.select(inst, [tech], [dyn]) if s.string == st and s.midi == midi][:1]
    ev, t = [], 0.5
    for s in sounds:
        ev.append(omix.Event(s, t)); t += 2.8
    mixed, _, _, _ = omix.render(ev, eo.SR, t + 1.0)
    cfg0 = DetectorConfig.for_instrument(inst, float(eo.SR))
    az = Analyzer(cfg0)
    cal = Calibrator(cfg0, az.n_long)
    az.run(mixed, calibrator=cal)
    return cal.finalize()


def _run(task):
    inst, variant, cal, mix, notes, kind = task
    cfg = DetectorConfig.for_instrument(inst, float(eo.SR))
    if variant == "B=1e-4":
        cfg.profile.inharmonicity_B = 1e-4
    elif variant == "B=3e-5":
        cfg.profile.inharmonicity_B = 3e-5
    elif variant == "calibrated":
        cfg.calibration = cal
    az = Analyzer(cfg)
    az.run(mix, track=True)
    sc = score([(n["onset"], n["offset"], n["midi"]) for n in notes], events_to_notes(az.events, eo.SR))
    return kind, variant, sc


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("instrument", choices=["guitar", "contrabass", "bass"])
    ap.add_argument("--technique", default=None)
    ap.add_argument("--n", type=int, default=6)
    ap.add_argument("--voices", type=int, default=3)
    a = ap.parse_args()
    inst = a.instrument
    tech = a.technique or ("ordinario" if inst == "guitar" else "pizzicato_secco")
    cal = learn(inst, tech)
    print(f"{inst} {tech}: calibration captured {cal.captured if cal else None}")
    ns = Namespace(instrument=inst, kind="lines,chords,strum,intervals", n=a.n, voices=a.voices, hits=2, techniques=tech, dynamics="mf,ff", seed=5, all_range=False)
    scenes = eo.build_scenes(ns)
    variants = ["profile default", "B=3e-5", "B=1e-4", "calibrated"]
    tasks = [(inst, v, cal, s["mix"], s["notes"], s["kind"]) for s in scenes for v in variants]
    with Pool(6) as p:
        res = p.map(_run, tasks)
    print(f"{'kind':10s}" + "".join(f"{v:>24s}" for v in variants))
    for kind in ("lines", "chords", "strum", "intervals", "ALL"):
        cells = []
        for v in variants:
            rs = [r for k, vv, r in res if vv == v and (kind == "ALL" or k == kind)]
            w = np.array([r["n_ref"] for r in rs], float)
            cells.append("  P{:.2f} R{:.2f} F{:.2f} x{:>3d}".format(*(np.average([r[m] for r in rs], weights=w) for m in ("P", "R", "F1")), sum(r["n_est"] for r in rs)))
        print(f"{kind:10s}" + "".join(f"{c:>24s}" for c in cells))


if __name__ == "__main__":
    main()
