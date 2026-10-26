# Efficient mode: architecture design (draft 2)

## Summary (read this first)

**What this is.** A plan for adding a second operating mode, "efficient", to the pitch detector. Efficient mode uses less processor time per second of audio, at the price of slightly lower precision and about 6 ms more delay before a note is reported. The existing mode, "full", stays exactly as it is today. Only these two modes will exist.

**Why.** The Bela board's processor is much weaker than a laptop's. Efficient mode is the first step towards running the detector on it. It is not enough on its own: my estimate is that it roughly halves the work, and the Bela needs the work cut by about three to ten times (an estimate; nobody has run the code on a Bela yet).

**How, in one sentence.** Efficient mode is a preset: a short list of existing settings (hop size, search grid, candidate limits) switched to cheaper values, with no new algorithm, so the full mode is not disturbed.

**Decisions made (2026-10-22):**

1. The extra ~6 ms delay is acceptable in efficient mode.
2. The Python reference will also get the table-based replacement for the `exp` function (called `kernel_table`), so efficient mode can be checked against Python note for note, just like full mode.
3. There are exactly two modes: full and efficient.
4. Efficient mode does not change the number of voices an instrument has.
5. The Bela build leaves out string identification completely (the code, the events, and the extra calibration values).

**What is still open:** nothing in this document. The larger question of whether Bela should share this code at all is in `BELA_DECISION.md`.


Status: draft, updated 2026-10-22 with the author's decisions. Nothing here is implemented. Companion to `BELA_PORT_REVIEW.md` (findings and measurements) and `ROADMAP.md` (efficiency items already planned).

## Implementation status (2026-10-26)

**Implemented in the Python reference, the C++ core, the command lines and `fidddle~` (`@efficient`).** Steps 1 to 5 and 7 of section 12 are done: lazy construction and the compile-time switch `FIDDDLE_NO_STRING_ID`, the time base (`Config::frames`, `Config::per_frame`; full mode unchanged), the `Quality` enum and `apply_quality`, candidate separation in cents, `noise_update_hops` and `kernel_table` in both languages (the same table, so Python and C++ agree event for event: `tools/compare_cpp.py --efficient`), and the host plumbing. Steps 6 and 8 are not done (WebAssembly calibration page, calibration header, Bela timing, `float`, thread split, `didddle~`).

**Differences from the plan, from measurements** (`tools/eval_profile.py`, ablation of every setting, 5 instruments, Orchidea scenes):

| Setting | Planned | Implemented | Why |
|---|---|---|---|
| `fit_max_harmonics` | 32 | 64 (unchanged) | The only setting that mattered: with 32, plucked cello and contrabass lost 0.04 to 0.06 F1. The time saved was within noise. |
| `max_candidates` | 12 | 16 | 12 cost bowed recall (cello 0.43 to 0.41); 16 is within 0.02 of full for every instrument. |
| `max_fit_iterations` | 2 (1 pass) | 1 | The code runs `min(2, max_fit_iterations)` passes, so 1 means one pass. |
| `noise_update_hops` | 4 | 4 | Neutral on F1. |
| `kernel_table` | on | on | Neutral on F1; table with 4096 entries, error below 2e-6, 0 beyond 5 sigma. |
| `allow_calibration` | off | off | `Calibrator` is frame-counted; `calibrate 1` is answered with `calibrate unavailable`. |

**Measured** (cello, one core of a laptop): load 5.6% in full mode, 1.8% efficient (3.1 times lower; the plan expected about 2 times). Note-on delay between −15 and +12 ms against full (mean about +1 ms; the plan expected +6 ms). F1 within 0.02 of full on all five profiles. Real guitar recording: precision 0.96 to 0.91. Real bass recording: one soft note with a weaker onset estimate.

## 1. Goals and non-goals

**Goal.** One core, two quality/cost levels. *Full* is today's behaviour (parity with the Python reference). *Efficient* trades some resolution and latency for a much lower cost per second of audio. Bela always runs Efficient; Max, WebAudio and the CLI can toggle it.

