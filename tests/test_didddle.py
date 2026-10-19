import numpy as np

from didddle.config import SeparatorConfig
from didddle.estimate import hann_kernel
from didddle.f0 import note_f0
from didddle.metrics import si_sdr
from didddle.separate import Separator
from didddle.stft import Stft
from fidddle.profile import InstrumentProfile
from fidddle.synth import Note, midi_hz

SR = 48000


def tone(f, n, rng, h_max=20):
    t = np.arange(n) / SR
    return sum(h ** -1.0 * np.sin(2 * np.pi * f * h * t + rng.uniform(0, 6.28)) for h in range(1, h_max + 1))


def cfg_cello(**kw):
    return SeparatorConfig.from_profile(InstrumentProfile.cello(), SR, **kw)


def test_stft_round_trip_is_exact():
    x = np.random.default_rng(0).standard_normal(10007)
    st = Stft(2048, 512)
    assert np.allclose(st.synthesize(st.analyze(x), len(x)), x, atol=1e-12)


def test_hann_kernel_peak_and_nulls():
    n = 4096
    assert abs(hann_kernel(0.0, n) - n / 2) < 1e-9
    assert abs(hann_kernel(2.0, n)) < 1e-6      # first null of the Hann main lobe


def test_window_size_follows_profile():
    assert cfg_cello().n_fft == 4096                                    # 4 * 48000 / 60 -> 4096
    assert SeparatorConfig.from_profile(InstrumentProfile.bass(), SR).n_fft == 8192


