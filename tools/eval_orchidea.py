"""Evaluate fidddle (note tracking) and didddle (separation) on polyphonic scenes built from OrchideaSOL one-shots.

  index                         what the library offers per technique / dynamic
  make   --save DIR             write scenes (mix wav, per-note stems, truth json) to inspect or reuse
  tracker                       fidddle note-level P/R/F1 on the mixes, recall broken down by technique / dynamic / register
  separate nominal|detector     didddle SI-SDR gain over the mixture per stem; pitches = the file-name pitch (nominal, NOT a ceiling:
                                real notes are cents off, so the detector can beat it) or measured by fidddle on the mix

Common: --instrument cello --kind chords,intervals,strum,lines --n 4 (scenes per kind) --voices 3 --hits 3
        --techniques ordinario,pizzicato_secco --dynamics pp,mf,ff --seed 0
Truth is exact: each note is one library file placed at a known time. Pitch is the file's nominal pitch (real notes sit a
few cents off); bowed note-offs are the cut point, plucked (pizzicato, col legno battuto, all guitar) offsets are the
natural decay capped at 2.5 s. Instruments: violin viola cello contrabass guitar.
"""
import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path
import numpy as np
import soundfile as sf

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from orchidea_scenes import Library, SceneSpec, generate
from tools.orchidea import catalog

SR = 44100
KINDS = ("chords", "intervals", "strum", "lines", "overlap")


def csv(s):
    return [t for t in s.split(",") if t] if s else None


def weights(s):
    """"a,b" -> ["a", "b"];  "plucked:1,sustained:3" -> {"plucked": 1.0, "sustained": 3.0} (groups: plucked, bowed, sustained, harmonics)"""
    items = csv(s)
    if not items:
        return None
    return {i.split(":")[0]: float(i.split(":")[1]) for i in items} if any(":" in i for i in items) else items


def build_scenes(a):
    """Scenes through orchidea_scenes. Notes outside the profile's range are not drawn, unless --all-range."""
    from fidddle.profile import InstrumentProfile
    lib = Library(catalog.RELEASE)
    midi_range = None
    if not getattr(a, "all_range", False):
        pr = getattr(InstrumentProfile, a.instrument)()
        midi_range = (int(np.ceil(69 + 12 * np.log2(pr.min_frequency_hz * 0.97 / 440))), int(np.floor(69 + 12 * np.log2(pr.max_frequency_hz / 440))))
    scenes = []
    for kind in csv(a.kind) or KINDS:
        spec = SceneSpec(instrument=a.instrument, kind=kind, voices=a.voices, hits=a.hits, techniques=weights(a.techniques), dynamics=weights(a.dynamics),
                         midi_range=midi_range, articulation=getattr(a, "articulation", "note"), polyphony=getattr(a, "polyphony", 3.0),
                         normalize_peak=getattr(a, "normalize", None), distinct_strings=(a.instrument == "guitar"), seed=a.seed, sr=SR)
        for i in range(a.n):
            sc = generate(lib, spec, i)
            scenes.append({"name": sc.name, "kind": kind, "instrument": a.instrument, "mix": sc.audio, "stems": sc.stems, "notes": sc.notes, "gain": sc.gain})
    return scenes


# ---- reporting ----------------------------------------------------------------------------------

def table(title, groups, cols):
    print(f"\n{title}")
    for k in sorted(groups):
        v = groups[k]
        print(f"  {k:28s}" + "".join(f"{f(v):>{w}}" for _, w, f in cols))


def register(n, lo, hi):
    t = (n["midi"] - lo) / max(hi - lo, 1)
    return "low" if t < 1 / 3 else "mid" if t < 2 / 3 else "high"


# ---- commands -----------------------------------------------------------------------------------

