"""CLI for rendering ground-truth test clips with the Spitfire BBC Symphony Orchestra VST. See
.claude/skills/bbcso-render/SKILL.md.

  status                              what is installed / captured / missing
  capture [--instrument ..] [--player section]   interactively save plugin states (one patch each; needs a human at the plugin UI; default: the 15 core leader patches)
  verify                              render a probe note per state; flags patches that behave like the wrong articulation
  params                              list the plugin's named parameters (dynamics, vibrato, mics, ...)
  scene  NAME --instrument cello --articulation pizzicato [--player leader]     single-voice scene
  pair   --lo cello --hi violin --interval fifth --articulation long             two-voice interval scene
  midi   FILE.mid --instrument cello --articulation spiccato                     render an existing MIDI file
  batch  SPEC.json                    many scenes (see SKILL.md for the spec format)
"""
import argparse
import json
import sys
from pathlib import Path
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from tools.bbcso import catalog, midi, scenes, states
from tools.bbcso.render import Track, render_scene, OUT_DIR


def parse_params(items):
    out = {}
    for it in items or []:
        k, _, v = it.rpartition("=")
        out[k] = float(v)
    return out


def cmd_status(a):
    import importlib.util
    print("VST3      :", catalog.VST3, "OK" if catalog.VST3.exists() else "MISSING")
    print("library   :", catalog.LIB, "OK" if catalog.LIB.exists() else "MISSING")
    print("dawdreamer:", "OK" if importlib.util.find_spec("dawdreamer") else "MISSING (pip install dawdreamer)")
    have = set(states.captured())
    print(f"\ncaptured patch states ({len(have)}) in {states.STATE_DIR}:")
    for inst, pl, art in sorted(have):
        print(f"  {inst:7s} {pl:8s} {art}")
    miss = [w for w in states.wanted() if w not in have]
    print(f"\ncore set not yet captured ({len(miss)}):")
    for inst, pl, art in miss:
        print(f"  {inst:7s} {pl:8s} {art:10s} -> pick '{catalog.patch_name(inst, art, pl)}'")


def cmd_capture(a):
    todo = states.wanted(a.instrument or None, a.player or ("leader",), a.articulation or None)
    have = set(states.captured())
    todo = [w for w in todo if a.force or w not in have]
    if not todo:
        print("nothing to capture")
        return
    try:
        for w in todo:
            states.capture(*w)
    except KeyboardInterrupt:
        print("\nstopped")


def cmd_verify(a):
    bad = 0
    for inst, pl, art in states.captured():
        ok, msg = states.check(inst, pl, art)
        bad += not ok
        print(f"{'ok ' if ok else 'BAD'} {inst:7s} {pl:8s} {art:10s} {msg}")
    print(f"\n{bad} suspicious state(s)" if bad else "\nall states behave as expected")


def cmd_params(a):
    import dawdreamer as daw
    e = daw.RenderEngine(44100, 512)
    p = e.make_plugin_processor("bbcso", str(catalog.VST3))
    for d in p.get_plugin_parameters_description():
        if not d["name"].startswith("MIDI CC"):
            print(f"{d['index']:3d} {d['name']:24s} default={d['defaultValueText']:>8s}  range {d['min']}..{d['max']}")


def common_track(a, name, inst, notes):
    return Track(name, inst, a.player, a.articulation, notes, a.dynamics, parse_params(a.param))


def finish(a, name, tracks, scenario):
    meta = render_scene(name, tracks, sr=a.sr, mono=not a.stereo, stereo=a.stereo, out_dir=a.out, settle=a.settle, scenario=scenario)
    print(f"wrote {Path(a.out or OUT_DIR) / name}.wav (+ .mid .json .stems/) : {len(meta['notes'])} notes, gain {meta['gain']:.2f}")


def cmd_scene(a):
    fn = scenes.MONO_SCENES[a.kind]
    kw = {k: v for k, v in dict(seed=a.seed, root=a.root).items() if v is not None}
    notes = fn(a.instrument, **kw)
    name = a.name or f"{a.kind}_{a.instrument}_{a.player}_{a.articulation}"
    finish(a, name, [common_track(a, a.instrument, a.instrument, notes)], {"kind": a.kind, **kw})


def cmd_pair(a):
    pair = scenes.interval_pair(a.lo, a.hi, a.interval, root=a.root)
    name = a.name or f"pair_{a.lo}_{a.hi}_{a.interval}_{a.player}_{a.articulation}"
    tracks = [common_track(a, k, inst, notes) for k, (inst, notes) in pair.items()]
    finish(a, name, tracks, {"kind": "pair", "interval": a.interval})


