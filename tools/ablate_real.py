"""Which part of the calibration matters on the real DI recordings, and does a partial calibration transfer?

Variants (guitar open-string pass, known truth: 6 plucks; scored as hits and extra notes):
  none            profile defaults
  B+tuning        per-string inharmonicity and tuning only
  +avg weights    ... and the harmonic profile averaged over strings
  +string weights ... and a profile per string (the full calibration)
and the same with the attack requirement off. Every calibration here is learned on the same pass (an optimistic upper bound).

Transfer: calibrate on a subset of the strings (the other plucks are blanked out of the calibration audio), then score all six
plucks of the full pass: the strings that were not calibrated show how far a partial calibration generalises.

Usage: .venv/bin/python tools/ablate_real.py [--instrument guitar|bass]
"""
import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path
import numpy as np
import soundfile as sf

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from tools.notes_report import run, pair
from tools.eval_real import FILES, score_open, DATA

CLI = ROOT / "core" / "build" / "fidddle_cli"


def calibrate(wav, profile, extra=()):
    out = subprocess.run([str(CLI), str(wav), "--profile", profile, "--calibrate", *extra], capture_output=True, text=True, check=True).stdout.splitlines()
    for l in out:
        j = json.loads(l)
        if "calibration" in j:
            return j["calibration"]
    return None


def variant(cal, level):
    """level: 'bt' (B+tuning), 'avg' (+average weights), 'full'. List layout: [2, n, (cap,B,cents)*n, nw, w..., (nsw, sw...)*n]."""
    v = list(cal)
    n = int(v[1])
    pos = 2 + 3 * n
    nw = int(v[pos])
    head = v[:pos]
    avg = v[pos + 1: pos + 1 + nw]
    rest = v[pos + 1 + nw:]
    if level == "bt":
        tail = [0.0] + [0.0] * n                      # no average weights, no per-string weights
        return head + tail
    if level == "avg":
        return head + [float(nw)] + avg + [0.0] * n
    if level == "sw":                                  # per-string profiles only: a string without one falls back to the default
        return head + [0.0] + rest
    return v


def csv(v):
    return ",".join(repr(float(x)) for x in v)


def score(wav, profile, extra, cal, plucks, attack):
    ex = list(extra) + (["--set", "attack_min_db=0"] if not attack else [])
    events, summ = run(wav, profile, ex, cal)
    notes = pair(events, summ["sr"])
    hits, extras = score_open(notes, plucks)
    return hits, len(extras), len(plucks)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--instrument", default="guitar", choices=("guitar", "bass"))
    ap.add_argument("--drop-average", action="store_true", help="in the transfer test, remove the averaged profile (uncalibrated strings fall back to the default weights)")
    a = ap.parse_args()
    stem = "guitar-open-strings" if a.instrument == "guitar" else "5string-bass-open-strings"
    prof, extra, plucks = FILES[stem]
    wav = DATA / f"{stem}.wav"
    cal = calibrate(wav, prof, extra)
    print(f"{stem}: calibration list of {len(cal)} numbers")
    print(f"\n{'variant':18s} {'attack on: hit/extras':>22s} {'attack off: hit/extras':>24s}")
    for name, c in (("none", None), ("B+tuning", csv(variant(cal, 'bt'))), ("+avg weights", csv(variant(cal, 'avg'))), ("+string weights", csv(cal)), ("string wts only", csv(variant(cal, 'sw')))):
        on = score(wav, prof, extra, c, plucks, True)
        off = score(wav, prof, extra, c, plucks, False)
        print(f"{name:18s} {on[0]:>12d}/{on[2]} {on[1]:>4d}      {off[0]:>12d}/{off[2]} {off[1]:>4d}")

    # transfer: calibrate on a subset of strings
    x, sr = sf.read(wav, always_2d=True)
    m = x[:, 0]
    bounds = [t for t, _ in plucks] + [len(m) / sr]
    print(f"\ntransfer (full pass scored; calibration learned from the listed strings only)")
    print(f"{'calibrated strings':24s} {'hits':>6s} {'extras':>7s}   extras on [calibrated | other] strings")
    n = len(plucks)
    for subset in ([0, 1, 2, 3, 4, 5][:n], [0, 2, 4][: (n + 1) // 2], [1, 3, 5][: n // 2], [0, 1, 2][: max(1, n // 2)], [3, 4, 5][-max(1, n // 2):] if n >= 6 else [n - 1]):
        y = np.zeros_like(m)
        for i in subset:
            i0 = int(max(0, bounds[i] - 0.2) * sr); i1 = int(bounds[i + 1] * sr) - int(0.3 * sr) if i + 1 < n else len(m)
            y[i0:i1] = m[i0:i1]
        with tempfile.TemporaryDirectory() as td:
            w2 = Path(td) / "sub.wav"
            sf.write(w2, y, sr)
            c = calibrate(w2, prof, extra)
        if c is not None and a.drop_average:
            c = variant(c, "sw")
        if c is None:
            print(f"{str(subset):24s}  (nothing captured)")
            continue
        events, summ = run(wav, prof, list(extra), csv(c))
        notes = pair(events, summ["sr"])
        hits, extras = score_open(notes, plucks)
        def which(ex):   # which pluck window an extra falls into
            t = ex["t0"]
            k = max(i for i in range(n) if plucks[i][0] - 0.1 <= t) if t >= plucks[0][0] - 0.1 else 0
            return k
        in_c = sum(1 for ex in extras if which(ex) in subset)
        print(f"{str(subset):24s} {hits:>4d}/{n} {len(extras):>7d}   {in_c} | {len(extras) - in_c}")


if __name__ == "__main__":
    main()
