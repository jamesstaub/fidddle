# fidddle

Real-time polyphonic pitch detector for string instruments: bass, cello, viola, violin and guitar profiles (up to 6 voices),
with an open-string calibration. Companion: `didddle`, a source separator driven by these pitch tracks (see `didddle/README.md`).
Design: [spec.md](spec.md). Python reference prototype first, then a portable C++ core, then a Max external.

## Setup
```
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python -m pytest -q
```

## Layout
| Path | Purpose |
| ---- | ------- |
| `fidddle/profile.py` | `InstrumentProfile` (bass, cello, viola, violin, guitar), `DetectorConfig`, `Calibration` |
| `fidddle/frontend.py` | DC blocker, frame scheduling (spec §3–4) |
| `fidddle/spectral.py` | Hann/FFT, whitening, noise floor, peaks, onset flux (§5) |
| `fidddle/salience.py` | Harmonic salience, candidates (§6) |
| `fidddle/fitter.py`, `strings.py` | Polyphonic fit (Gram/NNLS greedy selection, pitch refinement) and string feasibility (§7, §1.3) |
| `fidddle/calibrate.py` | Open-string calibration: per-string inharmonicity, tuning and harmonic profiles (§12.3) |
| `fidddle/tracker.py` | Voice tracking, state machine, note events with onset/delivery timestamps (§8–9) |
| `fidddle/analyzer.py` | Offline driver running the stages per frame |
| `fidddle/synth.py`, `evaluate.py` | Synthetic signals with exact truth; candidate-recall metrics |
| `fidddle/corpus.py` | Paths to the local corpus and the Basic Pitch CLI |
| `tools/inspect_corpus.py` | Per-channel level/noise/spectral summary of the corpus |
| `tools/run_basicpitch.py` | Per-channel Basic Pitch run; caches notes to `data/basicpitch/*.json` |
| `tools/compare_bp.py` | Candidate recall vs Basic Pitch notes on the real recordings |
| `tools/make_mixes.py`, `eval_mixes.py` | Overlap real mono clips into polyphonic mixes; compare ours vs Basic Pitch |
| `tools/synth_recall.py` | Candidate-recall sweep on synthetic chords |
| `tools/eval_fit.py` | Multi-pitch P/R/F1 of the fit on synthetic chords or `--mixes` (also scores Basic Pitch on the same frames); `--set key=value` overrides config |
| `tools/eval_tracker.py` | Note-level evaluation (`mir_eval`) on synthetic scenes, mixes, real solo clips and dead-air; `--only synth\|mixes\|solo\|dead` |
| `tools/eval_instruments.py` | Per-instrument synthetic scenes (frame-level fit and note-level tracker); `tools/make_synth_wavs.py` writes them to `data/synth` for parity runs |
| `tools/eval_calibration.py`, `compare_calibration.py` | Calibration experiments on synthetic strings with per-string inharmonicity; Python/C++ calibration parity |
| `tools/eval_real.py`, `notes_report.py`, `plot_notes.py` | Scorecard on the real DI guitar and 5-string bass recordings in `data/`; note table; spectrogram with the detected notes overlaid |
| `tools/eval_bbcso.py` | Benchmark on rendered Spitfire BBCSO audio with exact truth (`render` then `eval`); see the `bbcso-render` skill for what that audio can and cannot show |
| `tools/eval_orchidea.py`, `orchidea_errors.py`, `orchidea_scene_report.py`, `orchidea_notes.py` | OrchideaSOL one-shot scenes with exact truth (see the `orchidea-eval` skill): tracker/separation scores, false notes classified (sub-octave, fifth, late, ...), truth against detection for one scene, per-note stiffness and body-response measurements |
| `tools/compare_cpp.py` | Parity of the C++ core with the Python reference (events and per-frame pitches) |
| `tools/grid_track.sh` | Tracker parameter sweeps |
| `tools/grid_fit.sh`, `grid_mix.sh`, `grid_both.sh` | Small parameter sweeps over the above |

`data/` holds generated artifacts (channel splits, Basic Pitch output, mixes, synthetic scenes, BBCSO renders) and the real DI recordings; only the recordings and the captured BBCSO patch states cannot be regenerated.
Corpus channels: 0 = piezo, 1 = condenser. Basic Pitch is a comparison baseline, not ground truth.

