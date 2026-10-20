# didddle — source separation for string instruments

Python reference for the separator that sits behind `fidddle`. Opinionated like `fidddle`: harmonic string
tones with a known instrument profile, not arbitrary voices. `fidddle` supplies pitch tracks; `didddle` turns a
mono signal into one signal per voice slot plus a residual.

Status: Python reference (this directory) and a streaming C++ port (`core/`, below) that matches it to float32
precision, plus the Max external `didddle~`. Depends on `fidddle` read-only (`InstrumentProfile`, `Analyzer`, `synth`
in Python; the public headers and `Detector` in C++).

## Contract

    voices[v] + residual == input        (exactly, whatever the pitch tracks are)

Every estimator returns per-voice spectra `S`; shaping only moves signal between voices and residual, and the residual is always `x - sum(voices)`. So a fixed-latency copy of the
input, phase-inverted and summed with all outputs, cancels to rounding error (`null err` ~1e-16 in double).
Wrong or missing pitches cost separation quality, never completeness: unexplained audio lands in the residual.
In the C++ port compute the residual in the time domain as `delayed_input - sum(emitted voices)`, so the null
also holds in float32 and under any output crossfades.

## Modules

| file | role |
| ---- | ---- |
| `config.py` | `SeparatorConfig`; window size derived from the profile (`4 fs / f_min`, power of two) |
| `stft.py` | Hann/Hann weighted overlap-add STFT, exact round trip |
| `estimate.py` | per-frame voice spectra: `SinusoidLS` (default) and `CombMask` (baseline) |
| `shape.py` | time-domain gates and attack routing from note spans |
| `separate.py` | `Separator.process(x, f0, spans)` — STFT, estimator, ISTFT, shaping |
| `f0.py` | pitch tracks and note spans: exact (synthetic) or from the `fidddle` detector, restricted to what it could know at a given latency |
| `metrics.py` | SI-SDR, channel-to-stem grouping |

`tools/eval_separation.py` runs the experiments; `tests/test_didddle.py` the unit tests.

## Method

`SinusoidLS` models every partial of every active voice (`h f0 sqrt(1+B h^2)`) as one complex sinusoid and
solves a ridge least squares against the frame spectrum with the *exact* Hann kernel. Partials a few bins apart
separate coherently. Partials of different voices within 1 bin (octaves, fifths, thirds...) cannot be told
apart by their kernel; they share one unknown, split by each voice's spectral envelope interpolated over its
uncollided partials (Wiener share if both are known; a voice with no envelope there takes the remainder).

## Shaping (time domain, from note spans)

The stationary 93 ms fit smears each voice before its onset and after its end, and a plucked or bounced note
keeps 35-50 % of its energy in the first 40 ms, which the harmonic model cannot represent. From the detector's
note spans, `shape.py` therefore

1. gates each voice to its spans (3 ms fade in, 10 ms out);
2. hands the residual in the 80 ms after a note start to the voice that starts (simultaneous starts share it).

Detector onset estimates run 15-25 ms late and note ends ~120 ms late on plucked clips, so spans open 40 ms early
(`onset_lead_ms`), but never earlier than the detector knew the note (`f0.spans_from_run`). Frames that only
partly cover a note still carry its pitch (`margin = n_fft/2`) and the gate trims the rest.

## Latency model

A frame centred at `c` can be processed once its audio is in (`c + N/2`) and the pitch lookahead `D` has passed,
so the output delay is `L = N/2 + max(N/2, D)`. Gating happens at output time and may use detector information
up to `L`. At 44.1 kHz with `N = 4096` the floor is `L = 93 ms` (fast mode, `D <= N/2`).

- fixed latency: raise `L` so the note-on (delivered ~35-100 ms after the onset) is known before its audio is
  emitted and the attack can be back-filled;
- fast: `L = N`; a voice appears when the detector confirms it.

## Results (cello, 4096 window, hop 1024, LS estimator)

Synthetic stems with exact f0 (`oracle-synth`), SI-SDR range of the stems in dB:

| scene | LS | comb mask |
| ----- | -- | --------- |
| minor 3rd, major 3rd, 4th, tritone | 13-23 | 11-20 |
| fifth | 9-13 | 6-12 |
| octave, 19th (all upper partials collide) | 7-12 | 1.5-13 |
| minor 2nd (partials < 1 bin apart) | 0.5-5 | 0.5-7 |
| fast glide, 40 cent vibrato, plucked pair | 9-18 | |
| 3-4 voice chords, bowed/plucked | 7-17 | 3-13 |
| mean gain over the mixture | 12.9 dB | 10.6 dB |

