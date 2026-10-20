"""Benchmark fidddle (note tracking) on rendered Spitfire BBCSO audio with exact truth.

  .venv/bin/python tools/eval_bbcso.py render     # build the scene set and render it to data/bbcso/bench (about 5 minutes)
  .venv/bin/python tools/eval_bbcso.py eval       # score every rendered scene with the C++ detector and print grouped tables

The audio is a sampled orchestral library with a baked-in hall: it tests note logic, onsets, articulation handling and pairs at
known intervals, NOT phase, inharmonicity or dispersion of a single dry instrument. Truth onsets are the measured sound start
(`audio_onset`); detector delay is reported, not folded into the truth. Notes the renderer marks silent are dropped.
"""
import argparse
import json
import subprocess
import sys
from collections import defaultdict
from pathlib import Path
import numpy as np
import mir_eval
import soundfile as sf

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from tools.notes_report import run, pair

BENCH = ROOT / "data" / "bbcso" / "bench"   # set from --bench (a sibling directory name)
PROFILE = {"violin": "violin", "viola": "viola", "cello": "cello", "bass": "bass"}
ORDER = ["violin", "viola", "cello", "bass"]


def build_spec(dyn=90, params=None):
    scenes = []
    for inst in ORDER:
        arts = ["long", "pizzicato", "spiccato"] + ([] if inst == "bass" else ["tremolo"])
        for art in arts:
            for kind in ("open_strings", "scale", "repeated"):
                scenes.append({"name": f"{inst}_{art}_{kind}", "kind": kind, "instrument": inst, "articulation": art})
            for seed in (1, 2):
                scenes.append({"name": f"{inst}_{art}_random{seed}", "kind": "random_line", "instrument": inst, "articulation": art, "seed": seed})
    for lo, hi in (("cello", "viola"), ("viola", "violin"), ("cello", "violin")):
        for iv in ("minor_third", "major_third", "fourth", "tritone", "fifth", "major_sixth", "octave"):
            scenes.append({"name": f"pair_{lo}_{hi}_long_{iv}", "kind": "pair", "lo": lo, "hi": hi, "interval": iv, "articulation": "long"})
    for iv in ("major_third", "fifth", "octave"):
        scenes.append({"name": f"pair_cello_viola_pizzicato_{iv}", "kind": "pair", "lo": "cello", "hi": "viola", "interval": iv, "articulation": "pizzicato"})
    for art in ("long", "pizzicato"):
        scenes.append({"name": f"staggered3_{art}", "kind": "staggered", "instruments": ["cello", "viola", "violin"], "articulation": art, "seed": 4, "count": 6})
    for sc in scenes:
        sc["out"] = str(BENCH)
    d = {"player": "leader", "dynamics": dyn}
    if params:
        d["params"] = params
    return {"defaults": d, "scenes": scenes}


def cmd_render(a):
    BENCH.mkdir(parents=True, exist_ok=True)
    spec = ROOT / "data" / "bbcso" / f"{BENCH.name}_spec.json"
    params = dict(kv.split("=") for kv in a.param) if a.param else None
    params = {k: float(v) for k, v in params.items()} if params else None
    spec.write_text(json.dumps(build_spec(a.dynamics, params), indent=1))
    todo = [s for s in json.loads(spec.read_text())["scenes"] if a.force or not (BENCH / f"{s['name']}.json").exists()]
    if not todo:
        print("all scenes already rendered (use --force to redo)")
        return
    sub = json.loads(spec.read_text())
    sub["scenes"] = todo
    part = ROOT / "data" / "bbcso" / f"{BENCH.name}_todo.json"
    part.write_text(json.dumps(sub))
    subprocess.run([sys.executable, str(ROOT / "tools" / "bbcso_render.py"), "batch", str(part)], check=True)


def scene_profile(meta):
    sc = meta["scenario"]
    inst = sc.get("instrument") or sc.get("lo") or meta["tracks"][0]["instrument"]
    if sc.get("kind") == "staggered":
        inst = "cello"
    return PROFILE[inst]


def noise_bed(seconds=2.0):
    """The quietest `seconds` of the real noisy-DI recordings (broadband noise, 60 Hz hum and its harmonics, a 13 kHz line)."""
    best = None
    for f in sorted((ROOT / "data").glob("*.wav")):
        x, sr = sf.read(f, always_2d=True)
        m = x[:, 0]
        n = int(seconds * sr)
        hop = int(0.25 * sr)
        for i in range(0, len(m) - n, hop):
            r = float(np.sqrt(np.mean(m[i:i + n] ** 2)))
            if r > 0 and (best is None or r < best[0]):
                best = (r, m[i:i + n].copy(), f.name, sr)
    return best