**Decisions already made (from the author):**

- Efficient mode: coarser salience grid, hop 512, no string identity.
- Calibration is done in a **WebAssembly build of fidddle** in a Bela web page (OSC/websocket to the board) and saved on the device. The Bela runtime only *loads* a calibration.
- Another session is working on noise-floor update rate and `exp`/`log` cost.

**Non-goals for this document:** the push/analyze thread split and `float`/NEON (needed for Bela but independent of the mode, see §8), and the didddle redesign.

**Honest expectation.** The three listed changes are necessary but not sufficient for Bela. Rough estimate (unmeasured on target; cello, from `BELA_PORT_REVIEW.md` §3.3):

| Step | CPU utilisation on a Bela (1.0 = a whole core) |
|---|---|
| Today, Full mode | ~2.9 to 6.9 |
| + hop 512 (half as many frames per second) | ~1.5 to 3.4 |
| + 10-cent grid (salience is ~15% of a frame, halved) | ~1.4 to 3.2 |
| + string id skipped (guitar only; cello unaffected) | same for cello |
| + noise update every 4–8 hops, exp/log tables (other session, ~35% of a frame) | ~0.9 to 2.1 |
| + `float`/NEON, decimation, trimmed fitter limits | target ≤ 0.4 |

So the mode should be designed as a **preset layer over independent settings**, so that each later optimisation just becomes another setting that the Efficient preset turns on.

## 2. Core principle: a setting per feature, a preset on top

Every efficiency feature is a field in `Config` whose **default reproduces Full-mode behaviour exactly**. `Efficient` is a function that sets a list of those fields; it contains no logic of its own.

Why: it keeps Full bit-compatible with the Python reference (`tools/compare_cpp.py`), lets any single feature be tested and A/B'd, and means the other session's work lands as new settings rather than a fork.

```
// core/include/fidddle/config.hpp (sketch)
enum class Quality : uint8_t { Full, Efficient };

struct Config {
    ...
    // efficiency settings; defaults == Full behaviour
    double grid_step_cents      = 5.0;     // exists
    int    hop_size             = 256;     // exists
    bool   string_id            = false;   // exists (guitar profile sets true)
    int    max_candidates       = 24;      // exists
    int    fit_max_harmonics    = 64;      // exists
    int    max_fit_iterations   = 8;       // exists (refine passes = min(2, this))
    int    noise_update_hops    = 1;       // NEW (other session)
    bool   kernel_table         = false;   // NEW (other session): table exp for the Gaussian kernel
    ...
    static Config for_instrument(int profile_id, double sample_rate, Quality q = Quality::Full);
    void apply_quality(Quality q);         // sets the settings above; called by for_instrument
};
```

`for_instrument` already applies per-instrument tuning; quality is applied *after* it so Efficient never overrides an instrument-specific safety setting without intent (e.g. the plucked-string attack parameters).

### 2.1 Proposed Efficient preset

| Field | Full | Efficient | Exists today? | Note |
|---|---|---|---|---|
| `hop_size` | 256 | 512 | yes | Needs the time-base work in §3. |
| `grid_step_cents` | 5 | 10 | yes | Needs the separation fix in §4. |
| `string_id` | per profile | false | yes | Plus lazy allocation, §5. |
| `max_candidates` | 24 | 12 | yes | Fitter cost scales roughly with this. |
| `fit_max_harmonics` | 64 | 32 | yes | Halves row size. |
| `max_fit_iterations` | 8 (2 passes used) | 2 (1 pass) | yes | |
| `noise_update_hops` | 1 | 4 | **new, other session** | Time-based, see below. |
| `kernel_table` | false | true | **new, other session** | See §6. |
| `max_voices` | profile default | unchanged | yes | Stays a user setting; offer "2 voices" as a separate, explicit choice. |

Everything except the two "new" rows is already a field, so a first version of the preset can ship without touching the DSP.

## 3. Hop 512 is not a one-line change: make the time base explicit

Several constants are *per frame* and were tuned at hop 256. At hop 512 they silently double in duration. This is review item P2-2; it must be fixed before hop 512 is trustworthy. Inventory (all in `core/`):

