# Efficient mode: architecture design (draft 1)

Status: draft for discussion, 2026-10-22. Nothing here is implemented. Companion to `BELA_PORT_REVIEW.md` (findings and measurements) and `ROADMAP.md` (efficiency items already planned).

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

So the mode should be designed as a **preset layer over independent knobs**, so that each later optimisation just becomes another knob that the Efficient preset turns on.

## 2. Core principle: a knob per feature, a preset on top

Every efficiency feature is a field in `Config` whose **default reproduces Full-mode behaviour exactly**. `Efficient` is a function that sets a list of those fields; it contains no logic of its own.

Why: it keeps Full bit-compatible with the Python reference (`tools/compare_cpp.py`), lets any single feature be tested and A/B'd, and means the other session's work lands as new knobs rather than a fork.

```
// core/include/fidddle/config.hpp (sketch)
enum class Quality : uint8_t { Full, Efficient };

struct Config {
    ...
    // efficiency knobs; defaults == Full behaviour
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
    void apply_quality(Quality q);         // sets the knobs above; called by for_instrument
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

## 6. The `exp`/`log` table: optional first, default later

**Measured** (micro-benchmark on the dev machine, Apple silicon, double, `exp(-0.5 z²)` for `|z| ≤ 3.5`): `std::exp` 4.6 ns, a 1024-entry table on `u = z²` with linear interpolation 1.5 ns: **3.1× faster**, max absolute error 1.2e-4 (the error falls as 1/T², so about 7.5e-6 at 4096 entries; that figure is extrapolated, not measured). `exp` is ~31% of a frame in the quiet-machine profile, so a table kernel removes roughly 20% of a frame on the desktop. On a Cortex-A8 libm `exp` is much slower relative to a table lookup, so the gain there should be larger (unmeasured).

So it *is* noticeable: about a fifth of a frame on a laptop, probably more on Bela. Whether it should apply everywhere depends on parity, not speed:

- A 1e-4 change in kernel values can flip a borderline decision (a candidate just above/below the gain threshold, a tracker confirm by one frame). The "all 572 events identical to Python" check would fail.
- But the Python reference can use the **same table** (deterministic construction), and then C++ and Python agree again. Then the table can be the default everywhere, which also removes a Full/Efficient difference to test.

**Recommendation:**

1. Implement it as a `GaussKernel` object (one place, used by `Fitter::build_row`, `render_peaks`, `SalienceMap::support`, `OnsetFlux`), selected by `Config::kernel_table`. Default **off**, Efficient **on**.
2. Evaluate on the corpus (F1, timing error). If within the roadmap target (F1 within 0.01), port the same table to Python and make it the default in both, deleting the knob later if nothing needs the exact path.
3. `log` is a separate, harder case (wide dynamic range, used for magnitudes): leave to the other session; same rule applies, knob first.

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
| Input decimation (×2–×4) | independent, large | Structural (changes FFT sizes); decide separately. If adopted it can become an Efficient knob (`analysis_decimation`). |
| didddle | later | Hop 512 + decimation change its `grid` and latency; revisit then. |

Runtime-vs-compile-time rule: **knobs that only change loop bounds or thresholds are runtime (`Config`). Anything that changes the numeric type or table layout globally is compile-time.** Efficient mode is runtime so Max/Web can toggle it; Bela additionally compiles with `float` and the table kernel always on.

## 9. Host integration

- `fidddle::Settings` gets `bool efficient = false;` (or `Quality quality`), applied in `detector_config` before user overrides, so explicit attributes still win (same mechanism as `user_voices`/`user_minfreq`).
- Max: attribute `@efficient 0/1` (rebuilds the detector like other structural attributes). Help text states the cost: about +6 ms note-on latency and slightly coarser pitch.
- WebAudio: a parameter on the worklet; changing it rebuilds the detector.
- CLI: `--efficient`, and `--set key=value` for individual knobs for A/B tests.
- Bela: fixed `Quality::Efficient` at build time; no UI.
- `Detector::config()` reports the actual values so hosts can show the effective hop/latency.

## 10. Testing and quality budget

- **Full:** unchanged. `tools/compare_cpp.py` (event-for-event vs Python) must keep passing; the time-base refactor must not change any Full-mode number.
- **Efficient:** compare C++ Efficient against C++ Full (not Python) on the existing corpora (`data/`, `tools/eval_*`, the Orchidea scenes). Budget: F1 within 0.01 of Full on notes, median onset error ≤ +1 hop, no increase in false notes on the noisy DI takes. Report per-knob contributions so a bad knob can be dropped independently.
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
5. Merge the efficiency session's knobs into the preset (`noise_update_hops`, `kernel_table`).
6. Calibration header + WASM binding (§7); Bela web page.
7. Host attributes (Max, Web).
8. Measure on a Bela; decide on `float`, decimation and the thread split from the numbers.

## 13. Open questions

1. **Latency in Max/Web:** is a mode that adds ~6 ms note-on latency and a coarser grid acceptable as a user-facing toggle, or should it be hidden behind an "advanced" setting?
2. **Table kernel default:** are you willing to update the Python reference to the same table so it can become the default (§6)? If not, it stays Efficient-only.
3. **Naming:** `Quality::{Full, Efficient}` now, or leave room for more levels (e.g. `Balanced`)? I'd keep two until measurements show a useful middle.
4. **Voices on Bela:** keep cello at 4, or have Efficient default to 2 (bowed polyphony is realistically 1–2 voices)? I left it a user setting.
5. **Calibration scope on Bela:** per-string weights and `B`/`cents` only (no `logb`), which assumes string identity stays off on Bela. Confirm.
