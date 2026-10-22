"""Generate polyphonic scenes with exact truth from OrchideaSOL one-shots.

    from orchidea_scenes import Library, SceneSpec, generate

    lib = Library()                                        # or Library("/path/to/OrchideaSOL2020")
    spec = SceneSpec(instrument="contrabass", kind="overlap", voices=4,
                     techniques={"plucked": 1, "sustained": 2}, dynamics=["pp", "mf", "ff"], seed=3)
    scene = generate(lib, spec, index=0)                   # same spec, seed and index give the same scene
    scene.audio, scene.stems, scene.notes                  # mixture, one stem per note, truth (one dict per note)
    scene.write("out/", formats=("wav", "json", "midi", "stems"))

Scene kinds
  chords        `voices` different pitches struck together, `hits` times
  intervals     two notes a fixed interval apart (`intervals`), `hits` times
  strum         `voices` pitches rolled `strum_spread` seconds apart, `hits` times
  arpeggio      `voices` pitches one after another 0.12 to 0.3 s apart (they ring on), `hits` times
  lines         `voices` independent melodic lines of consecutive notes over `duration` seconds
  overlap       random notes at random times; `polyphony` is the mean number of notes sounding at once
  open_strings  every open string of the instrument, `hits` times each (for calibration), in random string order

Techniques and dynamics are drawn per note by default. `techniques` and `dynamics` take a list of names, or a dict of weights; a technique
may also be a group: "plucked", "bowed", "sustained" (bowed without tremolo, harmonics and col legno), "harmonics". `articulation` says
when the draw happens: "note" (every note), "voice" (once per voice or hit position) or "scene" (once for the scene).
"""
import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

import numpy as np
import soundfile as sf

from .library import OPEN_STRINGS, Library, technique_group
from .midi import write_midi
from .render import Event, render

KINDS = ("chords", "intervals", "strum", "arpeggio", "lines", "overlap", "open_strings")
ARTICULATION = ("note", "voice", "scene")


@dataclass
class SceneSpec:
    instrument: str = "cello"
    kind: str = "lines"
    voices: int = 3
    hits: int = 3
    duration: float = None             # seconds; lines and overlap (default 8), the other kinds size themselves
    techniques: object = None          # list of names or groups, or {name: weight}; None = every technique of the instrument
    dynamics: object = None            # list or {name: weight}; None = every dynamic
    midi_range: tuple = None           # (lo, hi); None = the range of the selected sounds
    articulation: str = "note"
    intervals: tuple = (3, 4, 5, 6, 7, 9, 12)
    polyphony: float = 3.0
    strum_spread: tuple = (0.03, 0.06)
    bowed_length: tuple = (1.0, 2.2)   # seconds a bowed note is held
    pluck_max_s: float = 2.5
    distinct_strings: bool = False     # a chord uses each string once (what a real player can do)
    gain_jitter_db: float = 0.0        # random level change per note, uniform in +-this
    lead_in: float = 0.3
    sr: int = 44100
    normalize_peak: float = None       # scale the scene to this peak (0..1); None keeps the library levels
    noise_snr_db: float = None         # add white noise at this signal-to-noise ratio (the stems stay noise-free)
    seed: int = 0

    def to_dict(self):
        return {k: (list(v) if isinstance(v, tuple) else v) for k, v in asdict(self).items()}

    @classmethod
    def from_dict(cls, d):
        known = {f for f in cls.__dataclass_fields__}
        bad = set(d) - known
        if bad:
            raise ValueError(f"unknown scene option(s): {sorted(bad)}")
        return cls(**{k: (tuple(v) if k in ("midi_range", "intervals", "strum_spread", "bowed_length") and v is not None else v) for k, v in d.items()})


@dataclass
class Scene:
    spec: SceneSpec
    index: int
    audio: np.ndarray                  # mixture (mono)
    stems: np.ndarray                  # (notes, samples); they add up to the mixture before noise is added
    notes: list                        # truth, one dict per note
    gain: float                        # shared gain that was applied to avoid clipping
    sr: int

    @property
    def name(self):
        return f"{self.spec.instrument}_{self.spec.kind}_{self.spec.seed}_{self.index}"

    @property
    def duration(self):
        return len(self.audio) / self.sr

    def to_dict(self):
        return {"name": self.name, "sr": self.sr, "gain": self.gain, "spec": self.spec.to_dict(), "index": self.index, "notes": self.notes}

    def write(self, directory, formats=("wav", "json", "stems"), subtype="PCM_24"):
        """Write the scene. formats: "wav" (mixture), "json" (truth), "stems" (one wav per note in <dir>/stems/), "midi" (truth as a MIDI file)."""
        out = Path(directory)
        out.mkdir(parents=True, exist_ok=True)
        paths = {}
        if "wav" in formats:
            paths["wav"] = out / f"{self.name}.wav"
            sf.write(paths["wav"], self.audio, self.sr, subtype=subtype)
        if "stems" in formats:
            (out / "stems").mkdir(exist_ok=True)
            paths["stems"] = []
            for i, st in enumerate(self.stems):
                p = out / "stems" / f"{self.name}.n{i}.wav"
                sf.write(p, st, self.sr, subtype=subtype)
                paths["stems"].append(p)
        if "json" in formats:
            paths["json"] = out / f"{self.name}.json"
            paths["json"].write_text(json.dumps(self.to_dict(), indent=1))
        if "midi" in formats:
            paths["midi"] = out / f"{self.name}.mid"
            write_midi(paths["midi"], self.notes)
        return paths


