import numpy as np
import pytest
from tools.bbcso import catalog, midi, scenes, states
from tools.bbcso.render import Track, analyse_track


def test_midi_roundtrip(tmp_path):
    notes = [midi.Note(48, 0.5, 1.25, 80), midi.Note(55, 0.5, 2.0, 100), midi.Note(48, 1.25, 1.5, 70)]
    midi.write_midi(str(tmp_path / "a.mid"), {"cello": notes})
    got = midi.read_midi(str(tmp_path / "a.mid"))["cello"]
    assert [(n.midi, n.velocity) for n in got] == [(48, 80), (55, 100), (48, 70)]
    for a, b in zip(sorted(notes, key=lambda n: (n.onset, n.midi)), got):
        assert abs(a.onset - b.onset) < 1e-3 and abs(a.offset - b.offset) < 1e-3


def test_catalog_names_match_installed_library():
    if catalog.patch_dir() is None:
        pytest.skip("BBCSO Discover not installed")
    assert catalog.patch_name("cello", "pizzicato", "leader") == "Celli Leader - Short Pizzicato"
    assert catalog.patch_name("violin", "long", "section") == "Violins 1 - Long"
    assert catalog.patch_name("viola", "tremolo", "leader") == "Viola Leader - Tremolo"
    assert catalog.patch_name("cello", "marcato", "section") is None       # sections only have long_marcato
    assert set(states.wanted()) <= {(i, "leader", a) for i in catalog.CORE_INSTRUMENTS for a in catalog.CORE_ARTICULATIONS}


@pytest.mark.parametrize("inst", ["violin", "viola", "cello"])
def test_scenes_stay_in_range(inst):
    spec = catalog.INSTRUMENTS[inst]
    for fn in scenes.MONO_SCENES.values():
        for n in fn(inst):
            assert spec["lo"] <= n.midi <= spec["hi"] and n.offset > n.onset
    assert scenes.random_line(inst, seed=3) == scenes.random_line(inst, seed=3)


def test_interval_pair_exact_interval():
    p = scenes.interval_pair("cello", "violin", "fifth")
    assert p["hi"][1][0].midi - p["lo"][1][0].midi == 7


def test_dynamics_sets_plugin_parameter():
    t = Track("t", "cello", "leader", "long", [midi.Note(48, 1.0, 3.0)], dynamics=64)
    assert t.effective_params()["Dynamics"] == pytest.approx(64 / 127)


def test_analyse_track_flags_silent_notes():
    sr = 44100
    x = np.zeros(sr * 3, np.float32)
    x[int(1.08 * sr):int(2.08 * sr)] = 0.3 * np.sin(2 * np.pi * 220 * np.arange(sr) / sr)
    a = analyse_track(x, [midi.Note(48, 1.0, 1.8), midi.Note(50, 2.5, 2.8)], sr)      # second note never sounds
    assert not a[0]["silent"] and a[1]["silent"]


def test_lag_lookup(monkeypatch):
    from tools.bbcso import lags
    monkeypatch.setattr(lags, "_table", {"cello/leader/long": {"48": {"lag_ms": 40.0, "spread_ms": 0.1}}})
    assert lags.lag_s("cello", "leader", "long", 48) == pytest.approx(0.04)
    assert lags.lag_s("cello", "leader", "long", 49) is None and lags.lag_s("cello", "section", "long", 48) is None


def test_render_scene_writes_mix_stems_truth(tmp_path, monkeypatch):
    import json
    import soundfile as sf
    from tools.bbcso import render
    sr = 44100

    def fake(track, sr=sr, settle=0, tail=0, block=0):
        x = np.zeros((sr * 3, 2), np.float32)
        for n in track.notes:
            a = int((n.onset + 0.03) * sr)
            b = int(n.offset * sr)
            x[a:b] = (0.8 if track.name == "lo" else 0.4) * np.sin(2 * np.pi * 110 * np.arange(b - a) / sr)[:, None]
        return x

    monkeypatch.setattr(render, "render_track", fake)
    pair = scenes.interval_pair("cello", "violin", "fifth", note_s=1.5)
    tracks = [Track(k, i, "leader", "long", n) for k, (i, n) in pair.items()]
    meta = render.render_scene("t", tracks, sr=sr, out_dir=tmp_path)
    mix, _ = sf.read(tmp_path / "t.wav")
    lo, _ = sf.read(tmp_path / "t.stems" / "lo.wav")
    hi, _ = sf.read(tmp_path / "t.stems" / "hi.wav")
    assert mix.ndim == 1 and np.abs(mix).max() <= 0.951 and meta["gain"] < 1       # 0.8+0.4 clips -> shared gain
    assert np.allclose(mix, lo + hi, atol=1e-4)                                      # stems sum to the mixture
    j = json.loads((tmp_path / "t.json").read_text())
    assert {n["src"] for n in j["notes"]} == {"lo", "hi"}
    assert (tmp_path / "t.mid").exists() and not j["warnings"]


def test_reverb_defaults_to_zero_and_can_be_overridden():
    t = Track("t", "cello", "leader", "long", [midi.Note(48, 0.5, 1.0)])
    assert t.effective_params()["Reverb"] == 0.0
    assert Track("t", "cello", "leader", "long", [], params={"Reverb": 0.3}).effective_params()["Reverb"] == 0.3
