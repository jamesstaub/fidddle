"""Render the demo audio of the Max package from the local OrchideaSOL library (see README, "Credits"):

  <instrument>-open-strings.wav   every open string plucked a few times, for the calibration demo (all strings must be captured)
  <instrument>-polyphony.wav      overlapping notes with exact truth, to show the detector with and without calibration

The OrchideaSOL audio is used under the IRCAM Forum licence, which does not allow passing it on, so the rendered files are not
kept in the repository (package/fidddle/media/*.wav is git-ignored). Download OrchideaSOL 2020 from the IRCAM Forum
(https://forum.ircam.fr/projects/detail/orchideasol/, free account), unpack it to data/_OrchideaSOL2020_release/, then render:

  .venv/bin/python tools/make_demo_audio.py [--out package/fidddle/media]
"""
import argparse
import sys
from pathlib import Path
import numpy as np
import soundfile as sf

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from fidddle.analyzer import Analyzer
from fidddle.calibrate import Calibrator
from fidddle.profile import DetectorConfig
from tools.eval_tracker import events_to_notes, score
from tools.orchidea import catalog, mix as omix

SR = 44100
# open strings, string 1 = the highest; open-string notes are plucked for calibration (a bowed string measures no stiffness)
OPEN = {"cello": [57, 50, 43, 36], "violin": [76, 69, 62, 55], "guitar": [64, 59, 55, 50, 45, 40]}
OPEN_TECH = {"cello": "pizzicato_secco", "violin": "pizzicato_secco", "guitar": "ordinario"}
# polyphony: bowed lines for the bowed instruments, a strummed chord sequence for the guitar
POLY = {"cello": ("lines", 3, "ordinario"), "violin": ("lines", 3, "ordinario"), "guitar": ("strum", 5, "ordinario")}
DYNAMICS = ("mf", "ff", "pp")


def open_strings(inst, takes):
    events, t = [], 0.4
    for st, midi in enumerate(OPEN[inst], 1):
        for k in range(takes):
            c = [s for s in catalog.select(inst, [OPEN_TECH[inst]], [DYNAMICS[k % len(DYNAMICS)]]) if s.string == st and s.midi == midi]
            if not c:
                c = [s for s in catalog.select(inst, [OPEN_TECH[inst]]) if s.string == st and s.midi == midi]
            events.append(omix.Event(c[0], t))
            t += 2.9 if inst == "guitar" else 1.9
    return events, t + 0.6


def level(x, peak=0.5):
    """Studio one-shots are quiet; a real signal is not. Scale to a normal peak level before testing the detector."""
    return x * peak / max(np.abs(x).max(), 1e-9)


def all_captured(inst, x):
    cfg = DetectorConfig.for_instrument(inst, float(SR))
    az = Analyzer(cfg)
    cal = Calibrator(cfg, az.n_long)
    az.run(x, track=True, calibrator=cal)
    return cal.done, cal.finalize()


def polyphony(inst, seeds=10):
    kind, voices, tech = POLY[inst]
    pool = catalog.select(inst, [tech], ["mf", "ff"])
    from fidddle.profile import InstrumentProfile
    pr = getattr(InstrumentProfile, inst)()
    pool = [s for s in pool if pr.min_frequency_hz * 0.97 <= 440.0 * 2 ** ((s.midi - 69) / 12) <= pr.max_frequency_hz]
    best = None
    for seed in range(seeds):
        rng = np.random.default_rng([7, seed])
        ev, dur = omix.scene(kind, pool, rng, voices, 3 if kind == "strum" else 3, techniques=[tech], dynamics=["mf", "ff"])
        mix, _, notes, _ = omix.render(ev, SR, dur)
        mix = level(mix)
        az = Analyzer(DetectorConfig.for_instrument(inst, float(SR)))
        az.run(mix, track=True)
        sc = score([(n["onset"], n["offset"], n["midi"]) for n in notes], events_to_notes(az.events, SR))
        if best is None or sc["F1"] > best[0]["F1"]:
            best = (sc, mix, notes, seed)
    return best


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(ROOT / "package" / "fidddle" / "media"))
    ap.add_argument("--instruments", default="cello,violin,guitar")
    ap.add_argument("--parts", default="all", choices=["all", "open"], help="open = only the open-string files")
    a = ap.parse_args()
    if not (catalog.RELEASE / "Strings").exists():
        sys.exit("OrchideaSOL not found. Download it from https://forum.ircam.fr/projects/detail/orchideasol/ (free IRCAM Forum account) "
                 f"and unpack it so that {catalog.RELEASE / 'Strings'} exists.")
    if "guitar" in a.instruments and not (catalog.RELEASE / "PluckedStrings" / "Guitar").exists():
        sys.exit("No PluckedStrings/Guitar folder found next to Strings/ in your OrchideaSOL copy. Check the unpacked folders, or run with --instruments cello,violin")
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    for inst in a.instruments.split(","):
        best = None
        for takes in range(1, 7):                  # the fewest takes that capture as many strings as this library allows
            ev, dur = open_strings(inst, takes)
            mix, _, _, _ = omix.render(ev, SR, dur)
            mix = level(mix)
            done, cal = all_captured(inst, mix)
            if best is None or sum(done) > sum(best[0]):
                best = (done, takes, dur, mix)
            if all(done):
                break
        done, takes, dur, mix = best
        sf.write(out / f"{inst}-open-strings.wav", mix, SR, subtype="PCM_16")
        print(f"{inst}: open strings, {takes} take(s) per string, {dur:.1f} s, strings captured {sum(done)} of {len(done)}", flush=True)
        if a.parts == "open":
            continue
        sc, mix, notes, seed = polyphony(inst)
        sf.write(out / f"{inst}-polyphony.wav", mix, SR, subtype="PCM_16")
        print(f"{inst}: polyphony seed {seed}, {len(notes)} notes, {len(mix) / SR:.1f} s, uncalibrated F1 {sc['F1']:.2f} (P {sc['P']:.2f}, R {sc['R']:.2f})")


if __name__ == "__main__":
    main()
