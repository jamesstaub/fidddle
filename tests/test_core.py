import numpy as np
import pytest

from fidddle.profile import DetectorConfig, InstrumentProfile
from fidddle.frontend import dc_block, frame_ends
from fidddle.analyzer import Analyzer
from fidddle.synth import chord, render
from fidddle.evaluate import candidate_recall


def test_long_window_derived_from_profile():
    assert DetectorConfig(sample_rate=44100).derived_long_fft() == 8192
    assert DetectorConfig(sample_rate=48000).derived_long_fft() == 8192
    assert DetectorConfig(sample_rate=96000).derived_long_fft() == 16384


def test_cello_profile():
    p = InstrumentProfile.cello()
    assert p.string_count == 4
    assert p.min_frequency_hz < p.open_string_hz[0]


def test_dc_block_removes_offset():
    x = np.ones(48000) * 0.5
    y = dc_block(x, 48000, 30.0)
    assert abs(y[-1]) < 1e-3


def test_frames_wait_for_full_window_and_share_end():
    ends = frame_ends(20000, 8192, 256)
    assert ends[0] == 8192
    assert np.all(np.diff(ends) == 256)
    assert ends[-1] <= 20000


@pytest.mark.parametrize("midis", [[36], [57], [48, 55], [36, 43, 50, 57]])
@pytest.mark.parametrize("kind", ["bowed", "plucked"])
def test_candidate_recall_synthetic(midis, kind):
    sr = 44100.0
    cfg = DetectorConfig(sample_rate=sr)
    notes = chord(midis, kind=kind, dur_s=2.5)
    x = render(notes, sr, 3.0, seed=3)
    az = Analyzer(cfg)
    frames = az.run(x)
    r, total = candidate_recall(frames, notes, sr, az.n_long)
    assert total > 50
    assert r[50] >= 0.97


def test_silence_yields_few_strong_candidates():
    cfg = DetectorConfig(sample_rate=44100.0)
    rng = np.random.default_rng(0)
    x = rng.standard_normal(44100 * 2) * 1e-4
    frames = Analyzer(cfg).run(x)
    strong = [sum(c.salience > 3.0 for c in f.candidates) for f in frames[len(frames) // 2:]]
    assert np.mean(strong) < 1.0
