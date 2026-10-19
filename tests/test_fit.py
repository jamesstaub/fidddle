import numpy as np
import pytest

from cellostop.profile import DetectorConfig, InstrumentProfile
from cellostop.analyzer import Analyzer
from cellostop.strings import feasible, assign_strings
from cellostop.synth import chord, render
from cellostop.evaluate import fit_scores
from cellostop.spectral import spectral_peaks


def test_string_feasibility():
    p = InstrumentProfile.cello()
    assert feasible([65.41, 98.0, 146.83, 220.0], p)
    assert feasible([130.0, 261.0], p)
    assert not feasible([70.0, 71.0], p)               # both below G2: only the C string fits
    assert not feasible([100.0] * 5, p)                # more notes than strings
    assert list(assign_strings([220.0, 70.0], p)) == [1, 0]


def test_peak_location_uses_raw_magnitude_not_plateau():
    # A clipped (flat-topped) W must not shift the located peak.
    n = 64
    M = np.exp(-0.5 * ((np.arange(n) - 20.3) / 1.2) ** 2) + 1e-6
    W = np.minimum(M * 100, 12.0)           # plateau around the maximum
    pf, pa = spectral_peaks(M, W, 1.0, 2.0)
    assert len(pf) == 1 and abs(pf[0] - 20.3) < 0.1


@pytest.mark.parametrize("midis", [[36], [57], [48, 52, 55], [50, 51], [36, 43]])
def test_fit_recovers_pitches(midis):
    sr = 44100.0
    cfg = DetectorConfig(sample_rate=sr)
    notes = chord(midis, dur_s=2.5)
    x = render(notes, sr, 3.0, seed=2)
    az = Analyzer(cfg)
    frames = az.run(x, fit=True, fit_stride=5)
    s = fit_scores(frames, notes, sr, az.n_long)
    assert s["frames"] > 20
    assert s["P"] >= 0.9 and s["R"] >= 0.9


def test_fit_silence_has_no_voices():
    cfg = DetectorConfig(sample_rate=44100.0)
    x = np.random.default_rng(0).standard_normal(44100 * 2) * 1e-4
    frames = Analyzer(cfg).run(x, fit=True, fit_stride=5)
    voices = [len(f.fit.voices) for f in frames if f.fit is not None][-10:]
    assert max(voices) == 0


def test_voice_count_never_exceeds_limit():
    sr = 44100.0
    cfg = DetectorConfig(sample_rate=sr, max_voices=2)
    notes = chord([36, 43, 50, 57], dur_s=2.0)
    x = render(notes, sr, 2.5, seed=1)
    frames = Analyzer(cfg).run(x, fit=True, fit_stride=8)
    assert max(len(f.fit.voices) for f in frames if f.fit is not None) <= 2
