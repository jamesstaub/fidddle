import json

import numpy as np
import soundfile as sf

from fidddle.__main__ import main
from fidddle.synth import Note, render


def _wav(tmp_path, name, notes, dur):
    path = tmp_path / name
    sf.write(path, render(notes, 44100.0, dur, seed=1), 44100)
    return str(path)


def test_command_line_prints_the_notes(tmp_path, capsys):
    wav = _wav(tmp_path, "a.wav", [Note(57, 0.3, 2.0, "bowed")], 2.6)
    main([wav, "--profile", "cello", "--json"])
    ev = [json.loads(l) for l in capsys.readouterr().out.splitlines()]
    assert [e["midi"] for e in ev if e["kind"] == "on"] == [57]
    assert any(e["kind"] == "off" for e in ev)


def test_command_line_calibrates_from_open_strings(tmp_path, capsys):
    opens = [40, 45, 50, 55, 59, 64]
    notes = [Note(m, 0.4 + 3.2 * i, 0.4 + 3.2 * i + 2.9, "plucked", B=5e-5 * (i + 1), tau0=2.5) for i, m in enumerate(opens)]
    cal = _wav(tmp_path, "open.wav", notes, 0.4 + 3.2 * 6 + 0.5)
    rec = _wav(tmp_path, "rec.wav", [Note(52, 0.3, 3.0, "plucked", B=1e-4, tau0=2.5)], 3.6)
    main([rec, "--profile", "guitar", "--calibrate-from", cal])
    out, err = capsys.readouterr()
    assert "strings learned" in err
    assert " on " in out
