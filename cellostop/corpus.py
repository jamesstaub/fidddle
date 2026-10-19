"""Locations of the local reference corpus and external baseline tools."""
from pathlib import Path

CORPUS_DIR = Path(
    "/Users/jamesstaub/Library/CloudStorage/GoogleDrive-james.staub@gmail.com/"
    "My Drive/audio/cello-gestures"
)
BASICPITCH_CLI = Path("/Users/jamesstaub/Repos/other/basicpitch.cpp/build/build-cli/basicpitch")

# Channel convention of the corpus recordings.
CH_PIEZO = 0
CH_CONDENSER = 1


def top_level_wavs():
    """Top-level .wav files only (subfolders hold other technique sets)."""
    return sorted(p for p in CORPUS_DIR.glob("*.wav") if not p.name.startswith("."))
