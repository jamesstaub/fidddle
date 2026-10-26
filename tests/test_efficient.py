import json
import math
import shutil
import subprocess
from pathlib import Path

import numpy as np
import pytest
import soundfile as sf

from fidddle.analyzer import Analyzer
from fidddle.calibrate import Calibrator
from fidddle.kernel import U_MAX, gauss
from fidddle.profile import Calibration, DetectorConfig
from fidddle.salience import Candidate, pick_candidates
from fidddle.synth import Note, render

ROOT = Path(__file__).resolve().parent.parent
CLI = ROOT / "core" / "build" / "fidddle_cli"
SR = 44100.0


def test_full_mode_is_the_default_and_keeps_the_reference_time_base():
    cfg = DetectorConfig.for_instrument("cello", SR)
    assert cfg.quality == "full" and cfg.hop_size == 256 and cfg.grid_step_cents == 5.0 and not cfg.kernel_table
    assert [cfg.frames(n) for n in (6, 4, 14, 26, 28, 36, 80, 88, 12)] == [6, 4, 14, 26, 28, 36, 80, 88, 12]      # unchanged at hop 256
    assert cfg.per_frame(0.3) == 0.3 and cfg.noise_update_hops == 1 and cfg.allow_calibration


def test_time_base_conversion_keeps_the_durations():
    cfg = DetectorConfig.for_instrument("cello", SR, quality="efficient")
    assert cfg.hop_size == 512
    assert [cfg.frames(n, 2) for n in (6, 4, 14, 26, 28, 36, 80, 88, 12)] == [3, 2, 7, 13, 14, 18, 40, 44, 6]
    assert cfg.frames(2, 1) == 1 and cfg.frames(9, 4) == 4                                  # lower limits
    a = 0.3                                                                                 # two small hops decay as much as one large hop
    assert (1 - cfg.per_frame(a)) == pytest.approx((1 - a) ** 2)


def test_efficient_preset_values_and_order():
    c = DetectorConfig.for_instrument("guitar", SR, quality="efficient")
    assert (c.hop_size, c.grid_step_cents, c.max_candidates, c.max_fit_iterations) == (512, 10.0, 16, 1)
    assert c.noise_update_hops == 4 and c.kernel_table and not c.string_id and not c.allow_calibration
    assert c.max_voices == 6 and c.attack_min_db == 8.0 and c.dup_extra_gain == 0.0          # the voice count and the instrument's tuning stay
    c2 = DetectorConfig.for_instrument("cello", SR, quality="efficient", max_candidates=24)  # explicit overrides win over the preset
    assert c2.max_candidates == 24
    with pytest.raises(ValueError):
        DetectorConfig.for_instrument("cello", SR, quality="turbo")


def test_gaussian_table_is_accurate():
    z2 = np.linspace(0, U_MAX - 1e-9, 20001)
    assert np.max(np.abs(gauss(z2, True) - np.exp(-0.5 * z2))) < 2e-6
    assert np.all(gauss(np.array([U_MAX, 30.0, 100.0]), True) == 0.0)
    assert np.array_equal(gauss(z2, False), np.exp(-0.5 * z2))


def test_candidate_separation_is_at_least_25_cents_on_any_grid():
    class Map:
        midi = np.arange(60.0, 61.0, 0.10)                    # a 10-cent grid
    S = np.zeros(len(Map.midi))
    S[3], S[5] = 1.0, 0.9                                      # two peaks 20 cents apart
    cfg = DetectorConfig.for_instrument("cello", SR, quality="efficient")
    out = pick_candidates(Map, S, np.zeros_like(S), np.zeros_like(S), np.zeros_like(S), cfg)
    assert len(out) == 1
    S[7] = 0.8                                                  # 40 cents from the first: allowed
    assert len(pick_candidates(Map, S, np.zeros_like(S), np.zeros_like(S), np.zeros_like(S), cfg)) == 2


def _notes(az):
    return sorted((e.midi_note, e.deliver_samples) for e in az.events if e.kind == "on")


def test_efficient_mode_finds_the_same_notes_as_full():
    notes = [Note(48, 0.3, 2.2, "bowed"), Note(55, 1.0, 2.6, "bowed"), Note(64, 2.2, 3.4, "bowed")]
    x = render(notes, SR, 4.0, seed=1)
    found = {}
    for q in ("full", "efficient"):
        az = Analyzer(DetectorConfig.for_instrument("cello", SR, quality=q))
        az.run(x, track=True)
        found[q] = _notes(az)
    assert [m for m, _ in found["full"]] == [m for m, _ in found["efficient"]] == [48, 55, 64]
    for (_, tf), (_, te) in zip(found["full"], found["efficient"]):
        assert -0.005 * SR <= te - tf <= 0.03 * SR          # later by at most about a hop and a half


def test_calibration_is_made_in_full_mode_and_used_in_efficient_mode():
    eff = DetectorConfig.for_instrument("guitar", SR, quality="efficient")
    with pytest.raises(ValueError):
        Calibrator(eff, 8192)
    cal = Calibration.empty(6)
    cal.captured = [True] * 6
    cal.B = [1e-4] * 6
    eff.calibration = cal
    assert eff.inharm_B(np.array([196.0]))[0] == pytest.approx(1e-4)


@pytest.mark.skipif(not CLI.exists(), reason="C++ core not built")
@pytest.mark.parametrize("profile", ["cello", "guitar"])
def test_cpp_efficient_mode_gives_the_same_events(tmp_path, profile):
    notes = [Note(52, 0.3, 2.0, "plucked", tau0=1.2), Note(59, 0.9, 2.4, "plucked", tau0=1.2), Note(64, 1.6, 2.8, "plucked", tau0=1.2)]
    wav = tmp_path / "x.wav"
    sf.write(wav, render(notes, SR, 3.4, seed=2), 44100, subtype="PCM_16")
    x, _ = sf.read(wav)
    az = Analyzer(DetectorConfig.for_instrument(profile, SR, quality="efficient"))
    az.run(x, track=True)
    py = [(e.kind, e.track_id, e.midi_note, e.deliver_samples) for e in az.events if e.kind in ("on", "off")]
    out = subprocess.run([str(CLI), str(wav), "--profile", profile, "--efficient"], capture_output=True, text=True, check=True).stdout.splitlines()
    cpp = [(j["ev"], j["id"], j["midi"], j["deliver"]) for j in (json.loads(l) for l in out if l.startswith("{")) if j.get("ev") in ("on", "off")]
    assert py == cpp and len(py) >= 4
