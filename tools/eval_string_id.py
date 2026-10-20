"""String identification inside the detector (spec §17.5), OrchideaSOL guitar.

1. A calibration pass assembled from the library's open-string notes (several dynamics, one pass) is run through the calibrator; it
   learns B, tuning and, for string identity, log(B/f^2) per string.
2. Scenes of stopped notes are detected with that calibration. Every "string" event is compared with the string that played the
   matching true note, and with the detector's pitch-only rule (the string_index of the track snapshot).

  .venv/bin/python tools/eval_string_id.py [--kind lines,chords] [--voices 1] [--n 12] [--dynamics mf,ff] [--no-feedback]
"""
import argparse
import sys
from argparse import Namespace
from pathlib import Path
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from fidddle.analyzer import Analyzer
from fidddle.calibrate import Calibrator
from fidddle.profile import DetectorConfig
from tools import eval_orchidea as eo
from tools.eval_physics import OPEN
from tools.orchidea import catalog, mix as omix


def calibrate(dynamics, cfg0):
    sounds = []
    for dyn in dynamics:
        for st, midi in enumerate(OPEN["guitar"], 1):
            sounds += [s for s in catalog.select("guitar", ["ordinario"], [dyn]) if s.string == st and s.midi == midi][:1]
    ev, t = [], 0.5
    for s in sounds:
        ev.append(omix.Event(s, t)); t += 2.8
    mixed, _, _, _ = omix.render(ev, eo.SR, t + 1.0)
    az = Analyzer(cfg0)
    cal = Calibrator(cfg0, az.n_long)
    az.run(mixed, calibrator=cal)
    return cal.finalize()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--kind", default="lines")
    ap.add_argument("--voices", type=int, default=1)
    ap.add_argument("--n", type=int, default=12)
    ap.add_argument("--hits", type=int, default=2)
    ap.add_argument("--dynamics", default="mf,ff")
    ap.add_argument("--seed", type=int, default=11)
    a = ap.parse_args()
    cfg0 = DetectorConfig.for_instrument("guitar", float(eo.SR))
    cal = calibrate(a.dynamics.split(","), cfg0)
    print("calibration: captured", cal.captured, "log(B/f^2)", [round(v, 2) for v in cal.logb])
    ns = Namespace(instrument="guitar", kind=a.kind, n=a.n, voices=a.voices, hits=a.hits, techniques="ordinario",
                   dynamics=a.dynamics, seed=a.seed, all_range=False)
    n_notes = n_ans = n_ok = n_pitch_ok = n_amb = n_amb_ok = n_amb_pitch_ok = 0
    rows = []
    for sc in eo.build_scenes(ns):
        cfg = DetectorConfig.for_instrument("guitar", float(eo.SR))
        cfg.calibration = cal
        az = Analyzer(cfg)
        frames = az.run(sc["mix"], track=True)
        for e in az.events:
            if e.kind != "string":
                continue
            t = e.deliver_samples / eo.SR
            truth = [n for n in sc["notes"] if n["midi"] == e.midi_note and n["onset"] - 0.1 <= t <= n["end"] + 0.3]
            if not truth:
                continue
            true_s = 7 - truth[0]["string"]           # library strings count from the highest, the profile from the lowest
            playable = [s for s in range(1, 7) if 0 <= e.midi_note - OPEN["guitar"][6 - s] <= 24]
            hs = max((s for s in range(6) if e.midi_note >= OPEN["guitar"][5 - s] - 0.5), default=-1)        # highest open string at or below the pitch
            hit, phit = e.string + 1 == true_s, hs + 1 == true_s
            n_ans += 1; n_ok += hit; n_pitch_ok += phit
            if len(playable) >= 2:
                n_amb += 1; n_amb_ok += hit; n_amb_pitch_ok += phit; rows.append((e.margin, hit, phit))
        n_notes += len(sc["notes"])
    print(f"{a.kind} voices {a.voices}: {n_notes} true notes, {n_ans} answered ({n_ans / max(n_notes, 1):.0%})")
    print(f"  all answered:           string correct {n_ok}/{n_ans}   (highest open string at or below the pitch, on the same notes: {n_pitch_ok}/{n_ans})")
    print(f"  playable on 2+ strings: string correct {n_amb_ok}/{n_amb} = {n_amb_ok / max(n_amb, 1):.2f}   (that rule: {n_amb_pitch_ok}/{n_amb} = {n_amb_pitch_ok / max(n_amb, 1):.2f})")
    for thr in (0.3, 1.0):
        sel = [(h, p) for m, h, p in rows if m >= thr]
        if sel:
            print(f"  margin >= {thr:.1f}: stiffness {sum(h for h, _ in sel)}/{len(sel)}, rule {sum(p for _, p in sel)}/{len(sel)}  ({len(sel) / len(rows):.0%} of the ambiguous answers)")
    low = [(h, p) for m, h, p in rows if m < 0.3]
    print(f"  margin < 0.3:  stiffness {sum(h for h, _ in low)}/{len(low)}, rule {sum(p for _, p in low)}/{len(low)}")
    print(f"  hybrid (stiffness when margin >= 0.3, else the rule): {sum(h if m >= 0.3 else p for m, h, p in rows)}/{len(rows)}")


if __name__ == "__main__":
    main()
