"""Run the basicpitch.cpp CLI over the corpus, per channel, and cache notes as JSON.

Outputs (all inside this repo):
  data/channels/<name>.<ch>.wav      single-channel copies of each recording
  data/basicpitch/<name>.<ch>.mid    Basic Pitch MIDI
  data/basicpitch/<name>.<ch>.json   [{onset, offset, midi, velocity}, ...]

Usage: .venv/bin/python tools/run_basicpitch.py [--only substr] [--force]
"""
import argparse
import json
import subprocess
import sys
from pathlib import Path

import mido
import soundfile as sf

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from fidddle.corpus import top_level_wavs, BASICPITCH_CLI

CH_DIR = ROOT / "data" / "channels"
BP_DIR = ROOT / "data" / "basicpitch"


def midi_to_notes(path):
    mid = mido.MidiFile(path)
    t = 0.0
    open_notes = {}
    notes = []
    for msg in mid:  # iterating a MidiFile yields messages with delta time in seconds
        t += msg.time
        if msg.type == "note_on" and msg.velocity > 0:
            open_notes[msg.note] = (t, msg.velocity)
        elif msg.type in ("note_off", "note_on") and msg.note in open_notes:
            on, vel = open_notes.pop(msg.note)
            notes.append({"onset": on, "offset": t, "midi": msg.note, "velocity": vel})
    return sorted(notes, key=lambda n: n["onset"])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", default="")
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()
    CH_DIR.mkdir(parents=True, exist_ok=True)
    BP_DIR.mkdir(parents=True, exist_ok=True)
    for p in top_level_wavs():
        if args.only and args.only not in p.name:
            continue
        x, sr = sf.read(p, always_2d=True)
        for c in range(x.shape[1]):
            stem = f"{p.stem.replace(' ', '_')}.{c}"
            wav = CH_DIR / f"{stem}.wav"
            js = BP_DIR / f"{stem}.json"
            if js.exists() and not args.force:
                continue
            sf.write(wav, x[:, c], sr)
            r = subprocess.run([str(BASICPITCH_CLI), str(wav), str(BP_DIR)], capture_output=True, text=True)
            mid = BP_DIR / f"{stem}.mid"
            if r.returncode != 0 or not mid.exists():
                print("FAILED", stem, r.stderr[-300:])
                continue
            notes = midi_to_notes(mid)
            js.write_text(json.dumps(notes))
            print(f"{stem:40s} {len(notes):4d} notes")


if __name__ == "__main__":
    main()
