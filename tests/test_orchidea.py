import numpy as np
import pytest
import soundfile as sf
from tools.orchidea import catalog, mix

SR = 44100


def fake_sound(tmp_path, name, midi, dur=2.0, technique="ordinario", dynamic="mf"):
    t = np.arange(int(dur * SR)) / SR
    x = 0.2 * np.sin(2 * np.pi * 440 * 2 ** ((midi - 69) / 12) * t) * np.minimum(1, t / 0.02)
    p = tmp_path / name
    sf.write(p, x, SR)
    return catalog.Sound(p, "cello", technique, midi, dynamic, 3, "N")


def test_parse_names():
    from pathlib import Path
    s = catalog.parse(Path("Vc-ord-A#2-ff-3c-N.wav"), "cello", "ordinario")
    assert (s.midi, s.dynamic, s.string, s.variant) == (46, "ff", 3, "N")
    assert catalog.parse(Path("Vc-ord-A3-ff-4c-N.wav"), "cello", "ordinario").midi == 57
    assert catalog.parse(Path("Vc-behind_bridge-N-N-1c-N.wav"), "cello", "behind_the_bridge") is None
    assert catalog.parse(Path("Vc-pizz_sec-C2-mf-3c-N.wav"), "cello", "pizzicato_secco").kind == "plucked"


def test_render_stems_sum_to_mix_and_truth(tmp_path):
    a, b = fake_sound(tmp_path, "a.wav", 48), fake_sound(tmp_path, "b.wav", 55)
    m, stems, notes, gain = mix.render([mix.Event(a, 0.5, 1.0), mix.Event(b, 1.0, None)], SR, 4.0)
    assert np.allclose(stems.sum(0), m) and gain == 1.0
    assert notes[0]["midi"] == 48 and notes[0]["onset"] == 0.5 and notes[0]["offset"] < 1.5 + 1e-6
    assert abs(stems[0][int(1.7 * SR):]).max() == 0                      # cut + fade finished before 1.6 s
    assert abs(stems[1][:int(0.99 * SR)]).max() == 0 and abs(stems[1][int(1.5 * SR)]).max() > 0


def test_clipping_scene_keeps_stem_relationships(tmp_path):
    a = fake_sound(tmp_path, "a.wav", 48)
    m, stems, _, gain = mix.render([mix.Event(a, 0.0, None, 20.0), mix.Event(a, 0.0, None, 20.0)], SR, 3.0)
    assert gain < 1 and abs(m).max() <= 0.951 and np.allclose(stems.sum(0), m)


@pytest.mark.skipif(not catalog.LIB.exists(), reason="OrchideaSOL not downloaded")
def test_scene_kinds_on_real_library():
    pool = catalog.select("cello")
    assert len(pool) > 500
    for kind in ("chords", "intervals", "strum", "lines"):
        ev, dur = mix.scene(kind, pool, np.random.default_rng(0))
        m, stems, notes, _ = mix.render(ev, SR, dur)
        assert len(notes) == len(stems) and np.allclose(stems.sum(0), m) and abs(m).max() > 0.01


@pytest.mark.skipif(not catalog.INSTRUMENT_PATHS["guitar"].exists(), reason="OrchideaSOL guitar not downloaded")
def test_guitar_is_indexed_and_plucked():
    g = catalog.select("guitar")
    assert len(g) > 100 and all(s.kind == "plucked" for s in g)
    assert {s.technique for s in g} >= {"ordinario", "pizzicato_bartok"}
    ev, dur = mix.scene("chords", g, np.random.default_rng(0), voices=6)
    m, stems, notes, _ = mix.render(ev, SR, dur)
    assert len(notes) == 18 and notes[0]["kind"] == "plucked" and np.allclose(stems.sum(0), m)