| Where | Constant | Meaning at hop 256 | Fix |
|---|---|---|---|
| `config.hpp` | `confirm_frames` 6, `strong_confirm_frames` 4 | 35 ms, 23 ms | Store as ms; derive frames = round(ms / hop_ms), minimum 2. |
| `config.hpp` | `onset_hist_frames` 14, `retrigger_min_age_frames` 26, `birth_hist_frames` 28/80, `pending_timeout_frames` 36/88, `harmonic_confirm_frames` 14, `octave_hold_frames` 12 | 81 ms … 465 ms | Same: ms in config, frames derived. |
| `tracker.cpp` | `miss_n >= 2` (pending dropped) | 12 ms | Derive from ms. |
| `tracker.cpp` | `t.vel *= 0.8`, `level_db += 0.5·Δ`, `conf += 0.3·Δ` per frame | smoothing time constants | Convert: `a' = 1 - (1 - a)^(hop/256)`. |
| `tracker.cpp` | `eta_sustain`, `eta_attack` per-frame gains | pitch smoothing | Same conversion. |
| `tracker.cpp` | `hist[9]` (velocity window) | 9 frames = 52 ms | Keep ≥ 4 frames, derive count from ms. |
| `spectral.hpp` | `OnsetFlux::beta_ = 0.02` (baseline smoothing) | ~290 ms | Same conversion. |
| `spectral.cpp` | `Whitener` noise `a_down_`/`a_up_` | already time-based | Nothing (good example). |

Rule going forward: **no per-frame constant in `Config` or the code; all are defined in time at a reference hop and converted once at construction**. A single helper, e.g. `Config::frames(ms)` and `Config::per_frame(a_ref)`, keeps this honest, and a unit test can assert that Full mode (hop 256) yields the same integers as today (so no behaviour change and Python parity holds).

Other hop-dependent behaviour to check, not just convert:

- **Onset flux** compares consecutive short-window spectra. At hop 512 the 2048-sample frames overlap 75% instead of 87.5%, so per-hop flux is larger. `onset_strong` (3.0) and the 1.5 weak-onset threshold are ratios to a baseline and may still hold, but must be re-validated on the eval corpus.
- **Onset timing resolution** becomes 11.6 ms (note events are `deliver_samples`-quantised). Plan on +6 ms mean note-on latency.
- `didddle::SplitterConfig::finalize()` sets the separator `grid = detector.hop_size`; frame times stay on the grid, so hop 512 should work but needs a test.
- `tests`: "block sizes that do not divide the hop" (listed in `ROADMAP.md`) matters more at 512; Bela blocks of 16/32/64/128 all divide it.

## 4. Coarser salience grid: separation must be defined in cents

`pick_candidates` computes `sep = nearbyint(min_candidate_separation_cents / grid_step_cents)`. At 5 cents that is 5 grid steps (25 cents). At 10 cents it is `nearbyint(2.5)` = 2 (round half to even), i.e. 20 cents: separation silently shrinks.

- Fix: compute `sep = ceil(min_sep_cents / grid_step_cents)` (≥ 25 cents guaranteed) **or** define the exclusion radius in cents and compare midi distance. The Python reference does the same `round`, so changing it changes Full as well. Cheapest safe option: leave Full's rounding as is (selected by a flag or by the fact that 25/5 is exactly 5), and use a distance-in-cents test only when `grid_step_cents != 5`. Mirror in Python before the corpus comparison.
- The candidate pitch is refined by parabolic interpolation on the salience curve and then by the ±20-cent joint refinement in the fitter; both use `grid_step_cents` already. Check that the fitter refinement step (5 cents) still gives enough resolution to pull a 10-cent candidate onto the peak. Expect small loss on vibrato-heavy bowed notes; measure with `tools/eval_*`.
- Memory: salience tables halve (≈ 190 KB saved).

## 5. Skipping string identity: also skip the allocation

