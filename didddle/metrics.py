"""Separation metrics and stem/channel matching."""
import numpy as np
from scipy.optimize import linear_sum_assignment

FLOOR_DB = -30.0


def si_sdr(est, ref):
    ref = np.asarray(ref, float)
    est = np.asarray(est, float)
    e_ref = np.dot(ref, ref) + 1e-20
    tgt = np.dot(est, ref) / e_ref * ref
    err = est - tgt
    return max(FLOOR_DB, 10 * np.log10((np.dot(tgt, tgt) + 1e-20) / (np.dot(err, err) + 1e-20)))


def group_channels(channels, stems):
    """Sum each output channel into the stem it correlates with most (a voice detector has no notion of
    stems; several voices of one source belong together). Returns (n_stems, n) estimates."""
    est = np.zeros_like(stems)
    ns = np.sqrt((stems ** 2).sum(axis=1)) + 1e-12
    for ch in channels:
        nc = np.sqrt((ch ** 2).sum())
        if nc < 1e-6:
            continue
        est[np.argmax(np.abs(stems @ ch) / (ns * nc))] += ch
    return est


def match_stems(channels, stems):
    """One-to-one channel->stem assignment maximising SI-SDR (BSS-style permutation). Unmatched stems get zeros."""
    sc = np.array([[si_sdr(c, s) for c in channels] for s in stems])
    rows, cols = linear_sum_assignment(-sc)
    est = np.zeros_like(stems)
    for r, c in zip(rows, cols):
        est[r] = channels[c]
    return est


def score(est, stems, mix):
    """Per-stem SI-SDR of est and its improvement over using the mixture as the estimate."""
    sdr = np.array([si_sdr(e, s) for e, s in zip(est, stems)])
    base = np.array([si_sdr(mix, s) for s in stems])
    return sdr, sdr - base
