# fidddle

Real-time polyphonic pitch detector for string instruments. It finds up to 6 notes at the same time in a mono signal
and follows them over time. Built-in profiles: **bass (5-string), cello, viola, violin, guitar**.

It comes in three forms that give the same results:

| Form | Where | Use |
| ---- | ----- | --- |
| Python reference | `fidddle/` | Read the algorithm, run experiments, run the benchmarks |
| C++17 core | `core/` | No dependencies, no memory allocation while processing. Meant for Max, Pure Data, Bela, WebAudio |
| Max 9 external `fidddle~` | `max/`, `package/` | Use it in a patch |

`didddle` is a companion project in the same repository. It splits a signal into one signal per detected note, using
the pitch tracks of fidddle. See [didddle/README.md](didddle/README.md).

This file is the main document of the project. `spec.md` is the original research and design document. It is kept as
an archive and is no longer updated.

**License:** [PolyForm Noncommercial 1.0.0](LICENSE). Free for noncommercial use. See [License](#license).

---

## Contents

1. [Quick start](#quick-start)
2. [How it works](#how-it-works)
3. [Instrument profiles](#instrument-profiles)
4. [Calibration](#calibration)
5. [String identification](#string-identification)
6. [Benchmarks](#benchmarks)
7. [Known limits](#known-limits)
8. [Run the Python code](#run-the-python-code)
9. [Build the C++ core and the Max object](#build-the-c-core-and-the-max-object)
10. [Use fidddle~ in Max](#use-fidddle-in-max)
11. [Releases](#releases)
12. [Repository layout](#repository-layout)
13. [Credits and references](#credits-and-references)
14. [License](#license)

---

## Quick start

```
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python -m pytest -q                                     # 80+ tests
.venv/bin/python -m fidddle recording.wav --profile guitar        # print the notes of a WAV file
```

---

## How it works

The input is mono audio. Every **hop** (256 samples, 5.8 ms at 44.1 kHz) the detector runs these stages:

1. **Input conditioning.** A DC blocker (30 Hz) removes offset and rumble. A ring buffer keeps the last samples.
2. **Spectrum.** One long Hann-windowed FFT (8192 samples for cello and guitar, 16384 = 372 ms for the 5-string bass, 4096 for viola and violin). The window length follows the lowest pitch the profile can search (6 to 10 periods of it). A second, short FFT (2048 samples) is used only to see note attacks.
3. **Whitening and noise floor.** The log spectrum minus its smooth envelope (about half an octave wide) gives a spectrum with flat partial levels. A slow noise floor (median over about 40 bins, smoothed in time) gates weak peaks. Spectral peaks are picked and their position is refined with a parabola on the log magnitude.
4. **Candidates.** Every pitch on a 5-cent grid inside the profile range gets a **harmonic salience**: the sum of the peak strengths found at its expected partials. Pitches near the notes already being tracked are always added. The best local maxima become candidates. A candidate does not need a visible fundamental.
5. **Polyphonic fit.** The observed peaks are explained as a sum of harmonic templates (one per note) with non-negative amplitudes. Notes are added one at a time (greedy). A note is kept only if it explains enough new energy, and each added note pays a small penalty. Pitches are then refined by ±20 cents. Two notes closer than 70 cents are not allowed, and a note that only repeats the partials of another one needs extra evidence. Partials of plucked strings are placed at `h·f·sqrt(1 + B·h²)`, where `B` is the inharmonicity of the string.
6. **Tracking.** Fitted notes are matched to existing tracks (Hungarian assignment on pitch distance). A track goes through `PENDING → ACTIVE → RELEASING`. A new note must stay for a few frames before it is reported. A repeated pluck on a ringing string is found by a rise of the energy at its partials. Guitar and bass notes must also show an **attack** (an 8 dB energy rise); this removes ghost notes that come from ringing strings. Octave and twelfth flicker is held back by a short octave hold.
7. **Output.** Note-on and note-off events (MIDI note, velocity, a stable voice **slot**, timestamps) and, for each slot, a continuous frequency and level.

Quiet notes: an absolute level gate (−58 dBFS) rejects noise. On the bowed profiles a note below the gate is still accepted when it is 30 dB above the local noise floor, so soft playing is not lost.

Timing at 44.1 kHz: a note-on arrives about 70–130 ms after the physical onset (longer for the bass), and a note-off about 100–200 ms after the sound ends. Mean analysis time is about 1 ms per 5.8 ms hop (5 to 7 times faster than real time on a laptop). The worst hop is about 3–5 ms.

---

## Instrument profiles

| Profile | Open strings (Hz) | Search range (Hz) | Voices | Long window |
| ------- | ----------------- | ----------------- | ------ | ----------- |
| bass (5-string, B0–G2) | 30.87, 41.20, 55.00, 73.42, 98.00 | 28–500 | 4 | 16384 samples (372 ms) |
| cello | 65.41, 98.00, 146.83, 220.00 | 60–1000 | 4 | 8192 (186 ms) |
| viola | 130.81, 196.00, 293.66, 440.00 | 120–1500 | 4 | 4096 (93 ms) |
| violin | 196.00, 293.66, 440.00, 659.26 | 185–2800 | 4 | 4096 (93 ms) |
| guitar | 82.41, 110.00, 146.83, 196.00, 246.94, 329.63 | 70–1400 | 6 | 8192 (186 ms) |

Differences between the profiles:

- **Guitar and bass are plucked.** A new note must show an attack. Notes may ring while other notes are played. The partials are stretched by `B` (bass prior `B = 5e-5`, guitar prior `B = 0`).
- **Cello, viola and violin are bowed.** A steady bowed string locks to an exact harmonic series, so `B = 0`. No attack is needed. The quiet-note rule above is on.
- **Custom tunings.** Set `voices`, `minfreq` and `maxfreq` yourself. A 4-string bass can use `minfreq 38` to get the shorter 186 ms window.

---

## Calibration

The default values are guesses. A calibration measures the real strings of **your** instrument.

**What you play:** pluck each **open** string on its own and let it ring for about a second. One string at a time, in any order. Do not bow (a bowed string is locked to a harmonic series and shows no stiffness). Anything that is not one clean note near an open string is ignored, so other playing in between does no harm. You do not need all strings. The calibration ends by itself when every string is captured.

**What it learns, per string:**

- the inharmonicity `B` (how much the partials are stretched), and the exact tuning,
- the typical balance of the partial levels,
- one stiffness value `log(B / f²)` that identifies the string (see the next section).

The result is applied at once and saved with the Max patch. It is plain data (a list of numbers), so you can also save it yourself.

**Does it help?** It is decisive when the profile is far off, for example plucked bass. It is neutral for guitar (a flat `B = 0` already works as well). See [Benchmarks](#benchmarks).

No annotated pitches, no recordings made in advance and no noise-free recordings are needed.

---

## String identification

For the **guitar** profile, after a calibration, the detector says which string played each note.

- A stiff string has `B` proportional to `f²` along its length. So `log(B / f²)` is almost a constant of the string.
- About 0.25 s after a note-on, the detector measures `B` of the note on a short Hann frame and compares `log(B / f²)` with the values learned in the calibration. Only strings that can play the pitch are candidates.
- If the best string wins by a margin of at least 0.3 (log units), that string is reported with the margin. If not, the answer is the **pitch rule** (the highest string that can play the pitch, usually the lowest fret) with margin 0. Margin 0 means "a guess".
- Strings are numbered as on a guitar: 1 is the highest.

On single guitar notes it is right for 86% of the pitches that exist on two or more strings, against 75% for the pitch rule alone. Every answer with a margin of at least 0.3 was right. For chords there is no gain, because the partials of the notes overlap. It does not work for bowed instruments (their `B` is 0).

---

## Benchmarks

All numbers come from the scripts in `tools/` (see [Run the Python code](#run-the-python-code)). Python and C++ give the same results (events match 538 of 538 in the parity test).

Note scores use `mir_eval`: a note is correct when its pitch is within 50 cents (exact MIDI for Orchidea) and its onset within ±0.1 s (±0.15 s for Orchidea). P is precision, R is recall.

### Synthetic strings (exact truth)

Additive strings with random partial phases and decays. Single notes, fifths, chords, strums and arpeggios of 1 to 6 strings.

| Profile | Note F1 |
| ------- | ------- |
| viola, violin | 1.00 |
| guitar (chords up to 6 notes) | 1.00 (frame-level 0.93) |
| cello, 4 open strings together | about 0.8 |
| bass, 4 strings together | about 0.6 |

Synthetic scenes are easier than real ones. Use them to find bugs, not to judge quality.

### Real DI recordings (noisy DI box, noise floor −63 to −72 dBFS, 60 Hz hum)

One acoustic guitar and one 5-string bass. The open-string files have a known truth. For the chord files the only reference is Basic Pitch, which is not a real truth, so treat P and R as relative numbers.

| Test | Profile default | Calibrated |
| ---- | --------------- | ---------- |
| guitar, 6 open strings found | 6 of 6, 2 extra notes | 6 of 6, 0 extra (tested on the same file) |
| guitar chords, P / R vs Basic Pitch | 0.95 / 0.33 | 0.81 / 0.34 |
| bass, 5 open strings found | 5 of 5, 0 extra | 5 of 5, 0 extra |
| bass chords, P / R vs Basic Pitch | 0.52 / 0.14 | 0.68 / 0.17 |

### OrchideaSOL: real isolated notes cut and summed (exact truth)

Scenes of notes from the OrchideaSOL library (real studio recordings of single notes). Pitch must match exactly. Calibration is learned from the open-string notes of the same library.

Note F1 for stopped notes (lines, chords, strums, intervals; 6 scenes of each kind):

| Task | Old guitar prior `B = 1e-4` | Flat `B = 0` | Flat `B = 3e-5` | Calibrated |
| ---- | --------------------------- | ------------ | --------------- | ---------- |
| guitar, all scene kinds | 0.44 | 0.68 | 0.59 | 0.67 |
| bass plucked, all scene kinds (old bass prior) | 0.25 | 0.29 | 0.24 | **0.57** |
| bass bowed, all scene kinds (old bass prior) | 0.28 | 0.35 | 0.31 | 0.38 |

The guitar default is now `B = 0`. The first column of the bass rows is the profile default `B = 5e-5`.

Guitar with the current default, by scene kind: lines 0.59, chords 0.74, strums 0.78, two-note intervals 0.86.

**Soft bowed notes.** The pp notes of the library peak at −42 (cello) to −48 dBFS (violin) and swell slowly. With the fixed −58 dBFS gate, 36 of 41 violin pp notes were missed. With the "30 dB over the noise floor" rule, missed notes dropped from 14 to 5 (cello), 15 to 6 (violin) and 19 to 3 (viola) of about 40, at the cost of a few extra short notes. The noisy real-DI results did not change.

**A wrong `B` prior.** A prior that is too high hurts far more than one that is too low. Bowed notes with `B = 3e-4` instead of 0 gave 38 → 63 detections (violin), 40 → 65 (viola), 85 → 132 (cello) for the same notes. So bowed profiles use `B = 0`.

### String identification (OrchideaSOL guitar, 162 single notes)

| Method | Correct, pitch on 2+ strings |
| ------ | ---------------------------- |
| pitch rule only | 92 of 123 (0.75) |
| stiffness, with fallback to the pitch rule | 106 of 123 (0.86) |
| stiffness, answers with margin ≥ 0.3 only | 47 of 47 (the rule: 33 of 47) |

### Run time

Desktop, 44.1 kHz, cello and guitar profiles: mean 0.9–1.1 ms per hop (budget 5.8 ms). String identification adds about 35 µs per hop on average. `process()` allocates no memory (checked by a unit test, also with string identification and during a calibration).

---

## Known limits

- **Dense chords:** in a strummed chord, low strings are often lost, because all their partials coincide with partials of the other notes. On the real guitar, recall against Basic Pitch is about 0.33.
- **Extra short notes:** short ghost notes still appear at note changes, mostly an octave or a twelfth from the real pitch. On the cello they are worst above about G5, where vibrato smears the partials and the second partial is stronger than the fundamental.
- **Latency:** the long window makes the note-on late by 70–130 ms (more for the bass). This cannot be removed without losing low-pitch accuracy.
- **Plucked profiles ignore legato.** A hammer-on or pull-off has no new attack, so it is not reported as a new note.
- **Calibration is for plucked strings only.** On a bowed instrument it measures nothing useful.
- **Orchestral pizzicato** is not a clean stiff string. A flat `B = 0` works as well as a measured `B` there.
- **Mono input.** The tests use dry, close-mic or DI signals of one instrument. Stereo ensemble mixes are expected to work worse and are not tested.
- **Test data:** the real DI recordings are one guitar and one bass. There is no real bowed DI recording with note labels yet. Stopped-position takes on the DI instruments, clean (low-noise) takes and chords with written fingerings are missing and would test more of the assumptions above.

---

## Run the Python code

```
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python -m pytest -q
```

**Detect notes in a file:**

```
.venv/bin/python -m fidddle recording.wav --profile cello
.venv/bin/python -m fidddle chords.wav --profile guitar --calibrate-from open-strings.wav
.venv/bin/python -m fidddle recording.wav --profile guitar --json        # one JSON object per event
```

`--calibrate-from` takes a recording of isolated plucked open strings (see [Calibration](#calibration)). The output has one line per event (`on`, `off`, and `string` for the guitar after a calibration).

**From Python:**

```python
import soundfile as sf
from fidddle.analyzer import Analyzer
from fidddle.profile import DetectorConfig

x, sr = sf.read("recording.wav")
az = Analyzer(DetectorConfig.for_instrument("cello", float(sr)))
az.run(x, track=True)
for e in az.events:                  # kind: "on", "off" or "string"
    print(e.kind, e.midi_note, e.velocity, e.slot, e.onset_est_samples / sr)
```

**Benchmarks and experiments** (all in `tools/`, run from the repository root):

| Script | What it does |
| ------ | ------------ |
| `eval_tracker.py` | Note scores on synthetic scenes, real clips and silence (`--only synth`, `mixes`, `solo`, `dead`) |
| `eval_instruments.py` | Per-instrument synthetic scenes |
| `eval_real.py` | Scorecard on the real DI guitar and bass files in `data/` (`--cal-from-open`) |
| `eval_defaults.py guitar\|bass` | Profile default against flat `B` against calibration, on OrchideaSOL scenes |
| `eval_orchidea.py` | Tracker and separation scores on OrchideaSOL scenes (see `.claude/skills/orchidea-eval/SKILL.md`) |
| `orchidea_errors.py`, `orchidea_scene_report.py` | Classify the false notes, or compare truth and detection for one scene |
| `eval_string_id.py` | String identification on OrchideaSOL guitar notes |
| `eval_physics.py`, `orchidea_notes.py` | Physical measurements on isolated notes: stiffness, mode locking, body response |
| `compare_cpp.py`, `compare_calibration.py`, `compare_stringid.py` | Check that the C++ core gives the same results as Python |
| `make_demo_audio.py` | Render the demo audio of the Max package from OrchideaSOL |
| `plot_notes.py` | Spectrogram with the detected notes drawn on it |

Data used by the scripts, all in `data/` (not in the repository):

- the real DI recordings (`guitar-*.wav`, `5string-bass-*.wav`),
- OrchideaSOL, downloaded from the IRCAM Forum (<https://forum.ircam.fr/projects/detail/orchideasol/>, free account) and unpacked to `data/_OrchideaSOL2020_release/OrchideaSOL2020/` (folders `Strings/` and `PluckedStrings/`). the guitar is in `PluckedStrings/`,
- optional: a cello corpus and the Basic Pitch command line tool (paths in `fidddle/corpus.py`), used only by the older comparison scripts.

---

## Build the C++ core and the Max object

Requirements: CMake 3.19 or newer, a C++17 compiler. For Max: Max 9 on macOS (the SDK is fetched by CMake, or put it in `third_party/max-sdk-base`).

**Core, command-line tool and unit tests:**

```
cmake -S core -B core/build && cmake --build core/build -j
core/build/fidddle_tests                                          # unit tests, including the no-allocation test
core/build/fidddle_cli recording.wav --profile guitar             # JSON lines: events and a summary
core/build/fidddle_cli session.wav --profile guitar --calibrate   # prints the learned calibration list
core/build/fidddle_cli chords.wav --profile guitar --calibration "<list>"
.venv/bin/python tools/compare_cpp.py --frames                    # same events and pitches as Python?
```

`--set name=value` changes a setting (for example `--set min_level_dbfs=-65`).

**Max external:** (the version number comes from the `VERSION` file)

```
cmake -S max -B max/build -G "Unix Makefiles" && cmake --build max/build -j
package/install.sh        # links package/fidddle into ~/Documents/Max 9/Packages (then restart Max)
```

The result is `package/fidddle/externals/fidddle~.mxo` (universal binary, ad-hoc signed; `didddle~.mxo` is built too). To share the object with other people you need to sign and notarize it with your own Apple developer account.

The package also contains the help file (`help/`), the reference pages (`docs/`), a demo patch (`examples/fidddle-demo.maxpat`) and the demo audio (`media/`, see below).

**Demo audio.** The help file plays short examples for cello, violin and guitar: the open strings (for the calibration demo) and a polyphonic passage (for the detector demo). The audio is not included in this repository or package. The notes come from the OrchideaSOL library, and its IRCAM Forum licence does not allow passing the audio on. Get it yourself and render the examples:

1. Download **OrchideaSOL 2020** from the IRCAM Forum (free account needed): <https://forum.ircam.fr/projects/detail/orchideasol/>. More information: <https://www.orch-idea.org/datasets/> and <https://zenodo.org/records/3686252>.
2. Unpack it to `data/_OrchideaSOL2020_release/` so that the folders `data/_OrchideaSOL2020_release/OrchideaSOL2020/Strings/` (violin, viola, cello, bass) and `.../PluckedStrings/Guitar/` (guitar) exist. Both are part of the OrchideaSOL download.
3. Render the files:

```
.venv/bin/python tools/make_demo_audio.py        # writes package/fidddle/media/*.wav
```

The WAV files are listed in `.gitignore`. The help file finds them by name in the `media/` folder of the package.

---

## Use fidddle~ in Max

Open the help file (`fidddle~.maxhelp`) or `examples/fidddle-demo.maxpat`.

**Inlet:** mono audio signal. Also accepts the messages below.

**Outlets (left to right):**

| Outlets | Content |
| ------- | ------- |
| 0–5 | voice frequency in Hz, one signal per slot (0 when silent) |
| 6–11 | voice level, one signal per slot (linear) |
| 12 | list `<midinote> <velocity> <slot>`. Velocity 0 is a note-off. A repeated pluck sends the off, then the on |
| 13 | replies to `info`, calibration messages, and `string <slot> <string number> <margin>` |

**Attributes** (type `@` after the object name to see them):

| Attribute | Meaning |
| --------- | ------- |
| `@profile` | `bass` `cello` `viola` `violin` `guitar` (0–4). Sets `@voices`, `@minfreq` and `@maxfreq` to the defaults of that instrument |
| `@voices` | maximum number of notes at the same time, 1–6 |
| `@minfreq` `@maxfreq` | pitch search range in Hz. The analysis window follows `@minfreq` |
| `@minlevel` | level gate in dBFS (default −58) |
| `@confirm` | frames a new note must stay before it is reported |
| `@release` | note-off delay in ms (0 = profile default) |
| `@retrigger` | rise (dB) that counts as a new attack on a ringing note |
| `@calibration` | the learned calibration (a list of numbers). Saved with the patch |

Values you set yourself win over the profile defaults, whatever the order. Setting `@profile` again restores that instrument's defaults.

**Messages:**

| Message | Action |
| ------- | ------ |
| `calibrate 1` | start a calibration (then pluck each open string on its own) |
| `calibrate 0` | finish with the strings captured so far (the others keep the profile defaults) |
| `calibrate cancel` | abandon the session |
| `calibrate clear` | remove the calibration |
| `reset` | clear all tracks |
| `info` | print profile, analysis window, timing and latency on outlet 13 |

Progress comes from outlet 13: `calibrate started`, `progress`, `string`, `complete`, `applied`. Changing `@profile` removes the calibration.

**Calibration in a patch:**

1. Turn audio on. Send `calibrate 1`.
2. Pluck each open string once or twice, one at a time.
3. When all strings are captured the object finishes by itself. The calibration is saved with the patch.

**String messages:** on the guitar profile with a calibration, outlet 13 sends `string <slot> <string number> <margin>` about a quarter second after a note-on. Margin 0 means a guess.

---

## Releases

Releases are on GitHub under **Releases**. Each release has a version number like `1.4.2` and a zip file with the Max package (`fidddle-max-<version>-macos.zip`, universal binary for Apple Silicon and Intel, with a `.sha256` checksum). The changes of every version are in [CHANGELOG.md](CHANGELOG.md).

### Install a release

1. Download the zip from the Releases page and unzip it. You get a folder `fidddle`.
2. Move the folder to `~/Documents/Max 9/Packages/` and restart Max.
3. Check the version: send `info` to `fidddle~`. The first reply on outlet 13 is `version <number>`.

The objects are signed ad hoc unless the release says it is notarized. If macOS blocks them ("cannot be opened because the developer cannot be verified"), remove the quarantine mark once:

```
xattr -dr com.apple.quarantine ~/Documents/Max\ 9/Packages/fidddle
```

The demo audio is not in the zip (see [Build the C++ core and the Max object](#build-the-c-core-and-the-max-object)).

### Version numbers

The project uses [Semantic Versioning](https://semver.org/): `MAJOR.MINOR.PATCH`. The file `VERSION` in the repository root is the single source of the number. The build copies it into the Max objects, the C++ library, `python -m fidddle --version` and `package-info.json`.

| Change | Number that goes up |
| ------ | ------------------- |
| Bug fix, speed-up, or tuning that changes the detected notes but not the interface | PATCH |
| New attribute, message, outlet message, profile or command-line option, in a way that old patches still work | MINOR |
| Removed or renamed attribute, message or outlet; different argument or outlet format; a saved `@calibration` list that the new version cannot read | MAJOR |

The public interface is: the messages, attributes and outlets of the Max objects (including the format of `calibrate`, `string` and the `info` replies), the saved `@calibration` list, the C++ API in `core/include/fidddle/`, and the options of `python -m fidddle`. A new version must always read calibration lists written by older versions.

Before 1.0.0 the interface may still change in a MINOR version. Such changes are listed under "Changed" or "Removed" in the changelog. A tag with a suffix, like `v0.2.0-rc.1`, becomes a pre-release.

### Make a release (maintainer)

1. Write the changes under `## [Unreleased]` in `CHANGELOG.md`.
2. `python tools/set_version.py 0.2.0`. This updates `VERSION`, `package/fidddle/package-info.json` and the changelog (the `[Unreleased]` notes move to a dated `[0.2.0]` section).
3. Review the diff, commit it (`Release 0.2.0`) and push it to `main`.
4. Tag and push the tag: `git tag v0.2.0 && git push origin v0.2.0`.

The workflow `.github/workflows/release.yml` then checks that the tag matches `VERSION`, runs the Python and C++ tests, builds and packages the Max objects on a macOS runner, and creates the GitHub release with the changelog section as its text. Only tags that pass all tests produce a release.

To try the packaging on your machine, run `tools/package_release.sh`. It writes `dist/fidddle-max-<version>-macos.zip`.

**Signing and notarization (optional).** Without a certificate the objects are signed ad hoc. For a Developer ID signature and notarization, add these repository secrets: `MACOS_CERTIFICATE` (base64 of the `.p12` file), `MACOS_CERTIFICATE_PASSWORD`, `CODESIGN_IDENTITY` (for example `Developer ID Application: Name (TEAMID)`), and for notarization `APPLE_ID`, `APPLE_TEAM_ID`, `APPLE_APP_PASSWORD` (an app-specific password).

**Other build targets.** Each target is one job in `release.yml` that uploads its files as an artifact (for example `fidddle-<target>-<version>-<os>.zip`). Add the job to the `needs` list of the `publish` job and its files join the same release.

---

## Repository layout

| Path | Content |
| ---- | ------- |
| `fidddle/` | Python reference: `profile.py` (profiles, config, calibration data), `spectral.py`, `salience.py`, `fitter.py`, `tracker.py`, `calibrate.py`, `stringid.py`, `analyzer.py`, `synth.py` (synthetic strings), `__main__.py` (command line) |
| `core/` | C++17 core (`src/`, `include/fidddle/`), the command-line tool (`cli/`), unit tests (`tests/`) |
| `max/fidddle~`, `max/didddle~` | Max externals |
| `package/fidddle/` | Max package: help files, reference pages, demo patches, `media/` (demo audio, rendered locally) |
| `didddle/` | Source separator: Python reference. C++ in `core/src/didddle` |
| `tools/` | Benchmarks and experiments |
| `tests/` | Python tests |
| `VERSION`, `CHANGELOG.md` | Current version (single source) and the history of changes |
| `tools/package_release.sh`, `set_version.py`, `changelog_notes.py` | Release tools |
| `.github/workflows/` | CI (`ci.yml`) and releases (`release.yml`) |
| `spec.md` | Archived research and design document |
| `BELA_PORT_REVIEW.md` | Notes for a port to the Bela platform |

---

## Credits and references

fidddle was written by James Staub, with a lot of help from Claude Code (Anthropic) for the code, the experiments and the documentation.

The algorithms below are standard methods from the literature, written again from the descriptions. No code from these works was copied. Where an idea is used directly, it is listed here.

### Data and tools used directly

- **OrchideaSOL**, used for testing. C. E. Cella, D. Ghisi, V. Lostanlen, F. Lévy, J. Fineberg, Y. Maresz, "OrchideaSOL: a dataset of extended instrumental techniques for computer-aided orchestration," *Proc. International Computer Music Conference (ICMC)*, 2020. Dataset page: <https://www.orch-idea.org/datasets/>, download: <https://forum.ircam.fr/projects/detail/orchideasol/> (free IRCAM Forum account), metadata: <https://zenodo.org/records/3686252>. The notes were recorded at IRCAM in 1996–1999 (Studio On Line). The audio is used under the **IRCAM Forum licence** (https://forum.ircam.fr/legal/contrat-de-licence-forum-ircam/), the metadata under CC BY 4.0. The library is **not** included in this repository.
- **Basic Pitch**, used as a comparison baseline only. R. M. Bittner, J. J. Bosch, D. Rubinstein, G. Meseguer-Brocal, S. Ewert, "A lightweight instrument-agnostic model for polyphonic note transcription and multipitch estimation," *ICASSP*, 2022 (https://github.com/spotify/basic-pitch, Apache-2.0). Run through **basicpitch.cpp** by Sevag H (MIT), <https://github.com/sevagh/basicpitch.cpp>.
- **Max SDK** (`max-sdk-base`), © Cycling '74, MIT licence. Max is a product of Cycling '74.
- **mir_eval**. C. Raffel, B. McFee, E. J. Humphrey, J. Salamon, O. Nieto, D. Liang, D. P. W. Ellis, "mir_eval: A transparent implementation of common MIR metrics," *ISMIR*, 2014. Used for the note scores.
- **NumPy, SciPy** (FFT, non-negative least squares, median filter, assignment solver), **soundfile**, **matplotlib**, **pytest**.
- The **real DI recordings** (guitar and 5-string bass) and the cello corpus used in the real-data tests were supplied by the author.

### Physics and acoustics

- **Inharmonicity of stiff strings** (`f_h = h·f₀·sqrt(1 + B·h²)`). H. Fletcher, "Normal vibration frequencies of a stiff piano string," *J. Acoust. Soc. Am.* 36(1), 203–209, 1964. Also N. H. Fletcher and T. D. Rossing, *The Physics of Musical Instruments*, 2nd ed., Springer, 1998.
- **Estimating `B` from the partials.** G. Galembo and A. Askenfelt, "Signal representation and estimation of spectral parameters by inharmonic comb filters with application to the piano," *IEEE Trans. Speech Audio Process.* 7(2), 197–203, 1999. F. Rigaud, B. David, L. Daudet, "A parametric model and estimation techniques for the inharmonicity and tuning of the piano," *J. Acoust. Soc. Am.* 133(5), 3107–3118, 2013. These are for the piano; fidddle uses a simpler least-squares fit of `(f_h/h)²` against `h²`.
- **Bowed strings lock to an exact harmonic series** (why bowed profiles use `B = 0`). H. von Helmholtz, *Die Lehre von den Tonempfindungen*, 1863. J. C. Schelleng, "The bowed string and the player," *J. Acoust. Soc. Am.* 53, 26–41, 1973. M. E. McIntyre, R. T. Schumacher, J. Woodhouse, "On the oscillations of musical instruments," *J. Acoust. Soc. Am.* 74(5), 1325–1345, 1983. L. Cremer, *The Physics of the Violin*, MIT Press, 1984.
- **Telling guitar strings apart from audio** (prior art for string identification). J. Abeßer, "Automatic string detection for bass guitar and electric guitar," *Proc. CMMR*, 2012. A. M. Barbancho, A. Klapuri, L. J. Tardón, I. Barbancho, "Automatic transcription of guitar chords and fingering from audio," *IEEE Trans. Audio Speech Lang. Process.* 20(3), 915–921, 2012. Their methods differ from the stiffness test used here.

### Signal processing and transcription

- **Harmonic salience, spectral whitening, iterative estimate-and-cancel multi-pitch analysis.** A. Klapuri, "Multiple fundamental frequency estimation based on harmonicity and spectral smoothness," *IEEE Trans. Speech Audio Process.* 11(6), 804–816, 2003. A. Klapuri, "Multiple fundamental frequency estimation by summing harmonic amplitudes," *ISMIR*, 2006.
- **Explaining a spectrum with non-negative harmonic templates.** M. Mauch and S. Dixon, "Approximate note transcription for the improved identification of difficult chords," *ISMIR*, 2010. C. L. Lawson and R. J. Hanson, *Solving Least Squares Problems*, Prentice-Hall, 1974 (the non-negative least squares method).
- **Window and peak interpolation.** F. J. Harris, "On the use of windows for harmonic analysis with the discrete Fourier transform," *Proc. IEEE* 66(1), 51–83, 1978. J. O. Smith and X. Serra, "PARSHL: an analysis/synthesis program for non-harmonic sounds based on a sinusoidal representation," *ICMC*, 1987 (parabolic interpolation of spectral peaks).
- **Onset evidence from the short-window spectrum.** J. P. Bello, L. Daudet, S. Abdallah, C. Duxbury, M. Davies, M. B. Sandler, "A tutorial on onset detection in music signals," *IEEE Trans. Speech Audio Process.* 13(5), 1035–1047, 2005. S. Dixon, "Onset detection revisited," *DAFx*, 2006.
- **Noise floor estimation.** The noise floor is a time-smoothed median across frequency, in the spirit of R. Martin, "Noise power spectral density estimation based on optimal smoothing and minimum statistics," *IEEE Trans. Speech Audio Process.* 9(5), 504–512, 2001. It is not the same algorithm.
- **Track assignment.** H. W. Kuhn, "The Hungarian method for the assignment problem," *Naval Research Logistics Quarterly* 2, 83–97, 1955; the SciPy solver follows D. F. Crouse, "On implementing 2D rectangular assignment algorithms," *IEEE Trans. Aerosp. Electron. Syst.* 52(4), 1679–1696, 2016.

The following parts are the author's own design and have no direct source: the attack requirement for plucked notes, the octave hold, the quiet-note rule (level relative to the noise floor), the open-string calibration, and the stiffness test for string identification.

---

## License

Copyright (c) 2026 James Staub.

fidddle and didddle are licensed under the **[PolyForm Noncommercial License 1.0.0](LICENSE)**. You may use, copy, change and share the code for any noncommercial purpose (personal use, study, research, hobby projects, education, nonprofit work). Commercial use needs a separate license from the author.

This is a *source-available* license, not an OSI-approved open source license, because the Open Source Definition does not allow a ban on commercial use.

Third-party parts keep their own licenses: the Max SDK (`third_party/`, MIT, © Cycling '74), and the audio and data you download yourself (OrchideaSOL: IRCAM Forum licence; see Credits).
