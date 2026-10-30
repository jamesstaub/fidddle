#!/bin/sh
# Builds the web package for a release:   dist/fidddle-web-<version>.zip   and   dist/fidddle-web-<version>.zip.sha256
# Builds the WebAssembly module in Docker unless SKIP_BUILD=1 (web/dist/fidddle.wasm must then exist).
set -e
cd "$(dirname "$0")/.."
VERSION="$(tr -d '[:space:]' < VERSION)"
NAME="fidddle-web-$VERSION"
STAGE="dist/stage-web/$NAME"
[ -n "$SKIP_BUILD" ] || web/build.sh
[ -f web/dist/fidddle.wasm ] || { echo "web/dist/fidddle.wasm is missing" >&2; exit 1; }
rm -rf dist/stage-web "dist/$NAME.zip" "dist/$NAME.zip.sha256"
mkdir -p "$STAGE/dist" "$STAGE/src" "$STAGE/demo"
cp web/dist/fidddle.wasm "$STAGE/dist/"
cp web/src/*.js "$STAGE/src/"
cp web/demo/* "$STAGE/demo/"
cp web/package.json "$STAGE/"
cp web/README.md "$STAGE/README.md"
cp LICENSE CHANGELOG.md THIRD_PARTY_NOTICES.md "$STAGE/"
echo "$VERSION" > "$STAGE/VERSION"
(cd dist/stage-web && zip -qr "../$NAME.zip" "$NAME")
(cd dist && shasum -a 256 "$NAME.zip" > "$NAME.zip.sha256")
echo "dist/$NAME.zip"
