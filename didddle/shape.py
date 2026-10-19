"""Time-domain shaping of voice outputs from note spans: gates remove the stationary model's pre- and
post-echo, transient routing hands each note's attack (left in the residual) to the voice that starts it.

Both only move signal between voices and residual, so the caller recomputes the residual as x - sum(voices)
afterwards and the outputs stay complementary.
"""
import numpy as np


def gate(spans, n, fade, release):
    """Gate in [0, 1]: open from each span's start (rising over `fade` samples), closed `release` samples after its end."""
    g = np.zeros(n)
    for a, b in spans:
        a = int(max(a, 0))
        b = int(min(b, n)) if np.isfinite(b) else n
        if b <= a:
            continue
        w = np.ones(b - a)
        k = min(fade, len(w))
        w[:k] = np.linspace(0.0, 1.0, k, endpoint=False) if k else w[:k]
        g[a:b] = np.maximum(g[a:b], w)
        r = min(release, n - b)
        if r > 0:
            g[b:b + r] = np.maximum(g[b:b + r], np.linspace(1.0, 0.0, r, endpoint=False))
    return g


def transient_windows(spans_per_voice, n, pre, length):
    """(V, n) windows, 1 at each note start falling to 0 over `length` samples (raised cosine)."""
    W = np.zeros((len(spans_per_voice), n))
    fall = 0.5 + 0.5 * np.cos(np.pi * np.arange(length) / length)
    for v, spans in enumerate(spans_per_voice):
        for a, _ in spans:
            a = int(a)
            lo, hi = max(a - pre, 0), min(a + length, n)
            if hi <= lo:
                continue
            w = np.ones(hi - lo)
            tail = np.arange(lo, hi) - a
            m = tail >= 0
            w[m] = fall[tail[m]]
            W[v, lo:hi] = np.maximum(W[v, lo:hi], w)
    return W


def shape(x, voices, spans, cfg):
    """Gate each voice to its spans, then move attack energy from the residual into the voice that starts.
    Returns new voices; residual = x - voices.sum(0)."""
    sr = cfg.sample_rate
    n = voices.shape[1]
    ms = lambda v: int(round(v * 1e-3 * sr))
    out = np.stack([voices[v] * gate(spans[v], n, ms(cfg.gate_fade_ms), ms(cfg.gate_release_ms)) for v in range(len(voices))])
    if cfg.transient_ms > 0:
        W = transient_windows(spans, n, 0, ms(cfg.transient_ms))
        tot = np.maximum(W.sum(0), 1.0)      # simultaneous starts share the attack
        out = out + (W / tot) * (x - out.sum(0))
    return out