# ---- drawing sounds ------------------------------------------------------------------------------------------------

def _weights(arg, library, instrument, group_fn=technique_group):
    """{name: weight} or None (= everything). Accepts a list, a dict of weights, or a single name."""
    if arg is None:
        return None
    if isinstance(arg, str):
        arg = [arg]
    items = arg.items() if isinstance(arg, dict) else [(a, 1.0) for a in arg]
    out = {}
    for name, w in items:
        for t in group_fn(instrument, name, library):
            out[t] = out.get(t, 0.0) + float(w)
    return out


def _choice(rng, names, weights):
    w = np.array([weights.get(n, 0.0) if weights else 1.0 for n in names], float)
    if w.sum() <= 0:
        w = np.ones(len(names))
    return names[int(rng.choice(len(names), p=w / w.sum()))]


class _Drawer:
    """Draws sounds near a target pitch from the allowed techniques and dynamics."""

    def __init__(self, library, spec):
        self.spec = spec
        self.tw = _weights(spec.techniques, library, spec.instrument)
        self.dw = _weights(spec.dynamics, library, spec.instrument, lambda i, n, l: [n]) if spec.dynamics is not None else None
        pool = library.select(spec.instrument, list(self.tw) if self.tw else None, list(self.dw) if self.dw else None, spec.midi_range)
        if not pool:
            raise ValueError(f"no sounds for {spec.instrument} with techniques={spec.techniques} dynamics={spec.dynamics} midi_range={spec.midi_range}")
        self.pool = pool
        self.midis = np.array(sorted({s.midi for s in pool}))
        self.lo, self.hi = int(self.midis.min()), int(self.midis.max())

    def sound(self, rng, midi=None, technique=None, dynamic=None, strings=None, exclude_strings=None):
        pool = self.pool
        if technique is not None:
            pool = [s for s in pool if s.technique == technique] or pool
        if dynamic is not None:
            pool = [s for s in pool if s.dynamic == dynamic] or pool
        if strings:
            pool = [s for s in pool if s.string in strings] or pool
        if exclude_strings:                                   # prefer the exact pitch on a free string, else the nearest pitch on one
            free = [s for s in pool if s.string not in exclude_strings]
            pool = free or pool
        if midi is None:
            midi = int(rng.choice(sorted({s.midi for s in pool})))
        best = min(abs(s.midi - midi) for s in pool)
        near = [s for s in pool if abs(s.midi - midi) == best]
        t = technique or _choice(rng, sorted({s.technique for s in near}), self.tw)
        near = [s for s in near if s.technique == t]
        d = dynamic or _choice(rng, sorted({s.dynamic for s in near}), self.dw)
        near = [s for s in near if s.dynamic == d]
        return near[int(rng.integers(len(near)))]

    def articulation(self, rng, midi=None):
        """(technique, dynamic) drawn once, for the voice and scene modes."""
        s = self.sound(rng, midi)
        return s.technique, s.dynamic

    def pitches(self, rng, n):
        """n different pitches inside the range."""
        allm = np.arange(self.lo, self.hi + 1)
        return sorted(int(m) for m in rng.choice(allm, size=min(n, len(allm)), replace=False))


def _length(rng, sound, spec):
    return None if sound.kind == "plucked" else float(rng.uniform(*spec.bowed_length))


def _event(rng, spec, sound, onset, voice=0):
    g = float(rng.uniform(-spec.gain_jitter_db, spec.gain_jitter_db)) if spec.gain_jitter_db else 0.0
    return Event(sound, float(onset), _length(rng, sound, spec), g, voice)


def _fixed(rng, spec, drawer, voice_key):
    """(technique, dynamic) to force for this note, by the articulation mode."""
    if spec.articulation == "note":
        return None, None
    key = voice_key if spec.articulation == "voice" else "scene"
    cache = drawer.__dict__.setdefault("_fixed", {})
    if key not in cache:
        cache[key] = drawer.articulation(rng)
    return cache[key]


