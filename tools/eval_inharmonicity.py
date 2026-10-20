"""Inharmonicity experiments (spec §17.10).

  real     measure the stiffness B and the departure from an exact harmonic series on single-note frames of the
           recorded clips (bowed against plucked), per channel
  synth    the same measurement on synthetic strings with known B (positive control: does it recover B?)
  identify can the data choose between B hypotheses? (fit explained fraction under each prior B, synthetic)
  cost     note-level cost of a wrong prior B for plucked (stiff) and bowed-locked (B = 0) strings
  strings  per-string B of the real DI guitar and 5-string bass open-string recordings vs the profile guess
  realcost the same on the recorded clips: explained fraction and agreement with the Basic Pitch notes (a proxy,
           not truth) for several prior B, bowed against plucked

Usage: .venv/bin/python tools/eval_inharmonicity.py real|synth|identify|cost [--clips a,b] [--channel 0]
"""
import argparse
import sys
from pathlib import Path
import numpy as np
import soundfile as sf

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from fidddle.analyzer import Analyzer
from fidddle.calibrate import Calibrator
from fidddle.frontend import dc_block, frame_ends
from fidddle.profile import DetectorConfig
from fidddle.salience import pick_candidates
from fidddle.spectral import magnitude, spectral_peaks
from fidddle.synth import Note, render
from tools.eval_tracker import score, events_to_notes

BOWED = ["bow-low-legato", "bow-open-accel_2", "bow-then-pizz", "bow-gliss", "bow-dbl-sustained_2", "bow-open-fifths"]
PLUCKED = ["pizz-mid-scale", "pizz-high-register_2", "pizz-open-5ths_2", "pizz-ascend-triads-1", "pizz-ascend-triads-2", "pizz-gliss"]


def partials_for_frames(x, sr, stride=2, min_db=-50.0, instrument="cello", pick=None):
    """Yield (end_sample, f0_hz, peak freqs, peak amps, ...) for frames whose fit is exactly one voice, or, with
    `pick(t_s, voices) -> f0 or None`, for the voice the caller selects (used where the truth says only one string rings)."""
    cfg = DetectorConfig.for_instrument(instrument, float(sr))
    az = Analyzer(cfg)
    x = dc_block(np.asarray(x, float), sr, cfg.dc_cutoff_hz)
    cal = Calibrator(cfg, az.n_long)
    for i, end in enumerate(frame_ends(len(x), az.n_long, cfg.hop_size)):
        M = magnitude(x[end - az.n_long: end], az.win_long)
        W, E, gate = az.whitener.process(M)
        if i % stride:
            continue
        S, hit, miss, inter = az.smap.compute(M, W, az.whitener.snr)
        cands = pick_candidates(az.smap, S, hit, miss, inter, cfg)
        peaks = spectral_peaks(M, W, az.smap.df, cfg.peak_min_w, amp=az.whitener.unclipped, snr=az.whitener.snr, min_snr=cfg.peak_min_snr)
        res = az.fitter.fit(W, E, cands, peaks, M=M)
        if pick is not None:
            f0 = pick(end / sr, [v for v in res.voices if v.level_db >= min_db])
            if f0 is None:
                continue
        elif len(res.voices) != 1 or res.voices[0].level_db < min_db:
            continue
        else:
            f0 = res.voices[0].f_hz
        pf, pa = np.asarray(peaks[0]), np.asarray(peaks[1])
        yield end, f0, pf, pa, cal, az.n_long


