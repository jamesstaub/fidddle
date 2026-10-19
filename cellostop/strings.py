"""String-feasibility constraint (spec §1.3)."""
import numpy as np


def feasible(pitches_hz, profile, tol_cents=50.0):
    """True if each pitch can sit on a distinct string with open pitch <= pitch.

    Ascending pitches p_i must satisfy p_i >= s_i (minus tolerance) against the
    ascending open strings; with only a lower bound per string this sorted
    comparison is equivalent to bipartite matching.
    """
    p = np.sort(np.asarray(pitches_hz, dtype=float))
    s = np.sort(np.asarray(profile.open_string_hz, dtype=float))
    if len(p) > len(s):
        return False
    tol = 2.0 ** (-tol_cents / 1200.0)
    return bool(np.all(p >= s[: len(p)] * tol))


def assign_strings(pitches_hz, profile, tol_cents=50.0):
    """String index (0 = lowest) per pitch, in input order, or -1 if infeasible.

    Greedy: lowest pitch gets the lowest string it can sound.
    """
    p = np.asarray(pitches_hz, dtype=float)
    out = -np.ones(len(p), dtype=int)
    if not feasible(p, profile, tol_cents):
        return out
    s = np.sort(np.asarray(profile.open_string_hz, dtype=float))
    tol = 2.0 ** (-tol_cents / 1200.0)
    for rank, i in enumerate(np.argsort(p)):
        out[i] = rank
        # use the lowest unused string at or below the pitch: rank-th string is minimal
        assert p[i] >= s[rank] * tol
    return out
