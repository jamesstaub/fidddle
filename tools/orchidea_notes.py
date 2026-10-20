"""Single-note measurements on OrchideaSOL one-shots (real dry recordings, nominal pitch from the file name).

  b       fit stiffness B per file from partial positions, f_h^2 / h^2 = f0^2 (1 + B h^2); summarize by instrument, technique,
          string and pitch (bowed against plucked lock-in, the B ~ f^2 law along a string, the profile B guesses)
  nominal how far the measured f0 sits from the file-name pitch (cents), by instrument and technique

Usage: .venv/bin/python tools/orchidea_notes.py b --instrument guitar [--techniques ordinario] [--dynamics mf] [--json out.json]
"""
import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path
import numpy as np
import soundfile as sf

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from tools.orchidea import catalog

NMAX = 24


def hz(midi):
    return 440.0 * 2 ** ((midi - 69) / 12)


def load(s, seg_s=(0.15, 1.3), max_s=None):
    x, sr = sf.read(s.path)
    x = x if x.ndim == 1 else x[:, 0]
    a, b = int(seg_s[0] * sr), int(min(seg_s[1], len(x) / sr) * sr)
    return x[a:b], sr


def measure(s, seg_s=None):
    """-> dict(f0, B, n, cents_off, resid_cents) or None. Peaks are tracked outward from the nominal pitch, each refit."""
    seg_s = seg_s or ((0.15, 1.3) if s.kind == "plucked" else (0.5, 1.8))
    x, sr = load(s, seg_s)
    if len(x) < sr * 0.3:
        return None
    n = 1 << int(np.ceil(np.log2(max(len(x), sr * 0.4))))
    n = min(n, 1 << 17)
    x = x[:n]
    X = np.abs(np.fft.rfft(np.pad(x * np.hanning(len(x)), (0, n - len(x)))))
    fr = np.fft.rfftfreq(n, 1 / sr)

    def peak_near(f, tol_cents):
        lo, hi = f * 2 ** (-tol_cents / 1200), f * 2 ** (tol_cents / 1200)
        k0, k1 = np.searchsorted(fr, lo), np.searchsorted(fr, hi) + 1
        if k1 - k0 < 3:
            return None
        k = k0 + int(np.argmax(X[k0:k1]))
        if k <= 0 or k >= len(X) - 1:
            return None
        a, b, c = np.log(X[k - 1] + 1e-12), np.log(X[k] + 1e-12), np.log(X[k + 1] + 1e-12)
        d = 0.5 * (a - c) / (a - 2 * b + c) if (a - 2 * b + c) != 0 else 0.0
        floor = np.median(X[max(0, k - 200):k + 200])
        if X[k] < 8 * floor:
            return None
        return (k + d) * (fr[1] - fr[0]), float(X[k])

    f_nom = hz(s.midi)
    f0, B = f_nom, 0.0
    hs, fs, amps = [], [], []
    # first pass: fundamental region, then grow the partial list, refitting (f0, B) each time
    for h in range(1, NMAX + 1):
        pred = f0 * h * np.sqrt(1 + B * h * h)
        if pred > 0.45 * sr:
            break
        tol = 60 if h == 1 else max(25, 80 / h)
        pk = peak_near(pred, tol)
        if pk is None:
            continue
        f, amp = pk
        hs.append(h)
        fs.append(f)
        amps.append(amp)
        if len(hs) >= 3:
            hh, ff = np.array(hs, float), np.array(fs)
            A = np.vstack([np.ones_like(hh), hh ** 2]).T
            y = (ff / hh) ** 2
            (c0, c1), *_ = np.linalg.lstsq(A, y, rcond=None)
            if c0 > 0:
                f0, B = np.sqrt(c0), max(c1 / c0, 0.0)
    if len(hs) < 5:
        return None
    hh, ff = np.array(hs, float), np.array(fs)
    pred = f0 * hh * np.sqrt(1 + B * hh * hh)
    resid = 1200 * np.log2(ff / pred)
    return {"f0": float(f0), "B": float(B), "n": len(hs), "cents_off": float(1200 * np.log2(f0 / f_nom)),
            "resid": float(np.sqrt(np.mean(resid ** 2))), "h": [int(v) for v in hs], "fh": [float(v) for v in fs],
            "db": [float(20 * np.log10(a + 1e-12)) for a in amps]}