def stiff_fit(cal, f0, pf, pa):
    """Progressive assignment (as the calibrator) then unconstrained fits of (f_h/h)^2 = c0 + c1 h^2.
    Returns f0, B, n, rms cents of the stiff fit and of the best exact-harmonic fit, or None."""
    B = 0.0
    h = p = None
    for hmax in (6, 10, 16, 24, 32):
        h, p, a = cal._assign(f0, B, pf, pa, hmax)
        if len(h) < 4:
            return None
        y = (p / h) ** 2
        w = h.astype(float)
        X = np.stack([np.ones(len(h)), h.astype(float) ** 2], axis=1)
        (c0, c1), *_ = np.linalg.lstsq(X * w[:, None], y * w, rcond=None)
        if c0 <= 0:
            return None
        f0, B = float(np.sqrt(c0)), c1 / c0
        B = float(np.clip(B, -2e-4, 2e-3))
    if len(h) < 8:
        return None
    cents = lambda pred: 1200 * np.log2(p / pred)
    stiff = cents(f0 * h * np.sqrt(1 + max(B, -1e-6) * h * h))
    # exact harmonic series with free f0 (weighted LS on p = f * h)
    fe = float(np.sum(p * h * h) / np.sum(h * h.astype(float) ** 2) * 0 + np.sum(p * h) / np.sum(h * h))
    harm = cents(fe * h)
    return f0, B, len(h), float(np.sqrt(np.mean(stiff ** 2))), float(np.sqrt(np.mean(harm ** 2)))


def measure(x, sr, stride=2, instrument="cello", with_time=False, pick=None):
    rows = []
    for end, f0, pf, pa, cal, _ in partials_for_frames(x, sr, stride, instrument=instrument, pick=pick):
        r = stiff_fit(cal, f0, pf, pa)
        if r:
            rows.append((end / sr,) + r if with_time else r)
    return np.array(rows)


def summarise(name, rows):
    if len(rows) == 0:
        print(f"  {name:24s}  no clean single-note frames")
        return
    f0, B, n, rs, rh = rows.T
    q = np.percentile(B, [25, 50, 75]) * 1e5
    print(f"  {name:24s} frames {len(rows):4d}  f0 {np.median(f0):6.1f} Hz  partials {np.median(n):4.1f}   B x1e5: {q[1]:6.2f} [{q[0]:5.2f},{q[2]:5.2f}]"
          f"   rms cents: stiff {np.median(rs):5.1f}  exact-harmonic {np.median(rh):5.1f}")


def run_real(args):
    for ch in [int(c) for c in args.channel.split(",")]:
        print(f"channel {ch} ({'piezo' if ch == 0 else 'condenser'})")
        for group, clips in (("bowed", BOWED), ("plucked", PLUCKED)):
            allrows = []
            for c in (args.clips.split(",") if args.clips else clips):
                x, sr = sf.read(ROOT / "data" / "channels" / f"{c}.{ch}.wav")
                rows = measure(x, sr)
                summarise(c, rows)
                allrows.append(rows)
            rows = np.concatenate([r for r in allrows if len(r)]) if any(len(r) for r in allrows) else np.zeros((0, 5))
            summarise(f"ALL {group}", rows)
            if args.clips:
                break


def synth_note(midi, kind, B, dur=2.5, onset=0.3):
    return Note(midi, onset, onset + dur, kind, 0.0 if kind == "plucked" else 8.0, B=B, tau0=2.5 if kind == "plucked" else 1.6)


def run_synth(args):
    sr = 44100.0
    print("synthetic strings, single notes C2 G2 D3 A3 (true B known): does the measurement recover it?")
    for kind, B in (("plucked", 0.0), ("plucked", 5e-5), ("plucked", 2e-4), ("bowed", 0.0), ("bowed", 2e-4)):
        rows = []
        for midi in (36, 43, 50, 57):
            x = render([synth_note(midi, kind, B)], sr, 3.4, snr_db=40.0, seed=midi)
            rows.append(measure(x, sr))
        rows = np.concatenate([r for r in rows if len(r)])
        summarise(f"{kind} B={B:.0e}", rows)


SCENES = {"single C2": [36], "single A3": [57], "fifth C2 G2": [36, 43], "open strings": [36, 43, 50, 57]}


def make(kind, B, midis):
    return [Note(m, 0.3 + 0.03 * i, 3.3, kind, 0.0 if kind == "plucked" else 8.0, B=B, tau0=2.5 if kind == "plucked" else 1.6) for i, m in enumerate(midis)]


