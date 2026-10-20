import numpy as np
import pytest

from fidddle.profile import DetectorConfig, InstrumentProfile
from fidddle.analyzer import Analyzer
from fidddle.synth import Note, render


@pytest.mark.parametrize("name,voices,fft", [("bass", 4, 16384), ("cello", 4, 8192), ("viola", 4, 4096),
                                              ("violin", 4, 4096), ("guitar", 6, 8192)])
def test_profile_table(name, voices, fft):
    cfg = DetectorConfig.for_instrument(name, 44100.0)
    assert cfg.max_voices == voices == cfg.profile.default_voices
    assert cfg.derived_long_fft() == fft
    assert cfg.profile.min_frequency_hz < cfg.profile.open_string_hz[0]
    assert cfg.profile.max_frequency_hz > cfg.profile.open_string_hz[-1] * 2
    assert cfg.profile.string_count >= cfg.max_voices


def test_profile_enum_order_matches_max_attribute():
    assert InstrumentProfile.ORDER == ("bass", "cello", "viola", "violin", "guitar")
    assert InstrumentProfile.by_index(4).name == "guitar"


def test_fit_band_follows_max_pitch():
    assert DetectorConfig.for_instrument("cello", 44100.0).derived_fit_band() == 4000.0
    assert DetectorConfig.for_instrument("violin", 44100.0).derived_fit_band() == pytest.approx(8400.0)
    assert DetectorConfig.for_instrument("violin", 12000.0).derived_fit_band() == pytest.approx(5400.0)  # capped at 0.45 fs


def test_overrides_win_over_profile():
    cfg = DetectorConfig.for_instrument("guitar", 44100.0, max_voices=3)
    assert cfg.max_voices == 3
    assert cfg.dup_extra_gain == 0.0          # guitar tuning stays


def _plucked(prof, midis, stagger=0.03):
    return [Note(m, 0.3 + stagger * i, 3.0, "plucked", B=prof.inharmonicity_B, tau0=2.5) for i, m in enumerate(midis)]


def test_guitar_six_string_chord_gives_six_notes():
    sr = 44100.0
    cfg = DetectorConfig.for_instrument("guitar", sr)
    notes = _plucked(cfg.profile, [40, 47, 52, 56, 59, 64])      # open E major
    x = render(notes, sr, 3.6, seed=1)
    az = Analyzer(cfg)
    az.run(x, track=True)
    ons = [e for e in az.events if e.kind == "on"]
    assert sorted(e.midi_note for e in ons) == [40, 47, 52, 56, 59, 64]       # no duplicates, no flicker
    onset = {n.midi: n.onset_s for n in notes}
    assert all(0.0 <= e.deliver_samples / sr - onset[e.midi_note] <= 0.25 for e in ons)
    assert {e.slot for e in ons} == set(range(6))


def test_violin_double_stop_and_high_register():
    sr = 44100.0
    cfg = DetectorConfig.for_instrument("violin", sr)
    notes = [Note(76, 0.3, 2.5, "bowed", 12.0), Note(93, 0.3, 2.5, "bowed", 12.0)]    # E5 + A6
    x = render(notes, sr, 3.0, seed=1)
    az = Analyzer(cfg)
    az.run(x, track=True)
    assert sorted(e.midi_note for e in az.events if e.kind == "on") == [76, 93]


def _soft_bowed(level_db):
    sr = 44100.0
    x = render([Note(50, 0.3, 2.0, "bowed")], sr, 2.6, snr_db=None, seed=0)
    return sr, x * 10 ** (level_db / 20) / np.abs(x).max() + np.random.default_rng(0).standard_normal(len(x)) * 10 ** (-100 / 20)


def test_quiet_bowed_note_counts_when_far_above_the_noise_floor():
    sr, x = _soft_bowed(-66.0)       # under the -58 dBFS level gate, but 30+ dB over a -100 dBFS noise floor
    for profile, expect in (("cello", 1), ("guitar", 0)):
        cfg = DetectorConfig.for_instrument(profile, sr)
        az = Analyzer(cfg)
        az.run(x, track=True)
        assert len([e for e in az.events if e.kind == "on"]) == expect, profile
    cfg = DetectorConfig.for_instrument("cello", sr)
    cfg.quiet_snr_db = 0.0
    az = Analyzer(cfg)
    az.run(x, track=True)
    assert not [e for e in az.events if e.kind == "on"]


def test_quiet_note_in_noise_stays_gated():
    sr, x = _soft_bowed(-66.0)
    x = x + np.random.default_rng(1).standard_normal(len(x)) * 10 ** (-66 / 20) * 0.5       # noise within 6 dB of the note
    az = Analyzer(DetectorConfig.for_instrument("cello", sr))
    az.run(x, track=True)
    assert not [e for e in az.events if e.kind == "on"]