`stringid::Measure` (≈ 1.5 MB), `History` (128 KB) and `Calibrator` (≈ 70 KB) are constructed for every profile today. In Efficient mode (and for cello/viola/violin in Full) they should not exist.

- Construct them in `Detector::Impl` only when needed: `Measure`/`History`/`Identifier` iff `cfg.string_id`; `Calibrator` lazily on first `calibrate_start()` (allocation off the audio thread: either a main-thread `prepare_calibration()` call or construct at startup behind a `Config::allow_calibration` flag, default true in Full, false in Efficient).
- `calibrate_start()` in a build/mode without a calibrator should post a `CalibEvent::Cancelled`-style "unavailable" event rather than silently ignore.
- `Detector::poll_string()` simply never returns anything when string id is off (already true).

## 6. The `exp`/`log` table: efficient mode only, same table in Python

**Measured** (micro-benchmark on the dev machine, Apple silicon, double, `exp(-0.5 z²)` for `|z| ≤ 3.5`): `std::exp` 4.6 ns, a 1024-entry table on `u = z²` with linear interpolation 1.5 ns: **3.1× faster**, max absolute error 1.2e-4 (the error falls as 1/T², so about 7.5e-6 at 4096 entries; that figure is extrapolated, not measured). `exp` is ~31% of a frame in the quiet-machine profile, so a table kernel removes roughly 20% of a frame on the desktop. On a Cortex-A8 libm `exp` is much slower relative to a table lookup, so the gain there should be larger (unmeasured).

So it *is* noticeable: about a fifth of a frame on a laptop, probably more on Bela. Whether it should apply everywhere depends on parity, not speed:

- A 1e-4 change in kernel values can flip a borderline decision (a candidate just above/below the gain threshold, a tracker confirm by one frame). The "all 572 events identical to Python" check would fail.
- But the Python reference can use the **same table** (deterministic construction), and then C++ and Python agree again. Then the table can be the default everywhere, which also removes a Full/Efficient difference to test.

**Recommendation:**

1. Implement it as a `GaussKernel` object (one place, used by `Fitter::build_row`, `render_peaks`, `SalienceMap::support`, `OnsetFlux`), selected by `Config::kernel_table`. Default **off**, Efficient **on**.
2. Evaluate on the corpus (F1, timing error). If within the roadmap target (F1 within 0.01), port the same table to Python and make it the default in both, deleting the setting later if nothing needs the exact path.
3. `log` is a separate and harder case, because it must work over a very wide range of values. Leave it to the other session, and handle it the same way as `exp`: add it as an optional setting that is off by default in full mode, and switch it on only in efficient mode.

**Decision (2026-10-22):** the table is used in efficient mode only, and the Python reference gets the same table, so efficient mode can be compared with Python note for note.

## 7. Calibration: do it in Full, carry it everywhere

Calibration is made by a WASM build, stored on the Bela, and loaded by the Efficient runtime. Design constraints:

- **Always calibrate in Full mode (hop 256).** `Calibrator` is frame-counted (`need_ 30`, `min_run_ 12`, `max_run_ 70` frames at hop 256), and its estimates assume 5-cent grid candidates and unthinned fitting. In the WASM page, force `Quality::Full` regardless of the host's setting; assert it.
- **Portability of the result.** The learned values (per-string `B`, tuning `cents`, per-string and averaged harmonic weights in the `fit_compress` amplitude domain) do not depend on hop, grid or mode, so a calibration made in Full applies to Efficient. It depends on `fit_compress` and the profile (`n_strings`), so store a small header: profile id, `fit_compress`, `n_strings`, and a format version; reject on mismatch rather than silently mis-applying.
- **Size and transport.** `Calibration::to_list` produces up to `LIST_CAP` = 259 numbers (~2 KB as `double`). The Bela web page can carry it as a JSON array over websocket/OSC; 32-bit float OSC arguments are adequate (B ≈ 1e-4 and cents have far more than float precision in practice; check by round-tripping a real calibration through float32 and re-running the CLI).
- **`logb` is only for string identity.** With string id skipped, drop the `logb` entries (list version 2) to shrink the message and avoid carrying meaningless data.
- **Storage.** On Bela, a JSON file in the project directory, loaded in `setup()` (non-RT), converted by `Calibration::from_list`, applied via `Settings::cal` / `cal_on`. The WASM page and the Bela runtime share `Settings::detector_config`, which guarantees they build identical configs.
- **WASM build.** `fidddle_core` has no threads or OS dependencies, and `Detector::calibrate_finish_now()` already exists for non-realtime use. A minimal binding exposes: construct with `Settings`, `process(float[])`, `calibrate_start/finish`, `poll_calib_event`, `take_calibration`. Needs `-std=c++17`, no exceptions required, and a check that `std::chrono::steady_clock` works in the Emscripten target (otherwise stub the timing, see P1-3).
- **Efficient mode in the WASM page** is useful for *previewing* detection with the saved calibration (so the user sees what Bela will do) but must be an explicit second step, not the calibration itself.

