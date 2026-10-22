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

Still open, each with its risk:

- **Salience (130 µs).** About 30,000 probes per hop, most of them misses. Only compute the pitches whose first partials have a peak near them. Risk: none if done as a pure skip; check with the unit test that compares with the plain formula.
- **Noise floor every 2 to 4 hops** (about 25 µs of the 52). Its time constants are 0.2 s and 10 s. Risk: a stale floor at an onset; needs the same change in the Python reference and an F1 check. Not done because it changes results.
- **Guitar fit (135 µs).** Six voices and more candidates make the Gram matrix and the non-negative solves the largest part. Try fewer candidates when the previous frame had a stable fit (verify-only mode, archived spec §17.6). Risk: slower reaction to a new note; needs a latency check.
- **Fast `exp` and `log` (own polynomial, vectorised).** Risk: bits differ from the Python reference; check the parity test and the accuracy to 1e-12.
- **Single precision** for the hot loops. Risk: loses exact parity with the Python reference; probably fine for Bela, not for the reference.
- **FFT (37 µs).** A split-radix or NEON real FFT. Risk: none for accuracy, but it is a small share now.
- **Worst-hop spikes.** String identification runs a 2048–16384-point FFT and a 41-bin median over every bin in one hop. Spread it over several hops. See `BELA_PORT_REVIEW.md`.
- The resonator bank (section 3) can also be the always-on cheap detector that decides when to run the full fit.

## 5. Portability

- **Windows build of the Max objects** (the Max SDK supports it; our code has not been compiled there). Add a Windows job to `release.yml`.
- **Linux in CI** (`ubuntu-latest`) to build and test the core. Also run the tests with AddressSanitizer and UBSan.
- **Python/C++ parity in CI.** `compare_cpp.py` needs local recordings. Make a synthetic-only parity set that CI can run.
- **Other hosts:** Pure Data external, WebAudio (WASM and AudioWorklet), Bela (`BELA_PORT_REVIEW.md` has the findings), maybe a plug-in (VST3, CLAP).
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
