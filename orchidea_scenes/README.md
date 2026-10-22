# orchidea_scenes

Build polyphonic test scenes with exact truth from the [OrchideaSOL](https://www.orch-idea.org/datasets/) one-shots (violin, viola, cello, contrabass, guitar).
Every scene gives you the mixture, one stem per note, and a truth list (onset, offset, pitch, technique, dynamic, string, source file).

It needs only NumPy, SciPy and soundfile. It does not depend on fidddle. It is written so that the folder can be copied or installed
(`pip install ./orchidea_scenes`) and used in other projects: pitch tracking, transcription, source separation, instrument or technique tests.

The audio of OrchideaSOL is not part of this code and is under the IRCAM Forum licence. Download it yourself (free IRCAM Forum account):
<https://forum.ircam.fr/projects/detail/orchideasol/>. Scenes made from it inherit that licence, so do not publish them.

## Find the library

The library root is the folder that contains `Strings/` and `PluckedStrings/`. It is found from, in this order: the `--root` option (or the
`root` argument), the environment variable `ORCHIDEA_ROOT`, and `data/_OrchideaSOL2020_release/OrchideaSOL2020` below the current folder.

## Command line

```
python -m orchidea_scenes index                         # what the library has: techniques, dynamics, pitch range
python -m orchidea_scenes index --instrument contrabass

# 10 scenes with 4 overlapping contrabass lines: two parts plucked, one part bowed, all dynamics
python -m orchidea_scenes generate --instrument contrabass --kind overlap --polyphony 4 --n 10 \
    --techniques plucked:2,sustained:1 --dynamics pp,mf,ff --out scenes --formats wav,json,stems,midi --seed 1

# guitar chords that a player could really play (each string once), peak level 0.5, white noise at 30 dB
python -m orchidea_scenes generate --instrument guitar --kind chords --voices 5 --distinct-strings --normalize 0.5 --noise-snr 30 --out scenes

# many scenes from a file
python -m orchidea_scenes generate --spec scenes.json --out scenes
```

`scenes.json` is a list of scene options. An entry may also have `n` (number of scenes):

```json
[
  {"instrument": "cello", "kind": "lines", "voices": 3, "techniques": ["sustained"], "n": 20, "seed": 1},
  {"instrument": "violin", "kind": "chords", "techniques": {"plucked": 1, "harmonics": 1}, "midi_range": [60, 100], "n": 5}
]
```

## Python

```python
from orchidea_scenes import Library, SceneSpec, generate, generate_many

lib = Library()                                    # or Library("/path/to/OrchideaSOL2020")
spec = SceneSpec(instrument="contrabass", kind="overlap", voices=4, polyphony=3.0,
                 techniques={"plucked": 1, "sustained": 2}, dynamics=["pp", "mf", "ff"], seed=3)
scene = generate(lib, spec, index=0)               # the same spec, seed and index always give the same scene
scene.audio                                        # mixture, mono, float
scene.stems                                        # (notes, samples); the stems add up to the mixture exactly (before added noise)
scene.notes                                        # truth, one dict per note (see below)
scene.write("out/", formats=("wav", "json", "stems", "midi"))

for sc in generate_many(lib, spec, 100):           # indices 0..99
    ...
lib.select("cello", techniques=["pizzicato_secco"], dynamics=["ff"], midi_range=(40, 60))   # plain queries on the library
```

## Scene kinds

| Kind | What it makes |
| ---- | ------------- |
| `chords` | `voices` different pitches struck together, `hits` times |
| `intervals` | two notes a fixed interval apart (`intervals`: semitones), `hits` times |
| `strum` | `voices` pitches rolled 30–60 ms apart (`strum_spread`), `hits` times |
| `arpeggio` | `voices` pitches one after another, 0.12–0.3 s apart; they ring on |
| `lines` | `voices` independent melodic lines of consecutive notes over `duration` seconds |
| `overlap` | notes at random times; `polyphony` is the mean number of notes sounding at once |
| `open_strings` | every open string, `hits` times each, in random order (a calibration pass) |

## Techniques and dynamics

- `techniques` and `dynamics` take a list of names, or a dict of weights (`{"plucked": 1, "sustained": 3}`; on the command line `plucked:1,sustained:3`).
- A technique can be a group: `plucked` (pizzicato, col legno battuto, all guitar), `bowed`, `sustained` (bowed without tremolo, harmonics and col legno), `harmonics`.
- Combinations: the technique and the dynamic are drawn for every note by default. `articulation="voice"` draws them once per voice (or once per chord position), `articulation="scene"` once for the whole scene.
- For each note the generator picks a pitch inside `midi_range` first, then a technique among those that have this pitch, then a dynamic. Pitches are exact library pitches. A technique that does not reach a pitch is not forced to.

## Options of `SceneSpec`

| Option | Meaning |
| ------ | ------- |
| `instrument` | `violin`, `viola`, `cello`, `contrabass`, `guitar` |
| `kind`, `voices`, `hits`, `duration` | see the kinds above (`duration` for `lines` and `overlap`, default 8 s) |
| `techniques`, `dynamics`, `articulation` | see above |
| `midi_range` | `(lo, hi)`, default: the range of the selected sounds |
| `distinct_strings` | each string once per chord, as a player must (best effort; the pitch may move by a semitone when it cannot be played) |
| `bowed_length` | seconds a bowed note is held, drawn uniformly (default 1.0–2.2); plucked notes ring up to `pluck_max_s` (2.5) |
| `gain_jitter_db` | random level change per note |
| `normalize_peak` | scale the scene to this peak (the library recordings are quiet, a real input is not) |
| `noise_snr_db` | add white noise at this SNR. The stems stay clean, so mixture ≠ sum of stems then |
| `sr`, `lead_in`, `seed` | sample rate (44100), silence before the first note, random seed |

## Truth

`scene.notes[i]` (and `notes` in the JSON file) has: `onset`, `offset` (note-off: the cut point of a bowed note, the end of the natural decay of a plucked note, capped at `pluck_max_s`),
`end` (when the sound has stopped), `midi`, `f0_hz` (nominal pitch from the file name; real notes are a few cents off), `instrument`, `technique`, `dynamic`, `string`,
`kind` (`plucked` or `bowed`), `file`, `voice`, `gain_db`, and `src` (the name of its stem). The JSON file also has the scene options, the shared gain, and the sample rate.

Bowed notes are cut after 1–2.2 s with a 60 ms fade. This is not a performance: no bow-change continuity, no legato, no shared room, abrupt note ends, unnaturally clean attacks.

## Files

`library.py` (index of the sounds, queries, technique groups), `render.py` (place sounds, stems, mixture), `scenes.py` (`SceneSpec`, kinds, `generate`), `midi.py` (MIDI export), `cli.py`.
Tests: `tests/test_orchidea_scenes.py` in the fidddle repository (a small fake library, no OrchideaSOL needed).
