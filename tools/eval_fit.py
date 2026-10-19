"""Multi-pitch fit evaluation on synthetic chords (and, with --mixes, polyphonic mixes).

Config overrides: --set key=value (repeatable), e.g. --set first_voice_min_gain=0.12
Usage: .venv/bin/python tools/eval_fit.py [--vib 0] [--stride 4] [--mixes]
"""
import argparse
import json
import sys
from pathlib import Path
import numpy as np
import soundfile as sf

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from cellostop.profile import DetectorConfig
from cellostop.analyzer import Analyzer
from cellostop.synth import chord, render
from dataclasses import replace
from cellostop.evaluate import fit_scores

CASES = {
    "1: C2": [36], "1: A3": [57], "1: E5": [76],
    "2: fifth C2+G2": [36, 43], "2: octave C2+C3": [36, 48], "2: third C3+E3": [48, 52], "2: dyad D3+Eb3": [50, 51],
    "3: triad C3 E3 G3": [48, 52, 55],
    "4: open strings": [36, 43, 50, 57], "4: C3 G3 E4 C5": [48, 55, 64, 72],
}


def set_overrides(cfg, items):
    for it in items or []:
        k, v = it.split("=")
        cur = getattr(cfg, k)
        setattr(cfg, k, type(cur)(v) if not isinstance(cur, tuple) else tuple(float(t) for t in v.split(",")))


def synth_eval(cfg, args, verbose=True):
    tot = {"tp": 0}
    rows = []
    agg = []
    for kind in args.kinds:
        for name, midis in CASES.items():
            notes = chord(midis, kind=kind, dur_s=3.0, vib_cents=args.vib)
            x = render(notes, cfg.sample_rate, 3.6, snr_db=args.snr, seed=1)
            az = Analyzer(cfg)
            frames = az.run(x, fit=True, fit_stride=args.stride)
            s = fit_scores(frames, notes, cfg.sample_rate, az.n_long)
            rows.append((kind, name, s))
            agg.append(s)
            if verbose:
                print(f"{kind:8s} {name:20s} P={s['P']:.2f} R={s['R']:.2f} F1={s['F1']:.2f} oct_fp={s['oct_fp']}/{s['fp']} count_acc={s['count_acc']:.2f} n={s['frames']}")
    f1 = np.mean([s["F1"] for s in agg])
    print(f"MEAN F1 {f1:.3f}  P {np.mean([s['P'] for s in agg]):.3f}  R {np.mean([s['R'] for s in agg]):.3f}  count_acc {np.mean([s['count_acc'] for s in agg]):.3f}")
    return f1


def mixes_eval(cfg, args):
    mdir = ROOT / "data" / "mixes"
    tot = {"n": 0}
    bp_rows = []
    for wav in sorted(mdir.glob("mix_*.wav")):
        meta = json.loads(wav.with_suffix(".json").read_text())

        class N:  # adapt reference notes to the evaluator
            pass
        notes = []
        for n in meta["notes"]:
            o = N()
            o.midi, o.onset_s, o.offset_s, o.kind = float(n["midi"]), n["onset"], n["offset"], "bowed"
            notes.append(o)
        x, sr = sf.read(wav)
        cfg.sample_rate = float(sr)
        az = Analyzer(cfg)
        frames = az.run(x, fit=True, fit_stride=args.stride)
        s = fit_scores(frames, notes, sr, az.n_long)
        bpjs = wav.with_suffix(".bp.json")
        if bpjs.exists():
            bp = json.loads(bpjs.read_text())
            class V:
                def __init__(self, m): self.midi = m
            class F:
                def __init__(self, vs): self.voices = vs
            win = az.n_long / sr
            bframes = [replace(f, fit=F([V(float(b["midi"])) for b in bp if b["onset"] <= f.t_s - win / 2 <= b["offset"]])) for f in frames if f.fit is not None]
            sb = fit_scores(bframes, notes, sr, az.n_long)
            bp_rows.append(sb)
        print(f"{wav.stem:14s} P={s['P']:.2f} R={s['R']:.2f} F1={s['F1']:.2f} fp/frame={s['fp']/max(s['frames'],1):.2f} count_acc={s['count_acc']:.2f} n={s['frames']}")
        tot["n"] += s["frames"]
        tot.setdefault("rows", []).append(s)
    rows = tot["rows"]
    w = np.array([r["frames"] for r in rows], float)
    P = np.average([r["P"] for r in rows], weights=w)
    R = np.average([r["R"] for r in rows], weights=w)
    if bp_rows:
        wb = np.array([r["frames"] for r in bp_rows], float)
        Pb = np.average([r["P"] for r in bp_rows], weights=wb)
        Rb = np.average([r["R"] for r in bp_rows], weights=wb)
        print(f"BASIC PITCH (same frames) P={Pb:.3f}  R={Rb:.3f}  F1={2*Pb*Rb/max(Pb+Rb,1e-9):.3f}  count_acc={np.average([r['count_acc'] for r in bp_rows], weights=wb):.3f}")
    print(f"POOLED (frame-weighted)  P={P:.3f}  R={R:.3f}  F1={2*P*R/max(P+R,1e-9):.3f}  count_acc={np.average([r['count_acc'] for r in rows], weights=w):.3f}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--vib", type=float, default=0.0)
    ap.add_argument("--snr", type=float, default=40.0)
    ap.add_argument("--stride", type=int, default=4)
    ap.add_argument("--kinds", nargs="+", default=["bowed", "plucked"])
    ap.add_argument("--mixes", action="store_true")
    ap.add_argument("--set", action="append")
    args = ap.parse_args()
    cfg = DetectorConfig(sample_rate=44100.0)
    set_overrides(cfg, args.set)
    if args.mixes:
        mixes_eval(cfg, args)
    else:
        synth_eval(cfg, args)


if __name__ == "__main__":
    main()
