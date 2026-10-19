#!/bin/sh
# usage: tools/grid_inst.sh <instrument> "--set a=1 ..." ...   mean fit F1 and note F1 per config
inst=$1; shift
for cfg in "$@"; do
  printf '%s => ' "$cfg"
  .venv/bin/python tools/eval_instruments.py $inst --stride 6 $cfg | grep -E "^MEAN" | tr '\n' ' '
  echo
done
