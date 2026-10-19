"""Build polyphonic test mixes by overlapping real mono cello clips.

Reference truth for a mix is the union of Basic Pitch notes computed on each
*isolated* source clip (shifted by its offset). That is a proxy, not annotation:
Basic Pitch can be wrong on a solo clip too, so the notes are filtered by
duration and the mixes are only trusted for relative comparisons.

Usage: .venv/bin/python tools/make_mixes.py [--channel 0] [--seed 0]
Writes data/mixes/mix_<k>voice_<n>.wav and .json
"""
import argparse
import json
import sys
from pathlib import Path
import numpy as np
import soundfile as sf

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# Mostly-monophonic sources (single line, arco or pizz).
SOURCES = ["bow-low-legato", "pizz-mid-scale", "pizz-high-register_2", "bow-then-pizz",
           "pizz-harmonic-descend", "bow-gliss", "jete-bounces", "bow-open-accel_2"]
OUT = ROOT / "data" / "mixes"


def load_source(stem, ch):
    x, sr = sf.read(ROOT / "data" / "channels" / f"{stem}.{ch}.wav")
    notes = json.loads((ROOT / "data" / "basicpitch" / f"{stem}.{ch}.json").read_text())
    return x, sr, notes


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--channel", type=int, default=0)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--per-size", type=int, default=4)
    ap.add_argument("--dur", type=float, default=8.0)
    ap.add_argument("--min-note", type=float, default=0.3)
    args = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(args.seed)
    for nv in (2, 3, 4):
        for k in range(args.per_size):
            picks = rng.choice(len(SOURCES), nv, replace=False)
            mix = None
            truth = []
            meta = []
            for si in picks:
                stem = SOURCES[si]
                x, sr, notes = load_source(stem, args.channel)
                n = int(args.dur * sr)
                start = int(rng.uniform(0, max(0, len(x) - n)))
                seg = x[start: start + n]
                if len(seg) < n:
                    seg = np.pad(seg, (0, n - len(seg)))
                gain = 10 ** (-rng.uniform(0, 6) / 20)
                seg = seg * gain
                mix = seg if mix is None else mix + seg
                t0 = start / sr
                for nt in notes:
                    on, off = nt["onset"] - t0, nt["offset"] - t0
                    on, off = max(on, 0.0), min(off, args.dur)
                    if off - on >= args.min_note:
                        truth.append({"onset": on, "offset": off, "midi": nt["midi"], "src": stem})
                meta.append({"src": stem, "start_s": t0, "gain_db": float(20 * np.log10(gain))})
            peak = np.max(np.abs(mix))
            if peak > 0.95:
                mix = mix * 0.95 / peak
            name = f"mix_{nv}voice_{k}"
            sf.write(OUT / f"{name}.wav", mix, sr)
            (OUT / f"{name}.json").write_text(json.dumps({"sr": sr, "sources": meta, "notes": sorted(truth, key=lambda n: n["onset"])}))
            print(name, [m["src"] for m in meta], f"{len(truth)} ref notes")


if __name__ == "__main__":
    main()