## 8. Where efficient mode sits relative to the rest of the Bela work

| Workstream | Depends on efficient mode? | Notes |
|---|---|---|
| Time-based parameters (§3) | prerequisite for hop 512 | Also fixes review P2-2 for all hosts. |
| Lazy construction (§5) | independent | Saves 1.7 MB everywhere; do first, low risk. |
| Push/analyze split + aux task (P0-1, P1-2) | independent | Needed on Bela whatever the mode; needs the 2× longer deadline Efficient gives. |
| `float` / NEON | independent | Compile-time (`Real` typedef), not a runtime mode: a runtime toggle would need both instantiations in one binary. Bela builds as `float`; Max/Web stay `double` unless measured otherwise. |
| Input decimation (×2–×4) | independent, large | Structural (changes FFT sizes); decide separately. If adopted it can become an Efficient setting (`analysis_decimation`). |
| didddle | later | Hop 512 + decimation change its `grid` and latency; revisit then. |

Runtime-vs-compile-time rule: **settings that only change loop bounds or thresholds are runtime (`Config`). Anything that changes the numeric type or table layout globally is compile-time.** Efficient mode is runtime so Max/Web can toggle it; Bela additionally compiles with `float` and the table kernel always on.

## 9. Host integration

- `fidddle::Settings` gets `bool efficient = false;` (or `Quality quality`), applied in `detector_config` before user overrides, so explicit attributes still win (same mechanism as `user_voices`/`user_minfreq`).
- Max: attribute `@efficient 0/1` (rebuilds the detector like other structural attributes). Help text states the cost: about +6 ms note-on latency and slightly coarser pitch.
- WebAudio: a parameter on the worklet; changing it rebuilds the detector.
- CLI: `--efficient`, and `--set key=value` for individual settings for A/B tests.
- Bela: fixed `Quality::Efficient` at build time; no UI.
- `Detector::config()` reports the actual values so hosts can show the effective hop/latency.

## 10. Testing and quality budget

- **Full:** unchanged. `tools/compare_cpp.py` (event-for-event vs Python) must keep passing; the time-base refactor must not change any Full-mode number.
- **Efficient:** compare C++ Efficient against C++ Full (not Python) on the existing corpora (`data/`, `tools/eval_*`, the Orchidea scenes). Budget: F1 within 0.01 of Full on notes, median onset error ≤ +1 hop, no increase in false notes on the noisy DI takes. Report per-setting contributions so a bad setting can be dropped independently.
- **Cost:** add timing assertions that are *relative* (Efficient mean per hop ≤ X% of Full on the same clip), since absolute timings vary by machine (the loaded-machine mistake in the first review).
- **Allocation:** extend the existing allocation-counting tests to run in Efficient mode and with `string_id` off.
- **Bela on-device:** once available, record Efficient `mean_us` / `max_us` in `BELA_PORT_REVIEW.md`'s log.

## 11. Coordination with the efficiency session

To avoid conflicts, split by file:

