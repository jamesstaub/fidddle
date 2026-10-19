"""Score the detector on the real DI recordings in data/ (guitar and 5-string bass).

Open-string files have a known truth (each open string plucked once, in order): we report how many of the expected notes were found
and how many extra notes appeared. Chord files have no truth, so they are compared with Basic Pitch (a rough reference, not ground truth)
and checked for the failure modes seen in practice: harmonic ghosts, very short notes, ringing notes dropped early.

Usage: .venv/bin/python tools/eval_real.py [--set key=value ...] [--cal-from-open]
"""
import argparse
import json
import subprocess
import sys
from pathlib import Path
import numpy as np
import soundfile as sf
import mir_eval

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from tools.notes_report import run, pair, stats, name
from tools.run_basicpitch import midi_to_notes
from fidddle.corpus import BASICPITCH_CLI

DATA = ROOT / "data"
BP_CACHE = DATA / "di_basicpitch"

# (file, profile, extra CLI args, expected open-string plucks as [(time_s, midi)] or None for chord files)
FILES = {
    "guitar-open-strings": ("guitar", [], [(0.55, 40), (2.94, 45), (5.51, 50), (8.17, 55), (10.66, 59), (12.95, 64)]),
    "5string-bass-open-strings": ("bass", [], [(0.63, 23), (2.74, 28), (4.65, 33), (6.87, 38), (9.21, 43)]),
    "guitar-bar-chords": ("guitar", [], None),
    "5string-bass-chords": ("bass", [], None),
}


def basic_pitch(stem):
    BP_CACHE.mkdir(exist_ok=True)
    js = BP_CACHE / f"{stem}.json"
    if js.exists():
        return json.loads(js.read_text())
    x, sr = sf.read(DATA / f"{stem}.wav", always_2d=True)
    mono = BP_CACHE / f"{stem}.wav"
    sf.write(mono, x[:, 0], sr)
    subprocess.run([str(BASICPITCH_CLI), str(mono), str(BP_CACHE)], capture_output=True, check=True)
    notes = midi_to_notes(BP_CACHE / f"{stem}.mid")
    js.write_text(json.dumps(notes))
    return notes


def score_open(notes, plucks):
    """Hits: expected pitch starting within 0.5 s of its pluck. Extras: every other note."""
    hits = 0
    used = set()
    for t, m in plucks:
        for i, n in enumerate(notes):
            if i not in used and n["midi"] == m and -0.1 <= n["t0"] - t <= 0.5:
                hits += 1
                used.add(i)
                break
    extras = [n for i, n in enumerate(notes) if i not in used]
    return hits, extras


def vs_bp(notes, bp):
    ref = [(n["onset"], n["offset"], n["midi"]) for n in bp if n["offset"] - n["onset"] >= 0.1]
    if not ref or not notes:
        return 0.0, 0.0, 0.0
    ri = np.array([[a, max(b, a + 0.02)] for a, b, _ in ref]); rp = 440.0 * 2 ** ((np.array([m for *_, m in ref]) - 69) / 12)
    ei = np.array([[n["t0"], max(n["t1"], n["t0"] + 0.02)] for n in notes]); ep = 440.0 * 2 ** ((np.array([n["midi"] for n in notes]) - 69) / 12)
    p, r, f, _ = mir_eval.transcription.precision_recall_f1_overlap(ri, rp, ei, ep, onset_tolerance=0.25, pitch_tolerance=50.0, offset_ratio=None)
    return p, r, f


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--set", action="append", default=[])
    ap.add_argument("--cal-from-open", action="store_true", help="calibrate on the matching open-string file and apply it to the chords")
    ap.add_argument("--in-sample", action="store_true", help="also apply the calibration to the open-string files it was learned from (an optimistic upper bound)")
    ap.add_argument("--verbose", action="store_true")
    a = ap.parse_args()
    extra_set = []
    for kv in a.set:
        extra_set += ["--set", kv]
    cals = {}
    if a.cal_from_open:
        for inst, stem in (("guitar", "guitar-open-strings"), ("bass", "5string-bass-open-strings")):
            args = [str(ROOT / "core/build/fidddle_cli"), str(DATA / f"{stem}.wav"), "--profile", inst, "--calibrate"]
            out = subprocess.run(args, capture_output=True, text=True, check=True).stdout.splitlines()
            for l in out:
                j = json.loads(l)
                if "calibration" in j:
                    cals[inst] = ",".join(repr(v) for v in j["calibration"])
    print(f"{'file':28s} {'notes':>5s} | {'open: hit/exp':>13s} {'extras':>6s} | {'vs BP P/R/F1':>16s} | {'harm.pairs':>10s} {'<150ms':>6s} {'window ms':>9s}")
    tot_extra = 0
    for stem, (inst, extra, plucks) in FILES.items():
        wav = DATA / f"{stem}.wav"
        cal = cals.get(inst) if (a.cal_from_open and (plucks is None or a.in_sample)) else None
        events, summ = run(wav, inst, extra + extra_set, cal)
        notes = pair(events, summ["sr"])
        st = stats(notes)
        if plucks:
            hits, extras = score_open(notes, plucks)
            tot_extra += len(extras)
            line = f"{hits:>6d}/{len(plucks):<6d} {len(extras):6d} |{'':>17s}|"
            if a.verbose:
                print("   extras:", [(round(n['t0'], 2), name(n['midi']), round(n['t1'] - n['t0'], 2)) for n in extras])
        else:
            p, r, f = vs_bp(notes, basic_pitch(stem))
            line = f"{'':>13s} {'':>6s} | {p:5.2f}/{r:4.2f}/{f:4.2f} |"
        print(f"{stem:28s} {st['notes']:5d} | {line} {st['harmonic_pairs_started_together']:10d} {st['shorter_than_150ms']:6d}")


if __name__ == "__main__":
    main()
