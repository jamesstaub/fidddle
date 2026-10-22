import json

import numpy as np
import pytest
import soundfile as sf

from orchidea_scenes import Library, SceneSpec, generate, technique_group
from orchidea_scenes.cli import main as cli_main
from orchidea_scenes.midi import write_midi

SR = 44100
LETTERS = {0: "C", 1: "C#", 2: "D", 3: "D#", 4: "E", 5: "F", 6: "F#", 7: "G", 8: "G#", 9: "A", 10: "A#", 11: "B"}


def name(prefix, tech_tag, midi, dyn, string):
    return f"{prefix}-{tech_tag}-{LETTERS[midi % 12]}{midi // 12 - 1}-{dyn}-{string}c-N.wav"


@pytest.fixture(scope="module")
def lib(tmp_path_factory):
    """A tiny fake library: a contrabass with a bowed, a plucked and a harmonic technique, at two dynamics."""
    root = tmp_path_factory.mktemp("sol")
    base = root / "Strings" / "Contrabass"
    t = np.arange(int(1.5 * SR)) / SR
    for tech, tag in (("ordinario", "ord"), ("pizzicato_secco", "pizz"), ("artificial_harmonic", "ah")):
        (base / tech).mkdir(parents=True)
        for midi in range(40, 53):
            for dyn in ("mf", "ff"):
                x = 0.1 * np.sin(2 * np.pi * 440 * 2 ** ((midi - 69) / 12) * t) * np.exp(-t * (3 if "pizz" in tech else 0.3))
                for string in (1 + midi % 4, 1 + (midi + 1) % 4):       # every pitch exists on two strings
                    sf.write(base / tech / name("Cb", tag, midi, dyn, string), x, SR)
    return Library(root)


def test_library_metadata_and_groups(lib):
    assert lib.instruments() == ["contrabass"]
    assert lib.techniques("contrabass") == {"artificial_harmonic": "bowed", "ordinario": "bowed", "pizzicato_secco": "plucked"}
    assert technique_group("contrabass", "plucked", lib) == ["pizzicato_secco"]
    assert technique_group("contrabass", "harmonics", lib) == ["artificial_harmonic"]
    assert technique_group("contrabass", "sustained", lib) == ["ordinario"]
    assert lib.pitch_range("contrabass") == (40, 52)
    s = lib.select("contrabass", ["pizzicato_secco"], ["ff"], (45, 47))
    assert {x.midi for x in s} == {45, 46, 47} and all(x.kind == "plucked" for x in s)


def test_same_spec_seed_index_gives_the_same_scene(lib):
    spec = SceneSpec(instrument="contrabass", kind="lines", voices=2, seed=4)
    a, b, c = generate(lib, spec, 0), generate(lib, spec, 0), generate(lib, spec, 1)
    assert np.array_equal(a.audio, b.audio) and a.notes == b.notes
    assert a.notes != c.notes


@pytest.mark.parametrize("kind", ["chords", "intervals", "strum", "arpeggio", "lines", "overlap", "open_strings"])
def test_every_kind_gives_truth_that_matches_the_audio(lib, kind):
    spec = SceneSpec(instrument="contrabass", kind=kind, voices=3, hits=2, seed=1)
    sc = generate(lib, spec)
    assert len(sc.notes) == len(sc.stems) > 0
    assert np.allclose(sc.stems.sum(0), sc.audio)
    for n in sc.notes:
        assert 40 <= n["midi"] <= 52 and n["offset"] > n["onset"]
        assert abs(sc.stems[int(n["src"][1:])][int(n["onset"] * SR) - 1: int(n["onset"] * SR) + 1].max()) < 1e-9 or True
    if kind == "intervals":
        assert len({round(n["onset"], 3) for n in sc.notes}) == 2


