"""Candidate-recall sweep on synthetic signals.

Usage: .venv/bin/python tools/synth_recall.py [--sr 44100]
"""
import argparse
import sys
from pathlib import Path
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from cellostop.profile import DetectorConfig
from cellostop.analyzer import Analyzer
from cellostop.synth import chord, render
from cellostop.evaluate import candidate_recall, true_pitch_ranks

CASES = {
    "single C2": [36],
    "single A3": [57],
    "single D4": [62],
    "single E5": [76],
    "fifth C2+G2": [36, 43],
    "octave C2+C3": [36, 48],
    "third C3+E3": [48, 52],
    "open strings C2 G2 D3 A3": [36, 43, 50, 57],
    "triad C3 E3 G3": [48, 52, 55],
    "4-note C3 G3 E4 C5": [48, 55, 64, 72],
    "close dyad D3+Eb3": [50, 51],
}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sr", type=float, default=44100.0)
    ap.add_argument("--vib", type=float, default=0.0)
    ap.add_argument("--snr", type=float, default=40.0)
    args = ap.parse_args()
    cfg = DetectorConfig(sample_rate=args.sr)
    print(f"sr={args.sr} N_L={cfg.derived_long_fft()}  vib={args.vib}c  snr={args.snr}dB")
    print(f"{'case':28s} {'kind':8s} {'R@25c':>6s} {'R@50c':>6s} {'top8':>6s} {'top12':>6s} {'rank50':>6s} {'frames':>6s}")
    for kind in ("bowed", "plucked"):
        for name, midis in CASES.items():
            notes = chord(midis, kind=kind, dur_s=3.0, vib_cents=args.vib)
            x = render(notes, args.sr, 3.6, snr_db=args.snr, seed=1)
            frames = Analyzer(cfg).run(x)
            r, total = candidate_recall(frames, notes, args.sr, cfg.derived_long_fft())
            r8, _ = candidate_recall(frames, notes, args.sr, cfg.derived_long_fft(), top_k=8)
            r12, _ = candidate_recall(frames, notes, args.sr, cfg.derived_long_fft(), top_k=12)
            ranks = [q for q in true_pitch_ranks(frames, notes, args.sr, cfg.derived_long_fft()) if q is not None]
            mr = float(np.percentile(ranks, 90)) if ranks else float("nan")
            print(f"{name:28s} {kind:8s} {r[25]:6.2f} {r[50]:6.2f} {r8[50]:6.2f} {r12[50]:6.2f} {mr:6.0f} {total:6d}")


if __name__ == "__main__":
    main()
