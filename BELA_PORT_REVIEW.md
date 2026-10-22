# Bela port review: fidddle / didddle C++ core

Living document. Re-run the review periodically and append to the [Review log](#review-log) at the bottom. Update the status column in the findings tables instead of deleting rows.

- **Reviewed:** 2026-10-20, HEAD `2e0fcb8` (clean tree). Previous pass: 2026-10-19 at `ee3e988`.
- **Scope:** `core/` (fidddle detector, plus the new calibration and string-identification code, and the new `didddle` separator) and how it would be driven from a Bela `render()`. The Max externals and the Python tooling were only read for context.
- **Method:** read everything in `core/src`, `core/include` and the diff since `ee3e988`. Built Release on macOS (arm64), ran both test suites (pass), timed the CLIs, and profiled with `sample`.
- **Not done:** nothing was compiled or run on Bela hardware. Every "on Bela" number below is an **estimate** from desktop measurements and the Cortex-A8 architecture.

## 0. What changed since the last review

| Area | Change | Bela impact |
|---|---|---|
| **Correction** | My 2026-10-19 timing (2.2 ms mean per hop) was taken while the machine was loaded. Re-measured on a quiet machine, and the *old* commit `ee3e988` gives the same numbers as today's: **0.81 ms mean** per hop on the same clip. | The CPU gap is about 2.7× smaller than I reported. Still a blocker, but the needed reduction is ~7–18×, not 20–50× (§3). |
| Calibration + per-string weights | `calibrator.cpp`, `Calibration` struct, `Config::inharm_B/string_index/partial_weights`, fitter uses per-string weights | Small CPU cost (+7% on a chord clip). New code is allocation-free (tests cover it). See §5, P2-6. |
| String identification | `stringid.cpp`: long-window stiffness measurement per note (guitar) | Spikes up to 16384-point FFT + 8k-bin median per measurement; +1.5 MB memory built even when unused. See P1-6, §6. |
| Tracker | attack-depth history, harmonic-suspect, octave hold, quiet-SNR path | Longer history ring for bass/guitar (80 frames). Frame counts again (P2-2). |
| Bass profile | 5 strings, 28 Hz minimum, so the long window is now **16384 samples** | Bass costs about 2× cello per hop and has 372 ms window latency. |
| `didddle` | New `didddle_core`: streaming separator (`Splitter` wraps `Detector`), per-voice audio out | New real-time and memory considerations; separator itself is cheap (§4b). |
| `settings.hpp` | `Settings::detector_config(sample_rate, slot_cap)` clamps `max_voices` | Mitigates P3-1 for hosts that use it. |
| `fft.hpp` | `RealFFT::inverse()` added (used by didddle) | Float / Ne10 replacement must now provide an inverse too (B-4). |
| Spec | `spec.md` §17.6 now quotes this document's profile | Numbers there should be updated, see §3.2. |

## 1. Verdict

**The core is still not portable to Bela as it stands, but the picture is better than I first said.** On a quiet laptop the detector uses ~0.8 ms of a 5.8 ms hop budget (cello triads), ~1.1 ms for a six-voice guitar chord clip. The Cortex-A8 is likely 20 to 50× slower on this kind of code, which makes the mean land at roughly **16 to 40 ms per hop** (3 to 7× real time) before any optimisation. That is a blocker, but a reachable one: about a **7 to 18×** reduction gets to 40% CPU.

The three blockers are unchanged:

1. **CPU cost** (§3). Needs `float`/NEON, cheaper transcendentals, decimation and trimmed fitter limits.
2. **Threading model** (§4). Analysis must leave `render()` and run in an `AuxiliaryTask`. `Detector` must be split into push/analyze halves. `didddle::Splitter` makes this harder (§4b).
3. **Numeric type.** The hot path is all `double`.

**First action (about 30 minutes, settles the question):** copy `core/` to a Bela, build `fidddle_cli` with `g++ -std=c++17 -O3 -mcpu=cortex-a8 -mfpu=neon -mfloat-abi=hard`, run `data/channels/pizz-ascend-triads-1.0.wav` through it, and read `mean_us`, `max_us` and `realtime_x` from the summary line. Re-scale §3.3 from that number. Do the same with `guitar__A_minor_5.wav --profile guitar` (with and without `--calibration`).

Note on terminology: the BeagleBone is a single-core Cortex-A8 Linux computer (Bela runs Xenomai on it), not a microcontroller. That helps with memory (512 MB) and hurts with FPU and cache (§3.3, §5).

## 2. Platform assumptions

Verify against the actual Bela image and board; they drive several conclusions.

| Item | Assumed | Why it matters |
|---|---|---|
| CPU | AM3358 Cortex-A8, 1 GHz, one core | No second core. Linux, the IDE, scope and the analysis task share it. |
| FPU | VFPv3 (non-pipelined "VFPLite") for scalar `float`/`double`, NEON for `float` SIMD only | NEON has no `double`. Scalar VFP on the A8 is far slower than on modern cores. |
| Caches | 32 KB L1D, 256 KB L2 | Per-hop working set is multiple MB (§6). |
| Integer divide | none in hardware | Every `%` and `/` on ints is a library call (P1-1). |
| Audio rate / block | 44.1 kHz, 16-sample blocks by default (configurable) | Hop is 256 samples = 5.8 ms; a block is only 0.36 ms. |
| Audio I/O | stereo codec in/out on Bela/Mini; 8-channel ADC/DAC on the analog side, at 22.05 kHz in 8-channel mode | didddle has up to 4 voice stems plus a residual to output (§4b). |
| Toolchain | on-board gcc; version depends on the image | `std::clamp` is used throughout and needs gcc 7+ / C++17 (B-2). |
| RT environment | Xenomai Cobalt; `render()` is a hard-RT thread | Linux syscalls and page faults in `render()` cause mode switches. |

## 3. Compute

### 3.1 Measurements on the dev machine (Apple silicon, double precision, Release, quiet machine)

Hop budget at 44.1 kHz / 256 samples = 5805 µs.

| Clip / profile | Mean per hop | p99 | Max | Notes |
|---|---|---|---|---|
| `pizz-ascend-triads-1.0.wav`, cello (3985 frames) | **0.83 ms** | 1.19 ms | 9.2 ms (one run), 1.4 ms (another) | Same clip on commit `ee3e988`: 0.81 ms. The new features add ~1–2% here. |
| `guitar__A_minor_5.wav`, guitar, no calibration | 1.11–1.14 ms | – | 1.8–2.0 ms | Six-voice default. |
| same, with calibration | 1.19–1.21 ms | – | 1.8–6.2 ms | +7%. |
| same, calibration + string id on | 1.36–1.38 ms | 2.0 ms | 2.3–2.5 ms | Another +15% mean; the cost is in a few spike frames (measurement of settled notes). |
| `calibration__guitar.wav`, `--calibrate` | 0.68 ms | 1.07 ms | 1.7 ms | Calibration mode is cheap per frame. |
| `didddle_cli` on the triads clip (detector + separator) | detector 0.82 ms, **separator 0.056 ms** mean, 0.14 ms max | – | detector max 2.5 ms | Separator hop is 1024 samples (23 ms), latency 4096 samples (93 ms). |

Notes:

- The cello number matches the spec's "about 1 ms per hop". My earlier "2.2 ms" was a loaded-machine artefact and is withdrawn. `spec.md` §17.6 repeats the profile shares from that first run; the updated shares are in §3.2.
- Even on a quiet machine individual frames occasionally take 8 to 15 ms (visible as `max_us` in some runs and not others). Something other than the algorithm is causing that (page faults on first touch, scheduler). On Bela that is a deadline miss unless memory is pre-touched in `setup()` (P1-5), and it reinforces that the worst case matters more than the mean.

### 3.2 Where the time goes (macOS `sample`, quiet run, cello triads, top of stack)

| Share | Function | Notes |
|---|---|---|
| ~31% | `exp` and its stub | from `SalienceMap::support`, `Fitter::build_row`, `Whitener::process`, `OnsetFlux::process` |
| ~18% | `Whitener::update_noise` | sorted sliding-window median (41 bins) over all 4097 bins, **every hop** |
| ~15% | `SalienceMap::compute` | ~980 grid points × 23 harmonic probes, each a `lower_bound` plus `exp`: ~22k probes per hop, fixed regardless of input |
| ~12% | `Fitter::fit` (+3% `build_row`) | ~100 row builds per frame, each ~700 `exp` |
| ~4% | `log` | |
| ~4% | `pick_candidates` sort | sorts the full ~980 grid every hop |
| ~4% | `RealFFT::forward` | radix-2 `double`, 8192-point real |
| ~3% | `spectral_peaks` | |

Takeaways:

- `exp`/`log` plus the loops around them are the cost. The FFT is only about 4%, so swapping in a faster FFT alone does not help. The noise-floor median is the second biggest item and the cheapest to cut (it need not run every hop).
- Cost is **mostly fixed per frame**, not input-dependent (grid, whitening and median are always full-size). Good for scheduling, but there are no cheap "idle" frames.
- New code that is *not* constant per frame: string-identity measurements (P1-6) and calibration (cheap).

### 3.3 Estimate for Bela (unmeasured)

A scalar-`double`, libm-heavy workload on a 1 GHz A8 is typically **20 to 50× slower** than on this laptop. Cello mean 0.83 ms becomes **~17 to 40 ms per 5.8 ms hop**; the six-voice guitar case ~22 to 55 ms; bass (16384-point window, twice the bins) roughly double the cello figure. To land at about 40% CPU the hop cost has to fall to about 2.3 ms: a **~7 to 18× reduction** (cello), ~10 to 25× (guitar). Replace this paragraph with the measured figure from the on-device run in §1.

Levers (all unmeasured; gains overlap and do not simply multiply):

| Lever | Affects | Plausible gain | Functional cost |
|---|---|---|---|
| `float` + `-mfpu=neon -ffast-math` on FFT, whitening, peak picking | FFT, per-bin loops | 2–4× on vectorisable loops | Parity with Python reference is lost (P2-3). |
| Table / polynomial `exp` and `log` (Gaussian LUT on `z²`) | ~35% of total | 3–6× on that third | Tiny accuracy loss; validate with tolerances. |
| Update noise floor every 4–8 hops, not every hop | 18% | up to 8× on that stage | Noise floor adapts slightly slower; time constants are 0.2 s / 10 s, so likely invisible. **Cheapest big win.** |
| Decimate input ×4 for cello/bass/guitar (×2 viola/violin) before the long FFT | FFT 8192→2048; whitener, median, peaks, flux shrink 4× | ~4× on all per-bin stages | Needs an anti-alias FIR. Cello fit band 4 kHz still fits below 0.45·11 kHz; violin must stay ×2. |
| Fewer candidates (24→12), fit harmonics (64→32), refine passes (2→1) | `Fitter` | 2–4× on the fitter | Slightly worse separation of dense chords. |
| Coarser salience grid (5→10 cents), skip grid points with no nearby peak | `SalienceMap` | 2–4× | Candidate pitch resolution drops; refinement recovers most. |
| Partial sort / selection instead of full sort of 980 grid points | `pick_candidates` | ~4% | none |
| Hop 256→512 | everything | 2× | +5.8 ms latency; **parameters counted in frames shift** (P2-2). |

Decimation, a `float`/LUT hot path, a slower noise update and trimmed fitter limits is the realistic combination. Whether it reaches the target is open until measured on hardware.

## 4. Threading and real-time architecture

### P0-1: `analyze()` runs inline in the audio path

`Detector::run` (`core/src/detector.cpp`, the per-sample loop in `Impl::run`) calls `analyze()` from inside `process()` whenever a hop completes. The Max external does the same and the burst is acceptable there. On Bela it is not: with 16-sample blocks one `render()` call would have to absorb a full-hop analysis (tens of ms per §3.3) while every other block has almost no work. That is a guaranteed underrun, independent of how much optimisation is done, unless a whole analysis is under roughly one block of time (~0.3 ms), which is unrealistic.

**Fix:** use a Bela `AuxiliaryTask`:

- `render()`: write input samples into a ring, count samples, call `Bela_scheduleAuxiliaryTask()` once per hop. Read the latest snapshot and drain the event queues at the end of each block.
- Aux task: analyse the newest `n_long` samples and write results.

This requires reshaping `Detector`:

| Needed change | Why |
|---|---|
| Split `process()` into `push(samples)` (wait-free, from `render()`) and `analyze_pending()` (worker) | One function does both today. |
| Make the input ring larger than `n_long` (e.g. `2·n_long`) | `ring` is exactly `n_long` samples and `analyze()` copies the whole ring starting at `widx`. If the writer advances during the copy, the worker reads a torn, partly newer window. |
| Pass the target end-sample index to the worker and compute the window from that | So late scheduling does not shift the window or the event timestamps. |
| Define behaviour when analysis falls behind (drop hops, analyze the newest, count drops in `Diagnostics`) | Otherwise backlog accumulates without bound. |
| Mirror the `stringid::History` (the second per-sample ring, `MAX_WIN = 16384`) the same way | It is pushed per sample on the audio side and read by the stiffness measurement on the analysis side; it also needs the producer/consumer split. It already uses a power-of-two mask, which is the right pattern. |

### P0-2: Single core shared with Linux

Even moved off the audio thread, an analysis task above ~50% of the only core will starve Linux (SSH, IDE, scope, watchdog). Treat "mean analysis time ≤ ~40% of hop time" as a hard acceptance criterion, plus a drop-hops fallback.

### P1-2: Cross-thread reads are not safe once there are two threads

- `Detector::latest()` returns a reference to a `PitchFrame` the worker rewrites every hop. Use a seqlock or a double buffer with an atomic index.
- `diagnostics()` has `uint64_t`/`double` fields written by the worker. **64-bit loads and stores are not atomic on 32-bit ARM**, so reads can tear. `samples_processed()` (`int64_t total`) has the same problem.
- `Detector::reset()` clears queue indices (`qh`, `qt`, `sqh`, `sqt`, `cqh`, `cqt`) from the caller's thread while the worker may be pushing. Make reset a request handled by the worker.
- `Detector::calibrating()` reads a plain `bool` written by the analysis thread. Benign on ARM but a data race; make it `std::atomic<bool>`.
- **New:** `calibrate_finish_now()` runs `finish_calibration()` on the caller's thread. The header says "offline only", which is right; do not call it from a Bela UI thread.
- **Good:** the new command/event plumbing (`calib_cmd` atomic exchange, SPSC `cq`/`sq` queues, `cal_ready` flag with acquire/release) is correctly structured for one producer and one consumer. `std::atomic<size_t>` indices are lock-free on ARMv7.

### P1-3: Timing calls in the analysis path

`analyze()` calls `std::chrono::steady_clock::now()` three times per hop; `didddle::Separator::frame()` calls it twice per frame. Usually fine from a Xenomai-managed thread (Bela routes `clock_gettime` through Cobalt), but verify with the mode-switch counter (`/proc/xenomai/sched/stat`, "MSW"). Make timing compile-time optional.

### P1-4: Output side

Not in the core, but it shapes the API:

- Bela has no MIDI-note outlet. Pitch is naturally a CV on an analog output; note on/off a digital pin or MIDI/OSC. The Bela `Midi` class and OSC use ALSA/sockets, which are not safe in `render()`; they belong in the aux task or a low-priority thread. That thread then becomes the **single consumer** of the event, string-event and calib-event queues.
- Analog outputs run at half the audio rate in the default 8-channel mode. Smooth/hold pitch CV accordingly.
- The "slots persistent per note" behaviour maps well onto a fixed number of CV/gate output pairs.
- **New:** `StringEvent` (which string a note was played on, ~0.2 s after note-on) arrives late by design. A Bela front end should treat it as a separate message, not part of note-on.

## 4b. didddle on Bela (new)

`didddle::Splitter` runs the detector and a spectral separator together and returns one delayed audio signal per voice plus a residual.

| Aspect | Finding |
|---|---|
| **Separator cost** | Cheap: 56 µs mean, 144 µs max per frame on the dev machine, one frame per 1024 samples. Scaled ×30 that is ~1.7 ms per 23 ms, about 7% of a core. Not the problem. |
| **Separator memory** | ~1.4 MB for cello (solver banded matrix ~400 KB, overlap-add rings ~650 KB, track log ~100 KB). Fine. Allocation-free after construction (test covers it). |
| **Splitter couples detector and separator on one thread** | `Splitter::process` splits each input block at analysis boundaries, calls `det_.process()` (which analyses inline) and pushes the results to the separator *before* the next segment. If the detector moves to a worker (P0-1), the pitch information reaches the separator late. The separator already has a built-in latency (4096 samples = 93 ms for cello) and a `latency_ms` option; the fix is to raise that latency by the worker's worst-case lag, and to feed the separator from the consumer side of the detector's queues, not from inside `process()`. This needs a redesign of `Splitter`, not a flag. |
| **Output channels** | Up to `max_voices` (4–6) voice stems + residual. Stock Bela has a stereo audio out. More channels means the 8-channel analog DAC (16-bit, reduced rate in the default mode), which is not suitable for full-band audio stems. Realistic options: pick one or two voices per audio output, or mix stems into stereo. |
| **Latency** | Output is delayed ≥ one separator window (93 ms cello, more for bass). Not usable for monitoring; fine for effects on the separated voices. |
| **`double*` API** | `process(const double* in, size_t n, double* const* voices, double* residual)`. Bela blocks are `float`; needs conversion buffers sized at `setup()`, or a `float` template. |
| **Recommendation** | Treat didddle as phase 2. Get the detector running on-device first. |

## 5. Platform-specific code problems

### P1-1: Integer `%` and 64-bit `%` in hot loops (Cortex-A8 has no hardware divide)

Status: **open, unchanged** (line numbers moved with the new code; search for these expressions).

| Location (`core/src`) | Cost on ARMv7-A8 |
|---|---|
| `detector.cpp`, `Impl::run`: `(total - n_long) % cfg.hop_size`, `total` is `int64_t` | A `__aeabi_ldivmod` call **for every input sample**. Replace with a down-counter. |
| `detector.cpp`, `Impl::run`: `widx = (widx + 1) % n_long` | idiv call per sample. Use a compare-and-wrap or a power-of-two mask (`History` already does). |
| `detector.cpp`, `analyze()`: `ring[(widx + i) % n_long]` | 8192 idiv calls per hop. Replace with two `std::copy` segments; `longbuf` is also redundant with `frame_l`. |
| `fft.hpp`: `k % h_`, `(h_ - k) % h_` in the split step | Two idiv per bin, per FFT (also used by `inverse`-adjacent code and by `stringid::Measure`). |
| `tracker.cpp`, `attack_depth()`: `% ms_cap_` in a nested loop | Up to ~800 idivs per call (guitar/bass, 80-frame history); called per pending track per frame. Use a moving index. |
| `detector.cpp`, `preroll_energy()` | `% n_long` in a loop of 2048, but only during the first `n_long` samples after start; negligible. |

### P1-5: Warm-up, first-frame spikes and page faults

The occasional 8–15 ms frames on a quiet desktop (§3.1) point at cold-memory effects. On Bela, `mlockall` is in effect but memory allocated in `setup()` is still first-touched in the first analysis unless pre-faulted. Run one throwaway analysis in `setup()` on zeros, then `reset()`. That needs a complete `reset()` (P2-1).

### P1-6 (new): String-identity measurement is a spike source

`stringid::Measure::stiffness` (per settled note, `N_MEAS = 2` measurements each, guitar only):

- a Hann window plus a real FFT of up to 16384 points,
- a 41-bin `nth_element` median at **every** bin (up to 8193 × 41 elements),
- a peak scan and a progressive least-squares fit.

On the dev machine this adds 0.5 to 0.8 ms to the frames where it runs (max 1.8 → 2.3–2.5 ms). Scaled ×30, one measurement is ~15 to 25 ms, and `Identifier::update` runs one per eligible voice in the same frame, so a rolled six-string chord can stack several. `Calibrator::update` does the same during calibration.

Recommendations: (a) at most one measurement per analysis frame (queue the rest); (b) run it from a *lower-priority* task than the main analysis, since its result is not time-critical (0.2 s delay already); (c) replace the per-bin `nth_element` with the sliding-window update `Whitener` already uses, or compute the noise floor on a decimated grid; (d) off by default on Bela until measured.

### P2-4: Denormals — unchanged

Silent digital input drives `dc_y1`, `noise_`, and the new `History`/filters toward the denormal range. VFP on the A8 takes a slow path for denormals; NEON (`float`) flushes to zero. Low risk with a real ADC; keep FTZ on when moving to `float`.

### P2-5: Default sample rate — unchanged

`Config::sample_rate` defaults to 48000. Bela runs 44100 by default and the rate must come from `context->audioSampleRate`. `Settings::detector_config` takes the rate as an argument (good), so use that path.

### P2-6 (new): Calibrated config helpers recompute per call

`Config::string_index`, `inharm_B` and `partial_weights` each build the string-frequency table (one `pow` per string), **sort** the string indices, and `partial_weights` calls `pow` per harmonic when there is no learned profile. `Fitter::build_row` now calls `inharm_B(f)` and `weights_for(f)` on every row build (~100 per frame), and the old precomputed `stretch_` table was replaced by a `sqrt` per harmonic per row. Measured cost on the dev machine is modest (+7% mean with calibration on) but it is pure overhead on an A8 (sort + `pow` + `sqrt` in the hottest loop). Fix: when `use_calibration` is set, precompute per-string `B`, string frequencies and weights once at construction (`Fitter` already does this for weights) and look up by string index.

## 6. Memory

**Not a concern on capacity; the cache footprint matters.** Rough footprint of one `Detector` with today's code, computed from the constructors (`double`; cello, 44.1 kHz, `n_long = 8192`):

| Component | Approx. size |
|---|---|
| Input ring, `longbuf`, `frame_l`, long Hann window | 4 × 64 KB = 256 KB |
| Long FFT buffers + twiddles | ~210 KB |
| Long `Whitener` (9 per-bin arrays) + index tables | ~330 KB |
| Short FFT / flux / short whitener (2048) | ~100 KB |
| Peaks scratch (`Peaks` × 2) | ~100 KB |
| `SalienceMap` (`G·K` tables) | ~380 KB |
| `Fitter` (rows reserve `34 × 704 × 12 B`, `Y_`, `scratch_`) | ~350 KB |
| `VoiceTracker` short-magnitude history (15 × 1025 bins × 8 B, corrected: the short FFT has 1025 bins) + DP scratch | ~230 KB bowed; **~770 KB plucked** (81-frame history for bass/guitar) |
| Event queues (512 `NoteEvent`, 64 `StringEvent`, 64 `CalibEvent`) | ~40 KB |
| **`stringid::Measure`** (FFT + window for 2048…16384, scratch for 8193 bins) — **constructed unconditionally, even for cello** | **~1.5 MB** |
| `stringid::History` (16384 doubles) | 128 KB |
| `Calibrator` (`B`/`cents` lists 8×512×2, other arrays) | ~70 KB |
| **Total (cello)** | **≈ 3.8 MB** (was ≈ 1.9 MB) |

Plus, for `didddle::Splitter`: ~1.4 MB. The bass profile doubles the long-window items (16384-point window): roughly +1.2 MB.

With 512 MB of RAM that is negligible, and `float` roughly halves it. Real notes:

- **Construct `stringid::Measure`, `History` and `Calibrator` lazily**, only when `string_id` / calibration is requested. At present they cost 1.7 MB and a few tens of thousands of `sin`/`cos` calls at startup for every profile, including cello.
- **Cache, not capacity, is the issue.** Each hop streams several hundred KB of arrays through a 256 KB L2. `float`, removing the redundant `longbuf` copy, and decimation all reduce traffic.
- **No heap use in the steady state.** `core/tests/test_core.cpp` now has allocation-count tests for plain analysis, calibration (`test_no_allocation_while_calibrating`) and string identity (`test_no_allocation_with_string_identity`); `test_didddle.cpp` covers the separator. Allocations that remain, and are fine outside `render()`: construction, `Detector::flush()` (local `std::vector`), the debug hook.
- Stack use per call is small: the largest locals are NNLS matrices (`A[16*16]` doubles ≈ 2 KB) and `double win[64]`.
- A second detector is built and swapped in the Max external on attribute change. On Bela, construct once in `setup()` and expose only parameters that can change without reallocation; others need a deferred rebuild on a non-RT thread.

## 7. Correctness and robustness findings

| ID | Sev | Finding | Status |
|---|---|---|---|
| P2-1 | Medium | `Detector::reset()` is **still incomplete**. It now clears the string-id and calibration state (good), but still does not reset `Whitener::noise_`/`noise_init_`, `OnsetFlux::prev_`/`baseline_`/`have_prev_`, or the tracker's `ms_`/`edb_` contents (only head/count). A reset detector behaves differently from a fresh one, which breaks warm-up-then-reset (P1-5). | open (partly improved) |
| P2-2 | Medium | Tuning parameters counted in **frames, not time**: `confirm_frames`, `strong_confirm_frames`, `onset_hist_frames`, `retrigger_min_age_frames`, and now also `harmonic_confirm_frames`, `octave_hold_frames`, `birth_hist_frames`, `pending_timeout_frames`, plus the hard-coded `miss_n >= 2`. Any change of hop size, analysis rate or dropped hops changes confirmation latency and retrigger behaviour. Convert to ms and derive frames from `hop_size`/`sample_rate` before changing the hop for Bela. | open (worse: 4 more) |
| P2-3 | Medium | Python parity test requires bit-level event identity. `float`, LUT `exp`, decimation and `-ffast-math` break that. Define a tolerance-based regression for the Bela build before optimising. | open |
| P3-1 | Low | `Config::max_voices` not enforced in `Detector` (tracker loops `i < cfg_.max_voices` over `tracks_[MAX_VOICES]`; `live[MAX_VOICES]`). `Settings::detector_config` now clamps it, so hosts using `Settings` are safe. `fidddle_cli --set max_voices=12` still reaches it. | partly fixed (Settings path only) |
| P3-2 | Low | Unchecked config: `noise_median_bins > 64` overflows `double win[64]`; non-power-of-two `long_fft_size`/`short_fft_size` gives a wrong FFT silently; `hop_size <= 0` divides by zero (SIGFPE on ARM). Validate in the `Detector` constructor. | open |
| P3-3 | Low | `nnls_qp` uses `P[16]`, `A[16*16]`: safe for `m ≤ MAX_VOICES + 2 = 10`. Add a `static_assert`. | open |
| P3-4 (new) | Low | `Calibration::from_list` accepts attacker/user-controlled lists (Max preset, OSC). It bounds `n_strings`, `n_weights` and `n_sw` correctly, but `has_logb()`/`from_list` v3 branch trusts `n >= pos + ns`; fine as written. Only note: validate `B`, `cents` and `weights` are finite (a NaN `B` flows into `sqrt(1 + B h²)` in the hot path). | open |
| P3-5 (new) | Low | `Fitter` weights: `weights_for` indexes `hw_s_[s]` after `string_index(f)`, which can return an index `≥ hw_s_.size()` only if `string_count > MAX_STRINGS`; guarded. No issue, noted for completeness. | closed |

## 8. Build and toolchain

| ID | Sev | Finding | Status |
|---|---|---|---|
| B-1 | High | **Bela does not use CMake.** The project Makefile compiles everything in the project directory. `core/CMakeLists.txt` (and `PROJECT_IS_TOP_LEVEL`, CMake ≥ 3.21) is not used. There are now **two** libraries (`fidddle_core`, `didddle_core`) with different private include paths (`src`, `src/didddle`). Provide a flat Bela project layout or a pack script (`tools/bela_pack.sh`) that copies sources and sets `-I`. | open |
| B-2 | Medium | C++17 required (`std::clamp` in many places). Bela's default project standard is older; pass `CPPFLAGS=-std=c++17`. `std::clamp` needs gcc ≥ 7, which older Debian-9-based Bela images (gcc 6) do not have. | open |
| B-3 | Medium | Flags: `-O3 -mcpu=cortex-a8 -mfpu=neon -mfloat-abi=hard`. `-ffast-math` only after the regression in P2-3 exists; the code relies on NaN-safe patterns such as `if (!(pf < fmax_))` and `std::isfinite` (didddle solver), which `-ffast-math` can break. | open |
| B-4 | Low | `fft.hpp` is `double`-only and now also provides `inverse()`. A `float` replacement (Bela's Ne10-based `Fft` library) must provide both, with the same half-spectrum layout. | open |
| B-5 | Low | Compile the debug hook (`std::function`) out of the Bela build. | open |
| B-6 (new) | Low | `CMakeLists.txt` builds `fidddle_cli`, `didddle_cli`, tests with `-Wall -Wextra`; no new warnings in a Release build on clang. Compile once with the Bela gcc to see its warnings (e.g. unused variables behind `if (M)`). | open |

## 9. Functionality trade-offs for Bela

Ordered by how much CPU they buy relative to what they cost.

| Option | Saves | Costs | Recommendation |
|---|---|---|---|
| Single instrument profile fixed at start (no runtime switch) | Avoids detector rebuild; allows static sizing | No on-the-fly instrument change | Take it. |
| Update the noise floor every 4–8 hops | ~15% | Noise floor reacts slightly slower | Take it; cheapest big win. |
| Decimate analysis stream (×4 cello/bass/guitar, ×2 viola/violin) | ~4× on per-bin stages | Small FIR in `render()`; partials above ~5 kHz unused (violin must stay ×2) | **Do this first** among structural changes. |
| `float` + table `exp`/`log` | ~2–5× | Loses bit parity with Python | Take it, with the tolerance regression. |
| Fewer voices (cello 4→2; guitar 6→3) | Fitter cost falls faster than linearly | No 3–4 note chords (spec says sustained bowed polyphony is realistically 1–2 voices) | Runtime option; default 2 on Bela. |
| Smaller candidate set (24→12), `fit_max_harmonics` 64→32 | 2–4× on the fitter | Worse separation in dense chords | Take, tune against the mix corpus. |
| Coarser salience grid, skip empty regions | 2–4× on `SalienceMap` | Coarser candidate pitch | Take. |
| **String identification off** (`string_id = false`) | Spike source (P1-6) and 1.7 MB | No string-of-origin events for guitar | **Off by default on Bela**; add back as a low-priority task if wanted. |
| **Calibration on-device** | CPU is small, but it is a UI/state-management feature | Needs a front end and storage | Do calibration on a desktop (Max/CLI), store the list, load it into Bela as a preset (`Calibration::to_list/from_list`). The list is ~1 KB. |
| **Bass profile** | – | 16384-sample window doubles per-bin cost and gives 372 ms window latency | Last to port; consider the 4-string setting (`minfreq` ≈ 38 Hz → 8192 window) as noted in the profile. |
| **didddle** | – | Needs Splitter redesign (§4b), multi-channel output, ≥93 ms latency | Phase 2. |
| Hop 256→512 | 2× | +5.8 ms latency; frame-count parameters shift (P2-2) | Only after P2-2 is fixed. |
| Smaller long FFT | ~2× | More octave errors, weaker low-note separation (`spec.md` §11.3) | Last resort. |
| Keep the string constraint and tracker logic | – | – | Keep; cheap relative to the spectral stages. |

If, after all of the above, measured cost is still too high, fall back to a **monophonic or two-voice mode** (`max_voices = 1–2`), which the architecture supports without code changes.

## 10. Suggested porting order

1. **Measure** the unmodified CLI on the target (§1). Record the numbers in the log below.
2. Add a **tolerance-based regression** (P2-3) so optimisations can be checked automatically against the Python reference and the new `compare_cpp.py`.
3. **Cheap wins:** remove per-sample/per-bin `%` (P1-1), drop `longbuf`, make timing optional, lazily construct `Measure`/`History`/`Calibrator`, precompute per-string tables (P2-6), complete `reset()` (P2-1), validate config (P3-1/2/4).
4. **Restructure** `Detector` into `push` + `analyze_pending` with enlarged rings, seqlocked snapshot and atomic diagnostics (P0-1, P1-2).
5. **Optimise for A8:** slower noise update, `float` build, LUT `exp`, input decimation. Re-measure after each.
6. Write the Bela project (`setup`/`render`/`AuxiliaryTask`), flat layout or pack script (B-1), C++17 flags (B-2).
7. Hardware validation: CPU meter, `/proc/xenomai/sched/stat` for mode switches, dropped-hop counter, event latency histogram.
8. Phase 2: string id as a low-priority task, then the `Splitter` redesign for didddle (§4b).

## 11. Open questions for the author

- Which Bela image and board (Bela/Mini/Gem/Pocket)? The gcc version (B-2) and available Ne10 library depend on it.
- Audio block size (16 default; 64–128 cuts overhead at the cost of control-rate latency)?
- Outputs needed on Bela (CV pitch, gates, MIDI, OSC, separated audio)? This decides which thread consumes the event queues (P1-4) and whether didddle is worth porting.
- Is cello-only (or cello/viola/violin) acceptable for the first Bela release? Bass (16384 window) and guitar (6 voices, string id) are the most expensive profiles.
- Should `spec.md` §17.6 be updated to the quiet-machine profile shares in §3.2 above? It currently quotes my first (loaded-machine) shares.

## Review log

| Date | Commit | Reviewer notes |
|---|---|---|
| 2026-10-19 | `ee3e988` + working tree | First pass. Desktop profile only. 3 blockers (CPU, threading, double-precision hot path), 5 P1, 5 P2, 3 P3, 5 build items. Reported 2.2 ms mean per hop (loaded machine; **withdrawn**). |
| 2026-10-20 | `2e0fcb8` | Rescan after calibration, string-id, tracker changes, bass profile change and the new didddle module. Re-measured on a quiet machine: 0.83 ms mean per hop (cello), same as `ee3e988`; new features add ~1–2% (cello), +7% (calibration) and +15% (string id) on the guitar chord clip. Needed reduction revised from 20–50× to ~7–18×. New findings: P1-6 (string-id spikes), P2-6 (per-call string tables), P3-4, B-6, lazy construction of `Measure`/`History`/`Calibrator` (memory 1.9 → 3.8 MB), `Splitter`/threading conflict (§4b). P2-1 partly improved, P2-2 worse (4 more frame-counted params), P3-1 partly fixed via `Settings`. |
| 2026-10-22 | `d116c63` | No re-scan. Design decisions recorded in `EFFICIENT_MODE_DESIGN.md`: calibration is made in a WASM build (Full mode) and loaded on Bela; Efficient mode = coarser grid, hop 512, no string id (plus fitter limits); table kernel stays optional until Python parity is decided. |
