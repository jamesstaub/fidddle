"""Calibrated note-on -> sound-start lags (see tools/bbcso_calibrate.py). The table is committed: the samples are the
same on every machine with BBCSO Discover, so it does not need re-measuring per install."""
import json
from pathlib import Path

TABLE_PATH = Path(__file__).resolve().parent / "onset_lags.json"
FRAC = 0.05

_table = None


def lag_s(instrument, player, articulation, midi):
    """Seconds from MIDI note-on to audible start, or None if this patch/pitch was not calibrated."""
    global _table
    if _table is None:
        _table = json.loads(TABLE_PATH.read_text()) if TABLE_PATH.exists() else {}
    e = _table.get(f"{instrument}/{player}/{articulation}", {}).get(str(midi))
    return None if e is None else e["lag_ms"] / 1000
