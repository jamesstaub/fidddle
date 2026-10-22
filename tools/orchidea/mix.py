"""Compatibility layer: rendering and scene building now live in the standalone package `orchidea_scenes`."""
import numpy as np

from orchidea_scenes.library import technique_group  # noqa: F401
from orchidea_scenes.render import FADE_S, FLOOR_DB, MAX_PLUCK_S, Event, extent, load, render  # noqa: F401
from orchidea_scenes.scenes import SceneSpec, build_events

INTERVALS = (3, 4, 5, 6, 7, 9, 12)


class _PoolLibrary:
    """A library view over a given list of sounds (what the old scene() received)."""

    def __init__(self, pool):
        self.pool = list(pool)

    def select(self, instrument=None, techniques=None, dynamics=None, midi_range=None, **kw):
        lo, hi = midi_range if midi_range else (None, None)
        return [s for s in self.pool if (not techniques or s.technique in techniques) and (not dynamics or s.dynamic in dynamics)
                and (lo is None or s.midi >= lo) and (hi is None or s.midi <= hi)]

    def techniques(self, instrument):
        return {s.technique: s.kind for s in self.pool}


def scene(kind, pool, rng, voices=3, hits=3, duration=None, techniques=None, dynamics=None):
    """-> (events, duration_s). kinds: chords, intervals, strum, arpeggio, lines, overlap (see orchidea_scenes.scenes)."""
    spec = SceneSpec(instrument=pool[0].instrument, kind=kind, voices=voices, hits=hits, duration=duration, techniques=techniques, dynamics=dynamics)
    return build_events(spec, _PoolLibrary(pool), rng)
