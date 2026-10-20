"""Which string played a note (spec §17.5): stiffness-based, for plucked instruments whose strings differ in B (guitar; later banjo,
mandolin, ...).

A stiff string has B proportional to f^2 along its length, so log(B / f^2) is nearly a constant of the string a pitch was played on.
The value for a note comes from a stiffness fit (see `didddle.physics.stiffness`) on long Hann frames about 0.2 s after the note starts;
the values of the strings come from their open-string notes (the calibration pass). The detector's own per-frame partial positions were
tried and are too noisy for this (chance level on single notes); the dedicated fit is what carries the information.

Offline prototype: `tools/eval_string_id.py`. Not used by the detector yet.
"""
import numpy as np


def classify(value, f_hz, centroids, open_hz, max_semitones=24):
    """-> (string index or -1, margin in log units). centroids: log(B / f^2) per string (None when unknown); strings that can sound
    f_hz are those whose open pitch is at or below it by at most max_semitones. The margin is the gap to the second-best string:
    a large margin is a trustworthy answer, a small one means the string is ambiguous."""
    best = []
    for s, (c, fo) in enumerate(zip(centroids, open_hz)):
        if c is None or not (0 <= 12 * np.log2(f_hz / fo) + 0.5 <= max_semitones):
            continue
        best.append((abs(value - c), s))
    if not best:
        return -1, 0.0
    best.sort()
    return best[0][1], (best[1][0] - best[0][0]) if len(best) > 1 else float("inf")
