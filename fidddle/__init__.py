"""Real-time polyphonic pitch detector for string instruments."""
from pathlib import Path

try:
    __version__ = (Path(__file__).resolve().parent.parent / "VERSION").read_text().strip()
except OSError:                      # installed without the repository: the version is unknown
    __version__ = "unknown"
