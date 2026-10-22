"""Compatibility layer: the OrchideaSOL index now lives in the standalone package `orchidea_scenes` (repository root).

The old function names stay so that the evaluation scripts in tools/ keep working. The instrument "bass" is accepted as an
alias of "contrabass" (the library's double bass); it is NOT the 5-string electric bass of fidddle's `bass` profile.
"""
from pathlib import Path

from orchidea_scenes.library import FOLDERS, OPEN_STRINGS, PLUCKED_PREFIXES, Library, Sound, parse  # noqa: F401

ROOT = Path(__file__).resolve().parent.parent.parent
RELEASE = ROOT / "data" / "_OrchideaSOL2020_release" / "OrchideaSOL2020"
LIB = RELEASE / "Strings"
INSTRUMENT_PATHS = {i: RELEASE / f for i, f in FOLDERS.items()}
PLUCKED = PLUCKED_PREFIXES
_lib = Library(RELEASE)


def _name(instrument):
    return "contrabass" if instrument == "bass" else instrument


def index(muted=False, originals_only=True):
    return Library(RELEASE, muted, originals_only).sounds if (muted or not originals_only) else _lib.sounds


def select(instrument=None, techniques=None, dynamics=None, lo=None, hi=None, **index_kw):
    lib = Library(RELEASE, index_kw.get("muted", False), index_kw.get("originals_only", True)) if index_kw else _lib
    return lib.select(_name(instrument), techniques, dynamics, (lo, hi) if (lo is not None or hi is not None) else None)


def summary(instrument=None):
    return _lib.summary(_name(instrument))
