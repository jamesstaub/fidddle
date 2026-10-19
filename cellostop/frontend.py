"""Input conditioning and frame scheduling (spec §3, §4)."""
import numpy as np
from scipy.signal import lfilter


def dc_block(x, sample_rate, cutoff_hz):
    """y[n] = a (y[n-1] + x[n] - x[n-1]),  a = 1 / (1 + 2 pi fc / Fs)  (§3.2)."""
    a = 1.0 / (1.0 + 2.0 * np.pi * cutoff_hz / sample_rate)
    return lfilter([a, -a], [1.0, -a], x)


def frame_ends(n_samples, long_size, hop):
    """Sample index (exclusive end) of each analysis frame.

    Causal, and the first frame waits until the longest window is full (§4.3).
    Both windows end at the same newest sample (§4.2).
    """
    return np.arange(long_size, n_samples + 1, hop)
