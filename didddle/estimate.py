"""Per-frame voice spectra: given the mixture spectrum X of one frame and each voice's f0, return S (V, bins).

Both estimators share the Partials table and the same contract; the separator takes the residual as
X - sum(S), so any estimator keeps the outputs complementary.
"""
import numpy as np


def hann_kernel(delta, n):
    """Complex DTFT of a periodic Hann window of length n at bin offset `delta` (window starts at sample 0)."""
    def dirichlet(d):
        d = np.asarray(d, float)
        near = np.abs(d) < 1e-9
        out = np.exp(-1j * np.pi * d * (n - 1) / n) * np.sin(np.pi * d) / np.where(near, 1.0, np.sin(np.pi * d / n))
        return np.where(near, float(n), out)
    return 0.5 * dirichlet(delta) - 0.25 * dirichlet(delta - 1) - 0.25 * dirichlet(delta + 1)


class Partials:
    """Flat table of the partials of the active voices: owner voice, harmonic number, position in bins."""

    def __init__(self, f0, cfg):
        h = np.arange(1, cfg.max_partials + 1)
        stretch = np.sqrt(1.0 + cfg.inharmonicity_B * h ** 2)
        voice, harm, nu = [], [], []
        for v, f in enumerate(f0):
            if not np.isfinite(f) or f <= 0:
                continue
            fr = f * h * stretch
            ok = fr < cfg.band_hz
            voice += [v] * int(ok.sum())
            harm += list(h[ok])
            nu += list(fr[ok] / cfg.df)
        self.voice, self.harm, self.nu = np.array(voice, int), np.array(harm, int), np.array(nu, float)

    def __len__(self):
        return len(self.nu)


def _clusters(nu, voice, gap):
    """Group partials of *different* voices that sit within `gap` bins of each other (single linkage)."""
    order = np.argsort(nu)
    cid = np.empty(len(nu), int)
    c = -1
    for j, i in enumerate(order):
        if j == 0 or nu[i] - nu[order[j - 1]] > gap:
            c += 1
        cid[i] = c
    return cid, c + 1


def _nearest_gap(nu):
    """Distance in bins from each partial to its closest neighbour."""
    order = np.argsort(nu)
    s = nu[order]
    d = np.full(len(nu), np.inf)
    if len(nu) > 1:
        g = np.diff(s)
        d[order[:-1]] = g
        d[order[1:]] = np.minimum(d[order[1:]], g)
    return d


def snap_to_peaks(nu, X, max_move, isolation=2.5):
    """Move isolated partials onto the local log-parabola peak of |X| (follows detuning and vibrato per partial)."""
    mag = np.abs(X)
    out = nu.copy()
    iso = _nearest_gap(nu) > isolation
    for i in np.flatnonzero(iso):
        k = int(round(nu[i]))
        if k < 2 or k >= len(mag) - 2:
            continue
        k += int(np.argmax(mag[k - 1: k + 2])) - 1
        lm, l0, lp = np.log(mag[k - 1] + 1e-12), np.log(mag[k] + 1e-12), np.log(mag[k + 1] + 1e-12)
        den = lm - 2 * l0 + lp
        if den >= -1e-12:
            continue
        cand = k + float(np.clip(0.5 * (lm - lp) / den, -0.5, 0.5))
        if abs(cand - nu[i]) <= max_move:
            out[i] = cand
    return out


class SinusoidLS:
    """Fit one complex sinusoid per partial to the frame spectrum by ridge least squares, using the exact
    Hann kernel, so overlapping partials 1-3 bins apart are separated coherently. Partials of different
    voices closer than `cluster_gap_bins` cannot be told apart by their kernel: they share one unknown whose
    fitted amplitude is split by a Wiener share from each voice's spectral envelope (interpolated over its
    uncollided partials)."""

    def __init__(self, cfg):
        self.cfg = cfg

    def __call__(self, X, f0):
        cfg = self.cfg
        V, nb = len(f0), len(X)
        S = np.zeros((V, nb), complex)
        P = Partials(f0, cfg)
        if len(P) == 0:
            return S
        nu = snap_to_peaks(P.nu, X, cfg.snap_bins) if cfg.snap_bins > 0 else P.nu
        cid, nc = _clusters(nu, P.voice, cfg.cluster_gap_bins)
        nu_c = np.array([nu[cid == c].mean() for c in range(nc)])
        R = cfg.kernel_radius
        lo = max(0, int(np.floor(nu_c.min())) - R)
        hi = min(nb, int(np.ceil(nu_c.max())) + R + 1)
        k = np.arange(lo, hi)
        d = k[:, None] - nu_c[None, :]
        A = 0.5 * hann_kernel(d, cfg.n_fft) * (np.abs(d) <= R)
        G = A.conj().T @ A
        lam = cfg.ridge * np.trace(G).real / nc
        c = np.linalg.solve(G + lam * np.eye(nc), A.conj().T @ X[lo:hi])

        amp = np.abs(c)
        size = np.bincount(cid, minlength=nc)
        # per-voice envelope over harmonic number from uncollided partials
        share = np.ones(len(P))
        env = {}
        for v in np.unique(P.voice):
            m = (P.voice == v) & (size[cid] == 1)
            if m.sum() >= 2:
                o = np.argsort(P.harm[m])
                env[v] = (P.harm[m][o], np.log(amp[cid[m]][o] + 1e-12))
        for cl in np.flatnonzero(size > 1):
            mem = np.flatnonzero(cid == cl)
            a = np.array([np.exp(np.interp(P.harm[i], *env[P.voice[i]], left=np.nan, right=np.nan)) if P.voice[i] in env else np.nan
                          for i in mem])   # nan outside the span of the voice's uncollided partials
            known = np.isfinite(a)
            if known.all():                       # Wiener share of the fitted amplitude
                share[mem] = a ** 2 / np.sum(a ** 2)
            elif known.any():                     # known voices take their interpolated level, the rest is theirs
                take = np.minimum(a[known] / max(amp[cl], 1e-12), 1.0)
                if take.sum() > 1.0:
                    take /= take.sum()
                share[mem[known]] = take
                share[mem[~known]] = (1.0 - take.sum()) / (~known).sum()
            else:
                share[mem] = 1.0 / len(mem)
        C = np.zeros((V, nc), complex)
        np.add.at(C, (P.voice, cid), c[cid] * share)
        S[:, lo:hi] = C @ A.T
        return S


class CombMask:
    """Baseline: Gaussian comb around each voice's partials; shared bins split equally, the rest is residual."""

    def __init__(self, cfg):
        self.cfg = cfg

    def __call__(self, X, f0):
        cfg = self.cfg
        V, nb = len(f0), len(X)
        S = np.zeros((V, nb), complex)
        P = Partials(f0, cfg)
        if len(P) == 0:
            return S
        w = np.zeros((V, nb))
        k = np.arange(nb)
        for v, nu in zip(P.voice, P.nu):
            lo, hi = max(0, int(nu) - 4), min(nb, int(nu) + 6)
            w[v, lo:hi] = np.maximum(w[v, lo:hi], np.exp(-0.5 * ((k[lo:hi] - nu) / cfg.mask_sigma_bins) ** 2))
        total = w.sum(axis=0)
        m = w / np.maximum(total, 1.0)
        return m * X[None, :]


ESTIMATORS = {"ls": SinusoidLS, "mask": CombMask}
