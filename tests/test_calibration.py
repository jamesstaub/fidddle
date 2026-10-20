import numpy as np
import pytest

from fidddle.profile import Calibration, DetectorConfig
from fidddle.analyzer import Analyzer
from fidddle.calibrate import Calibrator
from fidddle.synth import Note, render
from fidddle.evaluate import fit_scores  # noqa: F401  (import check)

SR = 44100.0
TRUE_B = [3e-5, 5e-5, 8e-5, 2.5e-4, 1.5e-4, 1e-4]
TRUE_CENTS = [6, -8, 4, -5, 9, -3]


def open_string_recording(order=(0, 1, 2, 3, 4, 5), extra_chord=False):
    cfg = DetectorConfig.for_instrument("guitar", SR)
    notes, t = [], 0.4
    for s in order:
        f = cfg.profile.open_string_hz[s] * 2 ** (TRUE_CENTS[s] / 1200)
        notes.append(Note(69 + 12 * np.log2(f / 440.0), t, t + 2.4, "plucked", B=TRUE_B[s], tau0=2.5))
        t += 3.0
    if extra_chord:      # a strummed chord in the middle of the session must not contribute
        for i, m in enumerate((40, 47, 52, 56, 59, 64)):
            notes.append(Note(m, t + 0.03 * i, t + 2.0, "plucked", B=1e-4, tau0=2.5))
        t += 3.0
    return render(notes, SR, t + 0.5, seed=1)


def calibrate(x):
    az = Analyzer(DetectorConfig.for_instrument("guitar", SR))
    cal = Calibrator(az.cfg, az.n_long)
    az.run(x, track=True, calibrator=cal)
    return cal, cal.finalize()


@pytest.fixture(scope="module")
def session():
    """One full six-string open-string session, calibrated once and shared."""
    return calibrate(open_string_recording())


def test_recovers_per_string_inharmonicity_and_tuning(session):
    cal, res = session
    assert res is not None and all(res.captured)
    for s in range(6):
        assert res.B[s] == pytest.approx(TRUE_B[s], rel=0.03)
        assert res.cents[s] == pytest.approx(TRUE_CENTS[s], abs=0.3)
    assert len(res.weights) >= 6 and all(w > 0 for w in res.weights)


def test_string_order_does_not_matter():
    cal, res = calibrate(open_string_recording(order=(3, 0, 5)))            # any order, and not every string needed
    assert res.captured == [True, False, False, True, False, True]
    assert res.B[3] == pytest.approx(TRUE_B[3], rel=0.03)


def test_chords_in_the_session_are_ignored():
    cal, res = calibrate(open_string_recording(order=(1, 4), extra_chord=True))
    assert res.captured == [False, True, False, False, True, False]
    for s in (1, 4):
        assert res.B[s] == pytest.approx(TRUE_B[s], rel=0.05)      # the chord did not pull the estimates


def test_chords_alone_capture_nothing():
    notes = [Note(m, 0.3 + 0.03 * i, 3.0, "plucked", B=1e-4, tau0=2.5) for i, m in enumerate((40, 47, 52, 56, 59, 64))]
    cal, res = calibrate(render(notes, SR, 3.6, seed=1))
    assert res is None or not res.any_strings


def test_uncaptured_strings_keep_profile_defaults():
    res = Calibration.empty(6)
    res.captured[0], res.B[0] = True, TRUE_B[0]
    cfg = DetectorConfig.for_instrument("guitar", SR)
    cfg.calibration = res
    assert cfg.inharm_B(np.array([82.41]))[0] == pytest.approx(TRUE_B[0], rel=0.01)                           # the calibrated string
    assert cfg.inharm_B(np.array([100.0]))[0] == pytest.approx(TRUE_B[0] * (100.0 / 82.41) ** 2, rel=0.01)   # fretted on it: B ~ f^2
    assert cfg.inharm_B(np.array([150.0]))[0] == pytest.approx(cfg.profile.inharmonicity_B * (150.0 / 146.83) ** 2, rel=0.01)       # uncaptured D string: profile B