def cmd_midi(a):
    tr = midi.read_midi(a.file)
    name = a.name or Path(a.file).stem
    tracks = [common_track(a, k, a.instrument, notes) for k, notes in tr.items()]
    finish(a, name, tracks, {"kind": "midi", "file": str(a.file)})


def cmd_batch(a):
    """SPEC.json: {"defaults": {...}, "scenes": [{"name":..., "kind": "scale"|"pair"|"staggered"|"midi", ...}]}
    Per-track keys: instrument, player, articulation, dynamics, params. Scene-level keys override defaults."""
    spec = json.loads(Path(a.spec).read_text())
    base = spec.get("defaults", {})
    for sc in spec["scenes"]:
        c = {**base, **sc}
        kind = c["kind"]
        trk = lambda name, inst, notes: Track(name, inst, c.get("player", "leader"), c.get("articulation", "long"), notes,
                                              c.get("dynamics", 127), c.get("params", {}))
        if kind == "pair":
            pr = scenes.interval_pair(c["lo"], c["hi"], c.get("interval", "fifth"), root=c.get("root"))
            tracks = [trk(k, inst, n) for k, (inst, n) in pr.items()]
        elif kind == "staggered":
            st = scenes.staggered(c["instruments"], seed=c.get("seed", 0), count=c.get("count", 8), overlap=c.get("overlap", 0.5))
            tracks = [trk(k, inst, n) for k, (inst, n) in st.items()]
        elif kind == "midi":
            tracks = [trk(k, c["instrument"], n) for k, n in midi.read_midi(c["file"]).items()]
        else:
            kw = {k: c[k] for k in ("seed", "root", "count", "note_s", "gap_s", "vel", "midi") if k in c}
            tracks = [trk(c["instrument"], c["instrument"], scenes.MONO_SCENES[kind](c["instrument"], **kw))]
        meta = render_scene(c["name"], tracks, sr=c.get("sr", 44100), stereo=c.get("stereo", False), out_dir=c.get("out"),
                            settle=c.get("settle", 3.0), scenario=c)
        print(f"{c['name']}: {len(meta['notes'])} notes, {len(meta['warnings'])} warnings")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    def add_render_opts(p):
        p.add_argument("--instrument", default="cello", choices=list(catalog.INSTRUMENTS))
        p.add_argument("--articulation", default="long", choices=list(catalog.ARTICULATIONS))
        p.add_argument("--player", default="leader", choices=["leader", "section"], help="leader = one solo player (closest to a real solo instrument)")
        p.add_argument("--dynamics", type=int, default=127, help="0-127 (plugin Dynamics parameter)")
        p.add_argument("--param", action="append", metavar="NAME=VAL", help='plugin parameter 0-1, e.g. "Vibrato=0"')
        p.add_argument("--sr", type=int, default=44100)
        p.add_argument("--stereo", action="store_true")
        p.add_argument("--settle", type=float, default=3.0, help="seconds to wait for samples to load before rendering")
        p.add_argument("--out", default=None)
        p.add_argument("--name", default=None)

    sub.add_parser("status").set_defaults(fn=cmd_status)
    sub.add_parser("verify").set_defaults(fn=cmd_verify)
    sub.add_parser("params").set_defaults(fn=cmd_params)
    c = sub.add_parser("capture")
    c.add_argument("--instrument", action="append")
    c.add_argument("--player", action="append")
    c.add_argument("--articulation", action="append")
    c.add_argument("--force", action="store_true")
    c.set_defaults(fn=cmd_capture)
    s = sub.add_parser("scene")
    s.add_argument("kind", choices=list(scenes.MONO_SCENES))
    s.add_argument("--seed", type=int, default=None)
    s.add_argument("--root", type=int, default=None)
    add_render_opts(s)
    s.set_defaults(fn=cmd_scene)
    p = sub.add_parser("pair")
    p.add_argument("--lo", default="cello", choices=list(catalog.INSTRUMENTS))
    p.add_argument("--hi", default="violin", choices=list(catalog.INSTRUMENTS))
    p.add_argument("--interval", default="fifth")
    p.add_argument("--root", type=int, default=None)
    add_render_opts(p)
    p.set_defaults(fn=cmd_pair)
    m = sub.add_parser("midi")
    m.add_argument("file")
    add_render_opts(m)
    m.set_defaults(fn=cmd_midi)
    b = sub.add_parser("batch")
    b.add_argument("spec")
    b.set_defaults(fn=cmd_batch)
    a = ap.parse_args()
    a.fn(a)


if __name__ == "__main__":
    main()
