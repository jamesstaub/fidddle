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
    assert cfg.inharm_B(np.array([150.0]))[0] == pytest.approx(1e-4 * (150.0 / 146.83) ** 2, rel=0.01)       # uncaptured D string: profile B


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