def with_noise(wav, snr_db, td):
    """Mix the real DI noise bed into a rendered scene at the given SNR (against the RMS of the scene's active audio)."""
    x, sr = sf.read(wav)
    x = x if x.ndim == 1 else x[:, 0]
    r, bed, name, bsr = noise_bed()
    assert bsr == sr
    reps = int(np.ceil(len(x) / len(bed)))
    n = np.tile(bed, reps)[:len(x)]
    # RMS of the frames that carry signal (the noise-only gaps would otherwise set the level)
    fr = x[: len(x) // 2048 * 2048].reshape(-1, 2048)
    active = np.sqrt(np.mean(fr ** 2, axis=1))
    sig = float(np.sqrt(np.mean(active[active > 0.2 * active.max()] ** 2)))
    gain = sig / (10 ** (snr_db / 20.0)) / max(float(np.sqrt(np.mean(n ** 2))), 1e-12)
    out = Path(td) / (Path(wav).stem + f"_snr{int(snr_db)}.wav")
    sf.write(out, x + gain * n, sr, subtype="PCM_24")
    return out


def score_scene(wav, meta, snr=None, extra=()):
    prof = scene_profile(meta)
    if snr is not None:
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            events, summ = run(with_noise(wav, snr, td), prof, list(extra))
    else:
        events, summ = run(wav, prof, list(extra))
    sr = summ["sr"]
    est = pair(events, sr)
    notes = [n for n in meta["notes"] if not n.get("silent")]
    res = {"profile": prof, "n_ref": len(notes), "n_est": len(est), "dur": summ["samples"] / sr,
           "no_audio_onset": sum(1 for n in notes if "audio_onset" not in n)}
    if not notes:
        return res
    t_ref = np.array([n.get("audio_onset", n["onset"]) for n in notes])
    ri = np.stack([t_ref, np.maximum(np.array([n["offset"] for n in notes]), t_ref + 0.02)], axis=1)
    rp = 440.0 * 2 ** ((np.array([n["midi"] for n in notes]) - 69) / 12)
    if est:
        ei = np.array([[e["t0"], max(e["t1"], e["t0"] + 0.02)] for e in est])
        ep = 440.0 * 2 ** ((np.array([e["midi"] for e in est]) - 69) / 12)
        m = mir_eval.transcription.match_notes(ri, rp, ei, ep, onset_tolerance=0.1, pitch_tolerance=50.0, offset_ratio=None)
        tp = len(m)
        res.update(tp=tp, P=tp / len(est), R=tp / len(notes))
        # latency: the delivery time of each matched note minus the true sound start (events carry deliver samples)
        deliver = {}
        for e in events:
            if e["ev"] == "on":
                deliver[e["id"]] = e["deliver"] / sr
        ids = [e["id"] for e in est]
        res["lat"] = [deliver[ids[j]] - t_ref[i] for i, j in m]
        res["matched_ref"] = [notes[i]["src"] for i, _ in m]
        # second view: accept a note delivered 0..0.4 s after the true start (what a user sees)
        dt = np.array([deliver[i] for i in ids])
        ei2 = np.stack([dt - 0.2, dt - 0.19], axis=1)
        m2 = mir_eval.transcription.match_notes(ri, rp, ei2, ep, onset_tolerance=0.2, pitch_tolerance=50.0, offset_ratio=None)
        res["tp_deliver"] = len(m2)
    else:
        res.update(tp=0, P=0.0, R=0.0, lat=[], matched_ref=[], tp_deliver=0)
    res["src_ref"] = [n["src"] for n in notes]
    return res


def f1(p, r):
    return 2 * p * r / (p + r) if p + r > 0 else 0.0


def agg(rows):
    tp = sum(r.get("tp", 0) for r in rows); ne = sum(r["n_est"] for r in rows); nr = sum(r["n_ref"] for r in rows)
    tpd = sum(r.get("tp_deliver", 0) for r in rows)
    P = tp / ne if ne else 0.0; R = tp / nr if nr else 0.0
    lat = [x for r in rows for x in r.get("lat", [])]
    mins = sum(r["dur"] for r in rows) / 60.0
    return dict(n=len(rows), nref=nr, nest=ne, P=P, R=R, F1=f1(P, R), Rd=tpd / nr if nr else 0.0,
                lat=1000 * float(np.median(lat)) if lat else float("nan"), ghosts_per_min=(ne - tp) / mins if mins else 0.0)


def cmd_eval(a):
    rows = {}
    for js in sorted(BENCH.glob("*.json")):
        meta = json.loads(js.read_text())
        wav = js.with_suffix(".wav")
        if not wav.exists() or meta.get("warnings") and a.skip_warned:
            continue
        if a.only and a.only not in js.stem:
            continue
        rows[js.stem] = (meta, score_scene(wav, meta, a.snr, [t for kv in a.set for t in ('--set', kv)]))
    if not rows:
        print("nothing rendered yet: run `render` first")
        return
    hdr = f"{'group':34s} {'scenes':>6s} {'ref':>5s} {'est':>5s} {'P':>5s} {'R':>5s} {'F1':>5s} {'R(del)':>6s} {'lat ms':>6s} {'ghost/min':>9s}"
    def show(title, groups):
        print(f"\n{title}\n{hdr}")
        for k, rs in groups:
            g = agg(rs)
            print(f"{k:34s} {g['n']:6d} {g['nref']:5d} {g['nest']:5d} {g['P']:5.2f} {g['R']:5.2f} {g['F1']:5.2f} {g['Rd']:6.2f} {g['lat']:6.0f} {g['ghosts_per_min']:9.1f}")
    mono = {k: v for k, v in rows.items() if v[0]["scenario"]["kind"] in ("open_strings", "scale", "repeated", "random_line")}
    by_art = defaultdict(list); by_inst = defaultdict(list); by_kind = defaultdict(list); by_ia = defaultdict(list)
    for k, (meta, r) in mono.items():
        sc = meta["scenario"]
        by_art[sc["articulation"]].append(r); by_inst[sc["instrument"]].append(r); by_kind[sc["kind"]].append(r)
        by_ia[(sc["instrument"], sc["articulation"])].append(r)
    show("MONOPHONIC, by articulation", sorted(by_art.items()))
    show("MONOPHONIC, by instrument", [(i, by_inst[i]) for i in ORDER if i in by_inst])
    show("MONOPHONIC, by scene kind", sorted(by_kind.items()))
    show("MONOPHONIC, instrument x articulation", [(f"{i} {a_}", by_ia[(i, a_)]) for i in ORDER for a_ in ("long", "pizzicato", "spiccato", "tremolo") if (i, a_) in by_ia])
    pairs = {k: v for k, v in rows.items() if v[0]["scenario"]["kind"] == "pair"}
    if pairs:
        by_iv = defaultdict(list); by_art_p = defaultdict(list)
        lo_hit = defaultdict(lambda: [0, 0]); hi_hit = defaultdict(lambda: [0, 0])
        for k, (meta, r) in pairs.items():
            sc = meta["scenario"]
            by_iv[sc["interval"]].append(r); by_art_p[sc["articulation"]].append(r)
            tracks = [t["track"] for t in meta["tracks"]]
            for which, src in zip(("lo", "hi"), tracks):
                tot = sum(1 for s in r.get("src_ref", []) if s == src)
                got = sum(1 for s in r.get("matched_ref", []) if s == src)
                tgt = lo_hit if which == "lo" else hi_hit
                tgt[sc["interval"]][0] += got; tgt[sc["interval"]][1] += tot
        order = ["minor_third", "major_third", "fourth", "tritone", "fifth", "major_sixth", "octave"]
        show("PAIRS (two instruments), by interval", [(i, by_iv[i]) for i in order if i in by_iv])
        print("\nrecall of each voice by interval (lower voice / upper voice)")
        for i in order:
            if i in lo_hit:
                print(f"  {i:12s} lower {lo_hit[i][0]:3d}/{lo_hit[i][1]:<3d}   upper {hi_hit[i][0]:3d}/{hi_hit[i][1]:<3d}")
        show("PAIRS, by articulation", sorted(by_art_p.items()))
    stag = [(k, [v[1]]) for k, v in rows.items() if v[0]["scenario"]["kind"] == "staggered"]
    if stag:
        show("STAGGERED three instruments (overlapping)", stag)
    allr = [v[1] for v in rows.values()]
    g = agg(allr)
    print(f"\nALL: {g['n']} scenes, ref {g['nref']}, est {g['nest']}, P {g['P']:.2f} R {g['R']:.2f} F1 {g['F1']:.2f}, median delivery latency {g['lat']:.0f} ms")
    if a.verbose:
        print("\nper scene:")
        for k, (meta, r) in sorted(rows.items()):
            print(f"  {k:40s} ref {r['n_ref']:3d} est {r['n_est']:3d} P {r.get('P',0):.2f} R {r.get('R',0):.2f}")
    if a.json:
        Path(a.json).write_text(json.dumps({k: {kk: vv for kk, vv in r.items() if kk not in ('lat', 'matched_ref', 'src_ref')} for k, (m, r) in rows.items()}, indent=1))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("render"); r.add_argument("--dynamics", type=int, default=90); r.add_argument("--force", action="store_true"); r.add_argument("--param", action="append", help="plugin parameter NAME=VAL for every scene, e.g. Release=0"); r.set_defaults(fn=cmd_render)
    e = sub.add_parser("eval"); e.add_argument("--only", default=""); e.add_argument("--set", action="append", default=[], help="config override passed to the detector, key=value"); e.add_argument("--verbose", action="store_true")
    e.add_argument("--skip-warned", action="store_true"); e.add_argument("--snr", type=float, default=None, help="mix the real DI noise bed in at this SNR (dB) before detecting"); e.add_argument("--json", default=None); e.set_defaults(fn=cmd_eval)
    for sp in (r, e):
        sp.add_argument("--bench", default="bench", help="output directory name under data/bbcso (use a different one per parameter set)")
    a = ap.parse_args()
    global BENCH
    BENCH = ROOT / "data" / "bbcso" / a.bench
    a.fn(a)


if __name__ == "__main__":
    main()
