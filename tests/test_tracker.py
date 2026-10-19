import numpy as np

from fidddle.profile import DetectorConfig
from fidddle.analyzer import Analyzer
from fidddle.synth import Note, render
from fidddle.tracker import ACTIVE


def run(notes, dur, seed=1, **kw):
    sr = 44100.0
    cfg = DetectorConfig(sample_rate=sr, **kw)
    x = render(notes, sr, dur, seed=seed)
    az = Analyzer(cfg)
    frames = az.run(x, track=True)
    return az.events, frames, sr


def ons(events):
    return [e for e in events if e.kind == "on"]


def test_sequential_notes_detected_with_bounded_latency():
    notes = [Note(m, 0.3 + 0.7 * i, 0.9 + 0.7 * i) for i, m in enumerate([40, 45, 52, 57])]
    ev, _, sr = run(notes, 3.8)
    on = ons(ev)
    assert [e.midi_note for e in on] == [40, 45, 52, 57]
    for e, n in zip(on, notes):
        assert 0.0 <= e.deliver_samples / sr - n.onset_s <= 0.15      # within the 40-100+ ms target band
        assert abs(e.onset_est_samples / sr - n.onset_s) < 0.1       # estimated physical onset is close
    offs = [e for e in ev if e.kind == "off"]
    assert len(offs) == len(on)                                       # every note is closed


def test_repeated_same_pitch_pluck_retriggers():
    notes = [Note(50, 0.3 + 0.5 * i, 0.3 + 0.5 * i + 0.45, "plucked") for i in range(6)]
    ev, _, _ = run(notes, 4.0)
    assert len(ons(ev)) == 6


def test_chord_has_distinct_tracks_and_ids():
    notes = [Note(m, 0.3 + 0.25 * i, 3.0, "plucked") for i, m in enumerate([36, 43, 50, 57])]
    ev, frames, _ = run(notes, 3.6)
    on = ons(ev)
    assert sorted(e.midi_note for e in on)[:4] == [36, 43, 50, 57] or {36, 43, 50, 57} <= {e.midi_note for e in on}
    assert len({e.track_id for e in on}) == len(on)                   # ids are unique and persistent


def test_never_more_active_tracks_than_limit():
    notes = [Note(m, 0.3, 2.5, "plucked") for m in (36, 43, 50, 57, 64)]
    _, frames, _ = run(notes, 3.0, max_voices=3)
    assert max(sum(s.state == ACTIVE for s in f.tracks) for f in frames) <= 3


def test_silence_produces_no_events():
    cfg = DetectorConfig(sample_rate=44100.0)
    x = np.random.default_rng(0).standard_normal(44100 * 3) * 1e-4
    az = Analyzer(cfg)
    az.run(x, track=True)
    assert az.events == []


def test_quiet_tone_below_level_gate_is_ignored():
    ev, _, _ = run([Note(48, 0.3, 2.5)], 3.0)
    assert len(ons(ev)) == 1
    sr = 44100.0
    cfg = DetectorConfig(sample_rate=sr, min_level_dbfs=-10.0)  # loud gate: the same note is too quiet
    x = render([Note(48, 0.3, 2.5)], sr, 3.0, seed=1)
    az = Analyzer(cfg)
    az.run(x, track=True)
    assert [e for e in az.events if e.kind == "on"] == []


def test_plucked_profile_ignores_a_voice_that_appears_without_an_attack():
    # a plucked E2 rings; a quieter C3 swells in underneath over 0.8 s. Nothing is plucked, so the plucked guitar profile
    # does not report it; with the requirement switched off it is reported.
    sr = 44100.0
    ring = render([Note(40, 0.3, 4.0, "plucked", B=1e-4, tau0=6.0)], sr, 4.5, seed=1)
    swell = render([Note(48, 1.2, 4.0, "bowed", B=1e-4)], sr, 4.5, seed=2, snr_db=None)
    ramp = np.clip((np.arange(len(swell)) / sr - 1.2) / 0.8, 0.0, 1.0)
    x = ring + 0.5 * swell * ramp

    def notes(**kw):
        cfg = DetectorConfig.for_instrument("guitar", sr, **kw)
        az = Analyzer(cfg)
        az.run(x, track=True)
        return sorted(e.midi_note for e in az.events if e.kind == "on")
    assert notes() == [40]
    assert notes(attack_min_db=0.0) == [40, 48]


def test_note_in_the_first_moments_of_audio_has_an_attack():
    # the bass analysis window is 372 ms; a pluck at 0.1 s happens before the first analysis frame exists
    sr = 44100.0
    cfg = DetectorConfig.for_instrument("bass", sr)
    x = render([Note(28, 0.1, 3.0, "plucked", B=5e-5, tau0=2.5)], sr, 3.5, seed=1)
    az = Analyzer(cfg)
    az.run(x, track=True)
    assert [e.midi_note for e in az.events if e.kind == "on"] == [28]