Real-clip mixes from `tools/make_mixes.py` (piezo channel; stems reconstructed from the mix metadata; one mix,
`mix_4voice_3`, differs from its stems by 5e-2). Pitches and spans from the detector run on each *isolated*
source (`oracle-real`). "Ceiling" = the isolated source rebuilt from its own voices; with attack routing it is
inflated (a long enough window routes everything), so judge by the gain over the mixture.

| source | SI-SDR | gain over mix | (no shaping) |
| ------ | ------ | ------------- | ------------ |
| bow-gliss | 0.3 | 11.5 | 11.6 |
| bow-low-legato | 7.6 | 3.9 | 3.9 |
| bow-open-accel | 5.4 | 2.6 | 2.1 |
| bow-then-pizz | 7.6 | 9.3 | 8.5 |
| pizz-mid-scale | 6.6 | 5.6 | 2.6 |
| pizz-high-register | 3.3 | 9.5 | 5.7 |
| pizz-harmonic-descend | -1.6 | 10.8 | 5.6 |
| jete-bounces | -7.3 | 9.2 | 6.4 |
| **mean over 12 mixes** | | **7.3** | **5.2** |

Pitches and spans from the detector run on the *mixture* (`detector`), scored per note (each detected note is
its own channel, grouped to the stem it correlates with most), mean gain over the mixture vs total latency:

| L | 93 ms | 150 ms | 250 ms |
| - | ----- | ------ | ------ |
| shaping off | 2.5 dB | 2.7 | 2.7 |
| gates + attack routing | 3.6 | 3.9 | 4.0 |

Findings:

1. Shaping is worth +1.2 dB on detector pitches and +2.1 dB with isolated-source pitches; it matters most for
   plucked and bounced material (+3 to +5 dB per source).
2. The remaining gap between isolated-source pitches (7.3 dB) and mixture pitches (3.6-4.0 dB) is detection on
   the mixture: ghost notes capture other sources' attacks, and 38-43 % of the reference onsets in the
   flageolet and jeté clips have no detected note. Window size, ridge and per-partial peak snapping change the
   gain by < 0.1 dB (a 2048 window costs 1.7 dB).
3. Latency beyond the 93 ms floor buys only ~0.3 dB.
4. Tried and dropped: a linear amplitude/phase trajectory per partial (glissando, vibrato, decay): +/-0.3 dB,
   worse on heavy vibrato. Stationarity inside a frame is not what limits quality.
5. LS beats the comb mask by ~2 dB on synthetic and ~1 dB on real mixes. Octaves are erratic (-4 to +6 dB per
   random draw): the split rests on interpolating a smooth envelope.
6. Scoring whole slots against stems is misleading: a slot is reused by different sources over time.

## Open items

- Detector on mixtures (ghost notes, missed flageolet/jeté onsets, late onset and end estimates). A per-voice
  confidence from the separator itself (fraction of partials above the noise) could suppress ghosts' attack
  routing.
- Real ground truth: OrchideaSOL scenes (`tools/eval_orchidea.py separate`) now give exact per-note stems from real
  recordings; a noisy DI chain, legato and real chords with per-string stems are still missing (spec §17.1).
- Latency floor: with this STFT `L >= N`. A lower floor needs a different synthesis structure (shorter windows
  for the upper band, multi-resolution) and must not cost detection quality.

## Physical assumptions tested for the separator (2026-10-20, `tools/eval_physics.py`, OrchideaSOL)

All five instruments, bowed and plucked; details and numbers in spec §17.

| Idea | Result for `didddle` |
| ---- | -------------------- |
| Per-voice inharmonicity \(B\) | **No gain.** With true pitches the separation gain moves by under 0.3 dB for plausible \(B\) (at most 1.4 dB when six times too high). Bowed strings are exact harmonic series (\(B \approx 0\) on all four instruments), so a bowed profile should use 0, but it does not matter here |
| Phase-locked split of coinciding partials | **Rejected.** Relative partial phases are not smooth across partial number (prediction at chance level) and not reproducible enough between recordings |
| Body-response (or any) prior to split coinciding partials | **No gain.** A hidden partial's level cannot be predicted to better than about 5 dB by any model; interpolating the neighbours is within 0.2 to 0.9 dB of the best, so octave and unison splits are limited by the information, not the estimator |
| Per-string timbre prior from calibration | **Not worth it** for the same reason; the body response does help the *detector* (spec §17.2) |

