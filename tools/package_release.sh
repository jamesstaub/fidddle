#!/bin/sh
# Build the Max package for a release and zip it:
#   dist/fidddle-max-<version>-macos.zip   and   dist/fidddle-max-<version>-macos.zip.sha256
#
# Needs macOS, CMake and Xcode command line tools. Run from anywhere.
# Signing: ad-hoc by default (works on the machine that built it; downloads need the quarantine step in the README).
#   CODESIGN_IDENTITY="Developer ID Application: Name (TEAMID)"   sign with your Developer ID (hardened runtime)
#   NOTARY_PROFILE=name                                            also notarize with a stored `notarytool` keychain profile
set -e
cd "$(dirname "$0")/.."
VERSION="$(tr -d '[:space:]' < VERSION)"
NAME="fidddle-max-$VERSION-macos"
STAGE="dist/stage/fidddle"

rm -rf dist/stage "dist/$NAME.zip" "dist/$NAME.zip.sha256"
mkdir -p dist/stage

cmake -S max -B max/build -G "Unix Makefiles" -DCMAKE_BUILD_TYPE=Release >/dev/null
cmake --build max/build -j

# the package without media/*.wav (not redistributable) and without build leftovers
mkdir -p "$STAGE"
for d in docs examples externals help media; do cp -R "package/fidddle/$d" "$STAGE/$d"; done
cp package/fidddle/package-info.json "$STAGE/"
find "$STAGE" -name '*.wav' -delete
find "$STAGE" -name '.DS_Store' -delete
cp LICENSE README.md CHANGELOG.md THIRD_PARTY_NOTICES.md "$STAGE/"

# every shipped object must carry this version
for x in "$STAGE"/externals/*.mxo; do
  v="$(/usr/libexec/PlistBuddy -c 'Print :CFBundleShortVersionString' "$x/Contents/Info.plist")"
  [ "$v" = "$VERSION" ] || { echo "$x has version $v, expected $VERSION (re-run cmake)" >&2; exit 1; }
  lipo -info "$x/Contents/MacOS/$(basename "$x" .mxo)" | grep -q arm64 || { echo "$x is not universal" >&2; exit 1; }
done

IDENTITY="${CODESIGN_IDENTITY:--}"
for x in "$STAGE"/externals/*.mxo; do
  if [ "$IDENTITY" = "-" ]; then codesign --force --sign - "$x"
  else codesign --force --options runtime --timestamp --sign "$IDENTITY" "$x"; fi
  codesign --verify --strict "$x"
done

(cd dist/stage && ditto -c -k --norsrc --noextattr --noacl --keepParent fidddle "../$NAME.zip")

if [ -n "$NOTARY_PROFILE" ] && [ "$IDENTITY" != "-" ]; then
  xcrun notarytool submit "dist/$NAME.zip" --keychain-profile "$NOTARY_PROFILE" --wait
fi

(cd dist && shasum -a 256 "$NAME.zip" > "$NAME.zip.sha256")
echo "built dist/$NAME.zip"
cat "dist/$NAME.zip.sha256"
