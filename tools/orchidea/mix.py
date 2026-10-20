"""Turn one-shots into polyphonic scenes with exact truth: events -> mixture + per-note stems + note list.

An Event places one Sound at an onset. Bowed sounds are cut to `length` with a short fade (a bow release); plucked ones
keep their natural decay, capped at MAX_PLUCK_S. Levels are the library's own (its dynamics are level-calibrated);
the whole scene gets one shared gain only if it would clip, so stem/mix relationships stay exact.
"""
from dataclasses import dataclass
import numpy as np
import soundfile as sf
from scipy.signal import resample_poly
from math import gcd

FADE_S = 0.06
MAX_PLUCK_S = 2.5
FLOOR_DB = -40.0


@dataclass
class Event:
    sound: object
    onset: float
    length: float = None        # seconds of note (bowed); None = natural decay
    gain_db: float = 0.0


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


def render(events, sr, duration):
    """-> mix (n,), stems (E, n), notes [dict] (onset/offset = note-on/note-off in s, end = when the sound stops)."""
    n = int(duration * sr)
    stems = np.zeros((len(events), n))
    notes = []
    for i, ev in enumerate(events):
        x = load(ev.sound, sr)
        a, b = extent(x, sr)
        x = x[a:b]
        natural = min(len(x), int(MAX_PLUCK_S * sr)) if ev.sound.kind == "plucked" else len(x)
        cut = natural if ev.length is None else min(natural, int(ev.length * sr))
        seg = x[:cut].copy()
        if cut < len(x):                                      # truncated: release, not a click
            f = min(int(FADE_S * sr), cut // 2)
            seg[cut - f:] *= 0.5 * (1 + np.cos(np.pi * np.arange(f) / f))
        seg *= 10 ** (ev.gain_db / 20)
        s0 = int(ev.onset * sr)
        s1 = min(n, s0 + len(seg))
        stems[i, s0:s1] = seg[: s1 - s0]
        notes.append({"onset": ev.onset, "offset": ev.onset + cut / sr - (FADE_S if cut < len(x) else 0.0),
                      "end": s1 / sr, "midi": ev.sound.midi, "src": f"n{i}", **ev.sound.meta()})
    mix = stems.sum(0)
    peak = np.abs(mix).max()
    gain = 0.95 / peak if peak > 0.95 else 1.0
    return mix * gain, stems * gain, notes, gain


# ---- scenes -------------------------------------------------------------------------------------------

INTERVALS = (3, 4, 5, 6, 7, 9, 12)


def pick(rng, pool, techniques=None, dynamics=None, midi=None):
    """Random Sound: technique first (so rare techniques are not drowned out), then dynamic, then pitch (nearest to `midi`
    if given, else random)."""
    techs = sorted({s.technique for s in pool if not techniques or s.technique in techniques})
    t = techs[rng.integers(len(techs))]
    ts = [s for s in pool if s.technique == t]
    dyns = sorted({s.dynamic for s in ts if not dynamics or s.dynamic in dynamics}) or sorted({s.dynamic for s in ts})
    d = dyns[rng.integers(len(dyns))]
    cand = [s for s in ts if s.dynamic == d]
    if midi is None:
        return cand[rng.integers(len(cand))]
    best = min(abs(s.midi - midi) for s in cand)
    near = [s for s in cand if abs(s.midi - midi) == best]
    return near[rng.integers(len(near))]


def _length(rng, sound):
    return None if sound.kind == "plucked" else float(rng.uniform(1.0, 2.2))


def scene(kind, pool, rng, voices=3, hits=3, duration=None, techniques=None, dynamics=None):
    """-> (events, duration_s). kinds:
    chords     `voices` different pitches struck together, `hits` times
    intervals  two notes at a fixed interval (3,4,5,6,7,9,12 semitones), `hits` times
    strum      `voices` pitches rolled 30-60 ms apart, `hits` times
    lines      `voices` independent melodic lines of consecutive notes over `duration` seconds (default 8)
    """
    lo, hi = min(s.midi for s in pool), max(s.midi for s in pool)
    ev = []
    if kind in ("chords", "intervals", "strum"):
        gap = 3.0
        for h in range(hits):
            t0 = 0.3 + h * gap
            if kind == "intervals":
                a = pick(rng, pool, techniques, dynamics)
                semi = int(INTERVALS[rng.integers(len(INTERVALS))])
                pitches = [a.midi, a.midi + semi]
                snds = [a, pick(rng, pool, techniques, dynamics, a.midi + semi)]
            else:
                midis = sorted(int(m) for m in rng.choice(np.arange(lo, hi + 1), size=voices, replace=False))
                snds = [pick(rng, pool, techniques, dynamics, m) for m in midis]
            for j, s in enumerate(snds):
                off = j * float(rng.uniform(0.03, 0.06)) if kind == "strum" else 0.0
                ev.append(Event(s, t0 + off, _length(rng, s)))
        return ev, 0.3 + hits * gap + 0.5
    if kind == "lines":
        dur = duration or 8.0
        for _ in range(voices):
            t = float(rng.uniform(0.2, 1.0))
            m = int(rng.integers(lo + 3, hi - 3))
            while t < dur - 1.0:
                s = pick(rng, pool, techniques, dynamics, m)
                ev.append(Event(s, t, _length(rng, s)))
                t += (ev[-1].length or float(rng.uniform(0.5, 1.2))) + float(rng.uniform(0.0, 0.4))
                m = int(np.clip(m + rng.integers(-7, 8), lo, hi))
        return ev, dur
    raise ValueError(kind)
