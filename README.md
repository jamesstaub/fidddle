# cellostop

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
| `cellostop/profile.py` | `InstrumentProfile` (cello preset) and `DetectorConfig` |
| `cellostop/frontend.py` | DC blocker, frame scheduling (spec §3–4) |
| `cellostop/spectral.py` | Hann/FFT, whitening, noise floor, peaks, onset flux (§5) |
| `cellostop/salience.py` | Harmonic salience, candidates (§6) |
| `cellostop/fitter.py`, `strings.py` | Polyphonic fit (Gram/NNLS greedy selection, pitch refinement) and string feasibility (§7, §1.3) |
| `cellostop/tracker.py` | Voice tracking, state machine, note events with onset/delivery timestamps (§8–9) |
| `cellostop/analyzer.py` | Offline driver running the stages per frame |
| `cellostop/synth.py`, `evaluate.py` | Synthetic signals with exact truth; candidate-recall metrics |
| `cellostop/corpus.py` | Paths to the local corpus and the Basic Pitch CLI |
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
cmake -S core -B core/build && cmake --build core/build -j && core/build/cellostop_tests
core/build/cellostop_cli data/channels/pizz-open-5ths_2.0.wav        # JSON lines: note events + summary

# parity with the Python reference (events and per-frame fitted pitches)
.venv/bin/python tools/compare_cpp.py --frames

# Max 9 external (third_party/ holds the vendored max-sdk-base; Xcode generator not required)
cmake -S max -B max/build -G "Unix Makefiles" && cmake --build max/build -j
package/install.sh        # symlinks package/cellostop into ~/Documents/Max 9/Packages (restart Max)
```
`package/cellostop/` is a Max package: `externals/cellostop~.mxo` (universal, ad-hoc signed), `help/`, `examples/cellostop-demo.maxpat`.

`cellostop~`: mono signal in; outlets = 4 voice-frequency signals (Hz, 0 = silent), 4 voice-level signals, one list outlet
`<midinote> <velocity> <slot>` (velocity 0 = note off; a retrigger sends the off, then the on), and info replies.
Attributes `@voices @minlevel @confirm @release @retrigger` (descriptions for `@` autocomplete live in `package/cellostop/docs/cellostop~.maxref.xml`);
messages `reset` and `info` (replies `analysis`, `timing_us` = mean/max analysis time per hop, `latency_ms` = mean/max note-on delay).
