# WebAudio implementation: design (draft 1)

Status: draft for discussion, 2026-10-26. Nothing here is built yet. Related documents: `EFFICIENT_MODE_DESIGN.md` (the cheaper operating mode), `BELA_DECISION.md` (why the core stays shared), `BELA_PORT_REVIEW.md` (measurements and problems found).

## Summary (read this first)

**What we are building.** A way to run the fidddle pitch detector in a web page. The page gives it live audio (microphone or any Web Audio source) and gets back two kinds of results:

1. **Audio-rate signals**: for each voice, a pitch signal, a loudness signal and an on/off gate. They can be connected straight to the controls of other Web Audio nodes, for example the frequency of an oscillator or the gain of an amplifier.
2. **Note events**: "note on" and "note off" messages with the note number and velocity, which a page can turn into Web MIDI messages or any other action.

**How.** The existing C++ core is compiled to WebAssembly (a compact binary format that browsers run at close to native speed) and runs inside an *AudioWorklet* (the browser's mechanism for custom audio code on the real-time audio thread). One detector runs once per analysis step, and both kinds of result come from that single run. The analysis is never done twice.

**Is it feasible?** Yes. I found no blockers (see the 2026-10-26 review). The open risks are speed on phones and tablets, and one browser detail I could not test here: whether the timing calls inside the core work in the audio worklet.

**What needs doing first:** make timing optional in the core, fix the incomplete `reset()`, and wrap the core in a small C interface for WebAssembly. Then build the audio worklet, the two JavaScript classes, and a demo page.

**Decisions already made that affect this design:**

- There is one detector and one analysis run; the signal outputs and the note events are two views of it.
- didddle (voice separation) is not part of the web version for now.
- The pitch glide defaults to 5 ms.
- Voice slots are stable (a note keeps its slot); sorting by pitch is an option, and the event API gives pitch-sorted lists of notes.
- The WebAssembly module is built in Docker, and the GitHub Actions workflows build, test and deploy it (section 9).
- Efficient mode (hop 512, coarser search, no string identification) is available on the web as a setting; the web build uses the same two modes as everywhere else (full and efficient).
- Calibration is done in a WebAssembly build in a web page (this is also the tool for Bela); see section 7.

**Words used here:** the *hop* is how often the detector runs one analysis step (every 256 samples; 512 in efficient mode). A *render quantum* is the chunk of 128 samples the browser hands to audio code at a time. A *voice slot* is one of the detector's output channels for a note; a slot keeps the same note for as long as the note lasts, and slots are not sorted by pitch.

## 1. Overall structure

```
 microphone / audio source
          |
          v
  +---------------------------------------------+
  | AudioWorklet processor (audio thread)       |
  |   WebAssembly: fidddle Detector (one)       |
  |   every 128 samples: feed audio in          |
  |   when a step completes: read voices        |
  |        |                         |          |
  |  signal outputs            note / calibration|
  |  (pitch, level, gate)      events (messages) |
  +--------|-------------------------|----------+
           v                         v
  Web Audio graph               main thread
  (oscillator.frequency,        (Web MIDI, callbacks,
   gain, filters ...)            calibration page)
```

Files (proposed, under a new `web/` folder):

| File | Role |
|---|---|
| `web/wasm/fidddle_c_api.cpp` | Small C interface over `Detector` (section 3) |
| `web/wasm/build.sh` or CMake preset | Emscripten build to `fidddle.wasm` |
| `web/src/processor.js` | The AudioWorklet processor |
| `web/src/fidddle-signals.js` | JavaScript class: audio-rate outputs |
| `web/src/fidddle-events.js` | JavaScript class: note and calibration events |
| `web/demo/` | Demo page: microphone in, oscillator out, event log, calibration |

## 2. The two outputs

### 2.1 Audio-rate signals

The worklet has one output with `3 x V` mono channels, where V is the number of voices (4 for cello, 6 for guitar). For each voice slot:

| Signal | Value | Typical use |
|---|---|---|
| frequency | Hz | connect to an oscillator's `frequency` |
| level | linear amplitude, 0 to 1 | connect to a gain node's `gain` |
| gate | 0 or 1 (ramped over a few ms) | connect to a gain node, or use as an envelope trigger |

Details that matter:

- **Connecting to a parameter.** A signal connected to an `AudioParam` is added to the parameter's own value, so the target's value should be set to 0 first (for an oscillator, `osc.frequency.value = 0`). The JavaScript class does this for you.
- **One channel per connection.** Connecting a multi-channel output to a parameter mixes the channels together. The JavaScript class therefore places a channel splitter after the worklet and gives the page ready-made handles, for example `signals.connectFrequency(slot, osc.frequency)`.
- **Gliding.** The detector updates once per hop (every 5.8 ms or 11.6 ms). If the raw values were output they would change in steps, which sounds like zipper noise. The worklet therefore glides between values. The time of the glide is a setting (default 5 ms, decided 2026-10-26). When a voice starts, its frequency jumps to the new pitch with no glide, so an oscillator does not sweep up from the previous note.
- **Unused slots.** An idle slot keeps its last frequency and sets its gate to 0. An earlier idea of outputting 0 Hz is wrong because it would make an oscillator sweep down to 0 Hz when a note ends.
- **Which voices appear.** Only confirmed notes (states "active" and "releasing") are output. Notes still waiting for confirmation are not, so a signal never reports a note that the event stream would later reject.
- **Order (decided: stable slots).** A slot keeps the same note for as long as the note lasts, so a voice patched to an oscillator stays on that oscillator. If two notes cross in pitch they do not swap oscillators, which would cause clicks. A page that wants "lowest voice to oscillator 1" can turn on `signals.sorted = true`, which orders the outputs by pitch (the detector already reports a rank, 0 for the lowest voice). Readers of events (MIDI, score following) are not affected: they get notes with their pitch, and a list of the sounding notes already sorted by pitch (section 2.4).
- **Delay.** A note appears on the signals about as late as its note-on event (about 50 to 90 ms after the real start, from the confirmation step). Pitch changes inside a held note follow with one hop of delay.

### 2.2 Note events

Messages sent from the worklet through its message port, batched so a message is sent only when there is something to say:

| Message | Contents |
|---|---|
| `note-on` | note number, velocity (1 to 127), voice slot, confidence, flags (retrigger, weak onset), time |
| `note-off` | note number, voice slot, flags (inferred release, retrigger, end of stream), time |
| `calibration` | progress, string captured, complete, finished (section 7) |

**Time.** The core reports times in samples. The worklet turns them into audio-context seconds using the first frame it processed as the origin. Two times are given: the estimated real start of the note and the time it was reported. Events can never be scheduled earlier than they arrive, so a page that wants to play a sound from a note-on plays it immediately; the estimated start is for logging and analysis.

**Web MIDI.** The core knows nothing about it. The main-thread class converts events to MIDI messages on request (`events.connectMidi(output)`), because the Web MIDI interface lives on the main thread.

**String events.** String identification is not part of the web build at first (it is guitar-only, spike-prone, and not needed on Bela). It can be added later as another message type.

### 2.3 One detector, two classes

The detector's event queue allows exactly one reader. The worklet is that reader. Both JavaScript classes subscribe to what the worklet sends, so there is never a second reader and never a second analysis. A page can use either class alone, or both on the same node.

### 2.4 The JavaScript interface

The aim is that the common jobs take a line or two each, without knowing anything about slots, hops or WebAssembly. Sketch (names are proposals):

```js
import { Fidddle } from './fidddle.js';    // from the release zip or the Pages site

const fid = await Fidddle.create(audioContext, {
  profile: 'cello',          // 'bass' | 'cello' | 'viola' | 'violin' | 'guitar' | 'contrabass'
  voices: 4,
  mode: 'full',              // or 'efficient'
  calibration: savedList,    // optional
});
micSource.connect(fid.node);                       // audio in

// 1. Patch pitch to Web Audio nodes
const osc = new OscillatorNode(audioContext, { frequency: 0 });
const amp = new GainNode(audioContext, { gain: 0 });
fid.signals.connectFrequency(0, osc.frequency);    // voice slot 0 pitch -> oscillator
fid.signals.connectGate(0, amp.gain);              // slot 0 on/off -> amplifier
osc.connect(amp).connect(audioContext.destination);
osc.start();

// 2. Send MIDI to other devices
fid.events.connectMidi(midiOutput, { channel: 0 });

// 3. React to notes in your own code
fid.events.addEventListener('noteon',  e => console.log(e.detail));   // { note, midiFloat, velocity, slot, confidence, time, onsetTime }
fid.events.addEventListener('noteoff', e => console.log(e.detail));
fid.events.activeNotes;     // sounding notes right now, sorted by pitch: [{ note, midiFloat, frequency, velocity, since }]
```

For score following and similar analysis:

- Events carry the **fractional note number** (`midiFloat`, so tuning in cents is visible), the confidence, and **times in audio-context seconds**: when the note was reported and the estimated real start. Pages can compare these to a score clock.
- `fid.events.activeNotes` is a ready sorted snapshot, so a follower does not have to track note-on/off pairs itself.
- An opt-in `trackFrames: true` setting also posts a message at every analysis step with each sounding note's current pitch and level. It is off by default, because it sends a message every 5.8 ms (11.6 ms in efficient mode).
- The events can also be read as an async stream (`for await (const e of fid.events.stream())`) for code that prefers that style.
- Events are plain objects with plain numbers, so they can be logged, recorded and replayed in tests.

## 3. The WebAssembly interface

The core is C++ classes; the worklet needs plain functions. A small C interface (`fidddle_c_api.cpp`), instead of a binding generator, because audio worklets cannot easily use generated glue code. Sketch:

```
handle  fid_create(profile, sample_rate, voices, efficient /*0|1*/)
void    fid_destroy(handle)
void    fid_set_calibration(handle, const double* list, int n)
float*  fid_input(handle)               // buffer the worklet copies 128 samples into
int     fid_process(handle, int n)      // returns how many analysis steps completed
const float* fid_voices(handle)         // per slot: frequency, level, state, confidence, rank, note
int     fid_poll_event(handle, float* out)         // 1 if an event was written
int     fid_poll_calib_event(handle, float* out)
void    fid_calibrate(handle, int command)         // start, finish, cancel
int     fid_take_calibration(handle, double* out)  // returns the number of values written
void    fid_reset(handle)
```

All memory is allocated when `fid_create` runs. The WebAssembly memory is fixed in size (no growth), so the views the worklet holds on it never become invalid. The core's `Settings` header (which turns the user-adjustable values into a configuration) is used by `fid_create`, so the web build, the Max object and the Bela build build identical configurations.

The browser compiles the `.wasm` file on the main thread and sends the compiled module to the worklet through the processor options; the worklet creates the instance. (Standard practice, not yet tried here.)

## 4. Speed

Measured on a laptop with the current code (mean per analysis step; native, not WebAssembly):

| Profile | Mean per step | Share of the 5.8 ms hop |
|---|---|---|
| cello | 0.34 ms | 6% |
| guitar | 0.58 ms | 10% |
| bass | 0.70 ms | 12% |
| violin | about 0.5 ms | 9% |
| contrabass | 0.57 ms | 10% |

How this plays out in a browser:

- The browser calls the worklet every 128 samples (2.7 ms at 48 kHz). With hop 256, one call in two does the analysis step and the other almost no work. In efficient mode (hop 512), one call in four.
- WebAssembly is usually somewhat slower than native code. A phone processor is usually slower than a laptop. Both are **assumptions I have not measured.** If phones are 3 to 5 times slower than this laptop, cello takes about 1 to 1.7 ms per step, which fits inside a 2.7 ms call but leaves less margin; guitar with string identification (up to 2.5 ms on the laptop) would not fit. This is why the web build leaves string identification out and offers efficient mode.
- Occasional single steps took up to about 10 ms on a quiet laptop (cause unknown, possibly the operating system). A browser audio thread cannot absorb that, so expect rare glitches on slow devices. The fallback is to run the detector in a separate worker thread; it needs shared memory, which browsers allow only on pages served with special security headers. It is not planned unless the measurements show it is needed.
- **How to measure in a browser.** The audio worklet has no reliable high-resolution clock, so time cannot be measured from inside it. Run the same WebAssembly module in an ordinary web worker with `performance.now()`, feeding it the test recordings, to get the cost per step on a real phone. This is the first thing to do once the module builds.
- The core currently reads the clock three times per step for its own statistics. Whether the clock works in the audio worklet is untested, so the timing code gets a compile-time switch to turn it off for the web build (milestone 1).

## 5. Browser settings that matter

- **Microphone processing off.** Browsers apply echo cancellation, noise suppression and automatic gain control by default; they distort a string instrument and must be switched off when the microphone is requested (`echoCancellation`, `noiseSuppression` and `autoGainControl` set to false).
- **Sample rate.** Create the audio context at 48 kHz and let the browser convert. The core accepts other rates, but at 96 kHz the analysis windows double in length and cost grows (bass: 32768 samples). Only 44.1 and 48 kHz are tested.
- **Mono.** The worklet adds the input channels together (or takes channel 0; a setting).
- **Secure context.** Audio worklets work only on pages served over HTTPS or from localhost.
- **Quantum size.** The browser currently always uses 128 samples, but the specification allows other sizes in future. The core accepts any block size, so the worklet reads the size from the data it is given.

## 6. Core changes needed first

| # | Change | Why | Size |
|---|---|---|---|
| 1 | Switch to turn off timing calls | clock may not work in the worklet | small |
| 2 | Complete `Detector::reset()` | users stop and restart the microphone; today a restarted detector differs from a fresh one (noise estimate and onset state are not cleared) | small |
| 3 | Check the configuration in the constructor (hop size, voice count, window sizes) | the web page passes user-chosen numbers | small |
| 4 | Do not build string-identification memory unless needed | about 1.7 MB saved, and starts faster | small |
| 5 | A "build without string identification" switch | shared with the Bela build | small |
| 6 | Efficient mode | for slow devices; see `EFFICIENT_MODE_DESIGN.md` | medium |

Items 1 to 3 are needed before any release. Items 4 to 6 can follow.

## 7. Calibration in the browser

The calibration page is the same WebAssembly build, running in full mode (calibration depends on the full-mode step length; see `EFFICIENT_MODE_DESIGN.md` section 7).

- **Live:** the user plays each open string; the worklet sends progress messages; at the end the page asks for the result (`fid_take_calibration`) and shows it.
- **From a file:** the same code can process a recorded file at faster than real time in a web worker (the core's `calibrate_finish_now` exists for this). Useful for testing.
- **Saving:** the result is a flat list of about 260 numbers. The page offers it as a download and, for Bela, sends it to the board over the connection the Bela example web apps use. The format is the same list the Max object stores, with a small header (instrument, format version) so a mismatch is rejected.
- **Applying:** `fid_set_calibration` before running, exactly as the Max object does.

## 8. Testing

1. **Same answers as the native build.** Run the test recordings through the WebAssembly module in Node.js and compare notes with the native command-line tool. Expect identical notes; tiny numeric differences are possible because the maths library differs, so the comparison allows a small tolerance.
2. **Speed on real devices.** The web worker measurement from section 4, on at least one laptop, one Android phone and one iPhone.
3. **Audio test page.** Play a synthetic cello recording into the page; check that the oscillator driven by the signal outputs follows the pitch, and that gate and level behave at note starts and ends (no sweep at note end, no glide at note start).
4. **Start/stop.** Stop and restart the microphone repeatedly; results after a restart must equal results from a fresh detector (needs item 2 of section 6).
5. **Memory.** The existing "no allocation while processing" tests must also pass for the WebAssembly build's configuration.
6. **Browsers.** Chrome, Firefox and Safari. Audio worklets and WebAssembly are supported in all three; the worklet clock and timing behaviour differ.

## 9. Build and deployment (Docker and GitHub Actions)

**Docker build.** A `web/Dockerfile` based on the official Emscripten image (`emscripten/emsdk`) with the version pinned to one number, so every build uses the same compiler. A script `web/build.sh` runs the container, builds the core with the C interface, and writes `fidddle.wasm` plus the JavaScript files to `web/dist/`. Anyone with Docker can build without installing Emscripten. Output must not depend on the machine (no timestamps or absolute paths in the files), so builds can be compared.

**Continuous integration** (extends the existing `.github/workflows/ci.yml`, which currently builds the native core on macOS and runs the tests):

| Job | Runs | What it does |
|---|---|---|
| `web-build` | on every push and pull request | Builds the WebAssembly module in the Docker image; uploads it as a workflow artifact |
| `web-test` | after `web-build` | Installs Node.js, runs the recordings through the module and compares the notes with the native tool (test 1 in section 8); fails the build on a difference |

**Deployment** (extends `.github/workflows/release.yml`, which runs when a version tag is pushed and already has one job per target):

| Job | When | What it does |
|---|---|---|
| `web-release` | version tag | Builds the module again in Docker, then attaches `fidddle-web-<version>.zip` to the GitHub release next to the Max packages |
| `web-demo` | version tag (and manual start) | Publishes the demo page to GitHub Pages so people can try it without installing anything |

Notes:

- The demo page needs the page to be served over HTTPS, which GitHub Pages does. No special security headers are needed, because the design does not use shared memory.
- The demo will not include the OrchideaSOL recordings (their licence does not allow redistribution; see `ROADMAP.md` section 1). It uses the microphone, and a few short synthetic or freely licensed clips.
- The first version of these jobs will be written together with the C interface (milestone 2), because the module has to exist before there is anything to build and test in CI.

## 10. Milestones

1. Core changes 1 to 3 (section 6). Native tests still pass.
2. The C interface, the Docker build and the CI jobs `web-build` and `web-test`. Run a recording through the module in Node.js (test 1).
3. Speed test in a web worker on a laptop and a phone (test 2). **Decision point:** if a phone is far too slow, schedule efficient mode first; if it is fine, continue.
4. The audio worklet processor and the signal class; demo page with an oscillator.
5. The event class, Web MIDI output.
6. Calibration page and Bela hand-off (shared with the Bela work).
7. Efficient mode as a page setting.
8. Packaging: the release zip and the GitHub Pages demo (jobs `web-release`, `web-demo`). There is no npm package (decided 2026-10-26); pages load the files from the release zip or the Pages site.

## 11. Decisions and open questions

Decided (2026-10-26):

| Question | Decision |
|---|---|
| didddle in the web version? | Not now. |
| Glide default | 5 ms. |
| Slots or pitch order? | Stable slots for the signal outputs, with `signals.sorted` as an option; event readers get pitch-sorted lists. Chosen so patching voices to oscillators does not click, and so MIDI and score following need no knowledge of slots (section 2.4). |
| WebAssembly build | In Docker, and built and deployed by GitHub Actions (section 9). |

Also decided (2026-10-26):

| Question | Decision |
|---|---|
| Publish to npm? | No. Distribution is the GitHub release zip and the GitHub Pages demo. |
| Show notes before they are confirmed? | No, and no opt-in. A note still waiting for confirmation does have a pitch estimate, but showing it would gain only about 23 to 35 ms and would need a way to take a note back. A page that wants quicker, less certain notes lowers the existing `confirm_frames` setting, which does the same job for all outputs at once. |

Still open:

1. **Package name.** `fidddle-web` is a placeholder (used for file and zip names).
2. **Licence text in the release zip.** The repository is source-available (PolyForm Noncommercial), not open source; the zip should carry the same licence file as the Max packages.

## 12. Update after the efficient mode was implemented (2026-10-26)

Core changes in section 6, state now:

| # | Change | State |
|---|---|---|
| 1 | Switch to turn off timing calls | **Not done.** `Detector::analyze` calls `std::chrono::steady_clock` for `Diagnostics` on every step. The optional stage timers (`FIDDDLE_STAGE_TIMING`) use it too and must stay off in the web build. |
| 2 | Complete `Detector::reset()` | **Not done.** It still does not clear the noise floor, the onset flux baseline, the tracker's short-window history or `hops_` (the new noise-update counter), so a restarted detector differs from a fresh one. |
| 3 | Check the configuration in the constructor | **Not done.** Note that `Config` now has settings that must be consistent: `hop_size` (256 or 512) with the time-base helpers, `noise_update_hops`, `kernel_table`. A web page should pass a `Quality`, not single numbers. |
| 4 | No string-identification memory unless needed | **Done.** `Measure`, `History` and `Identifier` are created only when `cfg.string_id`; the calibrator only when `cfg.allow_calibration`. |
| 5 | Build without string identification | **Done.** `cmake -DFIDDDLE_NO_STRING_ID=ON` (C++ define `FIDDDLE_NO_STRING_ID`): no `stringid.cpp`, no `string` events, no `logb` in the calibration list. Library 303 KB to 273 KB. For Emscripten pass the define. |
| 6 | Efficient mode | **Done** in the core, Python and Max. See `EFFICIENT_MODE_DESIGN.md`, "Implementation status" and section 14. |

Facts the web build can use:

- **Interface for the C layer.** Choose the mode with `Config::for_instrument(profile_id, sample_rate, Quality::Efficient)` (or `apply_quality`). `Settings` (header `settings.hpp`) has `bool efficient` and builds the same `Config` for every host. Profile ids are `bass 0, cello 1, viola 2, violin 3, guitar 4, contrabass 5`; new profiles are appended, so saved settings keep their meaning.
- **Hop and render quantum.** The hop is 256 samples (full) or 512 (efficient): 2 or 4 render quanta of 128, so a step always completes exactly at the end of a quantum. `Detector::process` accepts any block size anyway.
- **Speed (laptop, Apple silicon, one core, 44.1 kHz).** Full mode: 0.32 ms of analysis per 5.8 ms step for a cello (a load of 5.6%); efficient mode: 0.21 ms per 11.6 ms step (1.8%). The other profiles are within 0.18 to 0.37 ms. Not measured: WebAssembly (about 1.5 to 2 times slower than native is typical) and phones (milestone 3). A phone that is 5 to 10 times slower than the laptop would need about 30% to 55% of one core in full mode and 10% to 18% in efficient mode; treat that as a guess until measured.
- **Allocation.** `process()` does not allocate in either mode (unit tests count allocations, with and without string identification and during a calibration). The first call of `gauss_table()` builds a 32 KB static table, done in the constructors of the stages, not in `process()`.
- **Events.** `Detector::poll_event` (note events), `poll_string` (guitar, full mode with a calibration only), `poll_calib_event` (kinds `Started, Progress, StringDone, Complete, Finished, Cancelled, Unavailable`; `Unavailable` means calibration was asked for in efficient mode). `take_calibration` hands over the result once.
- **Calibration** is made in the full mode and used in both. The list has up to 259 numbers (version 2, or version 3 with the string values; version 1 lists are still read).
- **Reference output to test against.** `core/build/fidddle_cli file.wav --profile <name> [--efficient]` prints the events as JSON lines. `tools/compare_cpp.py [--efficient]` compares them with the Python reference event for event (526 of 526 full, 500 of 500 efficient on the repository's test files). The WebAssembly module can be checked against the same JSON.
- **Demo audio for the web page.** The OrchideaSOL audio cannot be passed on (IRCAM Forum licence, README "Credits"), so a hosted demo page must not use it. TinySOL (violin, viola, cello, bowed ordinario) and GuitarSet are CC BY 4.0 and can be shipped with attribution; check the licence text again before shipping. The microphone input needs no audio at all.
- **Licence of the release zip** (open question 2): the repository uses PolyForm Noncommercial 1.0.0; `LICENSE` and `THIRD_PARTY_NOTICES.md` are copied into the Max package by `tools/package_release.sh`; the web zip should get the same two files, plus the notices of Emscripten output if any apply.

Open questions added: (3) whether the page should expose `Quality` as a switch or choose it from a measured speed test at start-up; (4) whether `fid_reset` should also be available while the worklet runs (needs item 2 above first).


## 13. Progress (2026-10-27)

Milestone 1 and most of milestone 2 are done.

| Item | State |
|---|---|
| Core changes 1 to 3 (section 6) | **Done.** `FIDDDLE_NO_TIMING` removes the clock calls; `Detector::reset()` clears the noise floor, onset flux, fit, candidates, events and calibrator; `Config::check()` / `validate()` reject unusable settings (the constructor throws, `fidddle~` reports and keeps the running detector). Native tests pass. |
| C interface | **Done:** `web/wasm/fidddle_c_api.cpp`. Differs from the sketch in section 3: calibration is passed to `fid_create` (the detector takes it at construction, as in the Max object), there is no `fid_set_calibration`; `fid_scratch` is the buffer for events and calibration lists; `fid_create` returns null with `fid_last_error()` instead of throwing (the module is built without exceptions). |
| Docker build | **Done:** `web/Dockerfile` (emsdk 3.1.74) and `web/build.sh` give `web/dist/fidddle.wasm`, 152 KB, no imports (so the worklet needs no glue code), fixed 64 MB memory. Two builds give byte-identical files. |
| Same answers as native | **Done:** `web/test/compare_native.mjs` runs files through the module in Node in 128-sample blocks and compares with `fidddle_cli`: 126 of 126 events identical on five real recordings, 88 of 88 in efficient mode, 38 of 38 on synthetic scenes. |
| Reset equals fresh | **Done:** `web/test/reset_test.mjs`. |
| CI | **Written, not yet run on GitHub:** jobs `web-build` and `web-test` in `ci.yml` (the tests use the synthetic scenes from `tools/make_synth_wavs.py`, since the recordings are not in the repository). |

**Speed of WebAssembly (Node, laptop, `web/test/speed.mjs`, 44.1 kHz, mean per step):** cello 1.13 ms in full mode (19.5% of the 5.8 ms hop), 0.61 ms in efficient mode (5.3% of 11.6 ms); guitar 1.10 / 0.52 ms; bass 1.15 / 0.77 ms. That is about 3.5 times the native time, more than the 1.5 to 2 times assumed in section 12, so a phone 5 times slower than this laptop would use roughly 100% of a core in full mode and 27% in efficient mode. **Efficient mode should be the web default until a phone is measured.** Untried speed-ups: `-O3`, `-msimd128`, 32-bit floats.

Next: milestone 3 (a web worker page to time it on a phone), then the worklet processor and the signal class (milestone 4).


## 14. Progress (2026-10-30): the web version works in Chrome

Milestones 3 to 5 and most of 8 are done. The code is in `web/` (see `web/README.md`).

| Item | State |
|---|---|
| Audio-thread engine | **Done:** `web/src/engine.js` (detector, glide of pitch and level, gate, events; no browser dependencies, so it also runs in Node). |
| AudioWorklet processor | **Done:** `web/src/processor.js`. One output with 3 x V mono channels, messages through the port. |
| Page-side library | **Done:** `web/src/fidddle.js`. `Fidddle.create`, `signals.connectFrequency / connectLevel / connectGate`, `signals.sorted`, `signals.glideMs`, `events` (`noteon`, `noteoff`, `frame`, `calibration`, `calibrationResult`, `activeNotes`, `stream()`, `connectMidi`), `calibrate`, `setCalibration`, `reset`, `destroy`. Efficient quality is the default. |
| Demo page | **Done:** `web/demo/index.html`. Both modes side by side: continuous (pitch signals drive oscillators, gate and level drive amplifiers) and MIDI (note events drive a built-in synth, a Web MIDI output, a log and a list of sounding notes), plus a pitch trace. Inputs: built-in test melody (no microphone needed), microphone (with echo cancellation, noise suppression and automatic gain off), or an audio file. |
| Speed test page | **Done:** `web/demo/speed.html` runs the module in a web worker and prints a table with a verdict, for use on phones. |
| Tests | **Done:** `engine_test.mjs` (19 checks incl. the processor with the AudioWorklet mocked), `calibration_test.mjs`, and `browser_test.mjs`, which runs the demo in headless Chrome with a real AudioWorklet: the detector starts, the melody's notes arrive as MIDI bytes on a fake port, the oscillators driven by the pitch signals sound at the detected pitch, they are silent between notes, no console errors. Passes for cello (efficient and full), guitar and violin. |
| Packaging and CI | **Written; the GitHub parts have not run yet.** `tools/package_web.sh` builds the zip (tested locally: the unzipped package passes the browser test). `ci.yml` now also runs the engine, calibration and headless Chrome tests. `release.yml` has jobs `web` (zip for the release) and `web-demo` (GitHub Pages; needs Pages enabled with source "GitHub Actions" in the repository settings; skipped for pre-release tags). No npm package. |

**Speed in a real browser (Chrome 148, headless, this laptop, web worker, mean per analysis step on the built-in melody; `demo/speed.html`):**

| Instrument | Efficient | Full |
|---|---|---|
| cello | 0.24 ms (2.2% load) | 0.36 ms (6.8%) |
| guitar | 0.27 ms (2.5%) | 0.44 ms (8.2%) |
| bass | 0.42 ms (3.9%) | 0.66 ms (12.4%) |
| violin | 0.20 ms (1.8%) | 0.30 ms (5.6%) |
| viola | 0.17 ms (1.6%) | 0.26 ms (4.9%) |
| contrabass | 0.29 ms (2.7%) | 0.47 ms (8.8%) |

This **corrects section 13**: the "3.5 times native" figure came from Node 18, whose WebAssembly engine is older. In Chrome the module is close to native speed (cello full 0.36 ms against 0.32 ms native). The built-in melody is simpler than real playing, so treat these as a floor. Still **not measured: phones and tablets, Firefox, Safari**; `speed.html` is the tool for that. The efficient default stays until a phone is measured.

**Things found while building it:**

- A worklet node that is not connected to anything is not run by the browser, so a page using only the note events would get nothing. The library keeps the node running with a muted path to the output.
- A `ChannelSplitterNode` after the worklet gives one connectable output per signal (connecting a multi-channel output to a parameter would add the channels together).
- A calibration is passed when the detector is created, so `setCalibration` replaces the detector inside the worklet.
- Delay from the estimated onset to the note-on event: about 20 to 40 ms on the built-in melody in both qualities. Real instruments will differ.

**Not done yet:** a test on a phone, Firefox and Safari; real Web MIDI hardware; a calibration page (the library supports it; no UI yet); pitch bend in `connectMidi`; the Bela hand-off of calibration lists.