def cmd_b(a):
    sel = catalog.select(a.instrument, a.techniques.split(",") if a.techniques else None, a.dynamics.split(",") if a.dynamics else None)
    rows = []
    for s in sel:
        m = measure(s)
        if m:
            rows.append({**s.meta(), **m})
    print(f"{a.instrument}: {len(rows)} of {len(sel)} files measured")
    by = defaultdict(list)
    for r in rows:
        by[(r["technique"], r["string"])].append(r)
    print(f"\n{'technique':26s} str  n   median B     B range (10-90%)       slope of log B vs log f (f^2 law => 2)   median |cents off|")
    for (t, st), rs in sorted(by.items()):
        Bs = np.array([r["B"] for r in rs])
        f = np.array([r["f0"] for r in rs])
        ok = Bs > 1e-7
        slope = np.polyfit(np.log(f[ok]), np.log(Bs[ok]), 1)[0] if ok.sum() >= 6 and np.ptp(np.log(f[ok])) > 0.3 else float("nan")
        print(f"{t:26s} {st:3d} {len(rs):3d}  {np.median(Bs):9.2e}  {np.percentile(Bs, 10):8.1e}-{np.percentile(Bs, 90):8.1e}   {slope:6.2f}   {np.median(np.abs([r['cents_off'] for r in rs])):6.1f}")
    if a.json:
        Path(a.json).write_text(json.dumps(rows))


def cmd_body(a):
    """Is the level of a partial a function of its partial number (per string) or of its absolute frequency (pooled)?
    Leave-one-note-out prediction error of each model on the dB levels (each note's level removed first)."""
    sel = catalog.select(a.instrument, a.techniques.split(",") if a.techniques else None, a.dynamics.split(",") if a.dynamics else None)
    notes = []
    for s in sel:
        m = measure(s)
        if m and len(m["h"]) >= 8:
            db = np.array(m["db"])
            notes.append({"string": s.string, "midi": s.midi, "h": np.array(m["h"]), "f": np.array(m["fh"]), "db": db - np.median(db)})
    print(f"{a.instrument}: {len(notes)} notes")
    edges = np.geomspace(60, 12000, 25)

    def fit_predict(train, test, key):
        tab = defaultdict(list)
        for n in train:
            for h, f, d in zip(n["h"], n["f"], n["db"]):
                tab[key(n, h, f)].append(d)
        mean = {k: np.mean(v) for k, v in tab.items() if len(v) >= 2}
        err = []
        for h, f, d in zip(test["h"], test["f"], test["db"]):
            k = key(test, h, f)
            if k in mean:
                err.append(d - mean[k])
        return err

    keys = {"partial number only (all strings)": lambda n, h, f: min(h, 16),
            "partial number per string": lambda n, h, f: (n["string"], min(h, 16)),
            "absolute frequency (all strings)": lambda n, h, f: int(np.searchsorted(edges, f)),
            "absolute frequency per string": lambda n, h, f: (n["string"], int(np.searchsorted(edges, f)))}
    base = np.concatenate([n["db"] for n in notes])
    print(f"{'model':36s} RMS error dB   (no model: {np.sqrt(np.mean(base ** 2)):.1f})")
    for name, key in keys.items():
        e = []
        for i, n in enumerate(notes):
            e += fit_predict(notes[:i] + notes[i + 1:], n, key)
        print(f"{name:36s} {np.sqrt(np.mean(np.square(e))):6.2f}   (n={len(e)})")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=["b", "body"])
    ap.add_argument("--instrument", default="cello")
    ap.add_argument("--techniques", default=None)
    ap.add_argument("--dynamics", default=None)
    ap.add_argument("--json", default=None)
    a = ap.parse_args()
    {"b": cmd_b, "body": cmd_body}[a.cmd](a)


if __name__ == "__main__":
    main()
