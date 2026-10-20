"""The stiffness measurement of tools/eval_inharmonicity.py on synthetic strings with known B (spec §17.10)."""
import numpy as np

from fidddle.synth import Note, render
from tools.eval_inharmonicity import measure

SR = 44100.0


def measured_B(kind, B, midi=50):
    x = render([Note(midi, 0.3, 2.7, kind, 0.0 if kind == "plucked" else 8.0, B=B, tau0=2.5)], SR, 3.2, snr_db=40.0, seed=3)
    rows = measure(x, SR)
    assert len(rows) > 50
    return np.median(rows[:, 1]), np.median(rows[:, 3]), np.median(rows[:, 4])   # B, rms stiff (cents), rms exact-harmonic


def test_recovers_B_of_a_stiff_string():
    B, rms_stiff, rms_harm = measured_B("plucked", 2e-4)
    assert abs(B / 2e-4 - 1) < 0.03
    assert rms_stiff < 1.0 and rms_harm > 10.0      # the stiff model explains the partials, the exact series does not


def test_a_locked_bowed_string_measures_zero():
    B, rms_stiff, rms_harm = measured_B("bowed", 0.0)
    assert abs(B) < 2e-6
    assert rms_harm < 1.0
