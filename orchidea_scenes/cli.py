"""Command line:  python -m orchidea_scenes <command>

  index      [--instrument I]            what the library offers: techniques, dynamics, pitch range
  generate   --instrument I --kind K ... write scenes (mixture wav, truth json, optional stems and MIDI)
  generate   --spec scenes.json          many scenes from a file: a list of scene options (each may have "n" and "name")
"""
import argparse
import json
import sys
from pathlib import Path

from .library import FOLDERS, Library
from .scenes import ARTICULATION, KINDS, SceneSpec, generate_many


def csv(s):
    return [t for t in s.split(",") if t] if s else None


def weights(s):
    """"a,b" -> ["a", "b"];  "a:2,b:1" -> {"a": 2, "b": 1}"""
    items = csv(s)
    if not items:
        return None
    if any(":" in i for i in items):
        return {i.split(":")[0]: float(i.split(":")[1]) if ":" in i else 1.0 for i in items}
    return items


def library(a):
    lib = Library(a.root, muted=getattr(a, "muted", False))
    if not lib.available():
        sys.exit(f"OrchideaSOL not found at {lib.root}. Download it (free IRCAM Forum account, see README) and pass --root or set ORCHIDEA_ROOT.")
    return lib


def cmd_index(a):
    lib = library(a)
    for inst in ([a.instrument] if a.instrument else lib.instruments()):
        lo, hi = lib.pitch_range(inst) or (0, 0)
        print(f"\n{inst}  (MIDI {lo}-{hi})")
        for t, d in lib.summary(inst).items():
            r = lib.pitch_range(inst, [t])
            print(f"  {t:28s} {lib.techniques(inst)[t]:8s} MIDI {r[0]:3d}-{r[1]:3d}   " + "  ".join(f"{k}:{v}" for k, v in sorted(d.items())))


def cmd_generate(a):
    lib = library(a)
    jobs = []
    if a.spec:
        for j, d in enumerate(json.loads(Path(a.spec).read_text())):
            d = dict(d)
            n = d.pop("n", 1)
            d.pop("name", None)
            jobs.append((SceneSpec.from_dict(d), n))
    else:
        jobs.append((SceneSpec(
            instrument=a.instrument, kind=a.kind, voices=a.voices, hits=a.hits, duration=a.duration, techniques=weights(a.techniques),
            dynamics=weights(a.dynamics), midi_range=tuple(int(x) for x in a.midi_range.split("-")) if a.midi_range else None,
            articulation=a.articulation, polyphony=a.polyphony, distinct_strings=a.distinct_strings, gain_jitter_db=a.gain_jitter,
            sr=a.sr, normalize_peak=a.normalize, noise_snr_db=a.noise_snr, seed=a.seed), a.n))
    total = 0
    for spec, n in jobs:
        for sc in generate_many(lib, spec, n):
            sc.write(a.out, csv(a.formats))
            total += 1
            print(f"{sc.name}: {len(sc.notes)} notes, {sc.duration:.1f} s")
    print(f"wrote {total} scene(s) to {a.out}")


def main(argv=None):
    ap = argparse.ArgumentParser(prog="python -m orchidea_scenes", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", default=None, help="OrchideaSOL2020 folder (default: $ORCHIDEA_ROOT or data/_OrchideaSOL2020_release/OrchideaSOL2020)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("index")
    p.add_argument("--instrument", choices=list(FOLDERS))
    p.set_defaults(fn=cmd_index)
    g = sub.add_parser("generate")
    g.add_argument("--spec", help="JSON file: a list of scene options (see SceneSpec); each entry may have 'n' scenes")
    g.add_argument("--instrument", default="cello", choices=list(FOLDERS))
    g.add_argument("--kind", default="lines", choices=list(KINDS))
    g.add_argument("--n", type=int, default=1, help="number of scenes")
    g.add_argument("--voices", type=int, default=3)
    g.add_argument("--hits", type=int, default=3)
    g.add_argument("--duration", type=float, default=None)
    g.add_argument("--techniques", help="names or groups (plucked, bowed, sustained, harmonics), optionally weighted: plucked:1,sustained:3")
    g.add_argument("--dynamics", help="for example pp,mf,ff or pp:1,ff:2")
    g.add_argument("--midi-range", help="LO-HI, for example 40-72")
    g.add_argument("--articulation", default="note", choices=ARTICULATION, help="when technique and dynamic are drawn")
    g.add_argument("--polyphony", type=float, default=3.0, help="kind overlap: mean number of notes sounding at once")
    g.add_argument("--distinct-strings", action="store_true", help="chords use each string once")
    g.add_argument("--gain-jitter", type=float, default=0.0, help="random level change per note, +- dB")
    g.add_argument("--sr", type=int, default=44100)
    g.add_argument("--normalize", type=float, default=None, help="scale each scene to this peak, for example 0.5")
    g.add_argument("--noise-snr", type=float, default=None, help="add white noise at this SNR in dB (the stems stay clean)")
    g.add_argument("--seed", type=int, default=0)
    g.add_argument("--out", default="scenes")
    g.add_argument("--formats", default="wav,json", help="wav, json, stems, midi (comma list)")
    g.set_defaults(fn=cmd_generate)
    a = ap.parse_args(argv)
    a.fn(a)
