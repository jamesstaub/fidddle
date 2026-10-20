"""Open-string calibration (spec §12.3).

The player plays each open string on its own and lets it ring. Frames that are not a clean single note
are ignored, so other playing in between is harmless, but chords or overlapping notes contribute nothing.

For every accepted frame the calibrator fits the observed partial frequencies to
    f_h = h * f0 * sqrt(1 + B h^2)   <=>   (f_h / h)^2 = f0^2 + (f0^2 B) h^2
by weighted least squares, which gives the string's true pitch and inharmonicity B, and it records the
level of each partial relative to the first eight (the harmonic weight profile). Per-string results are the
medians over many frames; the weight profile is averaged over strings.
"""
from dataclasses import dataclass
import numpy as np

from .profile import Calibration
from .stringid import DELAY_S, NO_VALUE, log_b, window_len

N_WEIGHTS = 24


@dataclass
class CalibEvent:
    kind: str            # "progress" | "string" | "complete"
    string: int = -1
    frames: int = 0
    needed: int = 0
    f0_hz: float = 0.0
    cents: float = 0.0
    B: float = 0.0


class Calibrator:
    def __init__(self, cfg, n_long, need_frames=30, min_run=12, max_run=70):
        self.cfg = cfg
        self.df = cfg.sample_rate / n_long
        self.nominal = np.array(cfg.profile.open_string_hz, dtype=float)
        self.n = len(self.nominal)
        self.need = need_frames
        self.min_run, self.max_run = min_run, max_run
        self.fmax = cfg.derived_fit_band()
        self.reset()

    def reset(self):
        n = self.n
        self.B_list = [[] for _ in range(n)]
        self.cents_list = [[] for _ in range(n)]
        self.prof_sum = np.zeros((n, N_WEIGHTS))
        self.prof_cnt = np.zeros((n, N_WEIGHTS))
        self.lb_list = [[] for _ in range(n)]       # log(B/f^2) from long-window stiffness fits (string identity)
        self.lb_last = [-1] * n
        self.frames = [0] * n
        self.done = [False] * n
        self.run_len = 0
        self.last_midi = None

    # ------------------------------------------------------------------------------------------
    def _assign(self, f0, B, pf, pa, hmax):
        h_list, p_list, a_list = [], [], []
        for h in range(1, hmax + 1):
            exp = f0 * h * np.sqrt(1.0 + B * h * h)
            if exp > self.fmax:
                break
            i = int(np.searchsorted(pf, exp))
            best = None
            for j in (i - 1, i):
                if 0 <= j < len(pf):
                    d = abs(pf[j] - exp)
                    if best is None or d < best[0]:
                        best = (d, j)
            if best is not None and best[0] <= 0.8 * self.df + 0.002 * exp:
                h_list.append(h)
                p_list.append(pf[best[1]])
                a_list.append(pa[best[1]])
        return np.array(h_list), np.array(p_list), np.array(a_list)

    def _estimate(self, f0, B, pf, pa):
        # pf, pa: all peaks of the frame (sorted by frequency)
        """Progressive (partials up to 6, 10, 16, 24, 32) weighted fit of f0 and B. None if not clean."""
        h = p = a = None
        for hmax in (6, 10, 16, 24, 32):
            h, p, a = self._assign(f0, B, pf, pa, hmax)
            if len(h) < 4:
                return None
            y = (p / h) ** 2
            X = np.stack([np.ones_like(h, dtype=float), h.astype(float) ** 2], axis=1)
            w = h.astype(float)                       # sqrt of the h^2 weights
            coef, *_ = np.linalg.lstsq(X * w[:, None], y * w, rcond=None)
            c0, c1 = coef
            if c0 <= 0:
                return None
            f0 = float(np.sqrt(c0))
            B = c1 / c0
            if B < -5e-5 or B > 2e-3:
                return None
            B = max(B, 0.0)
        pred = f0 * h * np.sqrt(1.0 + B * h * h)
        rms = float(np.sqrt(np.mean((pred - p) ** 2)))
        if len(h) < 6 or rms > 0.6 * self.df:
            return None
        # reject a lock onto an upper harmonic: a comparably strong peak at f0/2, f0/3 or f0/4 means f0 is not the fundamental
        a1 = float(a[0]) if h[0] == 1 else 0.0
        for k in (2, 3, 4):
            lo, hi = np.searchsorted(pf, f0 / k * 0.97), np.searchsorted(pf, f0 / k * 1.03)
            if hi > lo and a1 > 0 and float(np.max(pa[lo:hi])) > 0.5 * a1:
                return None
        return f0, B, h, a

    # ------------------------------------------------------------------------------------------
    def update(self, voices, peaks, audio=None):
        """One analysis frame: the fitted voices and the (freq, unclipped amplitude) peaks the fit used."""
        events = []
        if self.complete:                      # every string captured: the detector finishes the calibration here
            return events
        # A clean single note: some voice (the "root") such that every other voice is a harmonic of it or a sub-octave of it,
        # and which sits near an open string. With the wrong inharmonicity assumed, the fit explains misaligned upper
        # partials as extra octave/twelfth voices and sometimes adds a ghost octave below, so several voices can qualify;
        # they are tried from the lowest up and the first whose partial structure actually fits is used.
        def related(root, o):
            r = o.f_hz / root.f_hz
            for q in (r, 1.0 / r):
                n = round(q)
                if n >= 2 and abs(q / n - 1.0) <= 0.025:
                    return True
            return o is root or o.gain <= 0.25 * root.gain       # a much weaker stray voice is not a second note
        valid = []
        for root in sorted(voices, key=lambda o: o.f_hz):
            if root.level_db < self.cfg.min_level_dbfs + 6.0 or not all(related(root, o) for o in voices):
                continue
            c = 1200.0 * np.log2(root.f_hz / self.nominal)
            s = int(np.argmin(np.abs(c)))
            if abs(c[s]) <= 150.0:
                valid.append((root, s))
        if not valid:
            self.run_len, self.last_midi = 0, None
            return events
        v = valid[0][0]
        if self.last_midi is None or abs(v.midi - self.last_midi) > 0.3:
            self.run_len = 0
        self.last_midi = v.midi
        self.run_len += 1
        if audio is not None and self.cfg.string_id:      # string identity: stiffness of the settled note on a long window
            x, end = audio
            v0, s0 = valid[0]
            n = window_len(self.cfg.sample_rate, v0.f_hz)
            if (self.run_len * self.cfg.hop_size >= n + DELAY_S * self.cfg.sample_rate and end >= n and len(self.lb_list[s0]) < 8
                    and (self.lb_last[s0] < 0 or end - self.lb_last[s0] >= n // 2)):
                self.lb_last[s0] = end
                lb = log_b(np.asarray(x[end - n:end], float), self.cfg.sample_rate, v0.f_hz)
                if lb is not None:
                    self.lb_list[s0].append(lb)
        if self.run_len < self.min_run or self.run_len > self.max_run:       # skip the attack; early decay carries the full spectrum
            return events
        pf, pa = peaks
        if len(pf) < 6:
            return events
        est = None
        for v, s in valid:
            B0 = float(np.median(self.B_list[s])) if len(self.B_list[s]) >= 5 else float(self.cfg.inharm_B(v.f_hz))
            est = self._estimate(v.f_hz, B0, np.asarray(pf), np.asarray(pa))
            if est is not None:
                break
        if est is None:
            return events
        f0, B, h, a = est
        self.B_list[s].append(B)
        self.cents_list[s].append(1200.0 * np.log2(f0 / self.nominal[s]))
        # harmonic profile in the fit's compressed-amplitude domain, relative to the first eight partials
        y = np.zeros(N_WEIGHTS)
        seen = np.zeros(N_WEIGHTS, bool)
        hm = int(min(N_WEIGHTS, h.max()))
        seen[:hm] = True
        for hh, aa in zip(h, a):
            if hh <= N_WEIGHTS:
                y[hh - 1] = max(aa, 0.0) ** self.cfg.fit_compress
        ref = float(np.mean(y[: min(8, hm)]))
        if ref > 0:
            self.prof_sum[s][seen] += y[seen] / ref
            self.prof_cnt[s][seen] += 1
        self.frames[s] += 1
        if self.frames[s] % 10 == 0 and not self.done[s]:
            events.append(CalibEvent("progress", s, self.frames[s], self.need))
        if self.frames[s] >= self.need and not self.done[s]:
            self.done[s] = True
            events.append(CalibEvent("string", s, self.frames[s], self.need, float(self.nominal[s] * 2 ** (np.median(self.cents_list[s]) / 1200)),
                                     float(np.median(self.cents_list[s])), float(np.median(self.B_list[s]))))
            if all(self.done):
                events.append(CalibEvent("complete", frames=sum(self.frames)))
        return events

    @property
    def complete(self):
        return all(self.done)

    def finalize(self):
        """Calibration from what has been captured so far, or None if no string is complete."""
        cal = Calibration.empty(self.n)
        for s in range(self.n):
            if self.done[s]:
                cal.captured[s] = True
                cal.B[s] = float(np.median(self.B_list[s]))
                cal.cents[s] = float(np.median(self.cents_list[s]))
        for s in range(self.n):                # string identity values do not need the full 30 frames
            if len(self.lb_list[s]) >= 2:
                cal.logb[s] = float(np.median(self.lb_list[s]))
        if not cal.any_strings:
            return None
        sums, cnts = np.zeros(N_WEIGHTS), np.zeros(N_WEIGHTS)
        for s in range(self.n):
            if self.done[s]:
                sums += self.prof_sum[s]
                cnts += self.prof_cnt[s]
        m = 0
        while m < N_WEIGHTS and cnts[m] >= 20:
            m += 1
        if m >= 6:
            w = sums[:m] / cnts[:m]
            w = w / max(np.mean(w[: min(8, m)]), 1e-9)
            cal.weights = [float(x) for x in np.maximum(w, 0.03)]
        # the profile of each captured string (a pitch uses the profile of the string it would be played on)
        for s in range(self.n):
            if not self.done[s]:
                continue
            ms = 0
            while ms < N_WEIGHTS and self.prof_cnt[s][ms] >= 10:
                ms += 1
            if ms >= 6:
                w = self.prof_sum[s][:ms] / self.prof_cnt[s][:ms]
                w = w / max(np.mean(w[: min(8, ms)]), 1e-9)
                cal.string_weights[s] = [float(x) for x in np.maximum(w, 0.03)]
        return cal
