#!/bin/sh
# usage: tools/grid_track.sh "--set a=1 ..." ...  tracker note-level scores on synthetic scenes and mixes
for cfg in "$@"; do
  echo "== $cfg"
  .venv/bin/python tools/eval_tracker.py --only synth $cfg | grep -E "MEAN|repeated"
  .venv/bin/python tools/eval_tracker.py --only mixes $cfg | head -1
done
