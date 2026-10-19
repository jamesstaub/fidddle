"""Golden comparison: C++ core (core/build/fidddle_cli) vs the Python reference on the same WAV.

Compares note events exactly (kind, track id, MIDI note, delivery sample, flags) and, with --frames,
the per-frame fitted pitches (tolerance in semitones).

Usage: .venv/bin/python tools/compare_cpp.py [files...] [--frames] [--tol 0.02]
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

CLI = ROOT / "core" / "build" / "fidddle_cli"
FLAG = {"retrigger": 1, "inferred_release": 2, "weak_onset": 4, "stream_end": 8}


def py_run(path, channel=0):
    x, sr = sf.read(path, always_2d=True)
    cfg = DetectorConfig(sample_rate=float(sr))
    az = Analyzer(cfg)
    frames = az.run(x[:, channel], track=True)
    ev = [(("on" if e.kind == "on" else "off"), e.track_id, e.midi_note, e.deliver_samples,
           sum(FLAG[f] for f in e.flags)) for e in az.events]
    return ev, frames


def cpp_run(path, channel=0, frames=False):
    args = [str(CLI), str(path), "--channel", str(channel)] + (["--frames"] if frames else [])
    out = subprocess.run(args, capture_output=True, text=True, check=True).stdout.splitlines()
    ev, fr, summary = [], [], None
    for line in out:
        j = json.loads(line)
        if "ev" in j:
            ev.append((j["ev"], j["id"], j["midi"], j["deliver"], j["flags"]))
        elif "summary" in j:
            summary = j
        else:
            fr.append(j)
    return ev, fr, summary


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("files", nargs="*")
    ap.add_argument("--frames", action="store_true")
    ap.add_argument("--tol", type=float, default=0.02)
    args = ap.parse_args()
    files = args.files or [str(p) for p in sorted((ROOT / "data" / "channels").glob("*.0.wav"))[:6]]
    tot_ev = tot_match = 0
    for f in files:
        pe, pframes = py_run(f)
        ce, cframes, summ = cpp_run(f, frames=args.frames)
        same = pe == ce
        tot_ev += max(len(pe), len(ce))
        n_match = sum(1 for a, b in zip(pe, ce) if a == b)
        tot_match += n_match
        line = f"{Path(f).name:42s} py={len(pe):3d} cpp={len(ce):3d} identical={'yes' if same else 'NO ':3s} matched={n_match}/{max(len(pe), len(ce))}"
        if summ:
            line += f"  cpp {summ['mean_us']:.0f}us/hop (max {summ['max_us']:.0f}, budget {summ['hop_us']:.0f})  {summ['realtime_x']:.1f}x realtime"
        print(line)
        if not same:
            for a, b in zip(pe, ce):
                if a != b:
                    print("   first difference  py:", a, " cpp:", b)
                    break
            else:
                print("   length differs; extra:", (pe if len(pe) > len(ce) else ce)[min(len(pe), len(ce))])
        if args.frames:
            d = []
            bad = 0
            for pf, cf in zip([fr for fr in pframes], cframes):
                pv = sorted(v.midi for v in pf.fit.voices)
                cv = sorted(v[0] for v in cf["fit"])
                if len(pv) != len(cv):
                    bad += 1
                    continue
                d += [abs(a - b) for a, b in zip(pv, cv)]
            print(f"   frames: {len(cframes)} compared, voice-count mismatches {bad}, max pitch diff {max(d) if d else 0:.4f} semitones")
    print(f"TOTAL events matched {tot_match}/{tot_ev}")


if __name__ == "__main__":
    main()
