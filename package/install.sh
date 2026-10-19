#!/bin/sh
# Link this package into Max 9's Packages folder (a symlink; remove it to uninstall).
set -e
SRC="$(cd "$(dirname "$0")/fidddle" && pwd)"
DEST="$HOME/Documents/Max 9/Packages/fidddle"
mkdir -p "$HOME/Documents/Max 9/Packages"
if [ -e "$DEST" ] && [ ! -L "$DEST" ]; then echo "$DEST exists and is not a symlink; leaving it alone"; exit 1; fi
ln -sfn "$SRC" "$DEST"
echo "linked $DEST -> $SRC"
echo "Restart Max (or rescan packages), then create [fidddle~]."