def test_calibration_list_round_trip(session):
    _, res = session
    back = Calibration.from_list(res.to_list())
    assert back == res
    assert Calibration.from_list([3.0, 1.0, 0.0]) is None           # unknown version


def test_calibration_improves_detection_with_mismatched_strings(session):
    _, res = session
    truth = DetectorConfig.for_instrument("guitar", SR)
    tc = Calibration.empty(6); tc.captured = [True] * 6; tc.B = list(TRUE_B)
    truth.calibration = tc
    notes = [Note(40, 0.3, 3.0, "plucked", B=float(truth.inharm_B(82.41)), tau0=2.5)]     # a single low E
    x = render(notes, SR, 3.5, seed=2)

    def count(cal):
        cfg = DetectorConfig.for_instrument("guitar", SR)
        cfg.calibration = cal
        az = Analyzer(cfg)
        az.run(x, track=True)
        return sum(e.kind == "on" for e in az.events)
    assert count(None) > 1            # profile B is wrong for this string: ghost octave/twelfth notes
    assert count(res) == 1


# ---- string identity (spec §17.5) ----------------------------------------------------------------------------------------

def _plucked_bank(midis, Bs, t0=0.4, gap=3.2, tau0=2.5):
    return [Note(m, t0 + gap * i, t0 + gap * i + gap - 0.3, "plucked", B=b, tau0=tau0) for i, (m, b) in enumerate(zip(midis, Bs))]


def test_calibration_list_roundtrip_with_string_values():
    c = Calibration.empty(6)
    c.captured = [True] * 6
    c.B = [1e-5, 2e-5, 6e-5, 2e-4, 1e-4, 4e-5]
    c.logb = [-21.0, -20.5, -19.6, -19.5, -20.6, -21.7]
    back = Calibration.from_list(c.to_list())
    assert back.logb == pytest.approx(c.logb)
    assert back.has_logb
    assert Calibration.from_list(Calibration.empty(6).to_list()).logb == [-99.0] * 6        # no values: the version-2 list


def test_string_of_a_stopped_note_is_named_from_its_stiffness():
    sr = 44100.0
    cfg = DetectorConfig.for_instrument("guitar", sr)
    opens = [40, 45, 50, 55, 59, 64]
    open_B = [1.5e-5, 3e-5, 1.2e-4, 3e-4, 1.5e-4, 5e-5]          # strings differ a lot, as on a real guitar
    az = Analyzer(cfg)
    cal = Calibrator(cfg, az.n_long)
    az.run(render(_plucked_bank(opens, open_B), sr, 0.4 + 3.2 * 6 + 0.5, seed=0), calibrator=cal)
    res = cal.finalize()
    assert res is not None and res.has_logb
    # G3 (55) played on the D string (index 2, fret 5): B follows the f^2 law along the string
    f_d, f = 146.83, 196.0
    x = render([Note(55, 0.3, 3.0, "plucked", B=open_B[2] * (f / f_d) ** 2, tau0=2.5)], sr, 3.6, seed=1)
    cfg2 = DetectorConfig.for_instrument("guitar", sr)
    cfg2.calibration = res
    az2 = Analyzer(cfg2)
    az2.run(x, track=True)
    ev = [e for e in az2.events if e.kind == "string"]
    assert len(ev) == 1 and ev[0].midi_note == 55
    assert ev[0].string == 2 and ev[0].margin > 0.3


def test_no_string_events_without_string_values():
    sr = 44100.0
    cfg = DetectorConfig.for_instrument("guitar", sr)
    x = render([Note(55, 0.3, 3.0, "plucked", B=1e-4, tau0=2.5)], sr, 3.6, seed=1)
    az = Analyzer(cfg)
    az.run(x, track=True)
    assert not [e for e in az.events if e.kind == "string"]