| Area | Owner | Files |
|---|---|---|
| Noise-floor update rate, `exp`/`log` tables, LUT kernel | efficiency session | `spectral.cpp/.hpp` (`Whitener`), `fitter.cpp` (`build_row`, `render_peaks`), `salience.cpp` (`support`), new `GaussKernel` |
| Quality enum, preset, time-base conversion, lazy construction, `Settings`/host plumbing, tests for the mode | this design | `config.hpp`, `settings.hpp`, `detector.cpp` (ctor), `tracker.cpp` (frame constants), hosts |

Contract between them: every new efficiency feature must be (a) a `Config` field whose default is the current exact behaviour, (b) listed in §2.1 so the preset can turn it on, (c) covered by a "Full is unchanged" test. `Config` is the one shared file; keep edits there to adding fields.

## 12. Suggested order of work

1. Lazy construction of `Measure`/`History`/`Calibrator` (§5). Small, safe, no behaviour change.
2. Time-base helpers and conversion of every frame constant, with a test that Full output is unchanged (§3).
3. `Quality` enum + `apply_quality` with the three listed changes plus candidate/harmonic/iteration limits (§2.1); CLI `--efficient`; the eval harness comparison (§10).
4. Candidate separation in cents (§4), mirrored in Python.
5. Merge the efficiency session's settings into the preset (`noise_update_hops`, `kernel_table`).
6. Calibration header + WASM binding (§7); Bela web page.
7. Host attributes (Max, Web).
8. Measure on a Bela; decide on `float`, decimation and the thread split from the numbers.

## 13. Decisions

| # | Question | Decision (2026-10-22) |
|---|---|---|
| 1 | Is ~6 ms extra delay acceptable in efficient mode? | Yes. |
| 2 | Add the table-based `exp` (`kernel_table`) to the Python reference too? | Yes, so efficient mode has the same note-for-note check as full mode. |
| 3 | How many modes? | Two: full and efficient. No middle level. |
| 4 | Should efficient mode change an instrument's voice count? | No. Voice count stays a separate user setting. |
| 5 | Does Bela need string identification? | No. The Bela build leaves out the string-identification code, its events and the extra string values (`logb`) in the saved calibration, entirely (compile-time switch, e.g. `FIDDLE_NO_STRING_ID`), not just turned off at run time. |

Consequences for the plan above: the voices row in §2.1 stays "unchanged"; §7 drops `logb` for Bela; step 1 in §12 gets a compile-time switch in addition to the lazy allocation.

## 14. Measurements, lessons and next steps (2026-10-26, after the implementation)

**How the numbers were made (to repeat them).**

- Test inputs: 8 to 13 s scenes from `orchidea_scenes` (for example `python -m orchidea_scenes generate --instrument cello --kind overlap --polyphony 3 --techniques sustained --normalize 0.5`), saved as `data/synth/perf_<instrument>.wav`. They are not in the repository (OrchideaSOL audio cannot be passed on).
- Time per step: `core/build/fidddle_cli file.wav --profile cello [--efficient]` prints `mean_us`, `max_us`, `hop_us` and `realtime_x` in its last line. Load = `mean_us / hop_us`. Repeat 3 times on an idle machine and take the best; a loaded machine gave wrong numbers more than once (spikes of 3 to 7 ms that were the operating system).
- Time per stage: `cmake -S core -B core/build-prof -DFIDDDLE_STAGE_TIMING=ON`, build `fidddle_cli`, run it; stderr has a table. (The timers use `std::chrono::steady_clock`: do not enable them in the WebAssembly build.)
- Accuracy: `python tools/eval_profile.py <instrument> --groups bowed,plucked --n 4 --variant full --variant efficient:quality=efficient`. A variant is `name:key=value,...`; `profile.<field>` edits the profile; `quality=efficient` applies the preset and later keys override it, so one setting can be put back to its full value (`quality=efficient,max_candidates=24`). The table has P/R/F1, the number of notes found against true, the median note-on delay and the median onset-estimate error.
- Real recordings: `python tools/eval_real.py [--efficient] [--cal-from-open]`.

