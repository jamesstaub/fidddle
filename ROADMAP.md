# Roadmap

Open work, from the testing and review done so far. Each item says why it matters and where the evidence is. Order inside a section is by value. The README has the current state and the benchmarks.

## 1. Test data (most useful next step)

- **GuitarSet** (Zenodo 1492449, CC BY 4.0). Real guitar playing with a pickup per string, so the truth is per string and per note. It would test chords, strums and string identification on real playing. These are the weak spots of the current tests (Orchidea has isolated notes, the real DI files have no labels). Add `tools/eval_guitarset.py`.
- **A bowed DI recording with note labels** (cello or violin). There is none. All the bowed results come from isolated studio notes or the older corpus. Needed for: extra short notes at note changes, vibrato, high register.
- **Stopped-position plucks on the DI guitar and bass**, a clean (low-noise) take, and chords with written fingerings. See the README, "Known limits".
- **Redistributable demo audio.** The OrchideaSOL audio cannot be passed on (IRCAM Forum licence). TinySOL (CC BY 4.0, violin, viola, cello, direct download at orch-idea.org) and GuitarSet (CC BY 4.0) can be shipped with attribution. Check each licence text again before shipping. Then the help patch works without a download step.
- **A script that makes the README tables** (`tools/run_benchmarks.py`), so the numbers cannot go out of date.

## 2. Quality and bugs

- **Sub-harmonic ghosts for high notes.** With the harmonic tier, a cello note above the normal range is now found (C6, E6 and C7 harmonics are reported), but extra notes at one half or one third of its pitch (C5, F4) often remain. Only the first partials of a high pitch are modelled, so a lower candidate can explain the same peak. A "unique evidence" test for lower candidates is the next thing to try (an earlier version of it did nothing on bowed cello lines, but this case is different).
- **Calibration misses some strings.** I traced the low E of the library's guitar: the calibrator rejects it for two reasons.
  1. The first partials are pulled by the body, so the fit of `(f/h)²` against `h²` on the first 6 partials gives a negative `B` (below the allowed −5e-5). A retry that leaves out partials 1 and 2 would fix it.
  2. The check "no strong peak at f0/2, f0/3 or f0/4" fires on low-frequency rumble at 41 Hz, which is below the lowest pitch of the profile and cannot be a note. The check should skip pitches below `minfreq`.
- **Short plucked notes** (violin, cello, contrabass pizzicato) need up to 6 plucks per string to reach the 30 accepted frames. Count frames of every pluck, but accept fewer frames when each is very clean.
- **Soft guitar notes.** The quiet-note rule is off for guitar and bass. Earlier Orchidea runs showed low recall for guitar pp (0.12). Test it with the attack requirement on.
- **Contrabass:** bright sul ponticello notes make octave notes (17 of 47 notes in a test). The contrabass has no real DI recording yet, so its defaults come from OrchideaSOL scenes only.
- **Chords on the guitar.** Recall against Basic Pitch is about 0.33. Low strings are lost where all their partials coincide with other notes. Ideas in the archived spec §17.2 (shared body response) and §17.3 (per-track `B`). Neither is implemented. The held-out measurements support the body response.
- **String identification in chords** gives no gain. Only measure while a note sounds alone, or use partials that are not shared.
- **Legato** (hammer-on, pull-off) is not reported on plucked profiles (spec §17.4, §17.5: admit a note that replaces a note on the same string).
- **Bass default `B`.** The real bass prefers `5e-5`, the Orchidea contrabass prefers 0. Decide when there is more bass data.
- **Max: changing `@profile` silently removes the calibration.** Post a warning.

## 3. Latency

