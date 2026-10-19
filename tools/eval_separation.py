"""Separation experiments for didddle.

  oracle-synth  synthetic stems, exact f0: the limit of the masking/LS step alone (by interval and chord)
  oracle-real   real-clip mixes, f0 from the detector run on each isolated source (non-causal)
  detector      same mixes/scenes, f0 from the detector run on the mixture, swept over lookahead

Usage: .venv/bin/python tools/eval_separation.py oracle-synth|oracle-real|detector [--method ls|mask] [--set k=v ...]
"""
import argparse
import json
import pickle
import sys
from pathlib import Path
import numpy as np
import soundfile as sf

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from didddle.config import SeparatorConfig
from didddle.f0 import truth_tracks, truth_spans, run_detector, tracks_from_run, spans_from_run, split_notes
from didddle.metrics import si_sdr, score, group_channels, match_stems
from didddle.separate import Separator
from fidddle.profile import DetectorConfig, InstrumentProfile
from fidddle.synth import Note, render_note

SR = 48000
MIXES = ROOT / "data" / "mixes"


def parse_sets(sets):
    out = {}
    for s in sets or ():
        k, v = s.split("=")
        t = type(getattr(SeparatorConfig, k, 0.0))
        out[k] = v if k == "method" else (v.lower() in ("1", "true", "yes") if t is bool else t(v))
    return out


def make_cfg(sr, profile, args):
    cfg = SeparatorConfig.from_profile(profile, sr, method=args.method, **parse_sets(args.set))
    if args.shape == "gate":
        cfg.transient_ms = 0.0
    return cfg


def use_spans(args):
    return args.shape != "off"


def horizons(L_s, cfg):
    """Detector information horizons for a total output delay L: a frame is processed once its audio is in
    (N/2 after its centre) and its pitch lookahead has passed, L = N/2 + max(N/2, D); gating happens at output time."""
    half = cfg.n_fft / 2 / cfg.sample_rate
    return max(L_s - half, half), L_s


# ---- synthetic scenes ---------------------------------------------------------------------------

def render_stems(notes, sr, dur, seed=0):
    rng = np.random.default_rng(seed)
    n = int(dur * sr)
    stems = np.zeros((len(notes), n))
    for i, nt in enumerate(notes):
        i0, y = render_note(nt, sr, n, rng)
        stems[i, i0: i0 + len(y)] = y
    return stems


def interval_scene(low, semis, kind="bowed", vib=15.0):
    return [Note(low, 0.2, 3.2, kind, vib), Note(low + semis, 0.2, 3.2, kind, vib)]


def chord_scene(midis, kind):
    return [Note(m, 0.3 + 0.02 * i, 3.3, kind, 12.0 if kind == "bowed" else 0.0) for i, m in enumerate(midis)]


def oracle_synth(args):
    prof = InstrumentProfile.cello()
    cfg = make_cfg(SR, prof, args)
    sep = Separator(cfg)
    scenes = {f"+{s:2d} st (C3)": interval_scene(48, s) for s in (1, 3, 4, 5, 6, 7, 12, 19)}
    scenes.update({f"+{s:2d} st (C2)": interval_scene(36, s) for s in (7, 12)})
    scenes["glide 48>55 + 62"] = [Note(48, 0.2, 1.4, "bowed", 0.0, glide_to=55), Note(62, 0.2, 1.4, "bowed", 0.0)]
    scenes["vibrato 40c 48 + 55"] = [Note(48, 0.2, 3.2, "bowed", 40.0), Note(55, 0.2, 3.2, "bowed", 40.0)]
    scenes["plucked 48 + 55"] = [Note(48, 0.2, 3.2, "plucked"), Note(55, 0.2, 3.2, "plucked")]
    scenes["chord bowed 40,47,55"] = chord_scene([40, 47, 55], "bowed")
    scenes["chord plucked 36,43,50,57"] = chord_scene([36, 43, 50, 57], "plucked")
    scenes["chord bowed 36,43,50,57"] = chord_scene([36, 43, 50, 57], "bowed")
    print(f"method={cfg.method} n_fft={cfg.n_fft} hop={cfg.hop}\n{'scene':28s} {'SI-SDR per stem (dB)':32s} {'gain over mix':>14s}  null err")
    allg = []
    for name, notes in scenes.items():
        dur = 3.8
        stems = render_stems(notes, SR, dur)
        mix = stems.sum(0)
        f0 = truth_tracks(notes, SR, len(mix), sep.centers(len(mix)))
        voices, res = sep.process(mix, f0, truth_spans(notes, SR) if use_spans(args) else None)
        sdr, gain = score(voices, stems, mix)
        null = np.max(np.abs(voices.sum(0) + res - mix))
        allg.append(gain.mean())
        print(f"{name:28s} {' '.join(f'{v:6.1f}' for v in sdr):32s} {gain.mean():14.1f}  {null:.1e}")
    print(f"mean gain {np.mean(allg):.1f} dB")


# ---- real mixes ---------------------------------------------------------------------------------

def load_mix(name, channel=0):
    """Reconstruct the isolated stems of a tools/make_mixes.py mix and verify them against the stored mix."""
    meta = json.loads((MIXES / f"{name}.json").read_text())
    mix, sr = sf.read(MIXES / f"{name}.wav")
    stems = []
    for s in meta["sources"]:
        x, _ = sf.read(ROOT / "data" / "channels" / f"{s['src']}.{channel}.wav")
        a = int(s["start_s"] * sr)
        seg = np.zeros(len(mix))
        part = x[a: a + len(mix)]
        seg[: len(part)] = part * 10 ** (s["gain_db"] / 20)
        stems.append(seg)
    stems = np.array(stems)
    raw = stems.sum(0)
    peak = np.max(np.abs(raw))
    if peak > 0.95:
        stems *= 0.95 / peak
    err = np.max(np.abs(stems.sum(0) - mix))
    return mix, stems, sr, [s["src"] for s in meta["sources"]], err


