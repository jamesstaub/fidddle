"""Table lookup for the Gaussian peak kernel exp(-z^2 / 2), used in efficient mode (Config.kernel_table).

The same table and the same arithmetic are in the C++ core (`GaussTable`), so efficient mode agrees with this reference note for
note. The table covers z^2 up to 25 (5 sigma) in 4096 steps with linear interpolation: the error is below 2e-6 inside and the kernel is
taken as 0 beyond 5 sigma (below 4e-6).
"""
import numpy as np

TABLE_SIZE = 4096
U_MAX = 25.0
_SCALE = TABLE_SIZE / U_MAX
_T = np.exp(-0.5 * np.arange(TABLE_SIZE + 2) * (U_MAX / TABLE_SIZE))


def gauss(z2, table):
    """exp(-0.5 * z2) for z2 >= 0: exact, or from the table (0 beyond U_MAX)."""
    z2 = np.asarray(z2, dtype=float)
    if not table:
        return np.exp(-0.5 * z2)
    p = z2 * _SCALE
    i = np.minimum(p.astype(np.int64), TABLE_SIZE)
    v = _T[i] + (_T[i + 1] - _T[i]) * (p - i)
    return np.where(z2 < U_MAX, v, 0.0)
