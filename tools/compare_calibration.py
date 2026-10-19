"""Parity: Python and C++ calibrators on the same synthetic open-string recording.

Usage: .venv/bin/python tools/compare_calibration.py [guitar|bass] [--weak-fundamental]
"""
import argparse
import json
import subprocess
import sys
from pathlib import Path
import numpy as np
import soundfile as sf

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from fidddle.profile import DetectorConfig
from fidddle.analyzer import Analyzer
from fidddle.calibrate import Calibrator
from fidddle.synth import render
from tools.eval_calibration import truth_calibration, open_string_recording, WEAK_FUND

CLI = ROOT / "core" / "build" / "fidddle_cli"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("instrument", nargs="?", default="guitar", choices=("guitar", "bass"))
    ap.add_argument("--weak-fundamental", action="store_true")
    args = ap.parse_args()
    sr = 44100.0
    inst = args.instrument
    prof = DetectorConfig.for_instrument(inst, sr).profile
    truth = DetectorConfig.for_instrument(inst, sr)
    truth.calibration = truth_calibration(inst, prof)
    notes, dur, _ = open_string_recording(inst, prof, truth, WEAK_FUND if args.weak_fundamental else None, "plucked", sr, 0)
    x = render(notes, sr, dur, snr_db=40.0, seed=1)
    wav = ROOT / "data" / "synth" / f"calibration__{inst}.wav"
    wav.parent.mkdir(parents=True, exist_ok=True)
    sf.write(wav, x, int(sr), subtype="PCM_16")

    xq, _ = sf.read(wav)
    az = Analyzer(DetectorConfig.for_instrument(inst, sr))
    cal = Calibrator(az.cfg, az.n_long)
    az.run(xq, track=True, calibrator=cal)       # the C++ detector always runs the tracker (its priors feed the fit)
    py = cal.finalize().to_list()

    out = subprocess.run([str(CLI), str(wav), "--profile", inst, "--calibrate"], capture_output=True, text=True, check=True).stdout.splitlines()
    cpp = None
    for line in out:
        j = json.loads(line)
        if "calibration" in j:
            cpp = j["calibration"]
    print("python:", np.round(py, 6).tolist())
    print("c++   :", np.round(cpp, 6).tolist() if cpp else None)
    if cpp and len(cpp) == len(py):
        d = np.abs(np.array(py) - np.array(cpp))
        rel = d / (np.abs(np.array(py)) + 1e-12)
        print(f"max abs diff {d.max():.3e}   max rel diff (values > 1e-6) {rel[np.abs(np.array(py)) > 1e-6].max():.3e}")
    else:
        print("MISMATCH in length or missing C++ result")


if __name__ == "__main__":
    main()