def build_events(spec, library, rng):
    """-> (events, duration_s)"""
    if spec.kind not in KINDS:
        raise ValueError(f"unknown scene kind {spec.kind!r}; choose from {KINDS}")
    if spec.articulation not in ARTICULATION:
        raise ValueError(f"articulation must be one of {ARTICULATION}")
    dr = _Drawer(library, spec)
    ev = []
    t0 = spec.lead_in
    if spec.kind in ("chords", "intervals", "strum", "arpeggio"):
        gap = 3.0
        for h in range(spec.hits):
            t = t0 + h * gap
            if spec.kind == "intervals":
                semi = int(spec.intervals[rng.integers(len(spec.intervals))])
                a = int(rng.integers(dr.lo, max(dr.lo, dr.hi - semi) + 1))
                midis = [a, a + semi]
            else:
                midis = dr.pitches(rng, spec.voices)
            snds = []
            used = set()
            for j, m in enumerate(midis):
                tech, dyn = _fixed(rng, spec, dr, j)
                s = dr.sound(rng, m, tech, dyn, exclude_strings=used if spec.distinct_strings else None)
                used.add(s.string)
                snds.append(s)
            off = 0.0
            for j, s in enumerate(snds):
                if spec.kind == "strum":
                    off = j * float(rng.uniform(*spec.strum_spread))
                elif spec.kind == "arpeggio":
                    off = j * float(rng.uniform(0.12, 0.3))
                ev.append(_event(rng, spec, s, t + off, j))
        return ev, t0 + spec.hits * gap + 0.5
    if spec.kind == "lines":
        dur = spec.duration or 8.0
        for v in range(spec.voices):
            t = float(rng.uniform(0.2, 1.0))
            m = int(rng.integers(dr.lo + 3, max(dr.lo + 4, dr.hi - 3)))
            while t < dur - 1.0:
                tech, dyn = _fixed(rng, spec, dr, v)
                s = dr.sound(rng, m, tech, dyn)
                e = _event(rng, spec, s, t, v)
                ev.append(e)
                t += (e.length or float(rng.uniform(0.5, 1.2))) + float(rng.uniform(0.0, 0.4))
                m = int(np.clip(m + rng.integers(-7, 8), dr.lo, dr.hi))
        return ev, dur
    if spec.kind == "overlap":
        dur = spec.duration or 8.0
        mean_len = 1.6                                    # a typical sounding time of one note
        t = float(rng.uniform(0.1, 0.4))
        k = 0
        while t < dur - 1.0:
            tech, dyn = _fixed(rng, spec, dr, k % max(spec.voices, 1))
            s = dr.sound(rng, None, tech, dyn)
            ev.append(_event(rng, spec, s, t, k % max(spec.voices, 1)))
            t += float(rng.exponential(mean_len / max(spec.polyphony, 0.5)))
            k += 1
        return ev, dur
    if spec.kind == "open_strings":
        strings = list(range(1, len(OPEN_STRINGS[spec.instrument]) + 1))
        t = t0
        order = []
        for _ in range(spec.hits):
            order += [int(x) for x in rng.permutation(strings)]
        for k, st in enumerate(order):
            m = OPEN_STRINGS[spec.instrument][st - 1]
            tech, dyn = _fixed(rng, spec, dr, st)
            s = dr.sound(rng, m, tech, dyn, strings=[st])
            e = _event(rng, spec, s, t, st - 1)
            ev.append(e)
            t += (e.length or (2.9 if spec.instrument == "guitar" else 1.9)) + 0.2
        return ev, t + 0.5
    raise AssertionError(spec.kind)


def generate(library, spec, index=0):
    """One scene. The same spec, seed and index always give the same scene."""
    rng = np.random.default_rng([spec.seed, KINDS.index(spec.kind), index])
    ev, dur = build_events(spec, library, rng)
    mix, stems, notes, gain = render(ev, spec.sr, dur, spec.pluck_max_s)
    if spec.normalize_peak:
        k = spec.normalize_peak / max(np.abs(mix).max(), 1e-12)
        mix, stems, gain = mix * k, stems * k, gain * k
    if spec.noise_snr_db is not None:
        sig = np.sqrt(np.mean(mix ** 2)) + 1e-12
        mix = mix + rng.standard_normal(len(mix)) * sig * 10 ** (-spec.noise_snr_db / 20)
    return Scene(spec, index, mix, stems, notes, gain, spec.sr)


def generate_many(library, spec, n):
    """n scenes with indices 0 .. n-1."""
    for i in range(n):
        yield generate(library, spec, i)
