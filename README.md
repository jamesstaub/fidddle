# fidddle

Real-time polyphonic pitch detector for string instruments (MVP: cello, up to 4 voices).
Design: [spec.md](spec.md). Python reference prototype first, then a portable C++ core, then a Max external.

## Setup
```
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python -m pytest -q
```

## Layout
| Path | Purpose |
| ---- | ------- |
| `fidddle/profile.py` | `InstrumentProfile` (cello preset) and `DetectorConfig` |
| `fidddle/frontend.py` | DC blocker, frame scheduling (spec §3–4) |
| `fidddle/spectral.py` | Hann/FFT, whitening, noise floor, peaks, onset flux (§5) |
| `fidddle/salience.py` | Harmonic salience, candidates (§6) |
| `fidddle/fitter.py`, `strings.py` | Polyphonic fit (Gram/NNLS greedy selection, pitch refinement) and string feasibility (§7, §1.3) |
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
| `tools/grid_track.sh` | Tracker parameter sweeps |
| `tools/grid_fit.sh`, `grid_mix.sh`, `grid_both.sh` | Small parameter sweeps over the above |

`data/` holds generated artifacts (channel splits, Basic Pitch output, mixes) and can be deleted and rebuilt.
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
| `@minfreq` `@maxfreq` | pitch search range in Hz (bass 35-500, cello 60-1000, viola 120-1500, violin 185-2800, guitar 70-1400) |
| `@minlevel` `@confirm` `@release` `@retrigger` | level gate, note-on confirmation frames, note-off delay (0 = profile default), re-attack threshold |

Set `@voices`, `@minfreq` or `@maxfreq` yourself for a custom tuning: explicit values win over the profile default whatever order the
attributes are typed in, and setting `@profile` again restores that instrument's defaults. The analysis window follows `@minfreq`
(about 186 ms for bass, cello and guitar, 93 ms for viola and violin at 44.1 kHz), so the lowest-pitched instruments have the most latency.
Messages `reset` and `info` (replies `profile`, `analysis`, `timing_us` = mean/max analysis time per hop, `latency_ms` = mean/max note-on delay).

### Calibration (guitar and bass especially)
Send `calibrate`, then pluck each **open** string on its own and let it ring for about a second: one string at a time, in any
order. Anything that is not a single clean note close to an open string is ignored, so chords, overlapping notes and fretted notes
contribute nothing; playing other things in between does no harm, it just does not help. You do not have to play every string
(`calibrate done` uses what was captured; the other strings keep the profile's defaults), and it finishes by itself when all are captured.
It measures each string's inharmonicity and tuning and the typical balance of the harmonics, applies them at once, and stores them in the
saved `@calibration` attribute (restored when the patch opens). `calibrate cancel` abandons a session and `calibrate clear` removes the
calibration; changing `@profile` discards it. Progress comes from the right outlet (`calibrate started`, `progress`, `string`, `complete`, `applied`).
Offline: `fidddle_cli session.wav --profile guitar --calibrate` prints the learned list; `--calibration "<list>"` applies one.

