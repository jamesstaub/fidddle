"""Classify false notes and misses of fidddle on OrchideaSOL scenes (python reference).

Every estimated note is labelled by its relation to the truth note it overlaps in time: ok (right pitch, onset within --tol),
late (right pitch, onset later than --tol: a slow attack, or a re-detection after a gap), split (a second event of the same
pitch inside one truth note), sub (an octave or more below a sounding truth pitch), super (an octave or more above),
fifth (a twelfth or a fifth, +/-7 or 19 semitones), near (within 2 semitones), other, orphan (no truth note sounding).

  .venv/bin/python tools/orchidea_errors.py --instrument cello --techniques ordinario --kind lines --voices 1 --n 12 [--set k=v]
"""
import argparse
import sys
from collections import Counter, defaultdict
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from tools import eval_orchidea as eo
from fidddle.profile import DetectorConfig
from tools.eval_tracker import run
from tools.eval_fit import set_overrides


def classify(e, truth, tol):
    on, off, m = e[0], e[1], e[2]
    sound = [t for t in truth if t["onset"] - 0.05 <= (on + off) / 2 <= t["end"] + 0.1]
    if not sound:
        return "orphan", None
    for t in sound:
        if t["midi"] == m:
            if abs(on - t["onset"]) <= tol:
                return "ok", t
            return ("late" if on > t["onset"] else "early"), t
    t = min(sound, key=lambda t: abs(t["midi"] - m))
    d = m - t["midi"]
    if abs(d) <= 2:
        return "near", t
    if d % 12 == 0:
        return ("sub" if d < 0 else "super"), t
    if abs(d) in (7, 19):
        return "fifth", t
    return "other", t


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    for k, d in (("instrument", "cello"), ("kind", "lines"), ("techniques", None), ("dynamics", None)):
        ap.add_argument("--" + k, default=d)
    for k, d in (("n", 8), ("voices", 1), ("hits", 3), ("seed", 0)):
        ap.add_argument("--" + k, type=int, default=d)
    ap.add_argument("--tol", type=float, default=0.15)
    ap.add_argument("--all-range", action="store_true")
    ap.add_argument("--set", action="append")
    a = ap.parse_args()
    cnt, miss, by_dyn, by_reg = Counter(), Counter(), defaultdict(Counter), defaultdict(Counter)
    dur = defaultdict(list)
    ntruth = 0
    for s in eo.build_scenes(a):
        cfg = DetectorConfig.for_instrument(a.instrument, float(eo.SR))
        set_overrides(cfg, [t for t in a.set or [] if not t.startswith("profile.")])
        for t in a.set or []:      # profile.<field>=<value> edits the instrument profile (for example profile.inharmonicity_B=3e-4)
            if t.startswith("profile."):
                k, v = t[8:].split("=")
                setattr(cfg.profile, k, type(getattr(cfg.profile, k))(v))
        est, _ = run(cfg, s["mix"], eo.SR)
        truth = s["notes"]
        for t in truth:
            t.setdefault("end", t["offset"] + 0.1)
        ntruth += len(truth)
        for e in est:
            c, t = classify(e, truth, a.tol)
            cnt[c] += 1
            dur[c].append(e[1] - e[0])
            if t is not None:
                by_dyn[t["dynamic"]][c] += 1
        for t in truth:
            if not any(e[2] == t["midi"] and abs(e[0] - t["onset"]) <= a.tol for e in est):
                miss[t["dynamic"]] += 1
                miss["_all"] += 1
    n_est = sum(cnt.values())
    print(f"{a.instrument} {a.techniques or 'all techniques'}: {ntruth} true notes, {n_est} detected, {miss['_all']} true notes without a matching note-on")
    print("detected notes by class: " + "  ".join(f"{k} {v} (median {sorted(dur[k])[len(dur[k]) // 2]:.2f}s)" for k, v in cnt.most_common()))
    for d in sorted(by_dyn):
        print(f"  during truth dynamic {d}: " + "  ".join(f"{k} {v}" for k, v in by_dyn[d].most_common()) + f"   | missed {miss[d]}")


if __name__ == "__main__":
    main()
