"""Render the per-instrument synthetic scenes to 16-bit WAV files in data/synth/ (for C++/Python parity runs).

Usage: .venv/bin/python tools/make_synth_wavs.py
"""
import sys
from pathlib import Path
import soundfile as sf

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from fidddle.profile import InstrumentProfile
from fidddle.synth import render
from tools.eval_instruments import SCENES, make_notes

OUT = ROOT / "data" / "synth"


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    sr = 44100
    for inst, scenes in SCENES.items():
        prof = InstrumentProfile.by_name(inst)
        for name, (midis, stagger) in scenes.items():
            notes = make_notes(name, midis, stagger, prof)
            x = render(notes, sr, max(n.offset_s for n in notes) + 0.6, snr_db=40.0, seed=1)
            fn = OUT / f"{inst}__{name.replace(' ', '_')}.wav"
            sf.write(fn, x, sr, subtype="PCM_16")
    print("wrote", len(list(OUT.glob("*.wav"))), "files to", OUT)


if __name__ == "__main__":
    main()
