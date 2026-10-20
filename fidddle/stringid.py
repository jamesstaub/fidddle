"""Which string played a note (spec §17.5): stiffness-based, for plucked instruments whose strings differ in B (guitar; later banjo,
mandolin, ...).

A stiff string has B proportional to f^2 along its length, so log(B / f^2) is nearly a constant of the string a pitch was played on.
The value for a note comes from a stiffness fit (partial positions of a long Hann frame) once the note has settled; the values of the
strings come from their open-string notes during calibration, measured the same way. The per-frame partial positions of the detector were
tried and are too noisy for this (chance level on single notes); the dedicated fit carries the information. No calibration, no answer.
"""
import numpy as np
from scipy.ndimage import median_filter

from .spectral import hann

FMAX = 6000.0          # partials above this are not used
HMAX = 40
B_MIN = 1e-6           # below this the string is too slack to tell from an exact series
DELAY_S = 0.2          # the stiffness window starts this long after the note was confirmed
N_MEAS = 2             # window measurements per note
NO_VALUE = -99.0       # stored log(B/f^2) of a string that was not measured
MARGIN_MIN = 0.3       # below this gap to the second-best string the stiffness is not trusted and the pitch rule answers instead


def window_len(sr, f_hz, periods=6, lo=2048, hi=16384):
    """Smallest power of two holding `periods` periods of the pitch."""
    n = 1 << int(np.ceil(np.log2(periods * sr / f_hz)))
    return int(min(max(n, lo), hi))


def _peaks(M, df, snr=6.0, floor_db=-75.0):
    noise = median_filter(M, size=41, mode="nearest")
    k = np.flatnonzero((M[1:-1] > M[:-2]) & (M[1:-1] >= M[2:]) & (M[1:-1] > snr * noise[1:-1]) & (M[1:-1] > M.max() * 10 ** (floor_db / 20))) + 1
    lm, l0, lp = np.log(M[k - 1] + 1e-12), np.log(M[k] + 1e-12), np.log(M[k + 1] + 1e-12)
    den = lm - 2 * l0 + lp
    d = np.where(den < -1e-12, np.clip(0.5 * (lm - lp) / np.where(den < -1e-12, den, -1), -0.5, 0.5), 0.0)
    return (k + d) * df, M[k]


def _assign(f0, B, pf, df, hmax):
    hs, ps = [], []
    for h in range(1, hmax + 1):
        e = f0 * h * np.sqrt(1.0 + B * h * h)
        if e > FMAX:
            break
        i = int(np.searchsorted(pf, e))
        cand = [j for j in (i - 1, i) if 0 <= j < len(pf)]
        if not cand:
            continue
        j = min(cand, key=lambda j: abs(pf[j] - e))
        if abs(pf[j] - e) <= 0.8 * df + 0.002 * e:
            hs.append(h)
            ps.append(pf[j])
    return np.array(hs), np.array(ps)


def stiffness(seg, sr, f_nom, min_partials=6):
    """(f0, B) of the string note in `seg` (len a power of two), or None. Progressive fit of f_h = h f0 sqrt(1 + B h^2)."""
    n = len(seg)
    df = sr / n
    M = np.abs(np.fft.rfft(seg * hann(n)))
    if M.max() <= 0:
        return None
    pf, pa = _peaks(M, df)
    if len(pf) < 4:
        return None
    f0, B = f_nom, 0.0
    h = None
    for hmax in (6, 10, 16, 24, HMAX):
        h, p = _assign(f0, B, pf, df, hmax)
        if len(h) < 4:
            return None
        w = h.astype(float)
        A = np.stack([np.ones(len(h)), w ** 2], axis=1)
        (c0, c1), *_ = np.linalg.lstsq(A * w[:, None], (p / h) ** 2 * w, rcond=None)
        if c0 <= 0:
            return None
        f0, B = float(np.sqrt(c0)), float(np.clip(c1 / c0, -2e-4, 3e-3))
    if len(h) < min_partials:
        return None
    return f0, B


def log_b(seg, sr, f_nom):
    """log(B / f0^2) of a note, or None when there is no usable measurement."""
    r = stiffness(seg, sr, f_nom)
    if r is None or r[1] <= B_MIN:
        return None
    return float(np.log(r[1] / r[0] ** 2))


def classify(value, f_hz, centroids, open_hz, max_semitones=24):
    """-> (string index or -1, margin). centroids: log(B / f^2) per string (NO_VALUE when unknown); strings that can sound f_hz are those
    whose open pitch is at or below it by at most max_semitones (open_hz ascending). The margin is the gap, in log units, between the
    best and second-best string by stiffness; when it is below MARGIN_MIN the answer is the pitch rule (the highest string that can
    sound the pitch, usually the lowest fret) and the margin is reported as 0: a guess."""
    cand = [s for s, fo in enumerate(open_hz) if 0 <= 12 * np.log2(f_hz / fo) + 0.5 <= max_semitones]
    if not cand:
        return -1, 0.0
    rule = max(cand)
    known = sorted((abs(value - centroids[s]), s) for s in cand if centroids[s] > NO_VALUE + 1)
    if len(known) < 2:
        return rule, 0.0
    margin = known[1][0] - known[0][0]
    return (known[0][1], margin) if margin >= MARGIN_MIN else (rule, 0.0)


class StringIdentifier:
    """Streaming: watches confirmed tracks, measures the stiffness of each after it has settled, and says which string it was."""

    def __init__(self, cfg):
        self.cfg = cfg
        self.sr = cfg.sample_rate
        self.states = {}                  # track id -> dict
        self.nominal = list(cfg.profile.open_string_hz)

    @property
    def enabled(self):
        c = self.cfg.calibration
        return bool(self.cfg.string_id and c is not None and c.has_logb)

    def update(self, x, end, snaps, make_event):
        """x: the input signal so far (indexable up to `end`), snaps: this frame's TrackSnapshots, make_event(kind, snap, string, margin)."""
        events = []
        if not self.enabled:
            return events
        c = self.cfg.calibration
        live = set()
        for s in snaps or []:
            if s is None or s.state != 2:                    # ACTIVE
                continue
            live.add(s.track_id)
            st = self.states.get(s.track_id)
            if st is None:
                st = self.states[s.track_id] = {"birth": end, "last": -1, "vals": [], "done": False, "snap": s}
            st["snap"] = s
            if st["done"]:
                continue
            n = window_len(self.sr, s.f_hz)
            if end - st["birth"] < DELAY_S * self.sr + n or end < n:
                continue
            if st["last"] >= 0 and end - st["last"] < n // 2:
                continue
            st["last"] = end
            v = log_b(np.asarray(x[end - n:end], float), self.sr, s.f_hz)
            if v is not None:
                st["vals"].append(v)
            if len(st["vals"]) >= N_MEAS:
                events += self._finish(st, c, make_event)
        for tid in [t for t in self.states if t not in live]:
            st = self.states.pop(tid)
            if not st["done"] and st["vals"]:
                events += self._finish(st, c, make_event)
        return events

    def _finish(self, st, c, make_event):
        st["done"] = True
        s = st["snap"]
        string, margin = classify(float(np.median(st["vals"])), s.f_hz, c.logb, self.nominal)
        return [make_event("string", s, string, margin)] if string >= 0 else []

    def flush(self, make_event):
        """End of input: answer for the notes still sounding that have a measurement."""
        events = []
        if self.enabled:
            for st in self.states.values():
                if not st["done"] and st["vals"]:
                    events += self._finish(st, self.cfg.calibration, make_event)
        self.states.clear()
        return events
