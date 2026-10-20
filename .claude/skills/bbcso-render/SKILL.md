---
name: bbcso-render
description: Render ground-truth MIDI + audio test clips (bowed, pizzicato, spiccato, tremolo on violin/viola/cello) with the Spitfire BBC Symphony Orchestra VST on this machine, for testing fidddle (pitch/note tracking) and didddle (source separation). Use when you need audio with exactly known notes, onsets, articulations or isolated per-voice stems.
---

# Rendering test clips with Spitfire BBCSO

Everything is driven by `tools/bbcso_render.py` (package `tools/bbcso/`), run with `.venv/bin/python` from the repo root.
It hosts the VST3 offline through DawDreamer, writes MIDI with mido, and emits audio plus a truth JSON. Output goes to
`data/bbcso/` (gitignored).

## What is installed (checked 2026-10-20)

- **BBC Symphony Orchestra Discover** (free edition, ~234 MB), VST3 at `/Library/Audio/Plug-Ins/VST3/`, library at
  `~/Spitfire/Spitfire Audio - BBC Symphony Orchestra`. Strings only matter here: Violins 1/2, Violas, Celli, Basses,
  each as a **section** (many players) and a **Leader** (one solo player), a handful of articulations in the UI.
- **Prefer `--player leader`** (the default). A section patch is a whole section playing in unison, so partial phases
  beat and drift unlike a single instrument. A leader patch is one player, much closer to what fidddle/didddle see in
  practice. Use `--player section` only when you want the harder, chorused case on purpose.

## One-time setup: capture patch states (needs a human)

Patch files are encrypted and patch choice is not a plugin parameter, so a patch can only be loaded by picking it in
the plugin UI and saving the plugin state. `status` shows what exists and what to pick:

```
.venv/bin/python tools/bbcso_render.py status
.venv/bin/python tools/bbcso_render.py capture                      # core leader set (long, pizzicato, spiccato, tremolo), one window each; Ctrl-C skips one, twice quits
.venv/bin/python tools/bbcso_render.py capture --instrument cello --articulation pizzicato --player section
```

`capture` opens the plugin editor, prints the exact patch name to choose (e.g. `Celli Leader - Short Pizzicato`),
and saves `data/bbcso/states/<instrument>__<player>__<articulation>.state` when the window is closed. After each capture it renders a probe note and warns if the patch behaves like the wrong articulation (a held
note should sustain for long/tremolo and die away for pizzicato/spiccato). Wait for the patch to finish loading
in the window before closing it. `verify` re-runs the probe on every saved state; **run it before trusting a set of
states and do not render from states it flags.** A state is a few KB and loads in about a second. **If `status` shows nothing captured, you cannot render: ask the user to run
`capture` (it opens a GUI window, so do not run it yourself in a non-interactive session).**

## Rendering

```
# one voice, exact notes: scene kinds = open_strings scale repeated random_line chord
.venv/bin/python tools/bbcso_render.py scene repeated --instrument cello --articulation pizzicato --name cello_pizz_rep
.venv/bin/python tools/bbcso_render.py scene random_line --instrument violin --articulation long --seed 3 --dynamics 60

# two voices at a known interval (stems are the exact per-voice truth): minor_third major_third fourth tritone fifth major_sixth octave
.venv/bin/python tools/bbcso_render.py pair --lo cello --hi viola --interval fifth --articulation long

# your own MIDI (one MIDI track = one stem, all rendered with the same instrument/articulation)
.venv/bin/python tools/bbcso_render.py midi my.mid --instrument cello --articulation spiccato

# many at once, mixing instruments / articulations per scene
.venv/bin/python tools/bbcso_render.py batch spec.json
```

Batch spec (`defaults` apply to every scene, scene keys override):
`{"defaults": {"player": "leader", "dynamics": 90}, "scenes": [{"name": "a", "kind": "scale", "instrument": "cello", "articulation": "long"}, {"name": "b", "kind": "pair", "lo": "cello", "hi": "violin", "interval": "octave"}, {"name": "c", "kind": "staggered", "instruments": ["cello", "viola", "violin"], "articulation": "long"}, {"name": "d", "kind": "midi", "file": "x.mid", "instrument": "viola"}]}`.
For mixed articulations in one mixture, render each articulation as its own scene and sum the stems yourself (a
scene shares one articulation). Scene generators live in `tools/bbcso/scenes.py`; add new ones there.

