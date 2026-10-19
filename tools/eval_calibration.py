"""Calibration experiments on synthetic strings whose inharmonicity differs per string.

1. Record the open strings one at a time (random order), run the calibrator, compare with the truth.
2. Detect chords synthesised with the true per-string model, with and without the calibration.

Usage: .venv/bin/python tools/eval_calibration.py guitar|bass [--seed 0] [--weak-fundamental]
"""
import argparse
import sys
from pathlib import Path
import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from fidddle.profile import DetectorConfig, Calibration
from fidddle.analyzer import Analyzer
from fidddle.calibrate import Calibrator
from fidddle.synth import Note, render
from fidddle.evaluate import fit_scores
from tools.eval_instruments import SCENES
from tools.eval_tracker import score, events_to_notes

# plausible per-string inharmonicity: wound strings are lower, plain strings higher; deliberately unlike the profile's constant
TRUE_B = {"guitar": [3e-5, 5e-5, 8e-5, 2.5e-4, 1.5e-4, 1e-4], "bass": [1.5e-5, 2e-5, 3e-5, 5e-5, 9e-5]}
TRUE_CENTS = {"guitar": [6, -8, 4, -5, 9, -3], "bass": [4, -7, 5, -4, 8]}
# a DI bass pickup often has a weak fundamental and a strong second harmonic
WEAK_FUND = (0.35, 1.0, 0.75, 0.5, 0.4, 0.3, 0.25, 0.2, 0.17, 0.14, 0.12, 0.1)


def truth_calibration(inst, prof):
    n = prof.string_count
    c = Calibration.empty(n)
    c.captured = [True] * n
    c.B = list(TRUE_B[inst])
    c.cents = [0.0] * n            # chords are played in tune; the open-string recording uses TRUE_CENTS separately
    return c


def mk_note(midi, onset, offset, truth_cfg, amps, kind):
    f = 440.0 * 2 ** ((midi - 69) / 12)
    return Note(midi, onset, offset, kind, 0.0, B=float(truth_cfg.inharm_B(f)), tau0=2.5, amps=amps)


def open_string_recording(inst, prof, truth_cfg, amps, kind, sr, seed):
    rng = np.random.default_rng(seed)
    order = rng.permutation(prof.string_count)
    notes = []
    t = 0.4
    for s in order:
        f = prof.open_string_hz[s] * 2 ** (TRUE_CENTS[inst][s] / 1200)
        midi = 69 + 12 * np.log2(f / 440.0)
        n = mk_note(midi, t, t + 2.4, truth_cfg, amps, kind)
        n.B = TRUE_B[inst][s]                      # the open string itself
        notes.append(n)
        t += 3.0
    return notes, t + 0.5, order


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("instrument", choices=("guitar", "bass"))
    ap.add_argument("--sr", type=float, default=44100.0)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--weak-fundamental", action="store_true")
    ap.add_argument("--snr", type=float, default=40.0)
    ap.add_argument("--stride", type=int, default=6)
    args = ap.parse_args()
    inst = args.instrument
    base_cfg = DetectorConfig.for_instrument(inst, args.sr)
    prof = base_cfg.profile
    truth_cfg = DetectorConfig.for_instrument(inst, args.sr)
    truth_cfg.calibration = truth_calibration(inst, prof)
    amps = WEAK_FUND if args.weak_fundamental else None
    kind = "plucked"

    # ---- 1. calibration recording --------------------------------------------------------
    notes, dur, order = open_string_recording(inst, prof, truth_cfg, amps, kind, args.sr, args.seed)
    x = render(notes, args.sr, dur, snr_db=args.snr, seed=args.seed + 1)
    az = Analyzer(DetectorConfig.for_instrument(inst, args.sr))
    cal_obj = Calibrator(az.cfg, az.n_long)
    az.run(x, calibrator=cal_obj)
    cal = cal_obj.finalize()
    print(f"{inst}: strings captured {sum(cal.captured) if cal else 0}/{prof.string_count} "
          f"(accepted frames per string {cal_obj.frames})")
    if cal is None:
        return
    print(f"{'string':>6s} {'trueB':>9s} {'estB':>9s} {'B err%':>7s} {'trueCents':>9s} {'estCents':>9s}")
    for s in range(prof.string_count):
        tb, eb = TRUE_B[inst][s], cal.B[s]
        print(f"{s:6d} {tb:9.2e} {eb:9.2e} {100*(eb-tb)/tb:7.1f} {TRUE_CENTS[inst][s]:9.1f} {cal.cents[s]:9.1f}")
    if cal.weights:
        tw = np.array(WEAK_FUND if args.weak_fundamental else [])
        print("learned harmonic weights:", np.round(cal.weights[:12], 2).tolist())
        if len(tw):
            print("true profile (rel. to first 8, ^0.5):", np.round((tw[:8] / tw[:8].mean()) ** 0.5, 2).tolist())

    # ---- 2. detection with and without the calibration -------------------------------------
    print(f"\n{'scene':28s} {'uncal F1':>9s} {'cal F1':>7s}   {'uncal est/ref':>13s} {'cal est/ref':>11s}")
    rows = {"uncal": [], "cal": []}
    for name, (midis, stagger) in SCENES[inst].items():
        cn = [mk_note(m, 0.3 + stagger * i, 3.3, truth_cfg, amps, kind) for i, m in enumerate(midis)]
        xs = render(cn, args.sr, 3.9, snr_db=args.snr, seed=1)
        res = {}
        for tag, c in (("uncal", None), ("cal", cal)):
            cfg = DetectorConfig.for_instrument(inst, args.sr)
            cfg.calibration = c
            a2 = Analyzer(cfg)
            a2.run(xs, track=True)
            est = events_to_notes(a2.events, args.sr)
            sc = score([(n.onset_s, n.offset_s, n.midi) for n in cn], est)
            res[tag] = sc
            rows[tag].append(sc["F1"])
        print(f"{name:28s} {res['uncal']['F1']:9.2f} {res['cal']['F1']:7.2f}   "
              f"{res['uncal']['n_est']:6d}/{res['uncal']['n_ref']:<6d} {res['cal']['n_est']:5d}/{res['cal']['n_ref']:<5d}")
    print(f"{'MEAN note F1':28s} {np.mean(rows['uncal']):9.3f} {np.mean(rows['cal']):7.3f}")


if __name__ == "__main__":
    main()
