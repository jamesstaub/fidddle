"""Parity: Python and C++ string identification on the same synthetic guitar (open-string calibration pass, then stopped notes).

Usage: .venv/bin/python tools/compare_stringid.py   (run tools/compare_calibration.py guitar first if data/synth/calibration__guitar.wav is missing)
"""
import json
import subprocess
import sys
from pathlib import Path
import numpy as np
import soundfile as sf

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from fidddle.analyzer import Analyzer
from fidddle.calibrate import Calibrator
from fidddle.profile import Calibration, DetectorConfig
from fidddle.synth import Note, render
from tools.eval_calibration import TRUE_B

CLI = ROOT / "core" / "build" / "fidddle_cli"
SR = 44100.0


def main():
    cfg = DetectorConfig.for_instrument("guitar", SR)
    open_hz = list(cfg.profile.open_string_hz)
    wav = ROOT / "data" / "synth" / "calibration__guitar.wav"
    xc, _ = sf.read(wav)
    az = Analyzer(cfg)
    cal = Calibrator(cfg, az.n_long)
    az.run(xc, track=True, calibrator=cal)
    res = cal.finalize()
    lst = res.to_list()
    print("string values:", np.round(res.logb, 3).tolist())
    # stopped notes: (string index, semitones above the open string); B follows f^2 along the string
    plan = [(2, 5), (3, 2), (1, 7), (4, 3), (0, 5), (5, 0), (3, 7), (2, 9), (1, 3), (4, 5)]
    notes, t = [], 0.4
    for s, fret in plan:
        f = open_hz[s] * 2 ** (fret / 12)
        notes.append(Note(int(round(12 * np.log2(open_hz[s] / 440.0) + 69)) + fret, t, t + 2.7, "plucked", B=TRUE_B["guitar"][s] * (f / open_hz[s]) ** 2, tau0=2.5))
        t += 3.0
    x = render(notes, SR, t + 0.5, snr_db=40.0, seed=3)
    path = ROOT / "data" / "synth" / "stringid__guitar.wav"
    sf.write(path, x, int(SR), subtype="PCM_16")
    xq, _ = sf.read(path)

    cfg2 = DetectorConfig.for_instrument("guitar", SR)
    cfg2.calibration = Calibration.from_list(lst)
    az2 = Analyzer(cfg2)
    az2.run(xq, track=True)
    py = [(e.midi_note, e.string, round(e.margin, 3)) for e in az2.events if e.kind == "string"]
    out = subprocess.run([str(CLI), str(path), "--profile", "guitar", "--calibration", ",".join(repr(v) for v in lst)], capture_output=True, text=True, check=True).stdout.splitlines()
    cpp = [(j["midi"], j["string"], round(j["margin"], 3)) for j in (json.loads(l) for l in out if l.startswith("{")) if j.get("ev") == "string"]
    truth = [(n.midi, s) for n, (s, _) in zip(notes, plan)]
    print("truth :", truth)
    print("python:", py)
    print("c++   :", cpp)
    same = len(py) == len(cpp) and all(a[0] == b[0] and a[1] == b[1] and abs(a[2] - b[2]) < 0.01 for a, b in zip(py, cpp))
    print("PARITY OK" if same else "PARITY MISMATCH", f"({len(py)} python, {len(cpp)} c++ answers)")


if __name__ == "__main__":
    main()