def run_notes(prior_B, notes, sr=44100.0):
    cfg = DetectorConfig.for_instrument("cello", sr)
    cfg.profile.inharmonicity_B = prior_B
    x = render(notes, sr, max(n.offset_s for n in notes) + 0.6, snr_db=40.0, seed=1)
    az = Analyzer(cfg)
    frames = az.run(x, track=True)
    est = events_to_notes(az.events, sr)
    ref = [(n.onset_s, n.offset_s, n.midi) for n in notes]
    s = score(ref, est)
    ex = [f.fit.explained for f in frames if f.fit is not None and f.fit.voices and f.t_s > 1.0 and f.t_s < 3.3]
    return s, float(np.mean(ex)) if ex else float("nan")


PRIORS = (0.0, 5e-5, 1e-4, 2e-4, 4e-4)


def run_identify(args):
    print("mean explained fraction of the spectrum (steady frames) under each prior B; the true B should win")
    print(f"{'truth':28s}" + "".join(f"{'B=' + format(b, '.0e'):>10s}" for b in PRIORS) + "   best")
    for kind, B in (("plucked", 2e-4), ("plucked", 1e-4), ("bowed", 0.0), ("bowed", 2e-4)):
        for name in ("single A3", "open strings"):
            ex = [run_notes(pb, make(kind, B, SCENES[name]))[1] for pb in PRIORS]
            print(f"{kind + ' B=' + format(B, '.0e') + ' ' + name:28s}" + "".join(f"{v:10.3f}" for v in ex) + f"   {PRIORS[int(np.nanargmax(ex))]:.0e}")


def run_cost(args):
    print("note-level F1 (est/ref notes) for a prior B, truth B = 2e-4 plucked or 0 bowed (locked)")
    print(f"{'scene':28s}" + "".join(f"{'B=' + format(b, '.0e'):>14s}" for b in PRIORS))
    for kind, B in (("plucked", 2e-4), ("bowed", 0.0)):
        for name, midis in SCENES.items():
            cells = []
            for pb in PRIORS:
                s, _ = run_notes(pb, make(kind, B, midis))
                cells.append(f"{s['F1']:.2f} ({s['n_est']}/{s['n_ref']})" if s else "-")
            print(f"{kind + ' ' + name:28s}" + "".join(f"{c:>14s}" for c in cells))


def _real_task(args):
    import json
    clip, ch, pb, seconds = args
    x, sr = sf.read(ROOT / "data" / "channels" / f"{clip}.{ch}.wav")
    x = x[: int(seconds * sr)]
    cfg = DetectorConfig.for_instrument("cello", float(sr))
    cfg.profile.inharmonicity_B = pb
    az = Analyzer(cfg)
    frames = az.run(x, track=True)
    est = events_to_notes(az.events, sr)
    bp = json.loads((ROOT / "data" / "basicpitch" / f"{clip}.{ch}.json").read_text())
    ref = [(n["onset"], n["offset"], n["midi"]) for n in bp if n["onset"] < seconds]
    s = score(ref, est)
    ex = [f.fit.explained for f in frames if f.fit is not None and len(f.fit.voices) >= 1]
    return clip, pb, float(np.mean(ex)) if ex else float("nan"), len(est), len(ref), s["F1"] if s else float("nan")