Knobs: `--dynamics 0-127` (the plugin's Dynamics parameter, default 127; MIDI CC1 does nothing through the host), `--param "Vibrato=0"` (any plugin parameter by name, 0-1;
list with `params`: Dynamics, Expression, Reverb, Release, Tightness, Vibrato, Variation, mic levels, Global Tune ...),
`--stereo`, `--sr`. Rendered audio is mono 44.1 kHz unless told otherwise. Velocity is per-note in the MIDI.

## Outputs (`data/bbcso/<name>.*`)

| file | content |
|---|---|
| `.wav` | the mixture (24-bit) |
| `.stems/<track>.wav` | each voice rendered alone: exact source for separation scoring (stems sum to the `.wav`; one shared gain is applied so levels stay consistent, recorded as `gain`) |
| `.mid` | one MIDI track per stem, 120 bpm |
| `.json` | `sr, tracks[], notes[], gain, warnings[]`. Each note: `onset, offset, midi, velocity, src, articulation` plus measured `audio_onset`, `onset_lag`, `silent`. Same `notes`/`src` shape as `data/mixes/*.json` |

## Reading the truth correctly

- `onset`/`offset`/`midi` are what was *sent*. The samples start a little after the note-on, and the lag is a fixed
  property of patch + pitch. `tools/bbcso/onset_lags.json` holds it per semitone for every core leader patch (made by
  `tools/bbcso_calibrate.py`; "sound start" = envelope reaches 5% of the note's peak), and each note in the truth json
  gets `audio_onset = onset + lag` and `onset_lag`. Typical lag: pizzicato 1-6 ms, spiccato 1-28 ms, bowed long 17-86 ms,
  tremolo 11-64 ms (varies by pitch, not by dynamics). Accuracy on unseen notes: pizz/spiccato within ~0.5 ms; bowed
  patches median 0.5-6 ms with occasional outliers of 9-45 ms (velocity-dependent attacks). Notes with no table entry
  (section players, bass pitches below the sampled range) have no `audio_onset`.
- "Sound start" is when the sample begins, not when a detector would fire: a slow bow swell is detected later. Report
  that detector delay as a result rather than folding it into the truth.
- `offset` is note-off; the release tail (set by the `Release` parameter) sounds after it. Do not score note-off
  against audio decay.
- Pitch is the sampled instrument's, in tune with the library (no per-note intonation error, no drift), and vibrato
  is on by default (`--param Vibrato=0` for a straight tone). Real bowed clips are messier than these.
- A `silent: true` note / entry in `warnings` means the note produced no audio (outside the patch's range, or samples
  had not finished streaming: raise `--settle`). Treat such a clip as invalid rather than scoring against it.
- Rendering is not assumed bit-reproducible across runs (round-robin / variation); keep the rendered wav, do not
  regenerate it in a test.

## Caveats to state when reporting results

- Audio is orchestral sample libraries with a hall mix: reverb tails, section chorus (for `section`), multi-mic phase
  relations. It tests note logic, onsets, articulation handling and separation under controlled overlap, **not**
  single-instrument phase/inharmonicity behaviour. A DI-style real recording (see `data/` real clips) remains the
  reference for those; say so when a result rests only on BBCSO renders.
- `Reverb` is forced to 0 on every render (overriding whatever the saved state holds), so material is as dry as the
  library's baked-in hall allows; raise it with `--param Reverb=0.3` to test tails. The json records the params used.
- The plugin UI offers only long / spiccato / pizzicato / tremolo (bass: no tremolo); legato, staccato etc. exist as
  patch files but are not loadable (`catalog.IN_PLUGIN` is the allowlist; `violin2` is not offered).
- The only single-player patches are the leaders; there is no other solo option in Discover. `bass` is available (no tremolo) but
  is not in the core capture set.

## Maintenance

- Tests (no plugin needed): `.venv/bin/python -m pytest tests/test_bbcso.py`.
- Requirements: `dawdreamer`, `mido`, `soundfile`, `numpy` (in `requirements.txt`).
- If the library is updated and a state stops loading, delete it and `capture --force` that patch.