What limits the separator now is detection on the mixture (ghost notes, missed onsets), which is the detector's
work, and the intrinsic ambiguity of coinciding partials.

## C++ core and the `didddle~` external

```
core/include/didddle/config.hpp     Config: window/hop/latency derived from the fidddle InstrumentProfile
core/include/didddle/separator.hpp  Separator: streaming DSP, no detector dependency (host pushes frames/events)
core/include/didddle/splitter.hpp   Splitter: Detector + Separator wired together; the one object a host needs
core/include/fidddle/settings.hpp   Settings: host-facing attributes -> fidddle::Config (shared by all hosts)
core/src/didddle/solver.*           SinusoidSolver: banded Cholesky replaces the dense solve
core/src/didddle/track_log.*        TrackLog: what the detector reported, as fixed rings
core/src/didddle/separator.cpp      frame scheduling, overlap-add, gates, attack routing, residual
core/cli/didddle_cli.cpp            wav in -> voice<N>.wav + residual.wav out (delayed by the latency)
core/tests/test_didddle.cpp         ctest target `didddle`
max/didddle~/didddle~.cpp           Max 9 external
```

Dependencies point one way: `didddle_core` -> `fidddle_core` (public headers, `Detector`, and its private
`RealFFT`, to which I added an `inverse()`; the forward transform is the same code and `fidddle_cli` output is
unchanged). Nothing in `fidddle` calls `didddle`. Hosts talk to `Splitter` (or `Separator` if they run their own
detector); a Pd/Bela/WebAudio target only needs the audio-callback glue.

**Streaming model.** The detector is driven in segments that end on its analysis boundaries; after each, its frame
and note events go into `TrackLog`. A separation frame falls due `L - N` samples after its audio is complete
(`L` = latency, `N` = window), picks the pitch of the analysis frame nearest in time, and everything it may use has
already been delivered, so there is no "lookahead" parameter, only `L`. `L` is rounded to the detector hop so frames
fall due exactly on detector boundaries. Voice output for sample `n` is emitted at `n + L`: gate and attack routing
use the note spans known at that moment; the residual is `delayed_input - sum(voices)` in the time domain.

**Attributes** (Max): `@latency` (ms, 0 = shortest = one window), `@transient` (attack length, ms), and, identical to
`fidddle~`, `@profile @voices @minfreq @maxfreq @minlevel @confirm @release @retrigger`, plus `calibrate` (the same
detector runs inside, so calibration works unchanged). Outlets: voice slots 0-5, residual, note list, info.
`info` also reports `latency <samples> <ms>`, the detector and separator timing. The shortest latency is one window:
85 ms (cello, 48 kHz), 171 ms bass, 43 ms viola/violin, 85 ms guitar.

**Verification.** `tools/compare_didddle_cpp.py <didddle_cli> clip.wav` runs the same clip through both
implementations: C++ vs Python agree to ~125 dB SI-SDR (float32 file precision) per slot and for the residual, at
the shortest and at 250 ms latency. `didddle_tests` checks the inverse FFT, that `voices + residual == input delayed
by latency` to 1e-12 for every stock profile at 44.1 and 48 kHz and any block size (64 to 4096), a synthetic major
third (13.1 / 12.4 dB with *detected* pitches), the latency modes, and zero heap allocations in `process()`.

**Cost** (Apple silicon, double precision, unoptimised): detector ~0.9 ms mean / 2.6 ms max per 5.8 ms hop; separator
61 us mean / 202 us max per 23 ms frame. Both run inline in the audio thread in `didddle~`, so the burst per hop is
the detector's.

**Build / test**

```
cmake -S core -B build && cmake --build build && ctest --test-dir build      # didddle_core, didddle_cli, didddle_tests
cmake -S max -B max/build && cmake --build max/build --target didddle_tilde  # package/fidddle/externals/didddle~.mxo
package/install.sh                                                            # then restart Max; help: didddle~.maxhelp
```

`examples/didddle-demo.maxpat` (also the help patcher) has an adc~/sfplay~ selector, a sum-of-voices/residual
monitor, and the null test: the input is delayed by the reported latency, inverted and summed with all seven
outputs; the peak meter reads ~0 (float32 rounding).

Not done: running inside a live Max session (the bundle builds, is universal, signed, and exports `ext_main`);
`mc.` outputs; a float32 / platform-FFT build; wiring `fidddle~` to `fidddle/settings.hpp` (it keeps its own copy
of that logic so as not to change a shipped object; `didddle~` already uses the shared header).
