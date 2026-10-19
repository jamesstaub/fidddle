"""Spectrogram of a WAV with the detector's notes overlaid, for judging real recordings by eye.

Usage: .venv/bin/python tools/plot_notes.py file.wav --profile bass --t0 0 --t1 15 --out out.png [--minfreq F] [--calibration "<list>"]
"""
import argparse
import sys
from pathlib import Path
import numpy as np
import soundfile as sf
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from tools.notes_report import run, pair, name


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("wav"); ap.add_argument("--profile", required=True)
    ap.add_argument("--t0", type=float, default=0.0); ap.add_argument("--t1", type=float, default=15.0)
    ap.add_argument("--fmin", type=float, default=30.0); ap.add_argument("--fmax", type=float, default=1500.0)
    ap.add_argument("--out", required=True)
    ap.add_argument("--calibration", default=None)
    ap.add_argument("--minfreq"); ap.add_argument("--maxfreq"); ap.add_argument("--voices")
    ap.add_argument("--set", action="append", default=[])
    a = ap.parse_args()
    x, sr = sf.read(a.wav, always_2d=True)
    x = x[:, 0]
    extra = []
    for k in ("minfreq", "maxfreq", "voices"):
        if getattr(a, k):
            extra += [f"--{k}", getattr(a, k)]
    for kv in a.set:
        extra += ["--set", kv]
    events, summ = run(a.wav, a.profile, extra, a.calibration)
    notes = pair(events, summ["sr"])
    i0, i1 = int(a.t0 * sr), int(a.t1 * sr)
    seg = x[i0:i1]
    n, hop = 16384, 1024
    win = np.hanning(n)
    frames = (len(seg) - n) // hop
    S = np.array([np.abs(np.fft.rfft(seg[i * hop:i * hop + n] * win)) for i in range(frames)]).T
    fr = np.fft.rfftfreq(n, 1 / sr)
    sel = (fr >= a.fmin) & (fr <= a.fmax)
    t = a.t0 + (np.arange(frames) * hop + n / 2) / sr
    fig, ax = plt.subplots(figsize=(18, 7))
    ax.pcolormesh(t, fr[sel], 20 * np.log10(S[sel] + 1e-9), shading="auto", cmap="magma", vmin=-20, vmax=60)
    ax.set_yscale("log"); ax.set_ylim(a.fmin, a.fmax)
    for nt in notes:
        if nt["t1"] < a.t0 or nt["t0"] > a.t1:
            continue
        f = 440.0 * 2 ** ((nt["midi"] - 69) / 12)
        ax.hlines(f, max(nt["t0"], a.t0), min(nt["t1"], a.t1), colors="cyan", lw=2)
        ax.text(max(nt["t0"], a.t0), f * 1.04, name(nt["midi"]), color="white", fontsize=8)
    ax.set_xlabel("s"); ax.set_ylabel("Hz")
    fig.tight_layout(); fig.savefig(a.out, dpi=90)


if __name__ == "__main__":
    main()