def test_outputs_are_complementary_for_any_f0():
    rng = np.random.default_rng(1)
    x = tone(110.0, SR, rng) * 0.1 + rng.standard_normal(SR) * 0.01
    for method in ("ls", "mask"):
        sep = Separator(cfg_cello(method=method))
        c = sep.centers(len(x))
        f0 = np.full((3, len(c)), np.nan)
        f0[0] = 123.0                       # wrong pitch, a second voice that is silent half the time
        f0[1, : len(c) // 2] = 200.0
        voices, res = sep.process(x, f0)
        assert np.max(np.abs(voices.sum(0) + res - x)) < 1e-10


def test_unrelated_voices_separate():
    rng = np.random.default_rng(2)
    n = SR
    a, b = tone(130.81, n, rng), tone(130.81 * 2 ** (4 / 12), n, rng)    # major third
    sep = Separator(cfg_cello())
    c = sep.centers(n)
    f0 = np.stack([np.full(len(c), 130.81), np.full(len(c), 130.81 * 2 ** (4 / 12))])
    voices, _ = sep.process(a + b, f0)
    mid = slice(SR // 4, 3 * SR // 4)
    assert si_sdr(voices[0][mid], a[mid]) > 12 and si_sdr(voices[1][mid], b[mid]) > 12   # 5th partial of a sits on 4th of b


def test_octave_dyad_gains_on_average():
    """Every upper partial sits on a lower one, so the split rests on envelope interpolation and varies a lot
    with the random partial phases/levels: assert only a modest mean gain over leaving the mixture alone."""
    gains = []
    for seed in range(4):
        rng = np.random.default_rng(seed)
        a, b = tone(130.81, SR, rng, 40), tone(261.62, SR, rng, 40)
        sep = Separator(cfg_cello())
        c = sep.centers(SR)
        f0 = np.stack([np.full(len(c), 130.81), np.full(len(c), 261.62)])
        voices, _ = sep.process(a + b, f0)
        mid = slice(SR // 4, 3 * SR // 4)
        gains += [si_sdr(v[mid], s[mid]) - si_sdr((a + b)[mid], s[mid]) for v, s in zip(voices, (a, b))]
    assert np.mean(gains) > 1.0


def test_note_f0_matches_nominal_pitch_and_glide():
    n = 3 * SR
    f = note_f0(Note(48, 0.5, 2.0, "plucked"), SR, n)
    assert np.isnan(f[0]) and abs(f[SR] - midi_hz(48)) < 1e-9
    g = note_f0(Note(48, 0.5, 2.0, "plucked", glide_to=50), SR, n)
    assert abs(g[int(2.0 * SR) - 1] / midi_hz(50) - 1) < 1e-3


# ---- shaping, spans, real clips -------------------------------------------------------------------

from pathlib import Path

import pytest
import soundfile as sf

from didddle.f0 import DetectorRun, run_detector, spans_from_run, split_notes, tracks_from_run
from fidddle.profile import DetectorConfig


def test_gate_removes_pre_echo_and_keeps_outputs_complementary():
    rng = np.random.default_rng(4)
    n = 2 * SR
    x = np.zeros(n)
    x[SR:] = tone(196.0, n - SR, rng)             # note starts at 1 s
    sep = Separator(cfg_cello(transient_ms=0.0))
    c = sep.centers(n)
    f0 = np.where(c >= SR - 2048, 196.0, np.nan)[None]   # frames partly covering the note carry its pitch
    ungated, _ = sep.process(x, f0)
    gated, res = sep.process(x, f0, [[(SR, n)]])
    assert np.max(np.abs(ungated[0][: SR - 2 * 2048])) < 1e-6
    assert np.max(np.abs(ungated[0][SR - 2000: SR - 100])) > 1e-3     # the stationary fit smears backwards ...
    assert np.max(np.abs(gated[0][: SR - 10])) < 1e-12                 # ... and the gate removes it
    assert np.max(np.abs(gated.sum(0) + res - x)) < 1e-12


def test_attack_goes_to_the_starting_voice():
    rng = np.random.default_rng(5)
    n = SR
    x = np.zeros(n)
    x[SR // 2:] = tone(196.0, n - SR // 2, rng) * 0.2
    click = rng.standard_normal(480) * 0.5            # 10 ms broadband attack at the onset
    x[SR // 2: SR // 2 + 480] += click
    c0 = cfg_cello(transient_ms=0.0)
    c1 = cfg_cello(transient_ms=80.0)
    out = []
    for cfg in (c0, c1):
        sep = Separator(cfg)
        c = sep.centers(n)
        v, _ = sep.process(x, np.where(c >= SR // 2 - 2048, 196.0, np.nan)[None], [[(SR // 2, n)]])
        out.append(v[0][SR // 2: SR // 2 + 480])
    assert np.sum((out[1] - (x[SR // 2: SR // 2 + 480])) ** 2) < 0.2 * np.sum((out[0] - x[SR // 2: SR // 2 + 480]) ** 2)


def fake_run(act, spans, sr=48000.0):
    return DetectorRun(np.arange(10, dtype=float) * 256 + 8192, 4096.0, act, spans, sr)


def test_spans_respect_what_the_detector_knew():
    sr = 48000.0
    run = fake_run([[(0, 1, 100.0)]], {1: [(sr, 1.1 * sr, 2 * sr, 2.2 * sr)]})
    assert spans_from_run(run) == [[(sr, 2 * sr)]]
    # lead opens early; a short horizon cannot open before the note was delivered, nor close before its note-off
    (a, b), = spans_from_run(run, 0.05, 0.04)[0]
    assert a == pytest.approx(max(sr - 0.04 * sr, 1.1 * sr - 0.05 * sr)) and b == pytest.approx(2.2 * sr - 0.05 * sr) or b == 2 * sr
    assert spans_from_run(run, np.inf, 0.04)[0][0][0] == pytest.approx(sr - 0.04 * sr)


def test_split_notes_separates_notes_of_one_slot():
    c = np.arange(0, 100000, 1024)
    f0 = np.where(c < 90000, 200.0, np.nan)[None]
    rows, sp = split_notes(f0, [[(10000, 30000), (50000, 80000)]], c, margin=2048)
    assert len(rows) == 2 and sp == [[(10000, 30000)], [(50000, 80000)]]
    assert not (np.isfinite(rows[0]) & np.isfinite(rows[1])).any()


CLIPS = Path(__file__).resolve().parent.parent / "data" / "channels"


@pytest.mark.skipif(not (CLIPS / "pizz-high-register_2.0.wav").exists(), reason="local corpus not present")
@pytest.mark.parametrize("clip,gain_db", [("pizz-high-register_2", 1.5), ("jete-bounces", 1.5)])
def test_attack_routing_recovers_real_plucks_and_bounces(clip, gain_db):
    """Pizzicato/jete keep 35-50% of their energy in the first 40 ms of each note; the voices of the
    isolated clip rebuild it much better once voices are gated and attacks routed."""
    x, sr = sf.read(CLIPS / f"{clip}.0.wav")
    x = x[: int(6 * sr)]
    run = run_detector(x, DetectorConfig.for_instrument("cello", float(sr)))
    got = {}
    for tag in ("off", "full"):
        sep = Separator(SeparatorConfig.from_profile(InstrumentProfile.cello(), sr))
        c = sep.centers(len(x))
        f0 = tracks_from_run(run, c, np.inf, sep.cfg.n_fft // 2)
        spans = spans_from_run(run, np.inf, sep.cfg.onset_lead_ms / 1000)
        keep = np.isfinite(f0).any(axis=1)
        v, res = sep.process(x, f0[keep], [spans[k] for k in np.flatnonzero(keep)] if tag == "full" else None)
        assert np.max(np.abs(v.sum(0) + res - x)) < 1e-12
        got[tag] = si_sdr(v.sum(0), x)
    assert got["full"] - got["off"] > gain_db, got
