"""Offline reference separator: STFT -> per-frame voice spectra -> ISTFT.

voices[v] + residual == x up to rounding, whatever the f0 tracks are.
"""
import numpy as np

from .estimate import ESTIMATORS
from .shape import shape
from .stft import Stft


class Separator:
    def __init__(self, cfg):
        self.cfg = cfg
        self.stft = Stft(cfg.n_fft, cfg.hop)
        self.estimate = ESTIMATORS[cfg.method](cfg)

    def centers(self, n_samples):
        """Sample index at which each frame's f0 is wanted."""
        return self.stft.centers(n_samples)

    def process(self, x, f0, spans=None):
        """x: (n,) mono. f0: (V, n_frames) Hz, NaN/0 = voice inactive.
        spans: optional per-voice [(start, end)] sample intervals; enables gating and attack routing.
        Returns (voices (V, n), residual (n,))."""
        x = np.asarray(x, float)
        X = self.stft.analyze(x)
        V, M = f0.shape
        assert M == X.shape[0], "f0 must be sampled at Separator.centers()"
        S = np.zeros((M, V, X.shape[1]), complex)
        for m in range(M):
            if np.isfinite(f0[:, m]).any():
                S[m] = self.estimate(X[m], f0[:, m])
        voices = np.stack([self.stft.synthesize(S[:, v], len(x)) for v in range(V)])
        if spans is None:
            return voices, self.stft.synthesize(X - S.sum(axis=1), len(x))
        voices = shape(x, voices, spans, self.cfg)
        return voices, x - voices.sum(0)