def cached_run(key, x, sr):
    """Detector runs dominate the cost and do not depend on separator settings: cache them."""
    f = ROOT / "data" / "separation" / "cache" / f"{key}.pkl"
    if f.exists():
        return pickle.loads(f.read_bytes())
    run = run_detector(x, DetectorConfig.for_instrument("cello", float(sr)))
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_bytes(pickle.dumps(run))
    return run


def oracle_real(args):
    names = sorted(p.stem for p in MIXES.glob("mix_*voice_*.wav"))
    names = [n for n in names if args.only in n]
    print(f"{'mix':16s} {'stem SI-SDR (dB)':36s} gain  ceiling  recon-err")
    gains, ceils = [], []
    by_src_all = {}
    for name in names:
        mix, stems, sr, src, rerr = load_mix(name)
        by_src = by_src_all
        cfg = make_cfg(sr, InstrumentProfile.cello(), args)
        sep = Separator(cfg)
        c = sep.centers(len(mix))
        chans, sp, groups, ceil = [], [], [], []
        for i, st in enumerate(stems):
            run = cached_run(f'{name}.stem{i}', st, sr)
            f0 = tracks_from_run(run, c, np.inf, cfg.n_fft // 2 if use_spans(args) else 0)
            spans = spans_from_run(run, np.inf, cfg.onset_lead_ms / 1000)
            keep = np.isfinite(f0).any(axis=1)
            chans.append(f0[keep])
            sp += [spans[k] for k in np.flatnonzero(keep)]
            groups += [i] * int(keep.sum())
            # ceiling: the isolated source rebuilt from its own voices alone = what the harmonic model can explain
            ceil.append(si_sdr(sep.process(st, f0[keep], [spans[k] for k in np.flatnonzero(keep)] if use_spans(args) else None)[0].sum(0), st)
                        if keep.any() else -30.0)
        f0 = np.concatenate(chans)
        if len(f0) == 0:
            continue
        voices, res = sep.process(mix, f0, sp if use_spans(args) else None)
        est = np.zeros_like(stems)
        for g, v in zip(groups, voices):
            est[g] += v
        sdr, gain = score(est, stems, mix)
        gains.append(gain.mean())
        ceils.append(np.mean(ceil))
        for sname, a, b, cc in zip(src, sdr, gain, ceil):
            by_src.setdefault(sname, []).append((a, b, cc))
        print(f"{name:16s} {' '.join(f'{v:6.1f}' for v in sdr):36s} {gain.mean():5.1f}  {np.mean(ceil):6.1f}   {rerr:.1e}")
    print(f"\n{'source':24s} {'n':>2s} {'SI-SDR':>7s} {'gain':>6s} {'ceiling':>8s}")
    for sname, v in sorted(by_src_all.items()):
        a = np.array(v)
        print(f"{sname:24s} {len(a):2d} {a[:, 0].mean():7.1f} {a[:, 1].mean():6.1f} {a[:, 2].mean():8.1f}")
    print(f"mean gain {np.mean(gains):.1f} dB, mean ceiling {np.mean(ceils):.1f} dB over {len(gains)} mixes")


def detector(args):
    names = [n for n in sorted(p.stem for p in MIXES.glob("mix_*voice_*.wav")) if args.only in n]
    lats = [float(v) / 1000 for v in args.latency.split(",")]
    print(f"gain over mixture (dB), mean over stems, detector pitches from the mixture. method={args.method} shape={args.shape}")
    print(f"{'mix':16s}" + "".join(f"{'L=' + str(int(l * 1000)) + 'ms':>9s}" for l in lats))
    tot = np.zeros(len(lats))
    for name in names:
        mix, stems, sr, _, _ = load_mix(name)
        cfg = make_cfg(sr, InstrumentProfile.cello(), args)
        sep = Separator(cfg)
        c = sep.centers(len(mix))
        run = cached_run(f"{name}.mix", mix, sr)
        row = []
        for L in lats:
            look_f0, look_gate = horizons(max(L, cfg.n_fft / sr), cfg)
            f0 = tracks_from_run(run, c, look_f0, cfg.n_fft // 2 if use_spans(args) else 0)
            spans = spans_from_run(run, look_gate, cfg.onset_lead_ms / 1000)
            f0, spans = split_notes(f0, spans, c, cfg.n_fft // 2 if use_spans(args) else 0)
            if len(f0) == 0:
                row.append(0.0)
                continue
            voices, res = sep.process(mix, f0, spans if use_spans(args) else None)
            est = group_channels(voices, stems)
            row.append(score(est, stems, mix)[1].mean())
        tot += row
        print(f"{name:16s}" + "".join(f"{v:9.1f}" for v in row))
    print(f"{'mean':16s}" + "".join(f"{v:9.1f}" for v in tot / len(names)))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", choices=["oracle-synth", "oracle-real", "detector"])
    ap.add_argument("--method", default="ls")
    ap.add_argument("--set", nargs="*")
    ap.add_argument("--only", default="")
    ap.add_argument("--latency", default="93,150,250,400", help="total output delays in ms (>= n_fft)")
    ap.add_argument("--shape", default="full", choices=["off", "gate", "full"])
    args = ap.parse_args()
    {"oracle-synth": oracle_synth, "oracle-real": oracle_real, "detector": detector}[args.mode](args)


if __name__ == "__main__":
    main()
