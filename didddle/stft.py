"""Hann/Hann weighted overlap-add STFT. Frame m is centred at `centers()[m]` (original sample index)."""
import numpy as np


def hann(n):
    return 0.5 - 0.5 * np.cos(2 * np.pi * np.arange(n) / n)   # periodic


class Stft:
    def __init__(self, n_fft, hop):
        self.n, self.hop = n_fft, hop
        self.win = hann(n_fft)
        # constant overlap-add gain of win^2 (analysis x synthesis window)
        self.norm = float(np.sum(self.win ** 2) / hop)

    def n_frames(self, n_samples):
        return -(-(n_samples + self.n) // self.hop) + 1

    def centers(self, n_samples):
        return np.arange(self.n_frames(n_samples)) * self.hop + self.n // 2 - self.n

    def analyze(self, x):
        m = self.n_frames(len(x))
        xp = np.zeros((m - 1) * self.hop + self.n)
        xp[self.n: self.n + len(x)] = x
        idx = np.arange(self.n)[None, :] + self.hop * np.arange(m)[:, None]
        return np.fft.rfft(xp[idx] * self.win, axis=1)

    def synthesize(self, X, n_samples):
        m = X.shape[0]
        yp = np.zeros((m - 1) * self.hop + self.n)
        fr = np.fft.irfft(X, n=self.n, axis=1) * self.win
        for i in range(m):
            yp[i * self.hop: i * self.hop + self.n] += fr[i]
        return yp[self.n: self.n + n_samples] / self.norm
