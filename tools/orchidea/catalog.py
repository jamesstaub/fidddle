"""Index of the OrchideaSOL2020 string one-shots, with metadata taken from the directory and file names:

  Strings/Violoncello/ordinario/Vc-ord-A3-ff-4c-N.wav  ->  instrument cello, technique ordinario, pitch A3 (MIDI 57),
  dynamic ff, string 4 ("4c" = corda), variant N.

Variant "N" is an original recording; "T12u", "R200d" etc. are transposed / resampled derivatives made for the Orchidea
library, excluded by default. Sounds without a pitch in the name (behind_the_bridge, ...) are unpitched and skipped.
Muted ("+sordina") instruments are excluded by default. Guitar lives under PluckedStrings/ and is always plucked.
"""
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
RELEASE = ROOT / "data" / "_OrchideaSOL2020_release" / "OrchideaSOL2020"
LIB = RELEASE / "Strings"

INSTRUMENT_PATHS = {"violin": LIB / "Violin", "viola": LIB / "Viola", "cello": LIB / "Violoncello", "bass": LIB / "Contrabass",
                    "guitar": RELEASE / "PluckedStrings" / "Guitar"}
_NOTE = re.compile(r"-([A-G])(#?)(-?\d)-([a-z]+)-(\d)c-(.+)\.wav$")
_SEMI = {"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11}
PLUCKED = ("pizzicato", "col_legno_battuto")          # techniques whose notes decay on their own


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
        """fidddle.synth note kind: plucked sounds decay by themselves, the rest are bowed."""
        return "plucked" if self.instrument == "guitar" or self.technique.startswith(PLUCKED) else "bowed"

    def meta(self):
        return {"file": self.path.name, "instrument": self.instrument, "technique": self.technique,
                "midi": self.midi, "dynamic": self.dynamic, "string": self.string, "variant": self.variant, "kind": self.kind}


def parse(path, instrument, technique):
    m = _NOTE.search(path.name)
    if not m:
        return None
    letter, sharp, octave, dyn, string, variant = m.groups()
    return Sound(path, instrument, technique, 12 * (int(octave) + 1) + _SEMI[letter] + (1 if sharp else 0), dyn, int(string), variant)


@lru_cache(maxsize=None)
def index(muted=False, originals_only=True):
    """All pitched string sounds as a tuple of Sound."""
    out = []
    for inst, root in INSTRUMENT_PATHS.items():
        dirs = [root] + (sorted(root.parent.glob(root.name + "+*")) if muted else [])
        for base in (d for d in dirs if d.exists()):
            for tech in sorted(p for p in base.iterdir() if p.is_dir()):
                for f in sorted(tech.glob("*.wav")):
                    s = parse(f, inst, tech.name)
                    if s and (s.variant == "N" or not originals_only):
                        out.append(s)
    return tuple(out)


def select(instrument=None, techniques=None, dynamics=None, lo=None, hi=None, **index_kw):
    return [s for s in index(**index_kw)
            if (instrument is None or s.instrument == instrument)
            and (not techniques or s.technique in techniques)
            and (not dynamics or s.dynamic in dynamics)
            and (lo is None or s.midi >= lo) and (hi is None or s.midi <= hi)]


def summary(instrument=None):
    """{technique: {dynamic: count}} for a quick look at what is available."""
    out = {}
    for s in select(instrument):
        out.setdefault(s.technique, {}).setdefault(s.dynamic, 0)
        out[s.technique][s.dynamic] += 1
    return out
