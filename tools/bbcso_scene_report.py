"""Side-by-side truth and detected notes for one BBCSO scene (what are the extra notes?).

Usage: .venv/bin/python tools/bbcso_scene_report.py cello_long_random1 [--set key=value ...]
"""
import argparse
import json
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from tools.notes_report import run, pair, name
import tools.eval_bbcso as eb
from tools.eval_bbcso import scene_profile

ap = argparse.ArgumentParser()
ap.add_argument("scene")
ap.add_argument("--set", action="append", default=[])
ap.add_argument("--profile", default=None)
ap.add_argument("--bench", default="bench")
a = ap.parse_args()
BENCH = eb.ROOT / "data" / "bbcso" / a.bench
meta = json.loads((BENCH / f"{a.scene}.json").read_text())
extra = []
for kv in a.set:
    extra += ["--set", kv]
events, summ = run(BENCH / f"{a.scene}.wav", a.profile or scene_profile(meta), extra)
est = pair(events, summ["sr"])
rows = []
for n in meta["notes"]:
    if n.get("silent"):
        continue
    rows.append((n.get("audio_onset", n["onset"]), "T", n["offset"], n["midi"], ""))
for e in est:
    rows.append((e["t0"], "E", e["t1"], e["midi"], f"vel {e['vel']} flags {e['flags']}"))
for t0, k, t1, m, info in sorted(rows):
    print(f"{t0:6.2f}-{t1:6.2f}  {'truth   ' if k=='T' else '      est'}  {name(m):>4s} ({m}) {info}")
