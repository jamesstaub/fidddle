"""Run the C++ detector on a WAV and print a note table plus simple sanity statistics.

There is no ground truth for real recordings, so the statistics look for the failure modes seen in practice:
simultaneous notes of the same MIDI pitch ("unisons"), harmonic ghosts (a note an octave/twelfth/... above another sounding
note that began at about the same time), very short notes, and notes below a plausible level.

Usage: .venv/bin/python tools/notes_report.py file.wav --profile guitar [--calibration "<list>"] [--minfreq F] [--maxfreq F] [--voices N]
"""
import argparse
import json
import subprocess
import sys
from pathlib import Path
import numpy as np

ROOT = Path(__file__).resolve().parent.parent
CLI = ROOT / "core" / "build" / "fidddle_cli"
NAMES = "C C# D D# E F F# G G# A A# B".split()


def name(m):
    return f"{NAMES[m % 12]}{m // 12 - 1}"


def run(wav, profile, extra=(), calibration=None, channel=0):
    args = [str(CLI), str(wav), "--profile", profile, "--channel", str(channel), *extra]
    if calibration:
        args += ["--calibration", calibration]
    out = subprocess.run(args, capture_output=True, text=True, check=True).stdout.splitlines()
    events = [json.loads(l) for l in out if '"ev"' in l]
    summ = [json.loads(l) for l in out if '"summary"' in l][0]
    return events, summ


def pair(events, sr):
    open_, notes = {}, []
    for e in events:
        if e["ev"] == "on":
            open_[e["id"]] = e
        elif e["id"] in open_:
            on = open_.pop(e["id"])
            notes.append(dict(t0=on["onset"] / sr, t1=e["onset"] / sr, midi=on["midi"], vel=on["vel"], id=on["id"], flags=on["flags"]))
    return sorted(notes, key=lambda n: n["t0"])


def stats(notes):
    n = len(notes)
    dup = harm = short = 0
    for i, a in enumerate(notes):
        if a["t1"] - a["t0"] < 0.15:
            short += 1
        for b in notes[:i]:
            overlap = min(a["t1"], b["t1"]) - max(a["t0"], b["t0"])
            if overlap <= 0.05:
                continue
            if a["midi"] == b["midi"]:
                dup += 1
            d = a["midi"] - b["midi"]
            r = 2.0 ** (abs(d) / 12.0)
            k = round(r)
            if k >= 2 and abs(r / k - 1.0) < 0.03 and abs(a["t0"] - b["t0"]) < 0.25:
                harm += 1
    return dict(notes=n, simultaneous_same_pitch=dup, harmonic_pairs_started_together=harm, shorter_than_150ms=short)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("wav")
    ap.add_argument("--profile", required=True)
    ap.add_argument("--calibration", default=None)
    ap.add_argument("--table", action="store_true")
    ap.add_argument("--minfreq"); ap.add_argument("--maxfreq"); ap.add_argument("--voices")
    ap.add_argument("--set", action="append", default=[])
    a = ap.parse_args()
    extra = []
    for k in ("minfreq", "maxfreq", "voices"):
        if getattr(a, k):
            extra += [f"--{k}", getattr(a, k)]
    for kv in a.set:
        extra += ["--set", kv]
    events, summ = run(a.wav, a.profile, extra, a.calibration)
    notes = pair(events, summ["sr"])
    if a.table:
        for n in notes:
            print(f"{n['t0']:7.2f}s {n['t1']-n['t0']:5.2f}s  {name(n['midi']):>4s} ({n['midi']})  vel {n['vel']:3d}  id {n['id']}")
    print(json.dumps(stats(notes)))


if __name__ == "__main__":
    main()
