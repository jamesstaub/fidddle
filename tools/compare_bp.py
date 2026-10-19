"""Candidate recall of our detector against Basic Pitch notes on the real corpus.

Basic Pitch is a comparison baseline, not ground truth: a miss can be our
error or a Basic Pitch error. Only BP notes lasting >= --min-dur are used, and
only in frames where the note covers the whole long window.

Usage: .venv/bin/python tools/compare_bp.py [--only substr] [--channel 0|1]
"""
import argparse
import json
import sys
from pathlib import Path
import numpy as np
import soundfile as sf

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from fidddle.profile import DetectorConfig
from fidddle.analyzer import Analyzer


def evaluate(wav, notes, cfg, min_dur):
    x, sr = sf.read(wav)
    cfg.sample_rate = float(sr)
    az = Analyzer(cfg)
    frames = az.run(x)
    win = az.n_long / sr
    notes = [n for n in notes if n["offset"] - n["onset"] >= min_dur]
    tot = h25 = h50 = h8 = 0
    for f in frames:
        act = [n for n in notes if n["onset"] <= f.t_s - win - 0.03 and f.t_s <= n["offset"] - 0.03]
        if not act:
            continue
        cm = np.array([c.midi for c in f.candidates])
        for n in act:
            tot += 1
            if len(cm) == 0:
                continue
            d = np.abs(cm - n["midi"]) * 100
            h25 += d.min() <= 25
            h50 += d.min() <= 50
            h8 += np.abs(cm[:8] - n["midi"]).min() * 100 <= 50 if len(cm[:8]) else 0
    ncand = np.mean([len(f.candidates) for f in frames]) if frames else 0
    return tot, h25, h50, h8, ncand


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", default="")
    ap.add_argument("--channel", type=int, default=None)
    ap.add_argument("--min-dur", type=float, default=0.4)
    args = ap.parse_args()
    cfg = DetectorConfig()
    print(f"{'file':34s} {'bpNoteFrames':>12s} {'R@25':>6s} {'R@50':>6s} {'R@50 top8':>9s} {'meanCands':>9s}")
    tot_all = [0, 0, 0, 0]
    for js in sorted((ROOT / "data" / "basicpitch").glob("*.json")):
        stem = js.stem
        ch = int(stem.rsplit(".", 1)[1])
        if (args.only and args.only not in stem) or (args.channel is not None and ch != args.channel):
            continue
        wav = ROOT / "data" / "channels" / f"{stem}.wav"
        tot, h25, h50, h8, nc = evaluate(wav, json.loads(js.read_text()), cfg, args.min_dur)
        if tot == 0:
            print(f"{stem:34s} {0:12d}")
            continue
        for i, v in enumerate((tot, h25, h50, h8)):
            tot_all[i] += v
        print(f"{stem:34s} {tot:12d} {h25/tot:6.2f} {h50/tot:6.2f} {h8/tot:9.2f} {nc:9.1f}")
    t = tot_all
    if t[0]:
        print(f"{'ALL':34s} {t[0]:12d} {t[1]/t[0]:6.2f} {t[2]/t[0]:6.2f} {t[3]/t[0]:9.2f}")


if __name__ == "__main__":
    main()
