#!/bin/sh
# usage: tools/grid_mix.sh "--set a=1 --set b=2" ...   pooled score on the real-clip mixes
for cfg in "$@"; do
  printf '%s => ' "$cfg"
  .venv/bin/python tools/eval_fit.py --mixes --stride 6 $cfg | grep POOLED
done
