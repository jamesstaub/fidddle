"""Compare our candidate recall and Basic Pitch note recall on the polyphonic mixes.

Frames are ours (causal, window end time t). A reference note counts in a frame
when it covers the whole long window. For Basic Pitch a reference pitch is
matched when a BP note of the same MIDI number is sounding at the window centre.

Usage: .venv/bin/python tools/eval_mixes.py [--run-bp]
"""
import argparse
import json
import subprocess
import sys
from pathlib import Path
import numpy as np
import soundfile as sf

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from cellostop.profile import DetectorConfig
from cellostop.analyzer import Analyzer
from cellostop.corpus import BASICPITCH_CLI
from tools.run_basicpitch import midi_to_notes

MIX = ROOT / "data" / "mixes"


def bp_notes(wav, force):
    js = wav.with_suffix(".bp.json")
    if js.exists() and not force:
        return json.loads(js.read_text())
    subprocess.run([str(BASICPITCH_CLI), str(wav), str(MIX)], capture_output=True, check=True)
    notes = midi_to_notes(MIX / f"{wav.stem}.mid")
    js.write_text(json.dumps(notes))
    return notes


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-bp", action="store_true", help="(re)run Basic Pitch on mixes")
    args = ap.parse_args()
    cfg = DetectorConfig()
    print(f"{'mix':16s} {'refFrames':>9s} | {'ours R@50':>9s} {'top8':>5s} {'top12':>5s} | {'BP recall':>9s} {'BP extra/frame':>14s}")
    agg = np.zeros(6)
    for wav in sorted(MIX.glob("mix_*.wav")):
        meta = json.loads(wav.with_suffix(".json").read_text())
        ref = meta["notes"]
        x, sr = sf.read(wav)
        cfg.sample_rate = float(sr)
        az = Analyzer(cfg)
        frames = az.run(x)
        win = az.n_long / sr
        bp = bp_notes(wav, args.run_bp)
        tot = ours = o8 = o12 = bph = 0
        extra = 0
        nfr = 0
        for f in frames:
            act = [n for n in ref if n["onset"] <= f.t_s - win - 0.03 and f.t_s <= n["offset"] - 0.03]
            if not act:
                continue
            nfr += 1
            cm = np.array([c.midi for c in f.candidates])
            tc = f.t_s - win / 2
            bpa = {n["midi"] for n in bp if n["onset"] <= tc <= n["offset"]}
            truth_m = {n["midi"] for n in act}
            extra += len(bpa - truth_m)
            for n in act:
                tot += 1
                if len(cm):
                    ours += np.abs(cm - n["midi"]).min() <= 0.5
                    o8 += np.abs(cm[:8] - n["midi"]).min() <= 0.5
                    o12 += np.abs(cm[:12] - n["midi"]).min() <= 0.5
                bph += n["midi"] in bpa
        if tot == 0:
            continue
        agg += [tot, ours, o8, o12, bph, extra]
        print(f"{wav.stem:16s} {tot:9d} | {ours/tot:9.2f} {o8/tot:5.2f} {o12/tot:5.2f} | {bph/tot:9.2f} {extra/max(nfr,1):14.2f}")
    t = agg
    print(f"{'ALL':16s} {int(t[0]):9d} | {t[1]/t[0]:9.2f} {t[2]/t[0]:5.2f} {t[3]/t[0]:5.2f} | {t[4]/t[0]:9.2f} {t[5]/max(t[0],1):14.2f}")


if __name__ == "__main__":
    main()
