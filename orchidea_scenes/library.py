"""Index of the OrchideaSOL string one-shots, with the metadata that the directory and file names carry.

  Strings/Violoncello/ordinario/Vc-ord-A3-ff-4c-N.wav  ->  instrument cello, technique ordinario, pitch A3 (MIDI 57),
  dynamic ff, string 4 ("4c" = corda), variant N.

Variant "N" is an original recording; "T12u", "R200d" and so on are transposed or resampled derivatives made for the Orchidea
library and are left out by default. Sounds without a pitch in the name (behind_the_bridge, ...) are skipped. Muted instruments
(folders "Violin+sordina") are left out by default. Guitar lives in PluckedStrings/ and is always plucked.

The library root is found, in this order, from the `root` argument, the environment variable ORCHIDEA_ROOT, or
`data/_OrchideaSOL2020_release/OrchideaSOL2020` below the current directory. It must contain `Strings/` (and `PluckedStrings/`).
"""
import os
import re
from dataclasses import dataclass
from pathlib import Path

# folder of each instrument below the library root
FOLDERS = {"violin": "Strings/Violin", "viola": "Strings/Viola", "cello": "Strings/Violoncello", "contrabass": "Strings/Contrabass",
           "guitar": "PluckedStrings/Guitar"}
# open strings (MIDI), string 1 = the highest, as the file names count them
OPEN_STRINGS = {"violin": [76, 69, 62, 55], "viola": [69, 62, 55, 48], "cello": [57, 50, 43, 36], "contrabass": [43, 38, 33, 28],
                "guitar": [64, 59, 55, 50, 45, 40]}
PLUCKED_PREFIXES = ("pizzicato", "col_legno_battuto")          # techniques whose notes decay on their own
_NOTE = re.compile(r"-([A-G])(#?)(-?\d)-([a-z]+)-(\d)c-(.+)\.wav$")
_SEMI = {"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11}


def default_root():
    env = os.environ.get("ORCHIDEA_ROOT")
    return Path(env) if env else Path.cwd() / "data" / "_OrchideaSOL2020_release" / "OrchideaSOL2020"


@dataclass(frozen=True)
class Sound:
    path: Path
    instrument: str
    technique: str
    midi: int
    dynamic: str
    string: int
    variant: str

    @property
    def kind(self):
        """"plucked" if the sound decays by itself (pizzicato, col legno battuto, every guitar sound), else "bowed"."""
        return "plucked" if self.instrument == "guitar" or self.technique.startswith(PLUCKED_PREFIXES) else "bowed"

    @property
    def f0_hz(self):
        return 440.0 * 2 ** ((self.midi - 69) / 12)

    def meta(self):
        return {"file": self.path.name, "instrument": self.instrument, "technique": self.technique, "midi": self.midi,
                "f0_hz": round(self.f0_hz, 3), "dynamic": self.dynamic, "string": self.string, "variant": self.variant, "kind": self.kind}


def parse(path, instrument, technique):
    """Sound for one file name, or None if the name has no pitch."""
    m = _NOTE.search(Path(path).name)
    if not m:
        return None
    letter, sharp, octave, dyn, string, variant = m.groups()
    return Sound(Path(path), instrument, technique, 12 * (int(octave) + 1) + _SEMI[letter] + (1 if sharp else 0), dyn, int(string), variant)


class Library:
    """The sounds of a local OrchideaSOL copy. `muted` adds the muted instruments, `originals_only=False` the processed derivatives."""

    def __init__(self, root=None, muted=False, originals_only=True):
        self.root = Path(root) if root else default_root()
        self.muted, self.originals_only = muted, originals_only
        self._sounds = None

    # ---- discovery ----------------------------------------------------------------------------------------------
    def instruments(self):
        """Instruments whose folder exists."""
        return [i for i, f in FOLDERS.items() if (self.root / f).exists()]

    def available(self):
        return (self.root / "Strings").exists()

    @property
    def sounds(self):
        if self._sounds is None:
            out = []
            for inst, folder in FOLDERS.items():
                base = self.root / folder
                dirs = [base] + (sorted(base.parent.glob(base.name + "+*")) if self.muted else [])
                for d in (d for d in dirs if d.exists()):
                    for tech in sorted(p for p in d.iterdir() if p.is_dir()):
                        for f in sorted(tech.glob("*.wav")):
                            s = parse(f, inst, tech.name)
                            if s and (s.variant == "N" or not self.originals_only):
                                out.append(s)
            self._sounds = tuple(out)
        return self._sounds

    # ---- queries ------------------------------------------------------------------------------------------------
    def select(self, instrument=None, techniques=None, dynamics=None, midi_range=None, strings=None, kind=None):
        """Sounds that match every given filter. techniques and dynamics are lists of names; midi_range is (lo, hi) inclusive;
        strings is a list of string numbers; kind is "plucked" or "bowed"."""
        lo, hi = midi_range if midi_range else (None, None)
        return [s for s in self.sounds
                if (instrument is None or s.instrument == instrument)
                and (not techniques or s.technique in techniques)
                and (not dynamics or s.dynamic in dynamics)
                and (lo is None or s.midi >= lo) and (hi is None or s.midi <= hi)
                and (not strings or s.string in strings)
                and (kind is None or s.kind == kind)]

    def techniques(self, instrument):
        """{technique: kind} of one instrument."""
        return {t: ("plucked" if instrument == "guitar" or t.startswith(PLUCKED_PREFIXES) else "bowed")
                for t in sorted({s.technique for s in self.select(instrument)})}

    def summary(self, instrument=None):
        """{technique: {dynamic: count}}"""
        out = {}
        for s in self.select(instrument):
            out.setdefault(s.technique, {}).setdefault(s.dynamic, 0)
            out[s.technique][s.dynamic] += 1
        return out

    def pitch_range(self, instrument, techniques=None):
        m = [s.midi for s in self.select(instrument, techniques)]
        return (min(m), max(m)) if m else None


def technique_group(instrument, name, library):
    """Expand a group name into technique names. Groups: "plucked", "bowed", "harmonics" (any technique with "harmonic" in its name),
    "sustained" (ordinario, sul ponticello, sul tasto, sforzato: bowed notes without tremolo). A plain technique name stays as it is."""
    techs = library.techniques(instrument)
    if name == "plucked":
        return [t for t, k in techs.items() if k == "plucked"]
    if name == "bowed":
        return [t for t, k in techs.items() if k == "bowed"]
    if name == "harmonics":
        return [t for t in techs if "harmonic" in t]
    if name == "sustained":
        return [t for t in techs if techs[t] == "bowed" and "tremolo" not in t and "harmonic" not in t and not t.startswith("col_legno")]
    return [name]
