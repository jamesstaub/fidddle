"""Tests of the physical assumptions of spec §17 on the OrchideaSOL one-shots (real isolated strings, known pitch,
string, technique and dynamic). Reads the library in place; writes nothing.

  bstring  guitar: does B follow the string and the f^2 law, and what does the pitch-only rule cost?
  inharm   stiffness B by instrument, excitation (bowed against plucked), string and pitch
  phase    do the partial phases of a note follow a stable, smooth pattern? (phase locking, spec §17.8)
  body     is a partial's weight a function of absolute frequency (shared body) or of partial number (per string)?

Usage: .venv/bin/python tools/eval_physics.py inharm|phase|body [--instruments cello,bass] [--n 40]
"""
import argparse
import sys
from collections import defaultdict
from pathlib import Path
import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from didddle import physics as P
from tools.orchidea import catalog

BOWED = "ordinario"
PLUCK = {"guitar": "ordinario"}
PLUCK_DEFAULT = "pizzicato_secco"
OPEN = {  # open-string MIDI pitches, string 1 = highest
    "violin": [76, 69, 62, 55], "viola": [69, 62, 55, 48], "cello": [57, 50, 43, 36], "bass": [43, 38, 33, 28],
    "guitar": [64, 59, 55, 50, 45, 40],
}


def f_of(m):
    return 440.0 * 2 ** ((m - 69) / 12)


def excitation(inst, tech):
    if inst == "guitar":
        return "plucked"
    return "plucked" if tech.startswith("pizzicato") else "bowed"


def steady_window(snd, dur):
    """(t0, t1) in seconds of the part of the note to analyse."""
    if excitation(snd.instrument, snd.technique) == "bowed":
        return 0.3, min(dur - 0.1, 2.0)
    return 0.04, min(dur, 0.9)


def notes(inst, tech, dynamics=("mf", "ff", "pp")):
    return [s for s in catalog.select(inst, [tech], list(dynamics))]


def measure_note(snd, hop_frac=0.5):
    x, sr = P.load(snd.path)
    f = f_of(snd.midi)
    n = P.window_for(sr, f)
    t0, t1 = steady_window(snd, len(x) / sr)
    rows = []
    for s in P.frame_starts(len(x), n, sr, t0, t1, hop_frac):
        r = P.stiffness(P.spectrum(x, s, n), sr / n, f)
        if r:
            rows.append(r)
    return rows


