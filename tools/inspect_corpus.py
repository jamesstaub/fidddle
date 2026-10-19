"""Per-channel level, noise-floor and spectral summary of the cello-gestures corpus.

Usage: .venv/bin/python tools/inspect_corpus.py
"""
import sys
from pathlib import Path

import numpy as np
import soundfile as sf

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from fidddle.corpus import top_level_wavs


def db(x):
    return 20 * np.log10(max(float(x), 1e-12))


def summarize(x, sr):
    # 50 ms frame RMS; noise floor = 10th percentile of frame RMS.
    n = int(0.05 * sr)
    m = len(x) // n
    rms = np.sqrt(np.mean(x[: m * n].reshape(m, n) ** 2, axis=1))
    peak = np.max(np.abs(x))
    floor = np.percentile(rms, 10)
    top = np.percentile(rms, 95)
    # spectral centroid of the whole file
    spec = np.abs(np.fft.rfft(x[: (len(x) // 2) * 2]))
    f = np.fft.rfftfreq((len(x) // 2) * 2, 1 / sr)
    cent = float((f * spec).sum() / max(spec.sum(), 1e-12))
    # energy below 60 Hz (handling/rumble) as fraction
    low = float(((spec[f < 60]) ** 2).sum() / max((spec**2).sum(), 1e-12))
    return peak, db(top), db(floor), cent, low


def main():
    print(f"{'file':32s} {'sr':>6s} {'dur':>5s} ch  {'peak':>6s} {'p95dB':>6s} {'floordB':>7s} {'dyn':>5s} {'centHz':>7s} {'<60Hz%':>6s}")
    for p in top_level_wavs():
        x, sr = sf.read(p, always_2d=True)
        for c in range(x.shape[1]):
            peak, top, floor, cent, low = summarize(x[:, c], sr)
            name = p.name if c == 0 else ""
            print(f"{name:32.32s} {sr:6d} {len(x)/sr:5.1f} {c:2d}  {peak:6.3f} {top:6.1f} {floor:7.1f} {top-floor:5.1f} {cent:7.0f} {100*low:6.2f}")


if __name__ == "__main__":
    main()
