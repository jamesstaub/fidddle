"""Voice f0 tracks for the separator, sampled at the separator's frame centres.

Two sources: exact tracks from synthetic notes (the oracle), and the fidddle detector with an explicit
lookahead `lookahead_s`, which models what a fixed-latency product could know when it must emit audio.
"""
from dataclasses import dataclass

import numpy as np

from fidddle.synth import midi_hz
from fidddle.analyzer import Analyzer
from fidddle.tracker import ACTIVE, RELEASING


def note_f0(note, sr, n):
    """Per-sample f0 (Hz) of a fidddle.synth.Note, NaN where it is silent. Mirrors fidddle.synth.render_note
    (kept separate so this package does not edit fidddle)."""
    f0 = np.full(n, np.nan)
    i0 = int(note.onset_s * sr)
    rel = 0.08 if note.kind == "bowed" else 0.0
    i1 = min(n, int((note.offset_s + rel) * sr))
    t = np.arange(i1 - i0) / sr
    ramp = np.clip((t - 0.25) / 0.3, 0, 1)
    cents = note.vib_cents * ramp * np.sin(2 * np.pi * note.vib_hz * t)
    if note.glide_to is not None:
        cents = cents + 100.0 * (note.glide_to - note.midi) * np.clip(t / max(note.offset_s - note.onset_s, 1e-6), 0, 1)
    f0[i0:i1] = midi_hz(note.midi) * 2.0 ** (cents / 1200.0)
    return f0


def truth_tracks(notes, sr, n, centers):
    """(V, len(centers)) exact f0 of each note at the frame centres."""
    idx = np.clip(centers, 0, n - 1)
    return np.stack([note_f0(nt, sr, n)[idx] for nt in notes])


# ---- detector-driven tracks -------------------------------------------------------------------

def _note_spans(events):
    """track_id -> [(on_est, on_deliver, off_est, off_deliver)] in samples; open notes end at +inf."""
    spans = {}
    for e in events:
        if e.kind == "on":
            spans.setdefault(e.track_id, []).append([e.onset_est_samples, e.deliver_samples, np.inf, np.inf])
        elif e.track_id in spans and np.isinf(spans[e.track_id][-1][2]):
            spans[e.track_id][-1][2:] = [e.onset_est_samples, e.deliver_samples]
    return spans


@dataclass
class DetectorRun:
    """What the detector produced for one signal, reduced to arrays (cheap to cache)."""
    ends: np.ndarray          # (F,) newest sample of each analysis frame
    half_window: float        # samples between a frame's centre and its end
    active: list              # per slot: [(frame, track_id, f_hz)] while ACTIVE/RELEASING
    spans: dict               # track_id -> [(on_est, on_deliver, off_est, off_deliver)]
    sample_rate: float


def run_detector(x, det_cfg):
    az = Analyzer(det_cfg)
    frames = az.run(x, track=True)
    act = [[] for _ in range(len(frames[0].tracks))]
    for j, f in enumerate(frames):
        for s, t in enumerate(f.tracks):
            if t.state in (ACTIVE, RELEASING):
                act[s].append((j, t.track_id, t.f_hz))
    return DetectorRun(np.array([f.end_sample for f in frames], float), az.n_long / 2, act,
                       _note_spans(az.events), det_cfg.sample_rate)


def tracks_from_run(run, centers, lookahead_s=np.inf, margin=0):
    """(n_slots, len(centers)) f0 in Hz, NaN where the slot is silent, using only what the detector could know.

    At target time c only information delivered by c + lookahead may be used: a frame is usable if it ended by
    then, a note is known once its note-on was delivered, and its end is known only once its note-off was.
    Within those limits the analysis frame nearest in time supplies the pitch (a frame is centred half a long
    window before its end, so a small lookahead gives stale pitch and a large one centred pitch). A large
    lookahead also back-fills a note to its estimated onset. `margin` extends a note's f0 that many samples
    before its onset and after its end, so frames that only partly cover it still model it (the gate trims the rest).
    """
    look = lookahead_s * run.sample_rate
    fcent = run.ends - run.half_window
    out = np.full((len(run.active), len(centers)), np.nan)
    for s, act in enumerate(run.active):
        if not act:
            continue
        aj = np.array([a[0] for a in act])
        for m, c in enumerate(centers):
            ok = np.flatnonzero(run.ends[aj] <= c + look)
            if len(ok) == 0:
                continue
            _, tid, f = act[ok[np.argmin(np.abs(fcent[aj[ok]] - c))]]
            for on_est, on_del, off_est, off_del in run.spans.get(tid, ()):
                if on_del <= c + look and c >= on_est - margin and (off_del > c + look or c <= off_est + margin):
                    out[s, m] = f
                    break
    return out


def spans_from_run(run, lookahead_s=np.inf, lead_s=0.0):
    """Per slot, the sample intervals in which its notes sound, as far as the detector could know at a given
    lookahead: a note opens at its estimated onset, or when it was confirmed if that is later, and closes at its
    estimated end, or when the note-off was delivered if that is later."""
    look = lookahead_s * run.sample_rate
    out = []
    for act in run.active:
        spans = []
        for tid in sorted({a[1] for a in act}):
            for on_est, on_del, off_est, off_del in run.spans.get(tid, ()):
                end = off_est if off_del - look <= off_est else off_del - look
                spans.append((max(on_est - lead_s * run.sample_rate, on_del - look), end))
        out.append(spans)
    return out


def truth_spans(notes, sr):
    return [[(nt.onset_s * sr, (nt.offset_s + (0.08 if nt.kind == "bowed" else 0.0)) * sr)] for nt in notes]


def split_notes(f0, spans, centers, margin=0):
    """Slot tracks -> one track per note, for scoring (a slot is reused by different sources over time, so
    whole-slot grouping would mix them). A frame belongs to the note whose span, widened by `margin`, is nearest."""
    rows, sp = [], []
    for s, slot_spans in enumerate(spans):
        for k, (a, b) in enumerate(slot_spans):
            lo = max([e for _, e in slot_spans[:k] if e <= a] + [-np.inf])
            hi = min([st for st, _ in slot_spans[k + 1:] if st >= b] + [np.inf])
            lo, hi = max(a - margin, (lo + a) / 2 if np.isfinite(lo) else -np.inf), min(b + margin, (b + hi) / 2 if np.isfinite(hi) else np.inf)
            row = np.where((centers >= lo) & (centers <= hi), f0[s], np.nan)
            if np.isfinite(row).any():
                rows.append(row)
                sp.append([(a, b)])
    return (np.array(rows) if rows else np.zeros((0, len(centers)))), sp
