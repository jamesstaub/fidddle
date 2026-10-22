# Roadmap

Open work, from the testing and review done so far. Each item says why it matters and where the evidence is. Order inside a section is by value. The README has the current state and the benchmarks.

## 1. Test data (most useful next step)

- **GuitarSet** (Zenodo 1492449, CC BY 4.0). Real guitar playing with a pickup per string, so the truth is per string and per note. It would test chords, strums and string identification on real playing. These are the weak spots of the current tests (Orchidea has isolated notes, the real DI files have no labels). Add `tools/eval_guitarset.py`.
- **A bowed DI recording with note labels** (cello or violin). There is none. All the bowed results come from isolated studio notes or the older corpus. Needed for: extra short notes at note changes, vibrato, high register.
- **Stopped-position plucks on the DI guitar and bass**, a clean (low-noise) take, and chords with written fingerings. See the README, "Known limits".
- **Redistributable demo audio.** The OrchideaSOL audio cannot be passed on (IRCAM Forum licence). TinySOL (CC BY 4.0, violin, viola, cello, direct download at orch-idea.org) and GuitarSet (CC BY 4.0) can be shipped with attribution. Check each licence text again before shipping. Then the help patch works without a download step.
- **A script that makes the README tables** (`tools/run_benchmarks.py`), so the numbers cannot go out of date.

## 2. Quality and bugs

- **Notes above the profile range make sub-octave ghosts.** A cello playing C6 (above `maxfreq`) gave C5 and F4 notes. Add a guard or a clear rule for energy above the range.
- **Calibration misses some strings.**
  - A guitar low E with a split fundamental (two peaks about 57 cents apart, string beating) is never captured, because the calibrator needs one clean note. Merge near-duplicate voices inside the calibrator.
  - Short plucked notes (violin, cello pizzicato) need up to 6 takes per string to reach the 30 accepted frames. Relax the rule for short notes.
- **Soft guitar notes.** The quiet-note rule is off for guitar and bass. Earlier Orchidea runs showed low recall for guitar pp (0.12). Test it with the attack requirement on.
- **No bowed double bass profile.** The bass profile is an electric bass (attack required, `B = 5e-5`). Bowed double bass (Orchidea) scores F1 0.38 with it. Add a bowed variant or an excitation attribute.
- **Chords on the guitar.** Recall against Basic Pitch is about 0.33. Low strings are lost where all their partials coincide with other notes. Ideas in the archived spec §17.2 (shared body response) and §17.3 (per-track `B`). Neither is implemented. The held-out measurements support the body response.
- **String identification in chords** gives no gain. Only measure while a note sounds alone, or use partials that are not shared.
- **Legato** (hammer-on, pull-off) is not reported on plucked profiles (spec §17.4, §17.5: admit a note that replaces a note on the same string).
- **Bass default `B`.** The real bass prefers `5e-5`, the Orchidea bass prefers 0. Decide when there is more bass data.
- **Max: changing `@profile` silently removes the calibration.** Post a warning.

## 3. Latency

- **Early-hint path.** A semitone resonator bank (the idea in luciamarock's Polyphonic-Pitch-Detector, GPL-3.0, so only the idea may be used) reaches 25% of its final level in 7–35 ms above 150 Hz, while our note-on takes 50–90 ms. Feed its pitches to the tracker as priors and shorten the confirmation count. Expected gain: 30–50 ms at best above 150 Hz, nothing for low strings. Must be checked for false notes on the noisy DI recordings. Measurement script: not committed (rebuild it from the coefficient formulas).
- **Shorter window for high notes.** The cello and guitar profiles use one 186 ms window for all notes. A second, shorter window for pitches above about 200 Hz would give earlier and cleaner onsets for them (multi-resolution analysis).
- **Tune the confirmation counts** (`confirm_frames` 6, strong onset 4) per profile on the Orchidea scenes.

## 4. Performance

- Transcendental calls (`exp`, `log`) are about a third of the time, salience 23%, the noise-floor median 12%, the fit 11%, the FFT 7%. Planned in the archived spec §17.6: tabulate the peak kernel, update the noise floor every 4–8 hops, skip the full search while all tracks are stable (verify-only mode), single precision for the hot loops. Target: 3 times less time per hop with F1 within 0.01.
- **Worst-hop spikes.** String identification runs a 2048–16384-point FFT and a 41-bin median over every bin in one hop. Spread it over several hops or compute the median on fewer bins. See `BELA_PORT_REVIEW.md`.
- The resonator bank can also be the always-on cheap detector that decides when to run the full fit.

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

- Many code comments still say "spec §…". `spec.md` is archived, so these pointers are history. Either keep the section numbers stable or replace them with README links.
- `tools/` has old scripts (`grid_*.sh`, older evaluation scripts). Remove or move the ones nobody uses.
- Unpushed or uncommitted at the time of writing: the two demo patches (`fidddle-demo.maxpat`, `didddle-demo.maxpat`) were re-saved in Max and differ from the repository.
- **To confirm by the author:** the statement in the README that no code from the cited works was copied; the bibliography details (written from memory, check page numbers and years); the sentence that the DI recordings and the cello corpus were supplied by the author; the licence choice (PolyForm Noncommercial is source-available, not OSI open source).
