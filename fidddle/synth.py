"""Synthetic string-like test signals with exact ground truth (spec §12.4)."""
from dataclasses import dataclass
import numpy as np


@dataclass
class Note:
    midi: float          # nominal pitch
    onset_s: float
    offset_s: float
    kind: str = "bowed"  # bowed | plucked
    vib_cents: float = 0.0
    vib_hz: float = 5.5
    glide_to: float = None   # target MIDI pitch reached linearly (in semitones) at offset
    B: float = 0.0           # string inharmonicity: partial h at h*f*sqrt(1+B*h^2)
    tau0: float = 1.6        # plucked decay time of the fundamental region, seconds


def midi_hz(m):
    return 440.0 * 2.0 ** ((m - 69.0) / 12.0)


def render_note(note, sr, n_total, rng, n_harm=24, amp=0.2):
    f0 = midi_hz(note.midi)
    i0 = int(note.onset_s * sr)
    rel = 0.08 if note.kind == "bowed" else 0.0
    i1 = min(n_total, int((note.offset_s + rel) * sr))
    t = np.arange(i1 - i0) / sr
    # vibrato after a 0.25 s delay with 0.3 s ramp
    ramp = np.clip((t - 0.25) / 0.3, 0, 1)
    cents = note.vib_cents * ramp * np.sin(2 * np.pi * note.vib_hz * t)
    if note.glide_to is not None:
        frac = np.clip(t / max(note.offset_s - note.onset_s, 1e-6), 0, 1)
        cents = cents + 100.0 * (note.glide_to - note.midi) * frac
    f_inst = f0 * 2.0 ** (cents / 1200.0)
    phase = 2 * np.pi * np.cumsum(f_inst) / sr
    y = np.zeros_like(t)
    # random per-note spectral tilt/dips so templates are not trivially matched
    tilt = rng.uniform(0.8, 1.2)
    for h in range(1, n_harm + 1):
        stretch = np.sqrt(1.0 + note.B * h * h)
        if f0 * h * stretch > 0.45 * sr:
            break
        a = h ** (-tilt) * rng.uniform(0.7, 1.0)
        if note.kind == "plucked":
            tau = note.tau0 / (1 + 0.35 * h)
            a = a * np.exp(-t / tau)
        y += a * np.sin(h * stretch * phase + rng.uniform(0, 2 * np.pi))
    if note.kind == "bowed":
        att = np.clip(t / 0.05, 0, 1)
        rls = np.clip((note.offset_s + rel - note.onset_s - t) / rel, 0, 1)
        y *= att * rls
    else:
        y *= np.clip(t / 0.003, 0, 1)
        if note.offset_s < note.onset_s + 1e6:
            rls = np.clip((note.offset_s + 0.05 - note.onset_s - t) / 0.05, 0, 1)
            y *= rls
    y *= amp / max(np.max(np.abs(y)), 1e-9) * rng.uniform(0.7, 1.0)
    return i0, y


def render(notes, sr, duration_s, snr_db=40.0, seed=0):
    rng = np.random.default_rng(seed)
    n = int(duration_s * sr)
    x = np.zeros(n)
    for note in notes:
        i0, y = render_note(note, sr, n, rng)
        x[i0: i0 + len(y)] += y
    if snr_db is not None:
        sig = np.sqrt(np.mean(x ** 2)) + 1e-12
        x += rng.standard_normal(n) * sig * 10 ** (-snr_db / 20)
    return x


def chord(midis, onset_s=0.3, dur_s=3.0, kind="bowed", vib_cents=0.0):
    return [Note(m, onset_s, onset_s + dur_s, kind, vib_cents) for m in midis]
