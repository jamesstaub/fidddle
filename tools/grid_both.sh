#!/bin/sh
# usage: tools/grid_both.sh "--set a=1 ..." ...  synthetic chords (SNR 40/20) and real-clip mixes
for cfg in "$@"; do
  echo "== $cfg"
  printf '  synth40: '; .venv/bin/python tools/eval_fit.py --stride 6 $cfg | grep MEAN
  printf '  synth20: '; .venv/bin/python tools/eval_fit.py --stride 6 --snr 20 $cfg | grep MEAN
  printf '  mixes:   '; .venv/bin/python tools/eval_fit.py --mixes --stride 6 $cfg | grep POOLED
done