## C++ core and Max external
```
# portable core + CLI + unit tests (no dependencies)
cmake -S core -B core/build && cmake --build core/build -j && core/build/fidddle_tests
core/build/fidddle_cli data/channels/pizz-open-5ths_2.0.wav        # JSON lines: note events + summary

# parity with the Python reference (events and per-frame fitted pitches)
.venv/bin/python tools/compare_cpp.py --frames

# Max 9 external (third_party/ holds the vendored max-sdk-base; Xcode generator not required)
cmake -S max -B max/build -G "Unix Makefiles" && cmake --build max/build -j
package/install.sh        # symlinks package/fidddle into ~/Documents/Max 9/Packages (restart Max)
```
`package/fidddle/` is a Max package: `externals/fidddle~.mxo` (universal, ad-hoc signed), `help/`, `examples/fidddle-demo.maxpat`.

`fidddle~`: mono signal in; outlets = 6 voice-frequency signals (Hz, 0 = silent), 6 voice-level signals, one list outlet
`<midinote> <velocity> <slot>` (velocity 0 = note off; a retrigger sends the off, then the on), and info replies.

Attributes (descriptions for `@` autocomplete live in `package/fidddle/docs/fidddle~.maxref.xml`):

| Attribute | Meaning |
| --- | --- |
| `@profile` | `bass` `cello` `viola` `violin` `guitar` (0-4). Sets the next three to that instrument's defaults |
| `@voices` | maximum simultaneous voices, 1-6 (4 for bass/cello/viola/violin, 6 for guitar) |
| `@minfreq` `@maxfreq` | pitch search range in Hz (bass 28-500, cello 60-1000, viola 120-1500, violin 185-2800, guitar 70-1400) |
| `@minlevel` `@confirm` `@release` `@retrigger` | level gate, note-on confirmation frames, note-off delay (0 = profile default), re-attack threshold |

Set `@voices`, `@minfreq` or `@maxfreq` yourself for a custom tuning: explicit values win over the profile default whatever order the
attributes are typed in, and setting `@profile` again restores that instrument's defaults. The analysis window follows `@minfreq`
(about 372 ms for the 5-string bass profile, 186 ms for cello and guitar, 93 ms for viola and violin at 44.1 kHz), so the lowest-pitched instruments have the most latency. The `bass` profile is a 5-string bass (B0 E1 A1 D2 G2); on a 4-string bass set `@minfreq 38` to get the 186 ms window, and leave the B string out of a calibration with `calibrate done`.
`@minlevel` is an absolute gate in dBFS; on the bowed profiles (cello, viola, violin) a note below it still counts when it is at least 30 dB above the noise floor, so soft playing on a clean signal is not lost.
The `guitar` and `bass` profiles are for plucked strings, so a new note must start with a pluck: a voice that appears in a decaying ring without a fresh attack (a sympathetic string, a ghost octave under a ringing string) is not reported, and neither are legato notes (hammer-ons, pull-offs) that have no attack of their own. Bowed profiles have no such requirement.
Messages `reset` and `info` (replies `profile`, `analysis`, `timing_us` = mean/max analysis time per hop, `latency_ms` = mean/max note-on delay).

### Calibration (guitar and bass especially)
Send `calibrate`, then pluck each **open** string on its own (do not bow: a bowed string is locked to an exact harmonic series, so it measures no inharmonicity) and let it ring for about a second: one string at a time, in any
order. Anything that is not a single clean note close to an open string is ignored, so chords, overlapping notes and fretted notes
contribute nothing; playing other things in between does no harm, it just does not help. You do not have to play every string
(`calibrate done` uses what was captured; the other strings keep the profile's defaults), and it finishes by itself when all are captured.
It measures each string's inharmonicity and tuning and the typical balance of the harmonics, applies them at once, and stores them in the
saved `@calibration` attribute (restored when the patch opens). `calibrate cancel` abandons a session and `calibrate clear` removes the
calibration; changing `@profile` discards it. Progress comes from the right outlet (`calibrate started`, `progress`, `string`, `complete`, `applied`).
Offline: `fidddle_cli session.wav --profile guitar --calibrate` prints the learned list; `--calibration "<list>"` applies one.

