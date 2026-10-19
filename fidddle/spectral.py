"""Windowing, FFT, peak interpolation, whitening and noise floor (spec §5)."""
import numpy as np
from scipy.ndimage import median_filter

EPS = 1e-9


def hann(n):
    # Periodic Hann, as used for spectral analysis.
    return 0.5 - 0.5 * np.cos(2 * np.pi * np.arange(n) / n)


def magnitude(frame, window):
    return np.abs(np.fft.rfft(frame * window))


def parabolic_peak(mag, k):
    """Sub-bin offset delta in [-0.5, 0.5] from log-magnitude parabola (§5.3).

    Returns None for flat/invalid peaks.
    """
    if k < 1 or k >= len(mag) - 1:
        return None
    lm, l0, lp = (np.log(mag[k - 1] + EPS), np.log(mag[k] + EPS), np.log(mag[k + 1] + EPS))
    den = lm - 2 * l0 + lp
    if den >= -1e-12:
        return None
    return float(np.clip(0.5 * (lm - lp) / den, -0.5, 0.5))


class Whitener:
    """Whitened long-window magnitude W and noise-floor gate (spec §5.4).

    Envelope = moving average of log-magnitude over a window that is a fraction
    of an octave wide but never narrower than `min_width_hz`, so it spans
    several harmonics even for low fundamentals and does not follow individual
    partials. Implemented with prefix sums so the cost is O(bins).
    """

    def __init__(self, cfg, n_fft):
        self.cfg = cfg
        self.n = n_fft
        self.nbins = n_fft // 2 + 1
        fs = cfg.sample_rate
        self.freqs = np.arange(self.nbins) * fs / n_fft
        min_w = cfg.whiten_min_width_hz or 3.0 * cfg.profile.min_frequency_hz
        half = 0.5 * np.maximum(self.freqs * (2 ** (cfg.whiten_octave_fraction / 2) - 2 ** (-cfg.whiten_octave_fraction / 2)), min_w)
        hb = half / (fs / n_fft)
        k = np.arange(self.nbins)
        self.lo = np.clip(np.floor(k - hb).astype(int), 0, self.nbins - 1)
        self.hi = np.clip(np.ceil(k + hb).astype(int) + 1, 1, self.nbins)
        self.noise = None
        hop_s = cfg.hop_size / fs
        self.a_down = 1 - np.exp(-hop_s / cfg.noise_down_tau_s)
        self.a_up = 1 - np.exp(-hop_s / cfg.noise_up_tau_s)

    def envelope(self, L):
        c = np.concatenate(([0.0], np.cumsum(L)))
        return (c[self.hi] - c[self.lo]) / (self.hi - self.lo)

    def update_noise(self, M):
        """Noise floor = time-smoothed frequency-median of |M|.

        The frequency median (robust to sparse harmonic peaks) estimates the
        local median noise level; the asymmetric time smoother then follows
        decreases quickly and increases slowly. Smoothing |M| bin-by-bin with the
        asymmetric rule instead would settle near a very low percentile of the
        noise distribution and badly overstate SNR.
        """
        m = median_filter(M, size=self.cfg.noise_init_median_bins, mode="nearest")
        if self.noise is None:
            self.noise = m
            return
        a = np.where(m < self.noise, self.a_down, self.a_up)
        self.noise = self.noise + a * (m - self.noise)

    def process(self, M):
        """Return (W, E_L, gate). W is the whitened, gated magnitude."""
        L = np.log(M + EPS)
        E = self.envelope(L)
        W = np.exp(np.clip(L - E, -self.cfg.whiten_clip, self.cfg.whiten_clip))
        self.update_noise(M)
        k = self.cfg.noise_kappa
        gate = np.clip(np.log((M + EPS) / (self.noise + EPS)) / np.log(k), 0.0, 1.0)
        self.unclipped = M / np.exp(E)
        self.snr = M / (self.noise + EPS)
        return W * gate, E, gate


class OnsetFlux:
    """Short-window whitened spectral flux (spec §5.5), baseline-normalised."""

    def __init__(self, cfg):
        n = cfg.short_fft_size
        self.win = hann(n)
        self.w = Whitener(cfg, n)
        self.prev = None
        self.baseline = 1e-3
        self.beta = 0.02

    def process(self, frame):
        M = magnitude(frame, self.win)
        self.last_M = M
        L = np.log(M + EPS)
        W = np.exp(np.clip(L - self.w.envelope(L), -self.w.cfg.whiten_clip, self.w.cfg.whiten_clip))
        F = 0.0 if self.prev is None else float(np.maximum(0.0, W - self.prev).sum())
        self.prev = W
        self.baseline += self.beta * (F - self.baseline)
        return F / (self.baseline + 1e-6), W


def spectral_peaks(M, W, df, min_w, amp=None, snr=None, min_snr=0.0, sidelobe_bins=3, sidelobe_ratio=3.0):
    """Local maxima of W with sub-bin frequencies from the log-|M| parabola (§5.3).

    Returns (freqs_hz, amplitudes) sorted by frequency.
    """
    # Maxima are located on the raw magnitude: the clipped W has flat plateaus whose
    # first bin is not the true peak. W only gates which maxima are significant.
    k = np.nonzero((M[1:-1] > M[:-2]) & (M[1:-1] >= M[2:]) & (W[1:-1] > min_w)
                   & ((snr[1:-1] >= min_snr) if snr is not None else True))[0] + 1
    if len(k) == 0:
        return np.zeros(0), np.zeros(0)
    if sidelobe_bins > 0 and len(k) > 1:
        # Drop local maxima in the skirt of a much stronger neighbouring peak
        # (Hann sidelobes). Only adjacent peaks need checking.
        m = M[k]
        drop = np.zeros(len(k), bool)
        near_prev = (k[1:] - k[:-1]) <= sidelobe_bins
        drop[1:] |= near_prev & (m[:-1] >= sidelobe_ratio * m[1:])
        drop[:-1] |= near_prev & (m[1:] >= sidelobe_ratio * m[:-1])
        k = k[~drop]
        if len(k) == 0:
            return np.zeros(0), np.zeros(0)
    lm, l0, lp = np.log(M[k - 1] + EPS), np.log(M[k] + EPS), np.log(M[k + 1] + EPS)
    den = lm - 2 * l0 + lp
    ok = den < -1e-12
    d = np.where(ok, 0.5 * (lm - lp) / np.where(ok, den, -1.0), 0.0)
    d = np.clip(d, -0.5, 0.5)
    return (k + d) * df, (W if amp is None else amp)[k]
