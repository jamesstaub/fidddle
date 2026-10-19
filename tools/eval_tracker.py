"""Note-level evaluation of the tracker (Milestone 4).

Scenes: synthetic staggered/overlapping notes with exact truth, the real-clip mixes
(reference = Basic Pitch notes of the isolated sources; Basic Pitch on the mix is scored on
the same footing) and the dead-air recordings (false notes only).

Usage: .venv/bin/python tools/eval_tracker.py [--set key=value ...] [--only synth|mixes|dead]
"""
import argparse
import json
import sys
from pathlib import Path
import numpy as np
import soundfile as sf
import mir_eval

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from fidddle.profile import DetectorConfig
from fidddle.analyzer import Analyzer
from fidddle.synth import Note, render
from tools.eval_fit import set_overrides


def hz(m):
    return 440.0 * 2.0 ** ((np.asarray(m, float) - 69.0) / 12.0)


def events_to_notes(events, sr):
    """Pair note-on/off per track id. Returns [(onset_s, offset_s, midi, deliver_s)]."""
    open_ = {}
    out = []
    for e in events:
        if e.kind == "on":
            open_[e.track_id] = e
        elif e.track_id in open_:
            on = open_.pop(e.track_id)
            out.append((on.onset_est_samples / sr, max(e.onset_est_samples / sr, on.onset_est_samples / sr + 0.02), on.midi_note, on.deliver_samples / sr))
    return out


def score(ref, est, onset_tol=0.15):
    """ref: [(on, off, midi)], est: [(on, off, midi, deliver)]. Returns P,R,F1 (onset+pitch), latency median."""
    if not ref:
        return None
    ri = np.array([[a, max(b, a + 0.02)] for a, b, _ in ref])
    rp = hz([m for _, _, m in ref])
    if not est:
        return {"P": 0.0, "R": 0.0, "F1": 0.0, "n_est": 0, "n_ref": len(ref), "lat": float("nan")}
    ei = np.array([[a, b] for a, b, _, _ in est])
    ep = hz([m for _, _, m, _ in est])
    P, R, F, _ = mir_eval.transcription.precision_recall_f1_overlap(ri, rp, ei, ep, onset_tolerance=onset_tol, pitch_tolerance=50.0, offset_ratio=None)
    # latency of matched notes
    match = mir_eval.transcription.match_notes(ri, rp, ei, ep, onset_tolerance=onset_tol, pitch_tolerance=50.0, offset_ratio=None)
    lat = [est[j][3] - ref[i][0] for i, j in match]
    return {"P": P, "R": R, "F1": F, "n_est": len(est), "n_ref": len(ref), "lat": float(np.median(lat)) if lat else float("nan")}


def scenes():
    """name -> list of Note (bowed unless stated)."""
    mono = [Note(m, 0.3 + 0.7 * i, 0.3 + 0.7 * i + 0.6, "bowed", 20.0) for i, m in enumerate([40, 45, 52, 57, 62, 55])]
    dbl = [Note(48, 0.3, 1.6, "bowed", 15.0), Note(55, 0.3, 1.6, "bowed", 15.0),
           Note(50, 2.0, 3.3, "bowed", 15.0), Note(57, 2.0, 3.3, "bowed", 15.0), Note(53, 3.6, 4.6, "bowed", 15.0), Note(60, 3.6, 4.6, "bowed", 15.0)]
    arp = [Note(m, 0.3 + 0.25 * i, 3.0, "plucked") for i, m in enumerate([36, 43, 50, 57])]
    strum = [Note(m, 0.3 + 0.03 * i, 2.5, "plucked") for i, m in enumerate([36, 43, 50, 57])] + \
            [Note(m, 3.0 + 0.03 * i, 5.0, "plucked") for i, m in enumerate([38, 45, 52, 59])]
    rep = [Note(50, 0.3 + 0.5 * i, 0.3 + 0.5 * i + 0.45, "plucked") for i in range(6)]
    return {"mono melody": mono, "double stops": dbl, "plucked arpeggio": arp, "strum x2": strum, "repeated pluck": rep}


