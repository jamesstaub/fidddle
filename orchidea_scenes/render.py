"""Place one-shots at known times and sum them: events -> mixture, per-note stems, truth.

Bowed sounds are cut to `length` with a short fade (a bow release); plucked sounds keep their natural decay up to `pluck_max_s`.
Levels are the library's own (its dynamics are level-calibrated). If the sum would clip, one shared gain is applied to the mixture
and to all stems, so the stems always add up to the mixture exactly.
"""
from dataclasses import dataclass
from math import gcd

import numpy as np
import soundfile as sf
from scipy.signal import resample_poly

FADE_S = 0.06
MAX_PLUCK_S = 2.5
FLOOR_DB = -40.0


@dataclass
class Event:
    sound: object
    onset: float
    length: float = None        # seconds of note (bowed); None = natural decay
    gain_db: float = 0.0
    voice: int = 0


_cache = {}


def load(sound, sr):
    key = (sound.path, sr)
    if key not in _cache:
        x, fs = sf.read(sound.path)
        x = x if x.ndim == 1 else x.mean(1)
        if fs != sr:
            g = gcd(int(fs), int(sr))
            x = resample_poly(x, int(sr) // g, int(fs) // g)
        _cache[key] = x.astype(np.float64)
    return _cache[key]


def extent(x, sr):
    """(start, end) sample indices where the 5 ms envelope is within FLOOR_DB of its peak."""
    n = max(1, int(0.005 * sr))
    env = np.convolve(np.abs(x), np.ones(n) / n, mode="same")
    idx = np.flatnonzero(env >= env.max() * 10 ** (FLOOR_DB / 20))
    return int(idx[0]), int(idx[-1]) + 1


def render(events, sr, duration, pluck_max_s=MAX_PLUCK_S):
    """-> mix (n,), stems (E, n), notes [dict] (onset and offset are note-on and note-off in s, end is when the sound stops), gain."""
    n = int(duration * sr)
    stems = np.zeros((len(events), n))
    notes = []
    for i, ev in enumerate(events):
        x = load(ev.sound, sr)
        a, b = extent(x, sr)
        x = x[a:b]
        natural = min(len(x), int(pluck_max_s * sr)) if ev.sound.kind == "plucked" else len(x)
        cut = natural if ev.length is None else min(natural, int(ev.length * sr))
        seg = x[:cut].copy()
        if cut < len(x):                                      # truncated: release, not a click
            f = min(int(FADE_S * sr), cut // 2)
            seg[cut - f:] *= 0.5 * (1 + np.cos(np.pi * np.arange(f) / f))
        seg *= 10 ** (ev.gain_db / 20)
        s0 = int(ev.onset * sr)
        s1 = min(n, s0 + len(seg))
        stems[i, s0:s1] = seg[: s1 - s0]
        notes.append({"onset": ev.onset, "offset": ev.onset + cut / sr - (FADE_S if cut < len(x) else 0.0), "end": s1 / sr,
                      "midi": ev.sound.midi, "src": f"n{i}", "voice": ev.voice, "gain_db": ev.gain_db, **ev.sound.meta()})
    mix = stems.sum(0)
    peak = np.abs(mix).max()
    gain = 0.95 / peak if peak > 0.95 else 1.0
    return mix * gain, stems * gain, notes, gain
