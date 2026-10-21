"""Run the detector on a WAV file and print the notes.

  python -m fidddle recording.wav --profile guitar
  python -m fidddle chords.wav --profile guitar --calibrate-from open-strings.wav
  python -m fidddle recording.wav --profile cello --json
"""
import argparse
import json
import sys

import numpy as np
import soundfile as sf

from .analyzer import Analyzer
from .calibrate import Calibrator
from .profile import DetectorConfig, InstrumentProfile

NAMES = "C C# D D# E F F# G G# A A# B".split()


def note_name(m):
    return f"{NAMES[m % 12]}{m // 12 - 1}"


def load(path, channel):
    x, sr = sf.read(path, always_2d=True)
    return x[:, min(channel, x.shape[1] - 1)].astype(float), int(sr)


def main(argv=None):
    ap = argparse.ArgumentParser(prog="python -m fidddle", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("wav")
    ap.add_argument("--profile", default="cello", choices=InstrumentProfile.ORDER)
    ap.add_argument("--channel", type=int, default=0, help="channel of a multi-channel file (default 0)")
    ap.add_argument("--calibrate-from", metavar="WAV", help="a recording of isolated plucked open strings: learn the strings from it first")
    ap.add_argument("--json", action="store_true", help="one JSON object per event instead of a table")
    a = ap.parse_args(argv)

    x, sr = load(a.wav, a.channel)
    cfg = DetectorConfig.for_instrument(a.profile, float(sr))
    if a.calibrate_from:
        xc, src = load(a.calibrate_from, a.channel)
        if src != sr:
            sys.exit("the calibration file and the recording must have the same sample rate")
        az = Analyzer(cfg)
        cal = Calibrator(cfg, az.n_long)
        az.run(xc, track=True, calibrator=cal)
        cfg.calibration = cal.finalize()
        if cfg.calibration is None:
            sys.exit("no open string could be learned from the calibration file (pluck each open string alone and let it ring)")
        print(f"# strings learned: {sum(cfg.calibration.captured)} of {len(cfg.calibration.captured)}", file=sys.stderr)

    az = Analyzer(cfg)
    az.run(x, track=True)
    if a.json:
        for e in az.events:
            print(json.dumps({"kind": e.kind, "midi": e.midi_note, "velocity": e.velocity, "slot": e.slot, "id": e.track_id,
                              "onset_s": round(e.onset_est_samples / sr, 4), "deliver_s": round(e.deliver_samples / sr, 4),
                              "string": e.string if e.kind == "string" else None, "margin": round(e.margin, 3) if e.kind == "string" else None}))
        return
    print(f"{'time_s':>8} {'event':6} {'note':5} {'midi':>4} {'vel':>4} {'slot':>4}  string")
    for e in az.events:
        t = e.deliver_samples / sr if e.kind == "string" else e.onset_est_samples / sr
        extra = ""
        if e.kind == "string":
            n = cfg.profile.string_count
            extra = f"{n - e.string}" + ("" if e.margin > 0 else " (guess)")       # numbered as on a guitar: 1 = the highest string
        print(f"{t:8.3f} {e.kind:6} {note_name(e.midi_note):5} {e.midi_note:4d} {e.velocity:4d} {e.slot:4d}  {extra}")


if __name__ == "__main__":
    main()