def run(cfg, x, sr):
    cfg.sample_rate = float(sr)
    az = Analyzer(cfg)
    az.run(x, track=True)
    return events_to_notes(az.events, sr), az.events


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--set", action="append")
    ap.add_argument("--only", default="")
    ap.add_argument("--snr", type=float, default=40.0)
    args = ap.parse_args()
    cfg = DetectorConfig(sample_rate=44100.0)
    set_overrides(cfg, args.set)
    sr = 44100.0
    sums = []
    if args.only in ("", "synth"):
        print(f"{'synthetic scene':22s} {'P':>5s} {'R':>5s} {'F1':>5s} {'est/ref':>8s} {'latency_ms':>10s}")
        for name, notes in scenes().items():
            dur = max(n.offset_s for n in notes) + 0.8
            x = render(notes, sr, dur, snr_db=args.snr, seed=1)
            est, _ = run(DetectorConfig(**{**cfg.__dict__}), x, sr)
            s = score([(n.onset_s, n.offset_s, n.midi) for n in notes], est)
            sums.append(s)
            print(f"{name:22s} {s['P']:5.2f} {s['R']:5.2f} {s['F1']:5.2f} {s['n_est']:3d}/{s['n_ref']:<4d} {1000*s['lat']:10.0f}")
        print(f"{'MEAN synthetic':22s} {np.mean([s['P'] for s in sums]):5.2f} {np.mean([s['R'] for s in sums]):5.2f} {np.mean([s['F1'] for s in sums]):5.2f}")
    if args.only in ("", "mixes"):
        rows, brows = [], []
        for wav in sorted((ROOT / "data" / "mixes").glob("mix_*.wav")):
            meta = json.loads(wav.with_suffix(".json").read_text())
            ref = [(n["onset"], n["offset"], n["midi"]) for n in meta["notes"]]
            x, sr2 = sf.read(wav)
            est, _ = run(DetectorConfig(**{**cfg.__dict__}), x, sr2)
            rows.append(score(ref, est, 0.25))
            bpf = wav.with_suffix(".bp.json")
            if bpf.exists():
                bp = [(b["onset"], b["offset"], b["midi"], b["onset"]) for b in json.loads(bpf.read_text())]
                brows.append(score(ref, bp, 0.25))
        def agg(rs):
            w = np.array([r["n_ref"] for r in rs], float)
            return tuple(np.average([r[k] for r in rs], weights=w) for k in ("P", "R", "F1"))
        print(f"{'mixes (onset tol 250ms)':28s} ours P={agg(rows)[0]:.2f} R={agg(rows)[1]:.2f} F1={agg(rows)[2]:.2f}   est/ref={sum(r['n_est'] for r in rows)}/{sum(r['n_ref'] for r in rows)}")
        if brows:
            print(f"{'':28s} BP   P={agg(brows)[0]:.2f} R={agg(brows)[1]:.2f} F1={agg(brows)[2]:.2f}   est/ref={sum(r['n_est'] for r in brows)}/{sum(r['n_ref'] for r in brows)}")
    if args.only in ("", "solo"):
        print("real solo/double-stop clips: reference = Basic Pitch on the same clip (notes >= 0.15 s); ours vs it")
        for stem in ("bow-low-legato", "pizz-mid-scale", "pizz-high-register_2", "bow-then-pizz", "pizz-harmonic-descend", "bow-open-fifths", "strum-diads", "pizz-open-5ths_2"):
            for ch in (0, 1):
                js = ROOT / "data" / "basicpitch" / f"{stem}.{ch}.json"
                wavp = ROOT / "data" / "channels" / f"{stem}.{ch}.wav"
                if not js.exists():
                    continue
                ref = [(n["onset"], n["offset"], n["midi"]) for n in json.loads(js.read_text()) if n["offset"] - n["onset"] >= 0.15]
                x, sr2 = sf.read(wavp)
                est, _ = run(DetectorConfig(**{**cfg.__dict__}), x, sr2)
                sc = score(ref, est, 0.25)
                print(f"  {stem:24s} ch{ch}  P={sc['P']:.2f} R={sc['R']:.2f} F1={sc['F1']:.2f}  est/ref={sc['n_est']}/{sc['n_ref']}")
    if args.only in ("", "dead"):
        for ch in (0, 1):
            x, sr2 = sf.read(ROOT / "data" / "channels" / f"dead-air.{ch}.wav")
            est, _ = run(DetectorConfig(**{**cfg.__dict__}), x, sr2)
            print(f"dead-air ch{ch}: false notes = {len(est)}")


if __name__ == "__main__":
    main()
