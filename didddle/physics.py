"""Measurements on isolated string notes: where the partials are, how stiff the string is, and the complex amplitude
(hence phase) of each partial. Used by tools/eval_physics.py to test the physical assumptions of spec §17 on real
recordings; independent of the detector (the pitch is given)."""
import numpy as np
import soundfile as sf
from scipy.ndimage import median_filter

from .estimate import hann_kernel
from .stft import hann

FMAX = 6000.0          # partials above this are not used
HMAX = 40


def load(path):
    x, sr = sf.read(path, always_2d=True)
    return x[:, 0].astype(float), sr


def window_for(sr, f_nom, periods=6, lo=2048, hi=16384):
    """Smallest power of two holding `periods` periods of the pitch, so neighbouring partials are resolved."""
    n = 1 << int(np.ceil(np.log2(periods * sr / f_nom)))
    return int(np.clip(n, lo, hi))


def frame_starts(n_samples, n, sr, t0, t1, hop_frac=0.25):
    """Start samples of Hann frames lying entirely within [t0, t1] seconds."""
    a, b = int(t0 * sr), min(int(t1 * sr), n_samples) - n
    return list(range(a, b + 1, max(1, int(n * hop_frac)))) if b >= a else []


def spectrum(x, start, n):
    return np.fft.rfft(x[start:start + n] * hann(n))


def peaks(X, df, snr=6.0, floor_db=-75.0):
    """Interpolated spectral peaks (freq, amp) above a median noise estimate and a floor under the maximum."""
    M = np.abs(X)
    noise = median_filter(M, size=41, mode="nearest")
    k = np.flatnonzero((M[1:-1] > M[:-2]) & (M[1:-1] >= M[2:]) & (M[1:-1] > snr * noise[1:-1]) & (M[1:-1] > M.max() * 10 ** (floor_db / 20))) + 1
    lm, l0, lp = np.log(M[k - 1] + 1e-12), np.log(M[k] + 1e-12), np.log(M[k + 1] + 1e-12)
    den = lm - 2 * l0 + lp
    d = np.where(den < -1e-12, np.clip(0.5 * (lm - lp) / np.where(den < -1e-12, den, -1), -0.5, 0.5), 0.0)
    return (k + d) * df, M[k]


def assign(f0, B, pf, pa, df, hmax):
    """Peaks matched to the partials of a (f0, B) series within 0.8 bin + 0.2% (as the calibrator)."""
    hs, ps, as_ = [], [], []
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
            hs.append(h); ps.append(pf[j]); as_.append(pa[j])
    return np.array(hs), np.array(ps), np.array(as_)


def stiffness(X, df, f_nom, min_partials=6):
    """Progressive fit of f_h = h f0 sqrt(1 + B h^2) on one frame. Returns dict or None."""
    pf, pa = peaks(X, df)
    if len(pf) < 4:
        return None
    f0, B = f_nom, 0.0
    h = p = a = None
    for hmax in (6, 10, 16, 24, HMAX):
        h, p, a = assign(f0, B, pf, pa, df, hmax)
        if len(h) < 4:
            return None
        y = (p / h) ** 2
        w = h.astype(float)
        A = np.stack([np.ones(len(h)), h.astype(float) ** 2], axis=1)
        (c0, c1), *_ = np.linalg.lstsq(A * w[:, None], y * w, rcond=None)
        if c0 <= 0:
            return None
        f0, B = float(np.sqrt(c0)), float(np.clip(c1 / c0, -2e-4, 3e-3))
    if len(h) < min_partials:
        return None
    cents = lambda pred: 1200 * np.log2(p / pred)
    stiff = cents(f0 * h * np.sqrt(1 + max(B, -1e-6) * h * h))
    fe = np.sum(p * h) / np.sum(h * h)
    return {"f0": f0, "B": B, "h": h, "freq": p, "amp": a, "n": len(h),
            "rms_stiff": float(np.sqrt(np.mean(stiff ** 2))), "rms_harm": float(np.sqrt(np.mean(cents(fe * h) ** 2)))}


def complex_amplitudes(X, nu, n, radius=4, ridge=1e-4):
    """Complex amplitude c_p of sinusoids at bin positions nu (one voice: partials far apart), from the frame
    spectrum X of a Hann-windowed frame; x[m] = Re(c e^{j 2 pi nu m / n}) with m counted from the frame start."""
    nb = len(X)
    lo = max(0, int(np.floor(nu.min())) - radius)
    hi = min(nb, int(np.ceil(nu.max())) + radius + 1)
    k = np.arange(lo, hi)
    d = k[:, None] - nu[None, :]
    A = 0.5 * hann_kernel(d, n) * (np.abs(d) <= radius)
    G = A.conj().T @ A
    lam = ridge * np.trace(G).real / len(nu)
    return np.linalg.solve(G + lam * np.eye(len(nu)), A.conj().T @ X[lo:hi])


def centre_phase(c, nu):
    """Phase of each partial at the frame centre (sample n/2): arg c + 2 pi nu (n/2) / n."""
    return np.angle(c) + np.pi * nu
