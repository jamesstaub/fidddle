"""String identification on the detector's own tracks (spec §17.5), OrchideaSOL guitar.

Centroids log(B/f^2) are learned from the open-string notes with a long-window stiffness fit (the calibration pass), then scenes
of stopped notes are tracked and every confirmed track is assigned a string from a stiffness fit 0.2 s into the note. Reported for notes whose pitch can sound on 2+ strings.

  .venv/bin/python tools/eval_string_id.py [--kind lines,chords] [--voices 1] [--n 6] [--dynamics mf,ff] [--delay 0.2] [--span 0.8]
"""
import argparse
import sys
from collections import defaultdict
from pathlib import Path
import numpy as np
import soundfile as sf

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from fidddle.analyzer import Analyzer
from fidddle.profile import DetectorConfig
from fidddle.stringid import classify
from tools import eval_orchidea as eo
from didddle import physics as P
from tools.orchidea import catalog

OPEN = [64, 59, 55, 50, 45, 40]                     # string 1 = highest
f_of = lambda m: 440.0 * 2 ** ((m - 69) / 12)


def run(x, cfg, sr):
    return Analyzer(cfg).run(x, track=True)


def long_value(x, sr, f_hz, t_start, t_end, hop_frac=0.5):
    """Median log(B/f^2) from stiffness fits on Hann frames of 6 periods inside [t_start, t_end] of the mix; None if too few."""
    n = P.window_for(sr, f_hz)
    v = []
    for st in P.frame_starts(len(x), n, sr, t_start, t_end, hop_frac):
        r = P.stiffness(P.spectrum(x, st, n), sr / n, f_hz)
        if r and r["B"] > 1e-6:
            v.append(float(np.log(r["B"] / r["f0"] ** 2)))
    return (float(np.median(v)), len(v)) if v else (None, 0)


def learn(cfg, dynamics):
    cent = [None] * 6
    for st in range(1, 7):
        vals = []
        for s in catalog.select("guitar", ["ordinario"], dynamics):
            if s.string == st and s.midi == OPEN[st - 1]:
                x, sr = sf.read(s.path); x = x if x.ndim == 1 else x[:, 0]
                v, n = long_value(x, sr, f_of(s.midi), 0.15, min(len(x) / sr, 1.6))
                if n >= 2:
                    vals.append(v)
        if vals:
            cent[st - 1] = float(np.median(vals))
    return cent


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--kind", default="lines")
    ap.add_argument("--voices", type=int, default=1)
    ap.add_argument("--n", type=int, default=6)
    ap.add_argument("--hits", type=int, default=2)
    ap.add_argument("--dynamics", default="mf,ff")
    ap.add_argument("--delay", type=float, default=0.1, help="seconds after the track's first frame where the stiffness window starts")
    ap.add_argument("--span", type=float, default=0.8, help="seconds of signal the stiffness frames may use")
    a = ap.parse_args()
    cfg0 = DetectorConfig.for_instrument("guitar", float(eo.SR))
    open_hz = [f_of(m) for m in OPEN]
    cent = learn(cfg0, a.dynamics.split(","))
    print("learned log(B/f^2) per string 1..6:", [None if c is None else round(c, 2) for c in cent])
    ns = argparse.Namespace(instrument="guitar", kind=a.kind, n=a.n, voices=a.voices, hits=a.hits, techniques="ordinario",
                            dynamics=a.dynamics, seed=11, all_range=False)
    tot = ok = amb_tot = amb_ok = notes_n = covered = 0
    chance = 0.0
    rows = []
    for sc in eo.build_scenes(ns):
        cfg = DetectorConfig.for_instrument("guitar", float(eo.SR))
        frames = run(sc["mix"], cfg, eo.SR)
        first_t = {}
        last_t = {}
        mid = {}
        for fr in frames:
            for s in fr.tracks or []:
                if s is not None and s.state == 2:
                    last_t[s.track_id] = fr.t_s
                    if s.track_id not in first_t:
                        first_t[s.track_id] = fr.t_s
                        mid[s.track_id] = int(round(s.midi))
        for n in sc["notes"]:
            notes_n += 1
        for tid, t0 in first_t.items():
            truth = [n for n in sc["notes"] if n["midi"] == mid[tid] and n["onset"] - 0.1 <= t0 <= n["end"]]
            if not truth:
                continue
            t1 = last_t[tid]
            v, cnt = long_value(sc["mix"], eo.SR, f_of(mid[tid]), t0 + a.delay, min(t1, t0 + a.delay + a.span))
            if cnt < 1:
                continue
            covered += 1
            pred, marg = classify(v, f_of(mid[tid]), cent, open_hz)
            playable = [s for s in range(6) if 0 <= mid[tid] - OPEN[s] <= 24]
            hit = pred + 1 == truth[0]["string"]
            tot += 1; ok += hit
            if len(playable) >= 2:
                amb_tot += 1; amb_ok += hit; chance += 1.0 / len(playable); rows.append((marg, hit))
    print(f"{a.kind} voices {a.voices}: {notes_n} true notes, {covered} tracks with >= 3 stiffness samples (matched to a true note)")
    print(f"  string correct, all matched tracks:        {ok}/{tot}")
    print(f"  string correct, pitch playable on 2+ strings: {amb_ok}/{amb_tot} = {amb_ok / max(amb_tot, 1):.2f}   (chance {chance / max(amb_tot, 1):.2f})")
    for thr in (0.0, 0.3, 0.6, 1.0):
        sel = [h for m, h in rows if m >= thr]
        if sel:
            print(f"  margin >= {thr:.1f}: {sum(sel)}/{len(sel)} = {np.mean(sel):.2f}  ({len(sel) / len(rows):.0%} of the ambiguous notes answered)")


if __name__ == "__main__":
    main()