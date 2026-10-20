---
name: orchidea-eval
description: Evaluate fidddle (note tracking) and didddle (source separation) on polyphonic string scenes built from OrchideaSOL one-shots (real recordings of violin/viola/cello/bass/guitar with known pitch, technique, dynamic). Use for per-technique / per-dynamic / per-register breakdowns of tracker recall and separation gain, or to generate mixtures with exact per-note truth from real samples.
---

# Evaluating on OrchideaSOL scenes

`tools/eval_orchidea.py` (package `tools/orchidea/`) builds polyphonic scenes by placing real one-shot recordings at
known times, so truth is exact (pitch, onset, offset, technique, dynamic, and each note's isolated stem). Run with
`.venv/bin/python` from the repo root.

## Data

`data/_OrchideaSOL2020_release/OrchideaSOL2020/` (gitignored): `Strings/` for violin, viola, cello, bass and `PluckedStrings/Guitar/` for guitar. Path and file name carry the metadata:
`Violoncello/ordinario/Vc-ord-A3-ff-4c-N.wav` = instrument, technique, pitch (MIDI 57), dynamic, string 4 ("4c"),
variant. Default catalog = pitched, unmuted, original recordings (variant `N`; `T12u`/`R200d` are processed
derivatives, `+sordina` is muted, `behind_the_bridge` etc. have no pitch). 4742 sounds: cello 1061, violin 1259, viola
1314, bass 1108. Mono 44.1 kHz, typically 5-12 s for bowed, ~1 s for pizzicato, no leading silence. `--instrument guitar` works in every command; its techniques are ordinario, ordinario_high_register (mf only), harmonic_fingering (p only), pizzicato_bartok (ff only), sul_ponticello (mf only), range D2-A6, always plucked (natural decay, capped at 2.5 s). Use `--voices 4-6` for strums and chords.

```
.venv/bin/python tools/eval_orchidea.py index --instrument cello     # techniques x dynamics available
```
Most techniques exist at one dynamic only (mostly `mf`); only ordinario, pizzicato and a few others have pp/mf/ff. So
`--dynamics ff` restricts you to few techniques; check `index` first.

## Commands

```
# fidddle: note-level P/R/F1 per scene kind, plus recall by technique / dynamic / register
.venv/bin/python tools/eval_orchidea.py tracker --instrument cello --n 4
.venv/bin/python tools/eval_orchidea.py tracker --techniques ordinario,pizzicato_secco --kind chords --voices 3 --set key=value

# didddle: SI-SDR gain over the mixture per note stem, by kind / technique / dynamic
.venv/bin/python tools/eval_orchidea.py separate detector --n 4       # pitches from fidddle run on the mix (realistic)
.venv/bin/python tools/eval_orchidea.py separate nominal --n 4        # pitches = file-name pitch (see caveat)

# write scenes (mix wav, per-note stems, truth json) to data/orchidea/ or --save DIR
.venv/bin/python tools/eval_orchidea.py make --kind lines --voices 4 --n 10 --seed 3
```
Scene kinds (`--kind`, comma list; default all): `chords` (N different pitches together, `--hits` times), `intervals`
(two notes 3/4/5/6/7/9/12 semitones apart), `strum` (N pitches rolled 30-60 ms apart), `lines` (`--voices` independent
melodic lines over 8 s). Each scene is reproducible from `--seed` + kind + index. `--techniques`/`--dynamics` take comma
lists and mix techniques within a scene (technique is drawn uniformly first, so rare techniques are not drowned out).
Add new scene kinds in `tools/orchidea/mix.py:scene`.

Wall time: tracker ~5 s per scene, separate detector ~8 s per scene, nominal ~4 s. Use `--n 2` for quick looks.

## Truth, and what it means

- Each note is one file placed at its onset. Bowed notes are cut after 1-2.2 s with a 60 ms fade (a bow release);
  plucked ones (`pizzicato*`, `col_legno_battuto`, and everything on guitar) keep their natural decay, capped at 2.5 s. `offset` in the truth is the
  note-off; `end` is when the sound stops. Levels are the library's own; if a scene would clip, one shared gain is
  applied to mix and stems together (stems always sum to the mix exactly).
- **Pitch truth is the nominal pitch from the file name.** Real notes sit some cents off, and some labels may be a
  semitone from what is heard (one cello ordinario file labelled 54 was tracked as 53 in a spot check; not
  investigated). Tracker scoring requires an exact MIDI match, so this counts as an error against fidddle.
- **Tremolo / sul ponticello tremolo / artificial-harmonic tremolo are one long note in the truth, but the sound is many
  bow strokes.** fidddle re-triggers on them (a single tremolo note produced 3-25 detections in spot checks), which the
  tracker table scores as false notes and low precision; separation gain on `tremolo` is also low (1.5 dB nominal).
  Judge those techniques separately from sustained and plucked ones.
- Scoring is `tools/eval_tracker.score` (mir_eval, onset tolerance `--tol`, default 0.15 s, pitch exact), and
  `didddle.metrics.score` for separation, so numbers are comparable with `eval_tracker.py` / `eval_separation.py`.
- `separate nominal` is **not an upper bound**: the detector run measures real pitch and can beat it (20.7 vs 18.7 dB
  mean gain in the first spot check). `separate detector` uses a 250 ms output delay, non-causal pitch lookahead like
  `eval_separation.py detector` (`--latency` to change).

## First results (2026-10-20, cello, `--n 2`, seed 0; small samples, directional only)

- Tracker, one voice at a time: pitch and onset right for clean ordinario/pizzicato notes, but extra short false notes
  (50-80 ms, often a harmonic above the true pitch) at attacks; 71 detections for 19 true notes in 4 single-voice `lines`
  scenes. Chords: 42 detected for 18 true (P 0.14, R 0.33).
- Separation, detector pitches: mean gain 20.7 dB, median 22.1 dB over 77 note stems (chords 20.3, intervals 22.0,
  lines 22.2, strum 17.6).
- Guitar (`--n 2 --voices 4`): tracker P/R/F1 chords 0.44/0.42/0.43, intervals 0.39/0.67/0.49, lines 0.50/0.56/0.53, strum 0.35/0.42/0.37;
  recall lowest on pp (0.12) and ordinario_high_register (0.28), best on ordinario (0.71) and ff (0.76). Separation with
  detector pitches: mean gain 20.4 dB (chords 16.8, lines 22.6, strum 18.9). Notes above ~F6 are outside fidddle's guitar
  profile range (max 1400 Hz) and the library goes up to A6.
Re-run before quoting; these are single small runs.

## Caveats to state when reporting

- These are isolated studio one-shots cut and summed, not a performance: no bow-change continuity, no legato, no
  shared room, abrupt (faded) note ends, unnaturally clean attack onsets, no ghost notes, accidental scrapes, or bow noise. They test pitch/onset logic and separation
  under controlled overlap, per technique. Real DI recordings in `data/` remain the check for realism.
- Overlapping notes get no shared reverb; every note is anechoic-ish and phase-independent of the others.
- The library has 1-3 recordings per (technique, pitch, dynamic), so many scenes reuse the same files.

## Maintenance

Tests: `.venv/bin/python -m pytest tests/test_orchidea.py` (fake audio, plus a real-library check that is skipped when
the data is absent).
