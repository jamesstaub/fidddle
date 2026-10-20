"""Polyphonic model fitting (spec §7).

Fits the whitened peak spectrum Y with a sum of harmonic templates. Because
the loss is quadratic and the model linear in the amplitudes, everything needed
is the template-observation correlations b_i = <T_i, Y> and the template Gram
matrix G_ij = <T_i, T_j>; amplitude fitting is then a tiny NNLS problem.

    D(a) = E0 - 2 b.a + a'Ga ,  E0 = <Y, Y>        (reported as D/E0, the
                                                    unexplained fraction)
"""
from dataclasses import dataclass, field
import numpy as np
from scipy.optimize import nnls

from .salience import hz_to_midi
from .strings import feasible, assign_strings


@dataclass
class Voice:
    f_hz: float
    midi: float
    amp_w: float          # amplitude in the whitened domain
    amp: float            # physical amplitude estimate (§5.4)
    gain: float           # marginal explained fraction when added
    confidence: float
    level_db: float = -120.0   # observed level (dBFS, sinusoid-RMS equivalent) at the voice's partials
    string_index: int = -1
    snr_db: float = 0.0        # observed level over the local noise floor at the voice's partials


@dataclass
class FitResult:
    voices: list
    unexplained: float            # D/E0 of the chosen model
    explained: float              # 1 - unexplained
    e0: float
    infeasible: bool = False
    path: list = field(default_factory=list)   # (n_voices, D/E0) along greedy path


