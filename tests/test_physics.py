"""Measurement primitives of didddle/physics.py on synthetic strings (known B, known phases), plus a check on the real
OrchideaSOL library when it is present (spec §17)."""
from pathlib import Path

import numpy as np
import pytest

from didddle import physics as P

SR = 44100.0


def stiff_string(f0, B, n, phases, H=20):
    t = np.arange(n) / SR
    return sum(np.sin(2 * np.pi * f0 * h * np.sqrt(1 + B * h * h) * t + phases[h - 1]) / h for h in range(1, H + 1))


def test_stiffness_recovers_B():
    rng = np.random.default_rng(0)
    n = 8192
    for B in (0.0, 1e-4, 3e-4):
        x = stiff_string(110.0, B, n + 100, rng.uniform(0, 6.28, 20))
        r = P.stiffness(P.spectrum(x, 0, n), SR / n, 110.0)
        assert r is not None and abs(r["B"] - B) < 3e-6 and abs(r["f0"] / 110.0 - 1) < 1e-3


def test_complex_amplitudes_recover_phase_at_the_frame_centre():
    n = 8192
    f0 = 110.0
    ph = np.random.default_rng(1).uniform(0, 6.28, 12)
    x = stiff_string(f0, 0.0, n + 100, ph, H=12)
    X = P.spectrum(x, 0, n)
    nu = f0 * np.arange(1, 13) / (SR / n)
    c = P.complex_amplitudes(X, nu, n)
    # sin(w m + p) has phase p - pi/2 at m = 0; at the centre m = n/2 it has advanced by w n / 2
    want = ph - np.pi / 2 + 2 * np.pi * f0 * np.arange(1, 13) * (n / 2) / SR
    got = P.centre_phase(c, nu)
    assert np.max(np.abs(np.angle(np.exp(1j * (got - want))))) < 0.02
    assert np.allclose(np.abs(c), 1.0 / np.arange(1, 13), rtol=0.02)


LIB = Path(__file__).resolve().parent.parent / "data" / "_OrchideaSOL2020_release"


@pytest.mark.skipif(not LIB.exists(), reason="OrchideaSOL library not present")
def test_real_bowed_cello_is_an_exact_harmonic_series():
    from tools.eval_physics import measure_note
    from tools.orchidea import catalog
    s = [s for s in catalog.select("cello", ["ordinario"], ["mf"]) if s.midi == 50][0]
    rows = measure_note(s)
    assert len(rows) >= 3
    assert abs(np.median([r["B"] for r in rows])) < 3e-6                      # mode-locked: no stiffness stretch
    assert np.median([r["rms_harm"] for r in rows]) < 4.0                      # exact series to a few cents