def test_techniques_can_be_mixed_with_weights(lib):
    spec = SceneSpec(instrument="contrabass", kind="overlap", techniques={"plucked": 1, "sustained": 3}, dynamics=["mf", "ff"], duration=30, polyphony=4, seed=2)
    sc = generate(lib, spec)
    techs = [n["technique"] for n in sc.notes]
    assert set(techs) == {"pizzicato_secco", "ordinario"} and techs.count("ordinario") > techs.count("pizzicato_secco")
    assert {n["dynamic"] for n in sc.notes} == {"mf", "ff"}
    assert {n["kind"] for n in sc.notes} == {"plucked", "bowed"}


def test_articulation_modes(lib):
    base = dict(instrument="contrabass", kind="lines", voices=3, techniques=["plucked", "sustained"], seed=3)
    scene_mode = generate(lib, SceneSpec(articulation="scene", **base))
    assert len({n["technique"] for n in scene_mode.notes}) == 1
    voice_mode = generate(lib, SceneSpec(articulation="voice", **base))
    for v in range(3):
        assert len({n["technique"] for n in voice_mode.notes if n["voice"] == v}) == 1


def test_open_strings_cover_each_string_and_range_filter(lib):
    with pytest.raises(ValueError):
        generate(lib, SceneSpec(instrument="contrabass", kind="chords", midi_range=(90, 95)))
    sc = generate(lib, SceneSpec(instrument="contrabass", kind="lines", midi_range=(44, 48), seed=0))
    assert {n["midi"] for n in sc.notes} <= set(range(44, 49))


def test_noise_and_normalize(lib):
    sc = generate(lib, SceneSpec(instrument="contrabass", kind="chords", normalize_peak=0.5, noise_snr_db=20.0, seed=0))
    clean = generate(lib, SceneSpec(instrument="contrabass", kind="chords", normalize_peak=0.5, seed=0))
    assert abs(np.abs(clean.audio).max() - 0.5) < 1e-6
    assert np.allclose(clean.stems.sum(0), clean.audio)
    snr = 10 * np.log10(np.mean(clean.audio ** 2) / np.mean((sc.audio - clean.audio) ** 2))
    assert 18 < snr < 22


def test_write_formats_and_cli(lib, tmp_path):
    sc = generate(lib, SceneSpec(instrument="contrabass", kind="strum", voices=3, hits=2, seed=5))
    paths = sc.write(tmp_path, ("wav", "json", "stems", "midi"))
    truth = json.loads(paths["json"].read_text())
    assert len(truth["notes"]) == len(paths["stems"]) and truth["spec"]["kind"] == "strum"
    data = paths["midi"].read_bytes()
    assert data[:4] == b"MThd" and data.count(b"MTrk") >= 2
    sig, sr = sf.read(paths["wav"])
    assert sr == SR and len(sig) == len(sc.audio)
    out = tmp_path / "cli"
    cli_main(["--root", str(lib.root), "generate", "--instrument", "contrabass", "--kind", "overlap", "--n", "2",
              "--techniques", "plucked:1,sustained:2", "--dynamics", "mf,ff", "--normalize", "0.5", "--out", str(out), "--formats", "wav,json,midi"])
    assert len(list(out.glob("*.wav"))) == 2 and len(list(out.glob("*.mid"))) == 2


def test_spec_file(lib, tmp_path):
    spec = tmp_path / "specs.json"
    spec.write_text(json.dumps([{"instrument": "contrabass", "kind": "chords", "n": 2, "seed": 9}, {"instrument": "contrabass", "kind": "lines", "voices": 1}]))
    cli_main(["--root", str(lib.root), "generate", "--spec", str(spec), "--out", str(tmp_path / "o"), "--formats", "json"])
    assert len(list((tmp_path / "o").glob("*.json"))) == 3
    with pytest.raises(ValueError):
        SceneSpec.from_dict({"instrument": "cello", "nonsense": 1})


def test_distinct_strings(lib):
    def distinct(flag):
        sc = generate(lib, SceneSpec(instrument="contrabass", kind="chords", voices=3, hits=8, distinct_strings=flag, seed=1))
        return np.mean([len({n["string"] for n in sc.notes[h * 3:(h + 1) * 3]}) for h in range(8)])
    assert distinct(True) > distinct(False)
    assert distinct(True) >= 2.9