class Fitter:
    def __init__(self, cfg, n_fft):
        self.cfg = cfg
        self.n = n_fft
        self.nb = n_fft // 2 + 1
        self.df = cfg.sample_rate / n_fft
        self.h = np.arange(1, cfg.fit_max_harmonics + 1)
        self.fmax = cfg.derived_fit_band()
        p = cfg.profile
        self.win_gain = n_fft / 4.0   # peak |X| of a unit sinusoid under a Hann window
        self.half = 5  # kernel half-support in bins
        self.offs = np.arange(-self.half, self.half + 1)

    # ---- templates -------------------------------------------------------
    def templates(self, f_list):
        """Dense (n_cand, nbins) magnitude templates for fundamentals f_list."""
        cfg = self.cfg
        f = np.asarray(f_list, dtype=float)
        T = np.zeros((len(f), self.nb))
        stretch = np.sqrt(1.0 + self.cfg.inharm_B(f)[:, None] * self.h[None, :] ** 2)
        pf = f[:, None] * self.h[None, :] * stretch                          # (C,H)
        valid = pf < self.fmax
        sig = (self.df * cfg.peak_sigma_bins + pf * (cfg.vibrato_widen_cents / 1200.0) * np.log(2.0)
               + pf * 0.5 * cfg.inharm_tol_B * self.h[None, :] ** 2)
        c = np.rint(pf / self.df).astype(int)                                 # (C,H)
        idx = c[:, :, None] + self.offs[None, None, :]                        # (C,H,O)
        inb = (idx >= 0) & (idx < self.nb) & valid[:, :, None]
        g = np.exp(-0.5 * ((idx * self.df - pf[:, :, None]) / sig[:, :, None]) ** 2)
        hw = self.cfg.partial_weights(len(self.h), self.cfg.fit_weight_exponent, f)      # (C, H)
        val = hw[:, :, None] * g * inb
        rows = np.broadcast_to(np.arange(len(f))[:, None, None], idx.shape)
        np.add.at(T, (rows[inb], idx[inb]), val[inb])
        return T

    def render_peaks(self, pf, pa):
        """Observed spectrum rendered from interpolated peaks with the template kernel.

        Using the same kernel for data and templates removes the mismatch
        between the (clipped, mainlobe-wide) raw spectrum and sharp templates.
        """
        cfg = self.cfg
        Y = np.zeros(self.nb)
        if len(pf) == 0:
            return Y
        keep = pf < self.fmax
        pf, pa = pf[keep], pa[keep]
        if len(pf) == 0:
            return Y
        amp = np.maximum(pa, 0.0) ** cfg.fit_compress
        c = np.rint(pf / self.df).astype(int)
        idx = c[:, None] + self.offs[None, :]
        inb = (idx >= 0) & (idx < self.nb)
        sig = self.df * cfg.peak_sigma_bins
        g = np.exp(-0.5 * ((idx * self.df - pf[:, None]) / sig) ** 2) * amp[:, None]
        np.maximum.at(Y, idx[inb], g[inb])
        return Y

    # ---- amplitude fit ---------------------------------------------------
    @staticmethod
    def _nnls(G, b, idx):
        """min a'Ga - 2b'a over a>=0 restricted to idx. Returns (a, reduction)."""
        Gs = G[np.ix_(idx, idx)]
        # factor G = R'R (+jitter) so NNLS runs on ||R a - R^-T b||
        L = np.linalg.cholesky(Gs + 1e-9 * np.eye(len(idx)))
        rhs = np.linalg.solve(L, b[idx])
        a, _ = nnls(L.T, rhs)
        red = 2 * b[idx] @ a - a @ Gs @ a      # E0 - D
        return a, float(red)

    def _dup_penalty(self, fs, sel, j):
        """Extra gain demanded when candidate j's series is nested with a chosen voice's.

        If f_j/f_i (or its inverse) is an integer >= 2, one series is a subset of
        the other, so the added voice can only explain amplitude differences.
        """
        cfg = self.cfg
        tol = cfg.dup_tol_cents / 1200.0
        for i in sel:
            r = fs[j] / fs[i]
            for q in (r, 1.0 / r):
                n = round(q)
                if n >= 2 and abs(np.log2(q / n)) <= tol:
                    return cfg.dup_extra_gain
        return 0.0

    def _gain_threshold(self, n_voices):
        vg = self.cfg.voice_gain
        return vg[min(n_voices - 1, len(vg) - 1)]

    # ---- main ------------------------------------------------------------
    def fit(self, W, E_L, cands, peaks, M=None, prior_midis=(), max_voices=None, noise=None):
        cfg, prof = self.cfg, self.cfg.profile
        V = max_voices or cfg.max_voices
        Y = self.render_peaks(*peaks)
        e0 = float(Y @ Y)
        if e0 <= 1e-6 or not cands:
            return FitResult([], 1.0, 0.0, e0)
        fs = np.array([c.f_hz for c in cands])
        T = self.templates(fs)
        b = T @ Y
        G = T @ T.T
        sel, path, last_red = [], [(0, 1.0)], 0.0
        a_cur = np.zeros(0)
        # greedy forward selection (§7.3)
        while len(sel) < V:
            best = None
            for j in range(len(cands)):
                if j in sel or any(abs(cands[j].midi - cands[i].midi) * 100.0 < cfg.min_voice_sep_cents for i in sel):
                    continue
                a, red = self._nnls(G, b, sel + [j])
                adj = red - self._dup_penalty(fs, sel, j) * e0
                if best is None or adj > best[3]:
                    best = (j, red, a, adj)
            if best is None:
                break
            j, red, a, adj = best
            gain = (adj - last_red) / ((e0 - last_red) if cfg.gain_relative else e0)
            need = cfg.first_voice_min_gain if not sel else self._gain_threshold(len(sel) + 1)
            if len(prior_midis) and np.min(np.abs(np.asarray(prior_midis) - cands[j].midi)) < 0.5:
                need *= cfg.prior_persist_factor
            if gain < need or a[-1] <= 0:
                break
            sel.append(j)
            a_cur, last_red = a, red
            path.append((len(sel), 1.0 - red / e0))
        if not sel:
            return FitResult([], 1.0, 0.0, e0, path=path)

        # joint refinement of pitches (§7.7): coordinate descent, bounded passes
        f_sel = fs[sel].copy()
        for _ in range(min(2, cfg.max_fit_iterations)):
            changed = False
            for vi in range(len(sel)):
                offs = np.arange(-cfg.refine_cents, cfg.refine_cents + 1e-9, cfg.refine_step_cents)
                trial = f_sel[vi] * 2.0 ** (offs / 1200.0)
                others = np.delete(f_sel, vi)
                Tt = self.templates(np.concatenate([others, trial]))
                To = Tt[: len(others)]
                best = (-1, f_sel[vi])
                for ti in range(len(trial)):
                    Tm = np.vstack([To, Tt[len(others) + ti]])
                    bm, Gm = Tm @ Y, Tm @ Tm.T
                    a, red = self._nnls(Gm, bm, list(range(len(Tm))))
                    if red > best[0]:
                        best = (red, trial[ti])
                if abs(best[1] - f_sel[vi]) > 1e-9:
                    f_sel[vi] = best[1]
                    changed = True
            if not changed:
                break
        Tm = self.templates(f_sel)
        bm, Gm = Tm @ Y, Tm @ Tm.T
        a, red = self._nnls(Gm, bm, list(range(len(f_sel))))

        # marginal gains by leave-one-out, for confidence
        voices = []
        strings = assign_strings(f_sel, prof) if prof.string_constraint != "off" else -np.ones(len(f_sel), int)
        infeasible = prof.string_constraint != "off" and not feasible(f_sel, prof)
        for i in range(len(f_sel)):
            keep = [k for k in range(len(f_sel)) if k != i]
            if keep:
                _, red_wo = self._nnls(Gm, bm, keep)
            else:
                red_wo = 0.0
            marg = (red - red_wo) / e0
            st = np.sqrt(1.0 + cfg.inharm_B(f_sel[i]) * self.h ** 2)
            kh = np.rint(f_sel[i] * self.h * st / self.df).astype(int)
            ok = (kh < self.nb) & (f_sel[i] * self.h * st < self.fmax)
            hwv = cfg.partial_weights(len(self.h), cfg.fit_weight_exponent, f_sel[i])
            env = float((hwv[ok] * np.exp(E_L[kh[ok]])).sum() / max(hwv[ok].sum(), 1e-9)) if ok.any() else 0.0
            conf = float(np.clip(marg / max(cfg.first_voice_min_gain * 3, 1e-9), 0.0, 1.0))
            lvl, snr = -120.0, 0.0
            if M is not None and ok.any():
                kk = kh[ok]
                loc = np.maximum.reduce([M[np.clip(kk + d, 0, self.nb - 1)] for d in (-1, 0, 1)])
                lvl = float(20 * np.log10(np.sqrt(np.sum((loc / self.win_gain) ** 2) / 2.0) + 1e-12))
                if noise is not None:
                    nz = float(20 * np.log10(np.sqrt(np.sum((noise[kk] / self.win_gain) ** 2) / 2.0) + 1e-12))
                    snr = lvl - nz
            voices.append(Voice(float(f_sel[i]), float(hz_to_midi(f_sel[i])), float(a[i]), float(a[i] * env), float(marg), conf, lvl, int(strings[i]), snr))
        voices.sort(key=lambda v: v.f_hz)
        return FitResult(voices, 1.0 - red / e0, red / e0, e0, infeasible, path)