def run_realcost(args):
    from multiprocessing import Pool
    priors = (0.0, 2e-5, 4e-5, 8e-5, 1.6e-4)
    clips = [("bowed", c) for c in ("bow-low-legato", "bow-open-fifths", "bow-then-pizz", "bow-dbl-sustained_2")] + \
            [("plucked", c) for c in ("pizz-mid-scale", "pizz-open-5ths_2", "pizz-ascend-triads-1", "pizz-ascend-triads-2", "pizz-high-register_2")]
    ch = int(args.channel.split(",")[0])
    tasks = [(c, ch, pb, 12.0) for _, c in clips for pb in priors]
    with Pool(8) as pool:
        res = pool.map(_real_task, tasks)
    table = {(c, pb): r for r in res for c, pb in [(r[0], r[1])]}
    print(f"channel {ch}. cells: mean explained fraction | notes detected/Basic Pitch | F1 against Basic Pitch (proxy)")
    print(f"{'clip':26s}" + "".join(f"{'B=' + format(b, '.0e'):>22s}" for b in priors))
    for kind, c in clips:
        cells = []
        for pb in priors:
            _, _, ex, ne, nr, f1 = table[(c, pb)]
            cells.append(f"{ex:.3f} | {ne}/{nr} | {f1:.2f}")
        print(f"{kind[:4] + ' ' + c:26s}" + "".join(f"{x:>22s}" for x in cells))


OPEN = {  # real DI recordings in data/: instrument, profile B guess, expected open-string plucks (time_s, midi)
    "guitar-open-strings": ("guitar", 1e-4, [(0.55, 40), (2.94, 45), (5.51, 50), (8.17, 55), (10.66, 59), (12.95, 64)]),
    "5string-bass-open-strings": ("bass", 5e-5, [(0.63, 23), (2.74, 28), (4.65, 33), (6.87, 38), (9.21, 43)]),
}


def run_strings(args):
    print("B of each plucked open string on the real DI recordings (frames within 40 cents of the open string, single clean voice)")
    for stem, (inst, prof_B, plucks) in OPEN.items():
        x, sr = sf.read(ROOT / "data" / f"{stem}.wav", always_2d=True)
        for ch in range(min(x.shape[1], 1)):
            starts = [t for t, _ in plucks]

            def pick(t, voices, starts=starts, plucks=plucks):
                # the string plucked most recently, if that pitch is among the fitted voices
                i = max([j for j, t0 in enumerate(starts) if t0 + 0.1 < t] or [-1])
                if i < 0:
                    return None
                f_nom = 440 * 2 ** ((plucks[i][1] - 69) / 12)
                near = [v.f_hz for v in voices if abs(1200 * np.log2(v.f_hz / f_nom)) < 40]
                return near[0] if near else None
            rows = measure(x[:, ch], sr, instrument=inst, with_time=True, pick=pick)
            print(f"{stem}  (profile B = {prof_B:.0e})")
            ends = [t for t, _ in plucks[1:]] + [1e9]
            for (t0, midi), t1 in zip(plucks, ends):
                f_nom = 440 * 2 ** ((midi - 69) / 12)
                k = (rows[:, 0] > t0 + 0.1) & (rows[:, 0] < min(t1 - 0.05, t0 + 2.5)) & (np.abs(1200 * np.log2(rows[:, 1] / f_nom)) < 40) if len(rows) else []
                r = rows[k]
                if len(r) < 5:
                    print(f"  midi {midi} ({f_nom:6.1f} Hz): too few clean frames ({len(r)})")
                    continue
                q = np.percentile(r[:, 2], [25, 50, 75]) * 1e5
                print(f"  midi {midi} ({f_nom:6.1f} Hz): frames {len(r):3d}  partials {np.median(r[:, 3]):4.1f}  B x1e5 {q[1]:6.2f} [{q[0]:5.2f},{q[2]:5.2f}]"
                      f"  ({q[1] / (prof_B * 1e5):4.2f} x profile)  rms cents stiff {np.median(r[:, 4]):4.1f}  exact-harmonic {np.median(r[:, 5]):4.1f}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", choices=["real", "synth", "identify", "cost", "realcost", "strings"])
    ap.add_argument("--clips", default="")
    ap.add_argument("--channel", default="0,1")
    args = ap.parse_args()
    {"real": run_real, "synth": run_synth, "identify": run_identify, "cost": run_cost, "realcost": run_realcost, "strings": run_strings}[args.mode](args)


if __name__ == "__main__":
    main()