**Time per step in efficient mode (cello, microseconds, 11.6 ms step):** FFT 44, whitening and noise floor 25, onset flux 19, peak picking 9, salience 79, candidates 12, fit 56, tracker 2 (mean 210). Guitar: fit 91 and salience 35 (mean 218). The FFT is now 16 to 18% of the step and the fit is the largest part for the guitar.

**Effect of each setting alone** (efficient preset with one setting put back to the full value; note F1 bowed / plucked; 4 scenes of each kind):

| Variant | cello | contrabass |
|---|---|---|
| full | 0.43 / 0.65 | 0.41 / 0.49 |
| first efficient preset (12 candidates, 32 harmonics) | 0.41 / 0.61 | 0.43 / 0.43 |
| + hop 256 | 0.41 / 0.62 | 0.42 / 0.40 |
| + grid 5 cents | 0.40 / 0.61 | 0.40 / 0.42 |
| + 24 candidates | 0.43 / 0.61 | 0.41 / 0.42 |
| **+ 64 harmonics** | 0.40 / **0.65** | 0.43 / **0.47** |
| + 2 refinement passes | 0.41 / 0.61 | 0.43 / 0.42 |
| + noise floor every step | 0.41 / 0.61 | 0.43 / 0.42 |
| + `exp()` instead of the table | 0.41 / 0.61 | 0.43 / 0.43 |
| final preset (16 candidates, 64 harmonics) | 0.41 / 0.67 | 0.43 / 0.48 |

So: hop, grid, passes, noise interval and the table are all neutral on F1; the number of fitted harmonics matters for low plucked notes; candidates matter a little for bowed recall.

**Lessons for the next steps.**

- Do not judge a preset on one instrument or one scene kind: the harmonic limit looked harmless on the guitar and the violin and cost 0.04 to 0.06 on plucked low notes.
- The onset estimate (not the note-on time) is what gets worse: soft notes have no strong onset in the flux, so the estimate falls back to a fixed look-back (`first_end - 0.35 n_long`) that is quantised to the step. In efficient mode the bass open-string test counted one soft note as a miss for this reason. The cheapest fix to try: compute the short-window flux at both half-steps and keep the larger value (about 15 µs per step).
- Python and C++ must change together. The tables (`fidddle/kernel.py`, `GaussTable` in `config.hpp`) are built the same way on purpose; any new efficiency setting needs a Python equivalent and an entry in `tools/compare_cpp.py --efficient` before it counts as done.
- A setting that changes results must default to the full-mode behaviour and be listed in `Config::apply_quality` and `DetectorConfig.EFFICIENT`. Those two lists are the preset; there is no other logic.

**Next steps, in order.**

1. **Timing on a real Bela** (the checkpoint in `BELA_DECISION.md`): build `fidddle_cli` there, run the `perf_*.wav` scenes in both modes, record `mean_us` and `max_us` in `BELA_PORT_REVIEW.md`. Target: mean at most 40% of the 11.6 ms step.
2. **Calibration check header.** The saved calibration is a flat list. Add a header with the profile id, `n_strings`, `fit_compress` and a format version, and reject a mismatch on load (Max, Bela, web). Drop the string values (`logb`) when the target is built with `FIDDDLE_NO_STRING_ID` (already done in the C++ code; the header is not).
3. **Calibration page** (WebAssembly, full mode) for Bela and the web: see `WEBAUDIO_DESIGN.md` section 7. It must refuse to run in efficient mode (`Calibrator` raises in Python, the C++ detector answers `CalibEvent::Unavailable`).
4. **`float` build** (a `Real` type alias, `double` for Max and the Python reference). Expect small result changes; keep the double build as the reference for parity.
5. **Analysis in a separate task** (push/analyze split) for Bela; see `BELA_PORT_REVIEW.md`.
6. **Input decimation by 2 to 4** if the checkpoint is still missed; it changes the FFT sizes, so it is a separate setting.
7. **`didddle~`**: `Settings::efficient` exists but the object has no attribute. The separator's grid equals the detector hop, so a hop of 512 should work, but nothing has tested it and its latency changes.
8. **Onset half-step flux** (above).

