"""Harmonic salience and candidate generation (spec §6)."""
from dataclasses import dataclass
import numpy as np

from .spectral import spectral_peaks


@dataclass
class Candidate:
    f_hz: float
    midi: float
    salience: float
    hit: float
    miss: float
    inter: float = 0.0


def midi_to_hz(m):
    return 440.0 * 2.0 ** ((np.asarray(m) - 69.0) / 12.0)


def hz_to_midi(f):
    return 69.0 + 12.0 * np.log2(np.asarray(f) / 440.0)


class SalienceMap:
    """Static (grid x harmonic) frequency tables, built once.

    Evidence for an expected partial at frequency P is the strongest nearby
    spectral peak, weighted by a Gaussian of the frequency error (§6.2). The
    width is ~Hann mainlobe, optionally widened proportionally to the harmonic
    number to tolerate vibrato (§6.3 / review item).
    """

    def __init__(self, cfg, n_fft):
        p = cfg.profile
        self.cfg = cfg
        fs = cfg.sample_rate
        self.df = fs / n_fft
        step = cfg.grid_step_cents / 100.0
        m0, m1 = hz_to_midi(p.min_frequency_hz), hz_to_midi(p.max_frequency_hz)
        self.midi = np.arange(m0, m1 + 1e-9, step)
        self.f = midi_to_hz(self.midi)
        h = np.arange(1, cfg.max_harmonics + 1)
        B = p.inharmonicity_B
        stretch = np.sqrt(1.0 + B * h ** 2)
        self.h = h
        self.pf = self.f[:, None] * h[None, :] * stretch[None, :]
        self.valid = self.pf < 0.45 * fs
        # midpoints between consecutive partials (h+1/2): empty in a true series
        self.mf = self.f[:, None] * (h[None, :-1] + 0.5)
        self.mvalid = self.mf < 0.45 * fs
        w = h.astype(float) ** (-p.harmonic_weight_exponent)
        self.w = np.where(self.valid, w[None, :], 0.0)
        self.wsum = self.w.sum(axis=1)
        wm = w[None, :-1] * np.ones((len(self.f), 1))
        self.wm = np.where(self.mvalid, wm, 0.0)
        self.wmsum = np.maximum(self.wm.sum(axis=1), 1e-9)

    def _support(self, P, hh, pf, pa):
        """Max over nearby peaks of amplitude * gaussian(frequency error)."""
        if len(pf) == 0:
            return np.zeros_like(P)
        c = self.cfg
        sigma = (self.df * c.peak_sigma_bins + P * (c.vibrato_widen_cents / 1200.0) * np.log(2.0)
                 + P * 0.5 * c.inharm_tol_B * hh ** 2)
        i = np.clip(np.searchsorted(pf, P), 1, len(pf) - 1)
        out = np.zeros_like(P)
        for j in (i - 1, i):
            out = np.maximum(out, pa[j] * np.exp(-0.5 * ((pf[j] - P) / sigma) ** 2))
        return out

    def compute(self, M, W, snr=None):
        cfg = self.cfg
        pf, pa = spectral_peaks(M, W, self.df, cfg.peak_min_w, snr=snr, min_snr=cfg.peak_min_snr)
        hh = self.h[None, :] * np.ones((len(self.f), 1))
        Q = self._support(self.pf, hh, pf, pa)
        hit = (self.w * Q).sum(axis=1) / self.wsum
        miss = (self.w * np.maximum(0.0, cfg.miss_threshold - Q)).sum(axis=1) / self.wsum
        Qm = self._support(self.mf, hh[:, :-1], pf, pa)
        inter = (self.wm * Qm).sum(axis=1) / self.wmsum
        S = hit - cfg.miss_weight * miss - cfg.interleave_weight * inter
        return S, hit, miss, inter


def pick_candidates(sm, S, hit, miss, inter, cfg, forced_midi=()):
    """Non-maximum suppression on the salience curve (§6.5).

    `forced_midi` are active-track predictions that must stay eligible.
    """
    sep = int(round(cfg.min_candidate_separation_cents / cfg.grid_step_cents))
    n = len(S)
    order = np.argsort(-S, kind="stable")
    taken = np.zeros(n, bool)
    out = []
    for i in order:
        if len(out) >= cfg.max_candidates or S[i] <= 0:
            break
        if taken[max(0, i - sep): i + sep + 1].any():
            continue
        taken[i] = True
        d = 0.0
        if 0 < i < n - 1:  # parabolic refinement on the salience curve
            den = S[i - 1] - 2 * S[i] + S[i + 1]
            if den < -1e-12:
                d = float(np.clip(0.5 * (S[i - 1] - S[i + 1]) / den, -0.5, 0.5))
        m = sm.midi[i] + d * (cfg.grid_step_cents / 100.0)
        out.append(Candidate(float(midi_to_hz(m)), float(m), float(S[i]), float(hit[i]), float(miss[i]), float(inter[i])))
    for fm in forced_midi:
        if not any(abs(c.midi - fm) < cfg.min_candidate_separation_cents / 100.0 for c in out):
            i = int(np.argmin(np.abs(sm.midi - fm)))
            out.append(Candidate(float(midi_to_hz(fm)), float(fm), float(S[i]), float(hit[i]), float(miss[i]), float(inter[i])))
    return out
