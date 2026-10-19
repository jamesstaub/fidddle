"""Per-instrument evaluation on synthetic chords with exact truth (frame-level fit and note-level tracker).

Usage: .venv/bin/python tools/eval_instruments.py guitar [--stride 4] [--set key=value ...] [--only fit|tracker]
"""
import argparse
import sys
from pathlib import Path
import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from fidddle.profile import DetectorConfig, InstrumentProfile
from fidddle.analyzer import Analyzer
from fidddle.synth import Note, render
from fidddle.evaluate import fit_scores
from tools.eval_fit import set_overrides
from tools.eval_tracker import score, events_to_notes

# (name, midi notes in string order, stagger seconds between onsets)
SCENES = {
    "guitar": {
        "single E2": ([40], 0), "single A3": ([57], 0), "single E5": ([76], 0),
        "power chord E2 B2 E3": ([40, 47, 52], 0.03),
        "A minor 5": ([45, 52, 57, 60, 64], 0.03),
        "C major 5": ([48, 52, 55, 60, 64], 0.03),
        "D minor 4": ([50, 57, 62, 65], 0.03),
        "E major 6": ([40, 47, 52, 56, 59, 64], 0.03),
        "G major 6": ([43, 47, 50, 55, 59, 67], 0.03),
        "E major arpeggio": ([40, 47, 52, 56, 59, 64], 0.25),
    },
    "bass": {"single E1": ([28], 0), "single D2": ([38], 0), "fifth E1 B1": ([28, 35], 0.03),
             "triad A1 E2 A2": ([33, 40, 45], 0.03), "four E1 A1 D2 G2": ([28, 33, 38, 43], 0.03)},
    "cello": {"single C2": ([36], 0), "fifth C2 G2": ([36, 43], 0.03), "open strings": ([36, 43, 50, 57], 0.03)},
    "viola": {"single C3": ([48], 0), "single A5": ([81], 0), "fifth C3 G3": ([48, 55], 0.03),
              "open strings": ([48, 55, 62, 69], 0.03)},
    "violin": {"single G3": ([55], 0), "single E6": ([88], 0), "fifth G3 D4": ([55, 62], 0.03),
               "open strings": ([55, 62, 69, 76], 0.03), "high double E5 A6": ([76, 93], 0.03)},
}


def make_notes(name, midis, stagger, prof, dur=3.0, true_b=None):
    kind = "plucked" if prof.name in ("guitar", "bass") else "bowed"
    return [Note(m, 0.3 + stagger * i, 0.3 + dur, kind, 0.0 if kind == "plucked" else 12.0,
                 B=prof.inharmonicity_B if true_b is None else true_b, tau0=2.5 if kind == "plucked" else 1.6) for i, m in enumerate(midis)]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("instrument", choices=InstrumentProfile.ORDER)
    ap.add_argument("--sr", type=float, default=44100.0)
    ap.add_argument("--stride", type=int, default=4)
    ap.add_argument("--snr", type=float, default=40.0)
    ap.add_argument("--only", default="")
    ap.add_argument("--true-b", type=float, default=None, help="synthesise with this inharmonicity instead of the profile's")
    ap.add_argument("--set", action="append")
    args = ap.parse_args()
    cfg0 = DetectorConfig.for_instrument(args.instrument, args.sr)
    set_overrides(cfg0, args.set)
    prof = cfg0.profile
    print(f"{args.instrument}: voices={cfg0.max_voices} window={cfg0.derived_long_fft()} fit band={cfg0.derived_fit_band():.0f} Hz")
    fit_rows, trk_rows = [], []
    if args.only in ("", "fit"):
        print(f"{'frame-level fit':26s} {'P':>5s} {'R':>5s} {'F1':>5s} {'cnt':>5s} {'frames':>6s}")
    for name, (midis, stagger) in SCENES[args.instrument].items():
        notes = make_notes(name, midis, stagger, prof, true_b=args.true_b)
        x = render(notes, args.sr, max(n.offset_s for n in notes) + 0.6, snr_db=args.snr, seed=1)
        if args.only in ("", "fit"):
            az = Analyzer(DetectorConfig(**{**cfg0.__dict__}))
            frames = az.run(x, fit=True, fit_stride=args.stride)
            s = fit_scores(frames, notes, args.sr, az.n_long)
            fit_rows.append(s)
            print(f"{name:26s} {s['P']:5.2f} {s['R']:5.2f} {s['F1']:5.2f} {s['count_acc']:5.2f} {s['frames']:6d}")
    if args.only in ("", "tracker"):
        print(f"{'note-level tracker':26s} {'P':>5s} {'R':>5s} {'F1':>5s} {'est/ref':>8s} {'lat_ms':>7s}")
        for name, (midis, stagger) in SCENES[args.instrument].items():
            notes = make_notes(name, midis, stagger, prof, true_b=args.true_b)
            x = render(notes, args.sr, max(n.offset_s for n in notes) + 0.6, snr_db=args.snr, seed=1)
            az = Analyzer(DetectorConfig(**{**cfg0.__dict__}))
            az.run(x, track=True)
            est = events_to_notes(az.events, args.sr)
            sc = score([(n.onset_s, n.offset_s, n.midi) for n in notes], est)
            trk_rows.append(sc)
            print(f"{name:26s} {sc['P']:5.2f} {sc['R']:5.2f} {sc['F1']:5.2f} {sc['n_est']:3d}/{sc['n_ref']:<4d} {1000*sc['lat']:7.0f}")
    if fit_rows:
        print(f"MEAN fit F1 {np.mean([r['F1'] for r in fit_rows]):.3f}  (P {np.mean([r['P'] for r in fit_rows]):.3f} R {np.mean([r['R'] for r in fit_rows]):.3f})")
    if trk_rows:
        print(f"MEAN note F1 {np.mean([r['F1'] for r in trk_rows]):.3f}  (P {np.mean([r['P'] for r in trk_rows]):.3f} R {np.mean([r['R'] for r in trk_rows]):.3f})")


if __name__ == "__main__":
    main()
