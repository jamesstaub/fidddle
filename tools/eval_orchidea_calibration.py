"""Open-string calibration on real recordings (OrchideaSOL one-shots), nothing written to disk.

1. Assemble a calibration pass from the library's open-string notes (pitch = the open string, one per string, random order),
   run fidddle's calibrator, and compare the B and tuning it learns with the stiffness measured directly from the same files.
2. Detect polyphonic scenes of other notes (chords, strums, intervals, lines; stopped notes on all strings) with and without
   the calibration: note-level P/R/F1 (exact pitch, onset +-0.15 s).

Usage: .venv/bin/python tools/eval_orchidea_calibration.py guitar|bass|cello|violin|viola [--technique pizzicato_secco] [--n 2]
"""
import argparse
import sys
from multiprocessing import Pool
from pathlib import Path
import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from argparse import Namespace
from fidddle.analyzer import Analyzer
from fidddle.calibrate import Calibrator
from fidddle.profile import DetectorConfig
from tools.eval_orchidea import build_scenes, SR
from tools.eval_physics import OPEN, measure_note
from tools.eval_tracker import score, events_to_notes
from tools.orchidea import catalog, mix as omix


def open_strings(inst, technique, dynamic="mf"):
    out = []
    for st, midi in enumerate(OPEN[inst], 1):
        c = [s for s in catalog.select(inst, [technique], [dynamic]) if s.string == st and s.midi == midi]
        if c:
            out.append(c[0])
    return out


def _detect(task):
    inst, mix, notes, cal = task
    cfg = DetectorConfig.for_instrument(inst, float(SR))
    cfg.calibration = cal
    az = Analyzer(cfg)
    az.run(mix, track=True)
    est = events_to_notes(az.events, SR)
    return score([(n["onset"], n["offset"], n["midi"]) for n in notes], est)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("instrument", choices=list(OPEN))
    ap.add_argument("--technique", default=None)
    ap.add_argument("--n", type=int, default=2)
    ap.add_argument("--voices", type=int, default=3)
    a = ap.parse_args()
    inst = a.instrument
    tech = a.technique or ("ordinario" if inst == "guitar" else "pizzicato_secco")
    opens = open_strings(inst, tech)
    if len(opens) < 2:
        raise SystemExit(f"fewer than two open-string notes for {inst} {tech}")
    rng = np.random.default_rng(0)
    order = rng.permutation(len(opens))
    events = [omix.Event(opens[i], 0.5 + 3.4 * k) for k, i in enumerate(order)]
    m, stems, notes, gain = omix.render(events, SR, 0.5 + 3.4 * len(events) + 0.5)
    cfg = DetectorConfig.for_instrument(inst, float(SR))
    az = Analyzer(cfg)
    cal_obj = Calibrator(cfg, az.n_long)
    az.run(m, calibrator=cal_obj)
    cal = cal_obj.finalize()
    print(f"{inst} {tech}: open strings used {len(opens)} (strings {[s.string for s in opens]}); captured "
          f"{sum(cal.captured) if cal else 0}; accepted frames per string {cal_obj.frames}")
    if cal is None:
        return
    print(f"  {'string':>6s} {'midi':>5s} {'calibrator B':>13s} {'direct B':>10s} {'ratio':>6s}   {'cents':>6s}")
    for s in opens:
        direct = measure_note(s)
        db = np.median([r["B"] for r in direct]) if direct else float("nan")
        idx = int(np.argmin([abs(np.log2(f / (440 * 2 ** ((s.midi - 69) / 12)))) for f in cfg.profile.open_string_hz[: cfg.profile.string_count]]))
        cb = cal.B[idx] if cal.captured[idx] else float("nan")
        print(f"  {idx:6d} {s.midi:5d} {cb:13.2e} {db:10.2e} {cb / db if db > 1e-7 else float('nan'):6.2f}   {cal.cents[idx] if cal.captured[idx] else float('nan'):6.1f}")

    # detection on other notes
    scenes = build_scenes(Namespace(instrument=inst, kind=None, n=a.n, voices=a.voices, hits=2, techniques=tech, dynamics=None, seed=7))
    tasks = [(inst, sc["mix"], sc["notes"], c) for sc in scenes for c in (None, cal)]
    with Pool(8) as pool:
        res = pool.map(_detect, tasks)
    print(f"\n{len(scenes)} scenes of {tech} (stopped notes on all strings; the open notes used above can recur)")
    print(f"  {'kind':10s} {'':>5s}{'P':>6s}{'R':>6s}{'F1':>6s}{'est/ref':>10s}")
    for kind in sorted({sc["kind"] for sc in scenes}):
        for tag, j in (("uncal", 0), ("cal", 1)):
            rows = [res[2 * i + j] for i, sc in enumerate(scenes) if sc["kind"] == kind and res[2 * i + j]]
            if rows:
                print(f"  {kind:10s} {tag:>5s}{np.mean([r['P'] for r in rows]):6.2f}{np.mean([r['R'] for r in rows]):6.2f}{np.mean([r['F1'] for r in rows]):6.2f}"
                      f"{sum(r['n_est'] for r in rows):6d}/{sum(r['n_ref'] for r in rows):<4d}")
    for tag, j in (("uncal", 0), ("cal", 1)):
        rows = [res[2 * i + j] for i in range(len(scenes)) if res[2 * i + j]]
        print(f"  {'ALL':10s} {tag:>5s}{np.mean([r['P'] for r in rows]):6.2f}{np.mean([r['R'] for r in rows]):6.2f}{np.mean([r['F1'] for r in rows]):6.2f}"
              f"{sum(r['n_est'] for r in rows):6d}/{sum(r['n_ref'] for r in rows):<4d}")


if __name__ == "__main__":
    main()
