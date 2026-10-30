#!/usr/bin/env bash
# Builds web/dist/fidddle.wasm in Docker. Usage: web/build.sh   (run from anywhere)
# With INSIDE_DOCKER=1 it compiles directly (used by the container itself).
set -euo pipefail
root="$(cd "$(dirname "$0")/.." && pwd)"

if [ -z "${INSIDE_DOCKER:-}" ]; then
  docker build -q -t fidddle-web-build "$root/web" >/dev/null
  exec docker run --rm -v "$root":/src -e INSIDE_DOCKER=1 -u "$(id -u):$(id -g)" fidddle-web-build web/build.sh
fi

cd /src
version="$(head -n1 VERSION | tr -d '[:space:]')"
mkdir -p web/dist
# No timestamps or absolute paths end up in the output (-ffile-prefix-map); fixed memory, so views never go stale.
em++ -std=c++17 -O2 -fno-rtti -ffile-prefix-map=/src= \
  -DFIDDDLE_NO_STRING_ID=1 -DFIDDDLE_NO_TIMING=1 -DFIDDDLE_VERSION="\"$version\"" \
  -Icore/include -Icore/src \
  core/src/spectral.cpp core/src/salience.cpp core/src/fitter.cpp core/src/tracker.cpp \
  core/src/calibrator.cpp core/src/detector.cpp web/wasm/fidddle_c_api.cpp \
  --no-entry -sSTANDALONE_WASM=1 -sALLOW_MEMORY_GROWTH=0 -sINITIAL_MEMORY=64MB -sSTACK_SIZE=1MB \
  -sFILESYSTEM=0 -sERROR_ON_UNDEFINED_SYMBOLS=1 \
  -o web/dist/fidddle.wasm
ls -l web/dist/fidddle.wasm
