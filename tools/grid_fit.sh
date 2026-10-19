#!/bin/sh
# usage: tools/grid_fit.sh "--set a=1 --set b=2" ...   (each argument is one config)
for cfg in "$@"; do
  printf '%s => ' "$cfg"
  .venv/bin/python tools/eval_fit.py --stride 6 $cfg | grep MEAN
done