def cmd_index(a):
    for inst in ([a.instrument] if a.instrument else catalog.INSTRUMENT_PATHS):
        print(f"\n{inst}")
        for t, d in catalog.summary(inst).items():
            print(f"  {t:28s}" + "  ".join(f"{k}:{v}" for k, v in sorted(d.items())))


def cmd_make(a):
    out = Path(a.save or ROOT / "data" / "orchidea")
    (out / "stems").mkdir(parents=True, exist_ok=True)
    for s in build_scenes(a):
        sf.write(out / f"{s['name']}.wav", s["mix"], SR, subtype="PCM_24")
        for i, st in enumerate(s["stems"]):
            sf.write(out / "stems" / f"{s['name']}.n{i}.wav", st, SR, subtype="PCM_24")
        (out / f"{s['name']}.json").write_text(json.dumps({"sr": SR, "kind": s["kind"], "gain": s["gain"], "notes": s["notes"]}, indent=1))
    print("wrote", len(list(out.glob("*.json"))), "scenes to", out)


def cmd_tracker(a):
    from fidddle.profile import DetectorConfig
    from tools.eval_tracker import run, score
    from tools.eval_fit import set_overrides
    scenes = build_scenes(a)
    lo, hi = min(s.midi for s in catalog.select(a.instrument)), max(s.midi for s in catalog.select(a.instrument))
    by = {"kind": defaultdict(list), "technique": defaultdict(list), "dynamic": defaultdict(list), "register": defaultdict(list)}
    per_kind = defaultdict(list)
    for s in scenes:
        cfg = DetectorConfig.for_instrument(a.instrument, float(SR))
        set_overrides(cfg, a.set)
        est, _ = run(cfg, s["mix"], SR)
        ref = [(n["onset"], n["offset"], n["midi"]) for n in s["notes"]]
        sc = score(ref, est, a.tol)
        per_kind[s["kind"]].append(sc)
        for n in s["notes"]:
            hit = any(abs(e[0] - n["onset"]) <= a.tol and e[2] == n["midi"] for e in est)
            for dim, key in (("kind", s["kind"]), ("technique", n["technique"]), ("dynamic", n["dynamic"]), ("register", register(n, lo, hi))):
                by[dim][key].append(hit)
    print(f"fidddle tracker on {len(scenes)} scenes, {a.instrument}, onset tol {a.tol}s, pitch must match exactly")
    rows = {}
    for k, rs in per_kind.items():
        w = np.array([r["n_ref"] for r in rs], float)
        rows[k] = {m: np.average([r[m] for r in rs], weights=w) for m in ("P", "R", "F1")} | {"n_est": sum(r["n_est"] for r in rs), "n_ref": int(w.sum())}
    table("scene kind", rows, [("P", 7, lambda v: f"{v['P']:.2f}"), ("R", 7, lambda v: f"{v['R']:.2f}"), ("F1", 7, lambda v: f"{v['F1']:.2f}"), ("est/ref", 12, lambda v: f"{v['n_est']}/{v['n_ref']}")])
    for dim in ("technique", "dynamic", "register"):
        table(f"recall by {dim}", by[dim], [("recall", 8, lambda v: f"{np.mean(v):.2f}"), ("n", 6, lambda v: f"{len(v)}")])


