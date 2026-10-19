# Bela port review: fidddle C++ core

Living document. Re-run the review periodically and append to the [Review log](#review-log) at the bottom. Update the status column in the findings tables instead of deleting rows.

- **Reviewed:** 2026-10-19, HEAD `ee3e988` plus the uncommitted working tree.
- **Scope:** `core/` (the portable library) and how `Detector` would be driven from a Bela `render()`. The Max external and the Python/didddle tooling were only read for context.
- **Method:** read all of `core/src`, `core/include`, `core/cli` and the relevant parts of `spec.md`. Built the core with `-O3`-style Release flags on macOS (arm64), ran the CLI on `data/channels/pizz-ascend-triads-1.0.wav`, and profiled it with `sample`.
- **Not done:** nothing was compiled or run on Bela hardware. Every "on Bela" number below is an **estimate** from the desktop measurements and the Cortex-A8 architecture, labelled as such.

## 1. Verdict

**The core is not portable to Bela as it stands.** The code is clean and the memory footprint is not a problem. The blocker is compute: the per-hop analysis is written in `double` precision with heavy `exp`/`log` use, and the BeagleBone's Cortex-A8 will be slow at exactly that.

Three things must change before the first on-device test is worth doing:

1. **CPU cost** must drop by roughly an order of magnitude or more (§3). The analysis already uses most of a hop budget on a laptop.
2. **Threading model.** Running `analyze()` inline in the audio callback (as the Max external does) will miss audio deadlines on Bela. The analysis needs to move to an `AuxiliaryTask` with a lock-free hand-off, and `Detector` needs to be split into a push half and an analyze half (§4).
3. **Numeric type.** Move the hot path to `float`, and replace `exp` and the FFT with NEON-friendly versions (§3.3).

**First action (about 30 minutes, settles the question):** copy `core/` to a Bela, build `fidddle_cli` with `g++ -O3 -mcpu=cortex-a8 -mfpu=neon -mfloat-abi=hard`, run it on a wav, and read `mean_us`, `max_us` and `realtime_x` from the summary line. Everything in §3 gets re-scaled from that one number.

Note on terminology: the BeagleBone is a single-core Cortex-A8 Linux computer (Bela runs Xenomai on it), not a microcontroller. That helps with memory (512 MB) and hurts with FPU and cache (§3.2, §5).

## 2. Platform assumptions

Verify these against the actual Bela image and board; they drive several conclusions.

| Item | Assumed | Why it matters |
|---|---|---|
| CPU | AM3358 Cortex-A8, 1 GHz, one core | No second core to run analysis on. Linux, the IDE, scope and the analysis task share it. |
| FPU | VFPv3 (non-pipelined "VFPLite") for `double`/`float` scalar, NEON for `float` SIMD only | NEON has no `double`. Scalar VFP on the A8 is far slower than on modern cores. |
| Caches | 32 KB L1D, 256 KB L2 | Current working set per hop is ~1.9 MB; see §6. |
| Integer divide | none in hardware (Cortex-A8 has no SDIV/UDIV) | Every `%` and `/` on ints is a library call. See P1-1. |
| Audio rate / block | 44.1 kHz, 16-sample blocks by default (configurable) | Hop is 256 samples = 5.8 ms; a block is only 0.36 ms. |
| Toolchain | on-board gcc; version depends on the image | `std::clamp` is used throughout and needs gcc 7+ / C++17 (§8). |
| RT environment | Xenomai Cobalt; `render()` is a hard-RT thread | Linux syscalls and page faults in `render()` cause mode switches. |

## 3. Compute: the main problem

### 3.1 Measurements on the dev machine (Apple silicon, double precision, Release)

`pizz-ascend-triads-1.0.wav`, cello profile, 44.1 kHz, hop budget 5805 µs:

| Metric | Value |
|---|---|
| Mean per hop (3985 frames, from `--frames` output) | 2.24 ms |
| Median | 2.08 ms |
| 99th percentile | 5.75 ms (≈ the whole hop budget) |
| Max | 13.5 ms |
| Max in CLI summary (includes the first frame) | 178.9 ms |
| Peaks per frame (max) / candidates (max) | 143 / 26 |

Two notes:

- `spec.md` §10.3 quotes "about 1 ms per hop". That is for lighter material. On dense pizzicato triads the mean is 2.2 ms, so the budget the Bela port must beat is the polyphonic case, not the single-note case.
- A single frame took 179 ms in the summary run while the per-frame maximum in the hook output was 13.5 ms. The slow call is most likely the first analysis (cold pages / first touch) or a scheduler hiccup. On Bela that is a deadline miss unless memory is pre-touched in `setup()`. See P1-5.

### 3.2 Where the time goes (macOS `sample`, ~4900 samples, top-of-stack)

| Share | Function | Notes |
|---|---|---|
| ~28% | `exp` (libm) | called from `SalienceMap::support`, `Fitter::build_row`, `Whitener::process`, `OnsetFlux::process` |
| ~23% | `SalienceMap::compute` | ~980 grid points × (12 + 11) harmonic probes, each a `lower_bound` plus an `exp`: ~22k exp per hop, fixed regardless of input |
| ~12% | `Whitener::update_noise` | sorted sliding-window median (41 bins) over all 4097 bins, every hop |
| ~11% | `Fitter::fit` + `build_row` | up to ~100 `build_row` calls per frame (candidates + 2 refinement passes × voices × 9 trial pitches), each 64 harmonics × 11 bins = ~700 exp |
| ~7% | `RealFFT::forward` | radix-2 `double`, 8192-point real |
| ~5% | `log` | `Whitener::process`, `spectral_peaks` |
| ~3% | `pick_candidates` sort | sorts the full ~980 grid every frame |

Takeaways:

- Transcendentals (`exp`/`log`) account for roughly a third of the cost and the loops around them most of the rest. The FFT is only about 7%, so swapping in a faster FFT alone does not fix this.
- Cost is **mostly fixed per frame**, not input-dependent (salience grid, whitening and median are always full-size). That is good for scheduling, since the worst case is not wildly above the mean, but it means there are no cheap "idle" frames to rely on.

### 3.3 Estimate for Bela (unmeasured)

A scalar-`double`, libm-heavy workload on a 1 GHz A8 is typically **20 to 50 times slower** than on this laptop. That puts the mean around **45 to 110 ms per 5.8 ms hop**: 8 to 19 times the real-time budget, before accounting for Linux sharing the same core. To land at roughly 40% CPU the hop cost has to fall to about 2.3 ms, so a **~20 to 50× reduction** is needed. Use the on-device run from §1 to replace this paragraph with a measured number.

Rough sizing of what each lever could contribute (all unmeasured; multipliers overlap and do not simply multiply):

| Lever | Affects | Plausible gain | Functional cost |
|---|---|---|---|
| `float` + `-mfpu=neon -ffast-math` for FFT, whitening, peak picking | FFT, per-bin loops | 2–4× on vectorisable loops | Parity with Python reference is lost (§7, P2-3). |
| Table / polynomial `exp` and `log` (Gaussian LUT on `z²`) | ~1/3 of total | 3–6× on that third | Tiny accuracy loss; LUT must be validated against `compare_cpp.py` tolerances. |
| Decimate input ×4 for cello/bass/guitar (×2 for viola/violin) before the long FFT | FFT size 8192→2048; whitener, median, peaks, flux all shrink 4× | ~4× on all per-bin stages | See §9: needs an anti-alias FIR; upper partial range shrinks (cello fit band 4 kHz still fits under 0.45·11 kHz). |
| Run `update_noise` every 4–8 hops instead of every hop | 12% | up to 8× on that stage | Noise floor adapts a little more slowly. Time constants are 0.2 s / 10 s so this is likely invisible. |
| Reduce `max_candidates` (24→12), `fit_max_harmonics` (64→32), `refine` passes (2→1) | `Fitter` | 2–4× on the fitter | Slightly worse separation of close or dense chords. |
| Coarser salience grid (5→10 cents) and skip grid points with no nearby peak | `SalienceMap` | 2–4× | Pitch resolution of candidates drops; the joint refinement stage (±20 cents) mostly recovers it. |
| Hop 256→512 | everything | 2× | Latency +5.8 ms; **several parameters are counted in frames, not ms** (see P2-2). |

Combining decimation, a `float`/LUT hot path, a slower noise update and trimmed fitter limits is the realistic route. Whether it reaches the target is open until measured on hardware.

## 4. Threading and real-time architecture

### P0-1: `analyze()` runs inline in the audio path

`Detector::process` (`core/src/detector.cpp:113-123`) calls `analyze()` from inside the per-sample loop whenever a hop completes. The Max external does the same and the burst is acceptable there. On Bela it is not: with 16-sample blocks one `render()` call would have to absorb a full-hop analysis (tens of ms per §3.3) and every other block has near-zero work. This is a guaranteed underrun, independent of how much optimisation is done, unless the analysis is below roughly one block of time (≈0.3 ms), which is unrealistic.

**Fix:** use a Bela `AuxiliaryTask` (Xenomai thread, lower priority than `render()`):

- `render()`: write input samples into a ring, count samples, and call `Bela_scheduleAuxiliaryTask()` once per hop. Drain the event queue and read the latest voice snapshot at the end of each block.
- Aux task: analyse the most recent `n_long` samples and write results.
- The hot loop must stay allocation-free (already true, see §6).

This requires reshaping `Detector`:

| Needed change | Why |
|---|---|
| Split `process()` into `push(samples)` (wait-free, called from `render()`) and `analyze_pending()` (called from the worker) | Currently one function does both. |
| Make the input ring larger than `n_long` (e.g. `2 * n_long` or `n_long + k·hop`) | Today `ring` is exactly `n_long` samples (`detector.cpp:41`) and `analyze()` reads the entire buffer starting at `widx` (`:64`). If the writer advances while the worker is copying, the worker reads a torn, partly newer window. |
| Pass the target end-sample index to the worker and compute the window from that | So late scheduling does not shift the analysis window or the event timestamps. |
| Define behaviour when analysis falls behind (drop hops and analyze the newest, never queue unboundedly) | A busy aux task would otherwise accumulate backlog without bound. Count drops in `Diagnostics`. |

### P0-2: Single core shared with Linux

Even moved off the audio thread, an analysis task that consumes more than ~50% of the only core will starve Linux (SSH, IDE, scope, the Bela watchdog and network). Treat "mean analysis time ≤ ~40% of hop time" as a hard acceptance criterion for the port, plus a drop-hops fallback when that is exceeded.

### P1-2: Cross-thread reads are not safe once there are two threads

In Max everything is on the audio thread. With a worker thread:

- `Detector::latest()` (`detector.cpp:164`) returns a reference to a `PitchFrame` the worker rewrites every hop (`analyze()` assigns the fields one by one). The audio thread would read a half-updated frame. Use a seqlock or a double buffer with an atomic index.
- `diagnostics()` returns a struct with `uint64_t`/`double` fields written by the worker. 64-bit loads and stores are **not atomic on 32-bit ARM**, so reads can tear. `samples_processed()` (`int64_t total`) has the same problem.
- `Detector::reset()` (`detector.cpp:136`) clears `qh`/`qt` from the caller's thread while the worker may be pushing. Reset should be a request flag handled by the worker.
- `std::atomic<size_t>` indices are fine on ARMv7 (lock-free, 32-bit wrap is handled by the unsigned subtraction in `push_event`).

### P1-3: Timing calls in the analysis path

`analyze()` calls `std::chrono::steady_clock::now()` three times per hop (`detector.cpp:62, 89, 103`). Under Xenomai this is usually fine from a Xenomai-managed thread (clock_gettime is routed through Cobalt in Bela's build), but verify with the mode-switch counter (`/proc/xenomai/sched/stat`, "MSW" column) that the aux task does not switch modes. Make the timing optional (compile-time flag or injected clock) so the production build carries none.

### P1-4: Output side

Not in the core, but it shapes the API:

- Bela has no MIDI-note outlet. Voice pitch is naturally a CV on an analog output, and note on/off a digital pin or MIDI/OSC. The Bela `Midi` class and OSC use ALSA/sockets, which are not safe to call from `render()`; they belong in the aux task or a lower-priority thread. This means the event queue consumer is **not** `render()` in that case, and the SPSC (single consumer) contract has to be kept by exactly one consumer thread.
- Analog outputs run at half the audio rate by default (8-channel, 22.05 kHz mode). Smooth/hold pitch CV accordingly.
- The Max external's "slots are persistent per note, not sorted by pitch" behaviour maps well onto a fixed number of CV/gate output pairs.

## 5. Platform-specific code problems

### P1-1: Integer `%` and 64-bit `%` in hot loops (Cortex-A8 has no hardware divide)

| Location | Cost on ARMv7-A8 |
|---|---|
| `detector.cpp:121`: `(total - n_long) % cfg.hop_size` where `total` is `int64_t` | A `__aeabi_ldivmod` call **for every input sample** (44,100/s). Replace with a down-counter. |
| `detector.cpp:119`: `widx = (widx + 1) % n_long` | idiv call per sample. Use a wrap-around compare, or a power-of-two mask. |
| `detector.cpp:64`: `ring[(widx + i) % n_long]` | 8192 idiv calls per hop (~0.25 ms on A8). Replace with two `memcpy`/`std::copy` segments. The chronological copy `longbuf` is also redundant with `frame_l`; window straight from the ring. |
| `fft.hpp:55`: `k % h_`, `(h_ - k) % h_` | Two idiv per output bin of the split step, per FFT (4097 bins × 2 FFTs). Handle `k = 0` and `k = h_` outside the loop. |

These are individually small next to §3 but trivially removable.

### P1-5: Warm-up, first-frame spikes and page faults

The 179 ms first-frame outlier (§3.1) suggests cold-memory costs. On Bela, `mlockall` is in effect but memory allocated in `setup()` is still touched for the first time in `render()` unless pre-faulted. Run one throwaway analysis in `setup()` on zeros, then `reset()`. That only works once `reset()` is complete (P2-1).

### P2-4: Denormals

On silent digital input, `dc_y1` (`detector.cpp:117`), the geometrically decaying `noise_` in `Whitener::update_noise`, and the one-pole filters all decay toward denormal range. VFP on the A8 takes a slow path for denormals; NEON (`float`) flushes to zero. Real Bela input includes ADC noise so this is low risk, but when switching to `float`, make sure FTZ is on (it is with the usual Bela NEON flags) or add a tiny DC offset.

### P2-5: Default sample rate

`Config::sample_rate` defaults to 48000 (`config.hpp:72`). Bela runs at 44100 by default and the rate must come from `context->audioSampleRate`. Everything derived (FFT size, hop time, `df`) follows from that, so a mismatch silently shifts every pitch. Consider removing the default or asserting it was set.

## 6. Memory

**Not a concern.** Rough footprint for one `Detector`, cello profile, 44.1 kHz (`n_long = 8192`, ~980 grid points, `float`-free, i.e. today's `double` code), computed from the allocations in the constructors:

| Component | Approx. size |
|---|---|
| Input ring, `longbuf`, `frame_l`, long Hann window | 4 × 64 KB = 256 KB |
| Long FFT buffers + twiddles | ~210 KB |
| Long `Whitener` (9 per-bin arrays) + index tables | ~330 KB |
| Short FFT / flux / short whitener (2048) | ~100 KB |
| Peaks scratch (`Peaks` × 2) | ~100 KB |
| `SalienceMap` (`G·K` tables, 3 sets) | ~380 KB |
| `Fitter` (rows reserve `34 × 704 × 12 B`, `Y_`, `scratch_`) | ~350 KB |
| `VoiceTracker` short-magnitude history (15 × 2049 doubles) + DP scratch | ~360 KB |
| Event queue (512 × `NoteEvent`) | ~30 KB |
| **Total** | **≈ 1.9 MB** |

With 512 MB of RAM that is negligible, and `float` roughly halves it. Real notes:

- **Cache, not capacity, is the issue.** Each hop streams several hundred KB of arrays through a 256 KB L2. Moving to `float`, removing the redundant `longbuf` copy and decimating (§3.3) all reduce traffic.
- **No heap use in the steady state.** `core/tests/test_core.cpp` counts allocations over several seconds of audio and reports zero. This should be re-run whenever the fitter or tracker changes. Allocations that remain, and are fine as long as they stay out of `render()`/the aux task: `Detector` construction, `Detector::flush()` (local `std::vector`, `detector.cpp:146`), and the debug hook (`FrameDebug::fit_voices`) when installed.
- Stack use per call is small: the largest locals are the NNLS matrices (`A[16*16]` doubles ≈ 2 KB) and `double win[64]`. Default aux-task stack sizes are sufficient.
- A second `Detector` is built and swapped in the Max external when an attribute changes. On Bela, construct once in `setup()` and expose only parameters that can change without reallocation; others need a deferred rebuild in a non-RT thread.

## 7. Correctness and robustness findings (found while reading; relevant to the port)

| ID | Sev | Finding | Status |
|---|---|---|---|
| P2-1 | Medium | `Detector::reset()` (`detector.cpp:130-139`) is incomplete. It does not reset `Whitener::noise_`/`noise_init_`, `OnsetFlux::prev_`/`baseline_`/`have_prev_`, or the tracker's `ms_` contents (only head/count). A reset detector behaves differently from a fresh one, which breaks the warm-up-then-reset idea in P1-5 and any "reset on stream restart" feature. | open |
| P2-2 | Medium | Several tuning parameters are **frame counts, not times**: `confirm_frames`, `strong_confirm_frames`, `onset_hist_frames`, `retrigger_min_age_frames` (`config.hpp`), plus the hard-coded `miss_n >= 2` in `tracker.cpp`. Any change of hop size (or analysis rate, or dropped hops) changes note-confirmation latency and retrigger behaviour. Convert to ms and derive frames from `hop_size`/`sample_rate` before changing the hop for Bela. | open |
| P2-3 | Medium | The Python parity test requires bit-level event identity (572 events identical, pitches within 1e-4 semitones, per `spec.md` §10.3). `float`, LUT `exp`, decimation and `-ffast-math` will not satisfy that. Define a tolerance-based regression for the Bela build (e.g. event match within ±N frames and ±M cents on the same clips) before starting the optimisation work, so changes can be checked. | open |
| P3-1 | Low | `Config::max_voices` is documented `<= MAX_VOICES` but not enforced in `Detector`. The tracker loops `i < cfg_.max_voices` over `tracks_[MAX_VOICES]` and writes `live[MAX_VOICES]` (`tracker.cpp:96-97, 157, 265`). `fidddle_cli --set max_voices=12` reaches that path. The Max external clamps, but a Bela UI/OSC front end must too. | open |
| P3-2 | Low | Other unchecked config values: `noise_median_bins > 64` overflows the `double win[64]` stack array (`spectral.cpp:48`); a non-power-of-two `long_fft_size` or `short_fft_size` produces a wrong FFT without any error (`fft.hpp` bit-reversal assumes power-of-two); `hop_size <= 0` is a divide by zero (SIGFPE on ARM) at `detector.cpp:121`. Validate in the `Detector` constructor and return an error rather than relying on callers. | open |
| P3-3 | Low | `nnls_qp` uses `P[16]`, `A[16*16]`: safe for the current `m ≤ MAX_VOICES + 2 = 10`, but raising `MAX_VOICES` past ~14 would overflow silently. Add a `static_assert`. | open |

## 8. Build and toolchain

| ID | Sev | Finding | Status |
|---|---|---|---|
| B-1 | High | **Bela does not use CMake.** The project Makefile compiles everything in the project directory. `core/CMakeLists.txt` (and `PROJECT_IS_TOP_LEVEL`, which needs CMake ≥ 3.21) is not used. Provide a flat Bela project layout or a pack script (`tools/bela_pack.sh`) that copies `core/src/*.cpp`, `core/src/*.hpp` and `core/include/fidddle/*.hpp` and sets `-I`. Keep the `#include "fidddle/..."` layout working. | open |
| B-2 | Medium | C++17 is required (`std::clamp` in 8 places; structured use of `constexpr`/`inline` statics). Bela's default project standard is older. Pass `CPPFLAGS=-std=c++17` (or `gnu++17`), and check the image's gcc: `std::clamp` needs gcc ≥ 7, which older Debian-9-based Bela images (gcc 6) do not have. If stuck on an old image, add a local `clamp` shim. | open |
| B-3 | Medium | Compile flags: `-O3 -mcpu=cortex-a8 -mfpu=neon -mfloat-abi=hard`. `-ffast-math` is attractive but the code relies on NaN-safe patterns such as `if (!(pf < fmax_))` (`fitter.cpp`) and exact `==`/`!=` comparisons in the median update (`spectral.cpp:56`). Enable it only after the regression in P2-3 exists, and check those sites. | open |
| B-4 | Low | FFT: `fft.hpp` is `double`-only with a small interface, as `spec.md` §10.1 intends. Bela ships a Ne10-based `Fft` library (`float`). Adding a `float` `RealFFT` with the same `forward()` shape, selected at compile time, is a contained change. Check the library in your image for the real-FFT API. | open |
| B-5 | Low | `<chrono>`, `<functional>` (`std::function debug_hook`) and `<atomic>` are all available on the ARM toolchain. The debug hook pulls in `std::function` and allocation on assignment; compile it out of the Bela build with a macro. | open |

## 9. Functionality trade-offs for Bela

Ordered by how much CPU they buy relative to what they cost. "Keep" means no reason to cut.

| Option | Saves | Costs | Recommendation |
|---|---|---|---|
| Single instrument profile fixed at build/start (no runtime switch) | Avoids `Detector` rebuild; allows tighter static sizing | No on-the-fly instrument change | Take it. Instrument change = restart of the aux task. |
| Decimate the analysis stream (×4 cello/bass/guitar, ×2 viola/violin) | ~4× on all per-bin stages | A small FIR in `render()` (cheap); partials above ~5 kHz (cello) unused, tracker's 3 kHz rise band still fits; violin must stay ×2 because of its 8.4 kHz fit band | **Do this first.** Largest single structural win. |
| `float` + table `exp`/`log` | ~2-5× | Loses bit parity with Python | Take it, with the tolerance-based regression (P2-3). |
| Slower noise-floor update (every 4-8 hops) | ~10% | Noise floor reacts slightly slower | Take it. |
| Fewer voices (`max_voices` 4→2 for cello; guitar 6→3) | Fitter cost falls roughly with voices² in the Gram/NNLS stage | No 3-4 note chords. The spec notes sustained bowed polyphony is realistically 1-2 voices, so the cost is mainly for rolled chords and pizzicato. | Make it a runtime option; default 2 on Bela, 4 when headroom allows. |
| Smaller candidate set (`max_candidates` 24→12) and `fit_max_harmonics` 64→32 | 2-4× on the fitter | Worse separation in dense chords | Take, then tune against the mix corpus. |
| Coarser salience grid, skip empty regions | 2-4× on `SalienceMap` | Coarser candidate pitch (refinement recovers most) | Take. |
| Hop 256→512 | 2× | +5.8 ms latency, and frame-count parameters shift (P2-2) | Only after P2-2 is fixed. |
| Smaller long FFT (`window_periods` lower or 4096 for cello) | FFT and per-bin stages ~2× | `spec.md` §11.3 notes more octave errors and weaker low-note separation; the low cello C2 at 65 Hz needs the long window | Last resort. |
| Keep the full string-constraint and tracker logic | — | — | Keep. Both are cheap relative to the spectral stages. |
| Drop the onset-flux short FFT | Removes a 2048-point FFT + whitening | Loses onset timing/retrigger detection | Keep unless still over budget after everything above; it shrinks with decimation anyway. |

If, after all of the above, the measured cost on hardware is still too high, the fallback is a **monophonic or two-voice mode** (`max_voices = 1-2`, smaller candidate set), which the architecture supports without code changes.

## 10. Suggested porting order

1. **Measure** the unmodified CLI on the target (§1). Record the numbers in the log below.
2. Add a **tolerance-based regression** (P2-3) so every later optimisation can be checked automatically against the Python reference.
3. **Cheap wins:** remove per-sample/per-bin `%` (P1-1), drop `longbuf`, make timing optional, complete `reset()` (P2-1), validate config (P3-1/2).
4. **Restructure** `Detector` into `push` + `analyze_pending` with the enlarged ring, seqlocked snapshot and atomic diagnostics (P0-1, P1-2).
5. **Optimise for A8:** `float` build, LUT `exp`, noise-update decimation, input decimation. Re-measure after each.
6. Write the Bela project (`setup`/`render`/`AuxiliaryTask`), flat layout or pack script (B-1), C++17 flags (B-2).
7. Hardware validation: CPU meter, `/proc/xenomai/sched/stat` for mode switches, dropped-hop counter, event latency histogram (`deliver_samples` vs wall clock).

## 11. Open questions for the author

- Which Bela image and board (Bela/Mini/Gem/Pocket) will be targeted? The gcc version (B-2) and available Ne10 library depend on it.
- What audio block size is intended (16 is default; 64-128 reduces overhead at the cost of control-rate latency)?
- What outputs are required on Bela (CV pitch only, gates, MIDI, OSC)? This decides which thread consumes the event queue (P1-4).
- Is cello-only acceptable for the first Bela release? It is the cheapest profile to decimate aggressively and has the lowest voice count.

## Review log

| Date | Commit | Reviewer notes |
|---|---|---|
| 2026-10-19 | `ee3e988` + working tree | First pass. No hardware available; desktop profile only. 3 blockers (CPU, threading, double-precision hot path), 5 P1, 5 P2, 3 P3, 5 build items. Core builds and `fidddle_tests` pass on macOS. |
