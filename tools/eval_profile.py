"""Compare detector settings on OrchideaSOL scenes: note-level P/R/F1 per scene group and variant.

  .venv/bin/python tools/eval_profile.py contrabass --groups bowed,plucked,mixed \\
      --variant "default" --variant "no-attack:attack_min_db=0" --variant "B0:profile.inharmonicity_B=0"

A variant is `name` or `name:key=value,key=value`. Keys are DetectorConfig fields; `profile.<field>` edits the instrument profile
(for example profile.max_frequency_hz). Scene groups are defined in GROUPS below (technique mixes, drawn per note).
"""
import argparse
import sys
from argparse import Namespace
from multiprocessing import Pool
from pathlib import Path
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from fidddle.analyzer import Analyzer
from fidddle.profile import DetectorConfig
from tools import eval_orchidea as eo
from tools.eval_tracker import events_to_notes, score

GROUPS = {
    "bowed": dict(techniques="sustained", dynamics="pp,mf,ff"),
    "tremolo": dict(techniques="tremolo,sul_ponticello_tremolo,sul_tasto_tremolo"),
    "plucked": dict(techniques="plucked", dynamics="pp,mf,ff"),
    "mixed": dict(techniques="plucked:1,sustained:2", dynamics="pp,mf,ff"),
    "harmonics": dict(techniques="harmonics"),
    "all": dict(techniques=None, dynamics=None),
}


def apply(cfg, settings):
    for k, v in settings:
        obj, name = (cfg.profile, k[8:]) if k.startswith("profile.") else (cfg, k)
        cur = getattr(obj, name)
        setattr(obj, name, type(cur)(float(v)) if isinstance(cur, (int, float)) and not isinstance(cur, bool) else type(cur)(v in ("1", "true", "True")) if isinstance(cur, bool) else v)


def _run(task):
    inst, vname, settings, group, mix, notes, tol = task
    cfg = DetectorConfig.for_instrument(inst, float(eo.SR))
    apply(cfg, settings)
    az = Analyzer(cfg)
    az.run(mix, track=True)
    return group, vname, score([(n["onset"], n["offset"], n["midi"]) for n in notes], events_to_notes(az.events, eo.SR), tol)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("instrument")
    ap.add_argument("--groups", default="bowed,plucked,mixed")
    ap.add_argument("--variant", action="append", default=[])
    ap.add_argument("--kinds", default="overlap,chords,lines")
    ap.add_argument("--n", type=int, default=4)
    ap.add_argument("--voices", type=int, default=3)
    ap.add_argument("--seed", type=int, default=21)
    ap.add_argument("--tol", type=float, default=0.15)
    ap.add_argument("--normalize", type=float, default=None)
    ap.add_argument("--all-range", action="store_true")
    a = ap.parse_args()
    variants = []
    for v in a.variant or ["default"]:
        name, _, rest = v.partition(":")
        variants.append((name, [tuple(kv.split("=")) for kv in rest.split(",") if kv]))
    tasks = []
    for g in a.groups.split(","):
        ns = Namespace(instrument=a.instrument, kind=a.kinds, n=a.n, voices=a.voices, hits=2, techniques=GROUPS[g].get("techniques"), dynamics=GROUPS[g].get("dynamics"),
                       seed=a.seed, all_range=a.all_range, articulation="note", polyphony=3.0, normalize=a.normalize)
        for sc in eo.build_scenes(ns):
            for name, settings in variants:
                tasks.append((a.instrument, name, settings, g, sc["mix"], sc["notes"], a.tol))
    with Pool(6) as p:
        res = p.map(_run, tasks)
    print(f"{a.instrument}: note P / R / F1 (est count) per group; scenes: {a.kinds}, {a.n} each")
    print(f"{'variant':22s}" + "".join(f"{g:>26s}" for g in a.groups.split(",")))
    for name, _ in variants:
        cells = []
        for g in a.groups.split(","):
            rs = [r for gg, vv, r in res if gg == g and vv == name]
            w = np.array([r["n_ref"] for r in rs], float)
            m = {k: np.average([r[k] for r in rs], weights=w) for k in ("P", "R", "F1")}
            cells.append(f"{m['P']:.2f}/{m['R']:.2f}/{m['F1']:.2f} ({sum(r['n_est'] for r in rs)}/{int(w.sum())})")
        print(f"{name:22s}" + "".join(f"{c:>26s}" for c in cells))


if __name__ == "__main__":
    main()