def cmd_separate(a):
    from didddle.config import SeparatorConfig
    from didddle.f0 import truth_tracks, truth_spans, run_detector, tracks_from_run, spans_from_run, split_notes
    from didddle.metrics import score, group_channels
    from didddle.separate import Separator
    from fidddle.profile import DetectorConfig, InstrumentProfile
    from fidddle.synth import Note
    from tools.eval_separation import horizons
    prof = InstrumentProfile.by_name(a.instrument)
    scenes = build_scenes(a)
    by = {"kind": defaultdict(list), "technique": defaultdict(list), "dynamic": defaultdict(list)}
    for s in scenes:
        cfg = SeparatorConfig.from_profile(prof, float(SR), method=a.method)
        sep = Separator(cfg)
        mix, stems = s["mix"], s["stems"]
        c = sep.centers(len(mix))
        if a.mode == "nominal":
            notes = [Note(n["midi"], n["onset"], n["offset"], n["kind"]) for n in s["notes"]]
            voices, _ = sep.process(mix, truth_tracks(notes, SR, len(mix), c), truth_spans(notes, SR))
            est = voices
        else:
            run = run_detector(mix, DetectorConfig.for_instrument(a.instrument, float(SR)))
            look_f0, look_gate = horizons(max(a.latency / 1000, cfg.n_fft / SR), cfg)
            f0 = tracks_from_run(run, c, look_f0, cfg.n_fft // 2)
            spans = spans_from_run(run, look_gate, cfg.onset_lead_ms / 1000)
            f0, spans = split_notes(f0, spans, c, cfg.n_fft // 2)
            if len(f0) == 0:
                est = np.zeros_like(stems)
            else:
                voices, _ = sep.process(mix, f0, spans)
                est = group_channels(voices, stems)
        _, gain = score(est, stems, mix)
        for n, g in zip(s["notes"], gain):
            for dim, key in (("kind", s["kind"]), ("technique", n["technique"]), ("dynamic", n["dynamic"])):
                by[dim][key].append(g)
    print(f"didddle {a.method}, pitches: {a.mode}{'' if a.mode == 'nominal' else f' (fidddle on the mix, {a.latency:.0f} ms)'}; "
          f"{len(scenes)} scenes, {a.instrument}. SI-SDR gain over the mixture, per note stem (dB)")
    for dim in by:
        table(f"by {dim}", by[dim], [("mean", 8, lambda v: f"{np.mean(v):.1f}"), ("median", 8, lambda v: f"{np.median(v):.1f}"), ("n", 6, lambda v: f"{len(v)}")])
    allg = [g for v in by["kind"].values() for g in v]
    print(f"\nall notes: mean {np.mean(allg):.1f} dB, median {np.median(allg):.1f} dB (n={len(allg)})")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    def common(p):
        p.add_argument("--instrument", default="cello", choices=list(catalog.INSTRUMENT_PATHS))
        p.add_argument("--kind", default=None, help=f"comma list of {','.join(KINDS)} (default all)")
        p.add_argument("--n", type=int, default=4, help="scenes per kind")
        p.add_argument("--voices", type=int, default=3)
        p.add_argument("--hits", type=int, default=3)
        p.add_argument("--techniques", default=None, help="names or groups, optionally weighted: plucked:1,sustained:3")
        p.add_argument("--dynamics", default=None)
        p.add_argument("--seed", type=int, default=0)
        p.add_argument("--articulation", default="note", choices=["note", "voice", "scene"], help="when technique and dynamic are drawn")
        p.add_argument("--polyphony", type=float, default=3.0, help="kind overlap: mean number of notes sounding at once")
        p.add_argument("--normalize", type=float, default=None, help="scale each scene to this peak, for example 0.5")
        p.add_argument("--all-range", action="store_true", help="also draw notes outside the instrument profile's frequency range")

    p = sub.add_parser("index"); p.add_argument("--instrument", default=None, choices=list(catalog.INSTRUMENT_PATHS)); p.set_defaults(fn=cmd_index)
    p = sub.add_parser("make"); common(p); p.add_argument("--save", default=None); p.set_defaults(fn=cmd_make)
    p = sub.add_parser("tracker"); common(p); p.add_argument("--tol", type=float, default=0.15); p.add_argument("--set", action="append"); p.set_defaults(fn=cmd_tracker)
    p = sub.add_parser("separate"); p.add_argument("mode", choices=["nominal", "detector"]); common(p)
    p.add_argument("--method", default="ls"); p.add_argument("--latency", type=float, default=250.0); p.set_defaults(fn=cmd_separate)
    a = ap.parse_args()
    a.fn(a)


if __name__ == "__main__":
    main()
