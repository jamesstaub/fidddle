"""Polyphonic test scenes with exact truth, built from OrchideaSOL one-shots. See README.md in this folder."""
from .library import FOLDERS, OPEN_STRINGS, Library, Sound, parse, technique_group
from .render import Event, render
from .scenes import ARTICULATION, KINDS, Scene, SceneSpec, build_events, generate, generate_many

__version__ = "0.1.0"
__all__ = ["Library", "Sound", "SceneSpec", "Scene", "Event", "generate", "generate_many", "render", "build_events", "parse",
           "technique_group", "KINDS", "ARTICULATION", "FOLDERS", "OPEN_STRINGS"]