- **Early-hint path.** A semitone resonator bank (the idea in luciamarock's Polyphonic-Pitch-Detector, GPL-3.0, so only the idea may be used) reaches 25% of its final level in 7–35 ms above 150 Hz, while our note-on takes 50–90 ms. Feed its pitches to the tracker as priors and shorten the confirmation count. Expected gain: 30–50 ms at best above 150 Hz, nothing for low strings. Must be checked for false notes on the noisy DI recordings. Measurement script: not committed (rebuild it from the coefficient formulas).
- **Shorter window for high notes.** The cello and guitar profiles use one 186 ms window for all notes. A second, shorter window for pitches above about 200 Hz would give earlier and cleaner onsets for them (multi-resolution analysis).
- **Tune the confirmation counts** (`confirm_frames` 6, strong onset 4) per profile on the Orchidea scenes.

## 4. Performance

Done (2026-10): the mean time per hop fell by 2.4 to 3.1 times (cello 1.00 to 0.32 ms). See the README, "Run time", for the list of changes and their risks. Where the time is now (cello, µs per hop): salience 130, fit 66, whitening and noise floor 52, FFT 37, onset flux 16, candidates 13, peak picking 7.

Done (2026-10-26): **efficient mode** (README, "Efficient mode"): a preset with hop 512, a 10-cent grid, 16 candidates, one refinement pass, a noise floor updated every 4th step and a table kernel. About a third of the processor time (cello 5.6% to 1.8% of a core). The noise-floor interval and the table kernel exist as separate settings (`noise_update_hops`, `kernel_table`) and are off in full mode, so full mode keeps its exact results.

Still open, each with its risk:

- **Efficient mode, next steps** (from `EFFICIENT_MODE_DESIGN.md` and `BELA_DECISION.md`): 32-bit floating point (compile-time `Real` type), the analysis in a separate low-priority task, input decimation by 2 to 4, the WebAssembly calibration page for Bela with a check header in the saved calibration, an efficient mode for `didddle~`, and timing on a real Bela (the decision checkpoint: mean at most 40% of the step). Risk: float loses exact parity with the Python reference.
- **Onset estimate in efficient mode.** Soft notes get an onset estimate that is up to 10 ms less precise (the onset flux is computed once per 11.6 ms). Idea, untested: compute the short-window flux at both half-steps (about 15 µs more per step).
- **Salience (130 µs full, 79 µs efficient).** About 30,000 probes per hop, most of them misses. Only compute the pitches whose first partials have a peak near them. Risk: none if done as a pure skip; the unit test that compares with the plain formula guards it.
- **Guitar fit (135 µs full, 91 µs efficient).** Six voices and more candidates make the Gram matrix and the non-negative solves the largest part. Try fewer candidates when the previous frame had a stable fit (verify-only mode, archived spec §17.6). Risk: slower reaction to a new note; needs a latency check.
- **Fast `exp` and `log` (own polynomial, vectorised)** for the full mode. Risk: bits differ from the Python reference; check the parity test and the accuracy to 1e-12.
- **FFT (37 µs).** A split-radix or NEON real FFT. Risk: none for accuracy, but a small share (15–18% in efficient mode).
- **Worst-hop spikes.** String identification runs a 2048–16384-point FFT and a 41-bin median over every bin in one hop. Spread it over several hops. See `BELA_PORT_REVIEW.md`.
- The resonator bank (section 3) can also be the always-on cheap detector that decides when to run the full fit.

## 5. Portability

- **Windows build of the Max objects** (the Max SDK supports it; our code has not been compiled there). Add a Windows job to `release.yml`.
- **Linux in CI** (`ubuntu-latest`) to build and test the core. Also run the tests with AddressSanitizer and UBSan.
- **Python/C++ parity in CI.** `compare_cpp.py` needs local recordings. Make a synthetic-only parity set that CI can run.
- **Other hosts:** Pure Data external, WebAudio (WASM and AudioWorklet: done for Chrome, see `web/README.md`; phones, Firefox and Safari still to test), Bela (`BELA_PORT_REVIEW.md` has the findings), maybe a plug-in (VST3, CLAP).
- Sample rates other than 44.1 and 48 kHz, and block sizes that do not divide the hop, should get explicit tests.
- **Releases:** notarization needs an Apple Developer account (secrets are described in the README). No release has been tested end to end yet. Try a pre-release tag first (`v0.1.0-rc.1`).

## 6. New features

- **Tuning attribute** (`@tuning`, for drop D, open G, capo). Today custom tunings need `@minfreq` and `@maxfreq`, and string identification and the string constraint use the built-in open strings.
- **More plucked profiles:** banjo, mandolin, ukulele, 12-string. Each needs its own open-string calibration, and a check that its strings really differ in `B / f²` (string identification) .
- **Per-string input** (hexaphonic pickup): one monophonic instance per string, string known by construction.
- **Save and load calibrations** as files from the Max object. The `@calibration` list is saved with the patch only.
- **Velocity** is derived from level only. A better mapping (attack energy) and a note-off velocity could be added.
- **Live input in Python** (a small streaming demo) for people without Max.
- didddle: see `didddle/README.md`.

## 7. Housekeeping

- **`orchidea_scenes` as its own project.** The package is self-contained (NumPy, SciPy, soundfile) with its own README, tests and `pyproject.toml`. To spin it off: move the folder, move `tests/test_orchidea_scenes.py`, add a licence, and decide whether to bundle a list of the IRCAM licence terms. Ideas: a `--seed-list`, loops of one note for onset tests, mixing several instruments in one scene, a sequence of MIDI-like events as input (`--score`).

- Many code comments still say "spec §…". `spec.md` is archived, so these pointers are history. Either keep the section numbers stable or replace them with README links.
- `tools/` has old scripts (`grid_*.sh`, older evaluation scripts). Remove or move the ones nobody uses.
- Unpushed or uncommitted at the time of writing: the two demo patches (`fidddle-demo.maxpat`, `didddle-demo.maxpat`) were re-saved in Max and differ from the repository.
- **To confirm by the author:** the statement in the README that no code from the cited works was copied; the bibliography details (written from memory, check page numbers and years); the sentence that the DI recordings and the cello corpus were supplied by the author; the licence choice (PolyForm Noncommercial is source-available, not OSI open source).

## 8. State of the project and lessons (kept here so they are not lost)

**State at 2026-10-26.** Released: `v0.1.0-rc.1` (the release workflow has been run once; signing and notarization are not set up). Not released yet: the contrabass profile, the harmonic upper tier, `orchidea_scenes`, the speed-up, efficient mode (all in `CHANGELOG.md` under Unreleased). Tests: 111 Python tests, the C++ unit tests (also built without string identification), and four parity checks (`tools/compare_cpp.py` with and without `--efficient`, `compare_calibration.py`, `compare_stringid.py`). Design documents written by other sessions: `EFFICIENT_MODE_DESIGN.md`, `BELA_DECISION.md`, `BELA_PORT_REVIEW.md`, `WEBAUDIO_DESIGN.md`.

**Rules that keep the project consistent.**

- The Python reference and the C++ core give the same events. Any change to the algorithm is made in both and checked with the parity scripts before it counts as done. Tables and constants that must be identical (the Gaussian table) are built the same way in both.
- A new setting defaults to the exact full-mode behaviour. The efficient mode is only the two lists `DetectorConfig.EFFICIENT` and `Config::apply_quality`.
- Per-frame constants are defined at the 256-sample reference hop (`frames()` and `per_frame()`); never add a bare frame count.
- `README.md` is the main document; `spec.md` is archived. Benchmarks in the README come from `tools/` scripts; rerun the script when a number changes.
- OrchideaSOL audio is under the IRCAM Forum licence: never commit it or anything rendered from it (`package/*/media/*.wav` is ignored; `tools/make_demo_audio.py` renders it locally). TinySOL and GuitarSet are CC BY 4.0 and could be shipped.
- The licence is PolyForm Noncommercial 1.0.0 (source-available). GPL code (for example the resonator-bank project reviewed in section 3) may be read for ideas but not copied.

**Findings worth remembering (so they are not repeated).**

- A prior inharmonicity `B` that is too high hurts far more than one that is too low; the guitar default is 0 and the bowed profiles use 0. Calibration only clearly helps the plucked electric bass.
- Widening the normal pitch range to cover harmonics makes the upper partials of ordinary notes into extra notes (plucked cello F1 0.65 to 0.45–0.61). The upper tier (near-pure tones only) avoids it. A sub-harmonic uniqueness guard did nothing on bowed cello lines.
- The long window is fixed by the lowest pitch; a longer window (10 periods) made contrabass scenes worse, not better.
- String identification works from `log(B/f²)` measured on a short Hann frame about 0.25 s into the note: 0.81 correct against 0.64 for the pitch rule on single guitar notes; no gain in chords. The per-frame `B` from the detector's own peaks is at chance level.
- Soft bowed notes were being lost by the absolute level gate (−58 dBFS); the "30 dB over the noise floor" rule fixed it for the bowed profiles without hurting the noisy recordings.
- Machine load spoils timing numbers. Measure on an idle machine, take the best of three, and use the mean per step, not the maximum.
- The calibrator needs 30 good frames per string; short plucked notes need 4 to 6 plucks per string. The low E of the library's guitar is rejected for two traced reasons (section 2).
- The OrchideaSOL library is quiet and has long tails; normalise the scene (`--normalize 0.5`) before testing a detector, as a real input would be.

**Open decisions for the author.**

1. Push the unpushed commits and cut the next release candidate (`python tools/set_version.py`, tag, push; try `v0.x.y-rc.N` first).
2. Whether to keep the 0.01-F1 budget of the design document or accept the measured 0.02 for efficient mode.
3. Which real recordings to add first: bowed cello or violin DI with note labels, stopped-position guitar takes, a contrabass.
4. The statements in the README that need the author's check (listed in section 7 of this file).

