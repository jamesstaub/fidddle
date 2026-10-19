"""Compare the C++ didddle_cli output with the Python reference on the same clip and the same latency.

Usage: .venv/bin/python tools/compare_didddle_cpp.py path/to/didddle_cli clip.wav [more.wav ...] [--latency MS] [--seconds S]
Per voice slot it prints the SI-SDR of the C++ output against the Python one (C++ output is delayed by the latency);
agreement above ~40 dB means the ports match.
"""
import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path
import numpy as np
import soundfile as sf

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from didddle.config import SeparatorConfig
from didddle.f0 import run_detector, tracks_from_run, spans_from_run
from didddle.metrics import si_sdr
from didddle.separate import Separator
from fidddle.profile import DetectorConfig, InstrumentProfile


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cli")
    ap.add_argument("clips", nargs="+")
    ap.add_argument("--latency", type=float, default=0.0)
    ap.add_argument("--seconds", type=float, default=8.0)
    a = ap.parse_args()
    for clip in a.clips:
        x, sr = sf.read(clip)
        x = (x[:, 0] if x.ndim > 1 else x)[: int(a.seconds * sr)]
        with tempfile.TemporaryDirectory() as td:
            wav = Path(td) / "in.wav"
            sf.write(wav, x, sr, subtype="FLOAT")
            info = json.loads(subprocess.check_output([a.cli, str(wav), str(Path(td) / "o"), "--latency", str(a.latency)]))
            cpp = [sf.read(Path(td) / f"o.voice{v}.wav")[0] for v in range(info["voices"])]
            cres = sf.read(Path(td) / "o.residual.wav")[0]
        L = info["latency_samples"]
        cfg = SeparatorConfig.from_profile(InstrumentProfile.cello(), sr)
        sep = Separator(cfg)
        c = sep.centers(len(x))
        run = run_detector(x, DetectorConfig.for_instrument("cello", float(sr)))
        half = cfg.n_fft / 2 / sr
        look_f0 = (L / sr) - half
        f0 = tracks_from_run(run, c, look_f0, cfg.n_fft // 2)
        spans = spans_from_run(run, L / sr, cfg.onset_lead_ms / 1000)
        v, res = sep.process(x, f0, spans)
        pad = lambda y: np.concatenate([np.zeros(L), y])[: len(x)]
        print(f"{Path(clip).name}: latency {L} samples")
        for k in range(len(v)):
            ref, got = pad(v[k]), cpp[k][: len(x)]
            e = np.sum(ref ** 2)
            if e < 1e-9 and np.sum(got ** 2) < 1e-9:
                continue
            print(f"  slot {k}: energy {e:9.3f}  C++ vs Python SI-SDR {si_sdr(got, ref):6.1f} dB   max|diff| {np.max(np.abs(got - ref)):.2e}")
        r = pad(res)
        print(f"  residual: C++ vs Python SI-SDR {si_sdr(cres[: len(x)], r):6.1f} dB   max|diff| {np.max(np.abs(cres[:len(x)] - r)):.2e}")


if __name__ == "__main__":
    main()
