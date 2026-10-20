"""What the installed BBCSO library offers, and the names we use for it.

Patch files (*.zmulti) are encrypted, so a patch cannot be loaded from here: it has to be picked once in the plugin
UI and saved as a state (see states.py). This module only maps our keys to the patch name to pick, by reading the
patch file names, so the capture checklist never goes stale.
"""
import re
from pathlib import Path

LIB = Path.home() / "Spitfire" / "Spitfire Audio - BBC Symphony Orchestra"
VST3 = Path("/Library/Audio/Plug-Ins/VST3/BBC Symphony Orchestra.vst3")

# instrument key -> (section name as it appears in patch file names, leader name, MIDI range of the real instrument)
INSTRUMENTS = {
    "violin": dict(section="Violins 1", leader="Violin 1 Leader", lo=55, hi=96),
    "violin2": dict(section="Violins 2", leader="Violin 2 Leader", lo=55, hi=96),
    "viola": dict(section="Violas", leader="Viola Leader", lo=48, hi=84),
    "cello": dict(section="Celli", leader="Celli Leader", lo=36, hi=76),
    "bass": dict(section="Basses", leader="Bass Leader", lo=28, hi=62),
}

# articulation key -> patch-name suffix (the part after "<Section> - ", with "_" for spaces)
ARTICULATIONS = {
    "long": "Long",
    "legato": "Legato",
    "long_cs": "Long CS",
    "marcato": "Short Marcato",          # leaders only; sections have "Long Marcato Attack" (long_marcato)
    "long_marcato": "Long Marcato Attack",
    "staccato": "Short Staccato",
    "spiccato": "Short Spiccato",
    "pizzicato": "Short Pizzicato",
    "pizz_bartok": "Short Pizzicato Bartok",
    "col_legno": "Short Col Legno",
    "tremolo": "Tremolo",
    "tremolo_sul_pont": "Tremolo Sul Pont",
    "flautando": "Long Flautando",
    "sul_tasto": "Long Sul Tasto",
    "sul_pont": "Long Sul Pont",
    "harmonics": "Long Harmonics",
    "short_harmonics": "Short Harmonics",
    "trill_maj2": "Trill (Major 2nd)",
    "trill_min2": "Trill (Minor 2nd)",
}

# Families the algorithms care about; each maps to the articulation keys that realise it.
FAMILIES = {
    "bowed": ["long", "legato", "marcato", "long_marcato", "sul_tasto", "flautando"],
    "pizz": ["pizzicato", "pizz_bartok"],
    "spiccato": ["spiccato", "staccato"],
    "tremolo": ["tremolo", "tremolo_sul_pont"],
}

# Default capture set: the minimum that covers bowed / pizz / spiccato / tremolo on violin, viola, cello.
CORE_INSTRUMENTS = ["violin", "viola", "cello"]
CORE_ARTICULATIONS = ["long", "pizzicato", "spiccato", "tremolo"]

# What the plugin UI actually offers per instrument (reported from the UI; the patch files on disk include more, e.g.
# legato and staccato, that the plugin does not list). Anything not here is treated as unavailable.
IN_PLUGIN = {
    "violin": ["long", "spiccato", "pizzicato", "tremolo"],
    "viola": ["long", "spiccato", "pizzicato", "tremolo"],
    "cello": ["long", "spiccato", "pizzicato", "tremolo"],
    "bass": ["long", "spiccato", "pizzicato"],
}


def patch_dir():
    for d in sorted((LIB / "Patches").glob("v*/Discover Strings"), reverse=True):
        return d
    return None


def _patch_files():
    d = patch_dir()
    return list(d.glob("*.zmulti")) if d else []


def patch_name(instrument, articulation, player):
    """The patch to pick in the plugin UI, e.g. 'Celli Leader - Short Pizzicato'; None if this library lacks it."""
    if articulation not in IN_PLUGIN.get(instrument, []):
        return None
    spec = INSTRUMENTS[instrument]
    base = spec["leader"] if player == "leader" else spec["section"]
    stem_re = re.compile(r"^BBCSODi_[a-z]___" + re.escape(base.replace(" ", "_")) + r"___" + re.escape(ARTICULATIONS[articulation].replace(" ", "_")) + r"$")
    for f in _patch_files():
        if stem_re.match(f.stem):
            return f"{base} - {ARTICULATIONS[articulation]}"
    return None


def available(instrument, player):
    """Articulation keys this library offers for the instrument/player."""
    return [a for a in ARTICULATIONS if patch_name(instrument, a, player)]