def run_inharm(args):
    insts = args.instruments.split(",")
    results = {}
    for inst in insts:
        for tech in (BOWED, PLUCK.get(inst, PLUCK_DEFAULT)):
            for snd in notes(inst, tech)[:: max(1, len(notes(inst, tech)) // args.n)]:
                rows = measure_note(snd)
                if len(rows) >= 2:
                    results[(inst, tech, snd.string, snd.midi, snd.dynamic)] = (
                        np.median([r["B"] for r in rows]), np.median([r["n"] for r in rows]),
                        np.median([r["rms_stiff"] for r in rows]), np.median([r["rms_harm"] for r in rows]))
    print("B x1e5 by instrument and excitation (median over notes [25%,75%]; n notes; partials; rms cents stiff / exact-harmonic)")
    for inst in insts:
        for tech in (BOWED, PLUCK.get(inst, PLUCK_DEFAULT)):
            v = np.array([r for k, r in results.items() if k[0] == inst and k[1] == tech])
            if len(v) == 0:
                continue
            q = np.percentile(v[:, 0], [25, 50, 75]) * 1e5
            print(f"  {inst:7s} {tech:16s} n {len(v):3d}  B {q[1]:6.2f} [{q[0]:6.2f},{q[2]:6.2f}]  partials {np.median(v[:, 1]):4.1f}  rms {np.median(v[:, 2]):4.1f} / {np.median(v[:, 3]):4.1f}")
    print("\nB x1e5 per string (median over pitches), bowed | plucked")
    for inst in insts:
        line = []
        for st in range(1, 7):
            cell = []
            for tech in (BOWED, PLUCK.get(inst, PLUCK_DEFAULT)):
                v = [r[0] for k, r in results.items() if k[0] == inst and k[1] == tech and k[2] == st]
                cell.append(f"{np.median(v) * 1e5:6.2f}({len(v)})" if len(v) >= 2 else "   -   ")
            if any(c.strip() != "-" for c in cell):
                line.append(f"s{st}: {cell[0]} | {cell[1]}")
        print(f"  {inst:7s} " + "   ".join(line))
    print("\nB against pitch within a string: log-log slope of B on f (plucked; the f^2 law predicts 2)")
    for inst in insts:
        tech = PLUCK.get(inst, PLUCK_DEFAULT)
        for st in range(1, 7):
            k = [(f_of(key[3]), r[0]) for key, r in results.items() if key[0] == inst and key[1] == tech and key[2] == st and r[0] > 1e-6]
            if len(k) >= 6 and max(f for f, _ in k) / min(f for f, _ in k) > 1.3:
                f, b = np.array(k).T
                sl, ic = np.polyfit(np.log(f), np.log(b), 1)
                r = np.corrcoef(np.log(f), np.log(b))[0, 1]
                print(f"  {inst:7s} string {st}: n {len(k):3d}  slope {sl:5.2f}  corr {r:5.2f}  f {f.min():5.0f}-{f.max():5.0f} Hz")
    return results


def run_bstring(args):
    """Guitar (the clean plucked case): predict B of every note from its string's open-string value with B ~ f^2,
    against the current detector rule (the highest open string at or below the pitch, whatever string was played)."""
    inst = "guitar"
    opens = OPEN[inst]
    Bm = defaultdict(list)                       # (string, midi) -> B per note
    for snd in notes(inst, PLUCK[inst]):
        rows = measure_note(snd)
        if len(rows) >= 2:
            Bm[(snd.string, snd.midi)].append(np.median([r["B"] for r in rows]))
    B = {k: float(np.median(v)) for k, v in Bm.items()}
    B_open = {st: B[(st, m)] for st, m in enumerate(opens, 1) if (st, m) in B}
    print("open-string B x1e5:", {st: round(v * 1e5, 2) for st, v in B_open.items()})

    def pred_true_string(st, m, p=2.0):
        return B_open[st] * (f_of(m) / f_of(opens[st - 1])) ** p

    def pred_pitch_rule(m):
        cand = [st for st in B_open if opens[st - 1] <= m + 0.5]
        if not cand:
            return None
        st = max(cand, key=lambda s: opens[s - 1])        # highest open string at or below the pitch
        return B_open[st] * (f_of(m) / f_of(opens[st - 1])) ** 2

    err_true, err_rule, n_wrong, n_all = [], [], 0, 0
    for (st, m), b in B.items():
        if m == opens[st - 1] or b <= 2e-6 or st not in B_open:
            continue
        pt, pr = pred_true_string(st, m), pred_pitch_rule(m)
        if pt is None or pr is None or pr <= 0:
            continue
        err_true.append(np.log(b / pt)); err_rule.append(np.log(b / pr))
        rule_st = max([s for s in B_open if opens[s - 1] <= m + 0.5], key=lambda s: opens[s - 1])
        n_all += 1; n_wrong += rule_st != st
    et, er = np.array(err_true), np.array(err_rule)
    print(f"stopped guitar notes with B > 0.2e-5: {len(et)}   the pitch-only rule names the wrong string for {n_wrong} of them")
    print(f"  log(B measured / B predicted), true string + f^2 law: median {np.median(et):+.2f}  rms {np.sqrt(np.mean(et ** 2)):.2f}  (factor {np.exp(np.sqrt(np.mean(et ** 2))):.2f})")
    print(f"  log(B measured / B predicted), pitch-only rule        : median {np.median(er):+.2f}  rms {np.sqrt(np.mean(er ** 2)):.2f}  (factor {np.exp(np.sqrt(np.mean(er ** 2))):.2f})")
    # free exponent over all strings jointly
    xs, ys = [], []
    for (st, m), b in B.items():
        if st in B_open and m != opens[st - 1] and b > 2e-6:
            xs.append(np.log(f_of(m) / f_of(opens[st - 1]))); ys.append(np.log(b / B_open[st]))
    xs, ys = np.array(xs), np.array(ys)
    print(f"  free exponent p in B = B_open (f/f_open)^p over {len(xs)} stopped notes: {np.sum(xs * ys) / np.sum(xs * xs):.2f}")
    print("same pitch on two strings (B x1e5):")
    by_pitch = defaultdict(dict)
    for (st, m), b in B.items():
        by_pitch[m][st] = b
    shown = 0
    for m, d in sorted(by_pitch.items()):
        if len(d) >= 2 and shown < 12:
            print(f"  midi {m}: " + "  ".join(f"s{st}:{v * 1e5:6.2f}" for st, v in sorted(d.items())))
            shown += 1


def note_phases(snd, hop_frac=0.25, kmax=20):
    """Relative partial phases psi_h = phi_h - h phi_1 at the centre of each steady frame of a note.
    Returns (psi (frames x K), amplitudes (frames x K)) for the first K consecutive harmonics, or None."""
    x, sr = P.load(snd.path)
    f = f_of(snd.midi)
    n = P.window_for(sr, f)
    t0, t1 = steady_window(snd, len(x) / sr)
    psi, amp = [], []
    for st in P.frame_starts(len(x), n, sr, t0, t1, hop_frac):
        X = P.spectrum(x, st, n)
        r = P.stiffness(X, sr / n, f)
        if not r:
            continue
        h = r["h"]
        K = 0
        while K < len(h) and h[K] == K + 1 and K < kmax:
            K += 1
        if K < 8:
            continue
        nu = r["f0"] * np.arange(1, K + 1) * np.sqrt(1 + max(r["B"], 0) * np.arange(1, K + 1) ** 2) / (sr / n)
        c = P.complex_amplitudes(X, nu, n)
        ph = P.centre_phase(c, nu)
        psi.append(ph - np.arange(1, K + 1) * ph[0]); amp.append(np.abs(c))
    if len(psi) < 4:
        return None
    K = min(len(p) for p in psi)
    return np.array([p[:K] for p in psi]), np.array([a[:K] for a in amp])


def circ_std(psi):
    """Circular standard deviation over frames (axis 0), per partial."""
    R = np.abs(np.mean(np.exp(1j * psi), axis=0))
    return np.sqrt(-2 * np.log(np.clip(R, 1e-6, 1)))


def run_phase(args):
    print("Phase structure of partials within a note: psi_h = phi_h - h phi_1 at the frame centre (75% overlapping frames)")
    print("  stability = circular std of psi_h over frames, median over h = 2..12 and notes (rad; 0 = locked, 1.8 = random)")
    print("  predict   = fraction of partials h = 3..14 whose time-mean psi_h is within 0.5 rad of a prediction from its neighbours")
    print("              (chance 0.16): 'lin' = 2 psi_{h-1} - psi_{h-2};  'gap' = mean phasor of h-1 and h+1 (mod 2pi | mod pi)")
    for inst in args.instruments.split(","):
        for tech in (BOWED, PLUCK.get(inst, PLUCK_DEFAULT)):
            if inst == "guitar" and tech == BOWED and False:
                continue
            stab, lin, gap2, gappi = [], [], [], []
            ss = notes(inst, tech)
            for snd in ss[:: max(1, len(ss) // args.n)]:
                r = note_phases(snd)
                if r is None:
                    continue
                psi, amp = r
                stab.append(np.median(circ_std(psi)[1:12]))
                mean = np.angle(np.mean(np.exp(1j * psi), axis=0))
                K = len(mean)
                hs = range(2, min(14, K - 1))
                e_lin = np.array([np.angle(np.exp(1j * (mean[h] - 2 * mean[h - 1] + mean[h - 2]))) for h in hs])
                e_gap = np.array([np.angle(np.exp(1j * (mean[h] - np.angle(np.exp(1j * mean[h - 1]) + np.exp(1j * mean[h + 1]))))) for h in hs])
                lin.append(np.mean(np.abs(e_lin) < 0.5))
                gap2.append(np.mean(np.abs(e_gap) < 0.5))
                gappi.append(np.mean((np.abs(e_gap) < 0.5) | (np.abs(np.abs(e_gap) - np.pi) < 0.5)))
            if stab:
                print(f"  {inst:7s} {tech:16s} notes {len(stab):3d}  stability {np.median(stab):4.2f} rad   predict lin {np.median(lin):4.2f}   gap {np.median(gap2):4.2f} | {np.median(gappi):4.2f}")


def run_phase_repro(args):
    """Is psi_h reproducible between recordings of the same string and pitch (different dynamics / variants)?
    If so a per-string phase table could be learned; if not, phase cannot be predicted at all."""
    print("circular difference of time-mean psi_h between two recordings of the same instrument, string and pitch (bowed)")
    print("  median |difference| over partials 2..12 and pairs (rad; random = 1.57); share of partials within 0.5 rad (random 0.16)")
    for inst in args.instruments.split(","):
        by = defaultdict(list)
        for snd in notes(inst, BOWED):
            r = note_phases(snd)
            if r is not None:
                by[(snd.string, snd.midi)].append((snd.dynamic, np.angle(np.mean(np.exp(1j * r[0]), axis=0))))
        diffs = []
        for key, lst in by.items():
            for i in range(len(lst)):
                for j in range(i + 1, len(lst)):
                    K = min(len(lst[i][1]), len(lst[j][1]))
                    if K >= 12:
                        diffs.append(np.abs(np.angle(np.exp(1j * (lst[i][1][1:12] - lst[j][1][1:12])))))
        if diffs:
            d = np.array(diffs)
            print(f"  {inst:7s} pairs {len(d):3d}  median |diff| {np.median(d):4.2f} rad   within 0.5 rad {np.mean(d < 0.5):4.2f}")


def run_sepB(args):
    """How much does the partial-position model (B) matter to the separator? Nominal pitches and spans (so detection
    is not in the way), Orchidea scenes of one technique, separator B swept."""
    from argparse import Namespace
    from didddle.config import SeparatorConfig
    from didddle.f0 import truth_tracks, truth_spans
    from didddle.metrics import score
    from didddle.separate import Separator
    from fidddle.profile import InstrumentProfile
    from fidddle.synth import Note
    from tools.eval_orchidea import build_scenes, SR
    for inst in args.instruments.split(","):
        prof = InstrumentProfile.by_name(inst)
        for tech in (BOWED, PLUCK.get(inst, PLUCK_DEFAULT)) if inst != "guitar" else (BOWED,):
            a = Namespace(instrument=inst, kind="chords,intervals,lines", n=args.scenes, voices=3, hits=2, techniques=tech, dynamics=None, seed=1)
            scenes = build_scenes(a)
            bvals = [("0", 0.0), ("profile", prof.inharmonicity_B), ("x4 profile", 4 * prof.inharmonicity_B), ("1e-4", 1e-4), ("3e-4", 3e-4)]
            res = {}
            for label, b in bvals:
                gains = []
                for sc in scenes:
                    cfg = SeparatorConfig.from_profile(prof, float(SR), inharmonicity_B=b)
                    sep = Separator(cfg)
                    mix, stems = sc["mix"], sc["stems"]
                    notes_ = [Note(n["midi"], n["onset"], n["offset"], n["kind"]) for n in sc["notes"]]
                    voices, _ = sep.process(mix, truth_tracks(notes_, SR, len(mix), sep.centers(len(mix))), truth_spans(notes_, SR))
                    gains += list(score(voices, stems, mix)[1])
                res[label] = (np.mean(gains), np.median(gains), len(gains))
            print(f"{inst:7s} {tech:16s} (profile B {prof.inharmonicity_B:.0e}, {len(scenes)} scenes)  gain mean/median dB: "
                  + "  ".join(f"B={l}: {m:5.1f}/{md:5.1f}" for l, (m, md, _) in res.items()))


def note_amplitudes(snd, hmax=30):
    """(h, freq, log amplitude) of the partials of a note, averaged over its steady frames (amplitude per unit of window)."""
    x, sr = P.load(snd.path)
    f = f_of(snd.midi)
    n = P.window_for(sr, f)
    t0, t1 = steady_window(snd, len(x) / sr)
    acc = defaultdict(list)
    for st in P.frame_starts(len(x), n, sr, t0, t1, 0.5):
        r = P.stiffness(P.spectrum(x, st, n), sr / n, f)
        if r:
            for h, fr, a in zip(r["h"], r["freq"], r["amp"]):
                if h <= hmax:
                    acc[int(h)].append((fr, np.log(a / n) * 20 / np.log(10)))     # dB per window length
    hs = sorted(h for h, v in acc.items() if len(v) >= max(2, 0.5 * len(acc.get(1, [0]))))
    if len(hs) < 8:
        return None
    return (np.array(hs), np.array([np.mean([a for a, _ in acc[h]]) for h in hs]), np.array([np.mean([b for _, b in acc[h]]) for h in hs]))


KNOTS = np.log(np.geomspace(60.0, 6500.0, 24))


def hat(logf):
    """Piecewise-linear basis on the knots (len(logf) x len(KNOTS))."""
    B = np.zeros((len(logf), len(KNOTS)))
    lf = np.clip(logf, KNOTS[0], KNOTS[-1])
    j = np.clip(np.searchsorted(KNOTS, lf) - 1, 0, len(KNOTS) - 2)
    t = (lf - KNOTS[j]) / (KNOTS[j + 1] - KNOTS[j])
    B[np.arange(len(lf)), j] = 1 - t
    B[np.arange(len(lf)), j + 1] = t
    return B


def fit_body(train, smooth=3.0):
    """R(f) (dB, at KNOTS) from open-string notes with a free offset and tilt per note. train: [(h, f, a)]."""
    K, N = len(KNOTS), len(train)
    rows, rhs = [], []
    for i, (h, f, a) in enumerate(train):
        M = np.zeros((len(h), K + 2 * N))
        M[:, :K] = hat(np.log(f))
        M[:, K + 2 * i] = 1.0
        M[:, K + 2 * i + 1] = np.log(h)
        rows.append(M); rhs.append(a)
    D = np.zeros((K - 2, K + 2 * N))
    for k in range(K - 2):
        D[k, k], D[k, k + 1], D[k, k + 2] = smooth, -2 * smooth, smooth
    g = np.zeros((2, K + 2 * N)); g[0, K::2] = 10.0; g[1, K + 1::2] = 10.0     # gauge: mean offset and tilt zero
    A = np.vstack(rows + [D, g]); b = np.concatenate(rhs + [np.zeros(K - 2 + 2)])
    sol, *_ = np.linalg.lstsq(A, b, rcond=None)
    return sol[:K]


def residual(la, basis_pred, h, tilt):
    """rms of (la - pred) after fitting a per-note offset (and tilt) by least squares."""
    y = la - basis_pred
    A = np.stack([np.ones(len(h))] + ([np.log(h)] if tilt else []), axis=1)
    c, *_ = np.linalg.lstsq(A, y, rcond=None)
    return float(np.sqrt(np.mean((y - A @ c) ** 2)))


def run_body(args):
    print("Predicting the partial levels (dB) of STOPPED notes from the OPEN strings of the same instrument and dynamic.")
    print("  rms error over partials after fitting each note's offset (and tilt). 'string profile' = what calibration stores (by partial number,")
    print("  per string); 'body' = smooth response of absolute frequency shared by all strings (spec 17.2). Median over notes.")
    print(f"  {'':24s}{'notes':>6s}{'tilt only':>11s}{'profile':>9s}{'profile+tilt':>14s}{'body':>7s}{'body+tilt':>11s}{'body(3 strings)':>17s}")
    for inst in args.instruments.split(","):
        for tech in (BOWED, PLUCK.get(inst, PLUCK_DEFAULT)):
            if inst == "guitar" and tech == BOWED and False:
                continue
            opens = OPEN[inst]
            data = []
            for snd in notes(inst, tech):
                r = note_amplitudes(snd)
                if r:
                    data.append((snd, r))
            out = defaultdict(list)
            for dyn in ("mf", "ff", "pp"):
                train = [(s, r) for s, r in data if s.dynamic == dyn and s.midi == opens[s.string - 1]]
                if len(train) < 4:
                    continue
                R = fit_body([r for _, r in train])
                # 3-string body: leave out the string with most open notes
                strings = sorted({s.string for s, _ in train})
                drop = max(strings, key=lambda st: sum(s.string == st for s, _ in train))
                R3 = fit_body([r for s, r in train if s.string != drop]) if len(strings) > 3 else R
                prof = {}
                for st in strings:
                    ms = [r for s, r in train if s.string == st]
                    L = min(len(r[0]) for r in ms)
                    hs0 = ms[0][0][:L]
                    if all(np.array_equal(r[0][:L], hs0) for r in ms):
                        P_ = np.mean([r[2][:L] for r in ms], axis=0)
                        prof[st] = (hs0, P_)
                for s, (h, f, a) in [(s, r) for s, r in data if s.dynamic == dyn and s.midi != opens[s.string - 1]]:
                    out["tilt"].append(residual(a, 0 * a, h, True))
                    out["body"].append(residual(a, hat(np.log(f)) @ R, h, False))
                    out["bodyt"].append(residual(a, hat(np.log(f)) @ R, h, True))
                    out["body3"].append(residual(a, hat(np.log(f)) @ R3, h, True))
                    if s.string in prof:
                        hp, Pp = prof[s.string]
                        k = np.isin(h, hp)
                        if k.sum() >= 8:
                            pred = np.array([Pp[list(hp).index(hh)] for hh in h[k]])
                            out["prof"].append(residual(a[k], pred, h[k], False))
                            out["proft"].append(residual(a[k], pred, h[k], True))
            if out["tilt"]:
                med = lambda k: np.median(out[k]) if out[k] else float("nan")
                print(f"  {inst + ' ' + tech:24s}{len(out['tilt']):6d}{med('tilt'):11.2f}{med('prof'):9.2f}{med('proft'):14.2f}{med('body'):7.2f}{med('bodyt'):11.2f}{med('body3'):17.2f}")


def run_collide(args):
    """Leave-one-out prediction of a hidden partial's level (dB) -- the quantity the separator needs when another voice's
    partial sits on it. (a) interpolation from the neighbouring partials (what didddle does), (b) the body response of
    absolute frequency learned from OTHER strings' open notes, with offset and tilt fitted on the note's remaining
    partials, (c) both: body prediction plus the interpolated residual."""
    print("rms error (dB) of the predicted level of one hidden partial, partials 2..16 (median over notes); hidden partial h, neighbours h-1 and h+1")
    print(f"  {'':24s}{'notes':>6s}{'interp':>8s}{'body':>7s}{'body+interp':>13s}{'quad fit':>10s}")
    for inst in args.instruments.split(","):
        for tech in (BOWED, PLUCK.get(inst, PLUCK_DEFAULT)):
            opens = OPEN[inst]
            data = [(s, r) for s in notes(inst, tech) for r in [note_amplitudes(s)] if r]
            tr = [r for s, r in data if s.midi == opens[s.string - 1]]
            if len(tr) < 4:
                continue
            R = fit_body(tr)
            E = defaultdict(list)
            for s, (h, f, a) in data:
                if s.midi == opens[s.string - 1]:
                    continue
                pred = hat(np.log(f)) @ R
                ei, eb, ebi, eq = [], [], [], []
                for i in range(len(h)):
                    if not (2 <= h[i] <= 16) or i == 0 or i == len(h) - 1 or h[i - 1] != h[i] - 1 or h[i + 1] != h[i] + 1:
                        continue
                    keep = np.arange(len(h)) != i
                    interp = 0.5 * (a[i - 1] + a[i + 1])
                    ei.append(a[i] - interp)
                    A = np.stack([np.ones(keep.sum()), np.log(h[keep])], axis=1)
                    c, *_ = np.linalg.lstsq(A, a[keep] - pred[keep], rcond=None)
                    b_ = pred[i] + c[0] + c[1] * np.log(h[i])
                    eb.append(a[i] - b_)
                    ebi.append(a[i] - (b_ + 0.5 * ((a[i - 1] - (pred[i - 1] + c[0] + c[1] * np.log(h[i - 1]))) + (a[i + 1] - (pred[i + 1] + c[0] + c[1] * np.log(h[i + 1]))))))
                    A2 = np.stack([np.ones(keep.sum()), np.log(h[keep]), np.log(h[keep]) ** 2], axis=1)
                    c2, *_ = np.linalg.lstsq(A2, a[keep], rcond=None)
                    eq.append(a[i] - (c2[0] + c2[1] * np.log(h[i]) + c2[2] * np.log(h[i]) ** 2))
                if len(ei) >= 4:
                    rms = lambda e: float(np.sqrt(np.mean(np.square(e))))
                    E["i"].append(rms(ei)); E["b"].append(rms(eb)); E["bi"].append(rms(ebi)); E["q"].append(rms(eq))
            if E["i"]:
                print(f"  {inst + ' ' + tech:24s}{len(E['i']):6d}{np.median(E['i']):8.2f}{np.median(E['b']):7.2f}{np.median(E['bi']):13.2f}{np.median(E['q']):10.2f}")


def run_string(args):
    """Guitar: which string played a note whose pitch exists on several strings? Feature: B / f^2 (a per-string constant
    if B follows the f^2 law), nearest centroid in log, trained on OTHER pitches (leave-one-pitch-out)."""
    inst = "guitar"
    feats = []
    for snd in notes(inst, PLUCK[inst]):
        rows = measure_note(snd)
        if len(rows) >= 2:
            b = np.median([r["B"] for r in rows])
            if b > 1e-6:
                feats.append((snd.string, snd.midi, np.log(b / f_of(snd.midi) ** 2)))
    feats = np.array(feats)
    ok = tot = 0
    base = 0
    rng_cols = {}
    for st, m, v in feats:
        others = feats[feats[:, 1] != m]
        cent = {int(s): np.median(others[others[:, 0] == s][:, 2]) for s in set(others[:, 0]) if (others[:, 0] == s).sum() >= 3}
        playable = [int(s) for s in cent if 0 <= m - OPEN[inst][int(s) - 1] <= 24]
        if int(st) in cent and len(playable) >= 2:
            pred = min(playable, key=lambda s: abs(v - cent[s]))
            ok += pred == int(st); tot += 1; base += 1.0 / len(playable)
    print(f"guitar notes whose pitch is playable on 2+ strings (within 24 semitones of the open string): {tot}")
    print(f"  string identified from B/f^2 alone: {ok}/{tot} = {ok / max(tot, 1):.2f}   (chance for the same notes: {base / max(tot, 1):.2f})")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", choices=["inharm", "bstring", "phase", "phase-repro", "sepB", "body", "collide", "string"])
    ap.add_argument("--instruments", default="violin,viola,cello,bass,guitar")
    ap.add_argument("--n", type=int, default=60, help="notes per (instrument, technique)")
    ap.add_argument("--scenes", type=int, default=3, help="scenes per kind (sepB)")
    args = ap.parse_args()
    {"inharm": run_inharm, "bstring": run_bstring, "phase": run_phase, "phase-repro": run_phase_repro, "sepB": run_sepB, "body": run_body, "collide": run_collide, "string": run_string}[args.mode](args)


if __name__ == "__main__":
    main()
