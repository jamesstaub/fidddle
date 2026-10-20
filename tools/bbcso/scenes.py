"""Scene generators: lists of Notes with exact, known truth, shaped for what fidddle / didddle must handle.

A scene is {track_name: (instrument, [Note])}; render.py attaches player / articulation / parameters to each track.
All take a seeded numpy Generator where randomness is involved, so a scene name + seed is reproducible.
"""
import numpy as np
from .catalog import INSTRUMENTS
from .midi import Note

OPEN_STRINGS = {"violin": [55, 62, 69, 76], "viola": [48, 55, 62, 69], "cello": [36, 43, 50, 57], "bass": [28, 33, 38, 43]}
MAJOR = [0, 2, 4, 5, 7, 9, 11, 12]


def _clip(inst, midi):
    spec = INSTRUMENTS[inst]
    return int(min(spec["hi"], max(spec["lo"], midi)))


def open_strings(inst, note_s=1.5, gap_s=0.5, vel=90, t0=0.5, **_):
    notes, t = [], t0
    for m in OPEN_STRINGS[inst]:
        notes.append(Note(m, t, t + note_s, vel))
        t += note_s + gap_s
    return notes


def scale(inst, root=None, note_s=0.6, gap_s=0.05, vel=90, t0=0.5, descending=False, **_):
    root = _clip(inst, root if root is not None else OPEN_STRINGS[inst][1] + 2)
    steps = MAJOR[::-1] if descending else MAJOR
    notes, t = [], t0
    for s in steps:
        notes.append(Note(_clip(inst, root + s), t, t + note_s, vel))
        t += note_s + gap_s
    return notes


def repeated(inst, midi=None, count=8, note_s=0.25, gap_s=0.15, vel=90, t0=0.5, **_):
    """Same pitch repeated: stresses onset detection / re-attack handling (pizz, spiccato, tremolo bursts)."""
    midi = _clip(inst, midi if midi is not None else OPEN_STRINGS[inst][1] + 7)
    return [Note(midi, t0 + i * (note_s + gap_s), t0 + i * (note_s + gap_s) + note_s, vel) for i in range(count)]


def random_line(inst, seed=0, count=12, note_s=(0.3, 0.9), gap_s=(0.0, 0.2), max_leap=7, vel=(60, 110), t0=0.5, **_):
    """Stepwise-ish random monophonic melody inside the instrument range."""
    rng = np.random.default_rng(seed)
    spec = INSTRUMENTS[inst]
    m = int(rng.integers(spec["lo"] + 5, spec["hi"] - 12))
    notes, t = [], t0
    for _ in range(count):
        d = float(rng.uniform(*note_s))
        notes.append(Note(m, t, t + d, int(rng.integers(*vel))))
        t += d + float(rng.uniform(*gap_s))
        m = _clip(inst, m + int(rng.integers(-max_leap, max_leap + 1)))
    return notes


def chord(inst, intervals=(0, 7), root=None, note_s=2.0, vel=90, t0=0.5, stagger_s=0.0, **_):
    """Simultaneous (or staggered) notes on one track: a section 'divisi' chord. Prefer separate tracks for truth stems."""
    root = _clip(inst, root if root is not None else OPEN_STRINGS[inst][0] + 12)
    return [Note(_clip(inst, root + iv), t0 + i * stagger_s, t0 + i * stagger_s + note_s, vel) for i, iv in enumerate(intervals)]


# Interval classes that matter for the separator (see didddle/README.md): unrelated intervals separate well,
# fifths ~10 dB, octaves are erratic.
INTERVALS = {"minor_third": 3, "major_third": 4, "fourth": 5, "tritone": 6, "fifth": 7, "major_sixth": 9, "octave": 12}


def interval_pair(inst_lo, inst_hi, interval="fifth", root=None, note_s=2.0, vel=90, t0=0.5, **_):
    """Two tracks sounding together at a fixed interval -> {track: (inst, notes)}; truth is exact per stem."""
    semis = INTERVALS[interval] if isinstance(interval, str) else int(interval)
    root = root if root is not None else max(INSTRUMENTS[inst_lo]["lo"] + 7, INSTRUMENTS[inst_hi]["lo"] - 2)
    lo = Note(_clip(inst_lo, root), t0, t0 + note_s, vel, "lo")
    hi = Note(_clip(inst_hi, root + semis), t0, t0 + note_s, vel, "hi")
    return {"lo": (inst_lo, [lo]), "hi": (inst_hi, [hi])}


def staggered(insts, seed=0, count=8, overlap=0.5, note_s=1.2, vel=90, t0=0.5, **_):
    """N voices, each a note chain, with entries staggered so that notes overlap (poly tracker / slot-reuse test)."""
    rng = np.random.default_rng(seed)
    out = {}
    for v, inst in enumerate(insts):
        spec = INSTRUMENTS[inst]
        t = t0 + v * note_s * (1 - overlap)
        notes = []
        for _ in range(count):
            m = int(rng.integers(spec["lo"] + 3, spec["hi"] - 12))
            notes.append(Note(m, t, t + note_s, vel, f"v{v}"))
            t += note_s * (1 + float(rng.uniform(0, 0.3)))
        out[f"v{v}"] = (inst, notes)
    return out


MONO_SCENES = {"open_strings": open_strings, "scale": scale, "repeated": repeated, "random_line": random_line, "chord": chord}
