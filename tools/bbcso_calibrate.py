"""Measure each captured patch's note-on -> sound-start lag per pitch, and write tools/bbcso/onset_lags.json.

Samples start a fixed time after the MIDI note-on (a lead-in that differs per sample, so per pitch). Dynamics
makes no difference and velocity is ignored by pizz/spiccato (bowed patches show occasional outliers), so the table is
indexed by patch and pitch only. Every pitch is
played twice, 3 s apart from its neighbours, to expose round-robin variation (stored as `spread_ms`).

"Sound start" = the first time the 2 ms envelope reaches 5% of the note's peak. A higher fraction measures how slowly a
bowed attack swells, not when the sound begins, so it is not used here.

Usage: .venv/bin/python tools/bbcso_calibrate.py [--instrument cello ...] [--player leader]
Rerun (and commit the json) if the library version changes.
"""
import argparse
import json
import sys
from pathlib import Path
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from tools.bbcso import catalog, states
from tools.bbcso.midi import Note
from tools.bbcso.render import Track, render_track, envelope
from tools.bbcso.lags import TABLE_PATH, FRAC

GAP = 3.0
REPEATS = 2


def measure(env, onset, sr):
    a = int((onset - 0.1) * sr)
    seg = env[a:int((onset + 1.5) * sr)]
    pk = seg.max()
    return None if pk < 1e-4 else (a + int(np.argmax(seg >= FRAC * pk))) / sr - onset


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--instrument", action="append")
    ap.add_argument("--player", action="append")
    a = ap.parse_args()
    sr = 44100
    table = json.loads(TABLE_PATH.read_text()) if TABLE_PATH.exists() else {}
    for inst, pl, art in states.captured():
        if (a.instrument and inst not in a.instrument) or (a.player and pl not in a.player):
            continue
        spec = catalog.INSTRUMENTS[inst]
        pitches = list(range(spec["lo"], spec["hi"] + 1))
        order = [p for _ in range(REPEATS) for p in pitches]
        notes = [Note(p, 0.5 + i * GAP, 0.5 + i * GAP + 1.0, 90) for i, p in enumerate(order)]
        stem = render_track(Track("c", inst, pl, art, notes, dynamics=100), sr, settle=2.0, tail=3.0).mean(1)
        env = envelope(stem, sr, 0.002)
        by = {}
        for n in notes:
            by.setdefault(n.midi, []).append(measure(env, n.onset, sr))
        entry = {}
        for p, v in by.items():
            v = [x for x in v if x is not None]
            if v:
                entry[str(p)] = {"lag_ms": round(1000 * float(np.median(v)), 2), "spread_ms": round(1000 * (max(v) - min(v)), 2)}
        table[f"{inst}/{pl}/{art}"] = entry
        lags = np.array([e["lag_ms"] for e in entry.values()])
        spr = np.array([e["spread_ms"] for e in entry.values()])
        print(f"{inst:7s}{art:10s} {len(entry)}/{len(pitches)} pitches  lag {lags.min():5.1f}..{lags.max():5.1f} ms  "
              f"repeat spread median {np.median(spr):.2f} max {spr.max():.2f} ms")
    TABLE_PATH.write_text(json.dumps(table, indent=0, sort_keys=True))
    print("wrote", TABLE_PATH)


if __name__ == "__main__":
    main()
