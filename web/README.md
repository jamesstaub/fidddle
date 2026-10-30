# fidddle for the web

Polyphonic pitch detection for string instruments in a web page. The C++ detector is compiled to WebAssembly and runs in an AudioWorklet (the browser's audio thread). It gives two kinds of result from **one** analysis run:

- **Continuous signals:** for each voice a frequency (Hz), a level and an on/off gate, as audio signals. Connect them to the controls of any Web Audio node, for example an oscillator's `frequency`.
- **Note events:** note-on and note-off with note number, velocity, confidence and times, as JavaScript events or Web MIDI messages.

Design and decisions: `../WEBAUDIO_DESIGN.md`. Licence: see `../LICENSE` (source-available, non-commercial).

## Try it

The page needs to be served over HTTP (browsers do not run audio worklets from `file://`):

```
python3 -m http.server -d web 8123      # from the repository root
```

Then open `http://localhost:8123/demo/` (the demo: both modes, with a built-in test melody, microphone or an audio file) and `http://localhost:8123/demo/speed.html` (times the detector on the device you open it on).

`web/dist/fidddle.wasm` must exist: `web/build.sh` builds it in Docker (pinned Emscripten), or download a release zip.

## Use it

```js
import { Fidddle } from './src/fidddle.js';

const ctx = new AudioContext({ sampleRate: 48123 });
const fid = await Fidddle.create(ctx, { profile: 'cello', quality: 'efficient' });
micSource.connect(fid.node);                          // audio in (any channel count; mixed to mono)

// continuous: patch a voice to Web Audio nodes
const osc = new OscillatorNode(ctx, { frequency: 0 });
const amp = new GainNode(ctx, { gain: 0 });
osc.connect(amp).connect(ctx.destination); osc.start();
fid.signals.connectFrequency(0, osc.frequency);       // voice 0 pitch
fid.signals.connectGate(0, amp.gain);                 // voice 0 on/off
fid.signals.connectLevel(0, otherGain.gain, { scale: 3 });   // loudness, if you want it

// events
fid.events.addEventListener('noteon',  (e) => console.log(e.detail));   // { note, midiFloat, frequency, velocity, slot, confidence, time, onsetTime }
fid.events.addEventListener('noteoff', (e) => console.log(e.detail));
fid.events.activeNotes;                               // sounding notes, sorted by pitch
fid.events.connectMidi(midiOutput, { channel: 0 });   // a MIDIOutput from navigator.requestMIDIAccess()
for await (const e of fid.events.stream()) { /* ... */ }
```

Options of `Fidddle.create`: `profile` (`bass`, `cello`, `viola`, `violin`, `guitar`, `contrabass`), `voices` (default: the instrument's), `quality` (`'efficient'`, the default, or `'full'`), `calibration` (a list), `glideMs` (5), `sorted` (false), `trackFrames` (false; also posts a `frame` event at every analysis step with each voice's current pitch and level, for pitch traces and score following).

Things to know:

- **Slots.** A note keeps its voice slot (and so its oscillator) for its whole duration. `fid.signals.sorted = true` orders the outputs by pitch instead.
- **Idle voices** keep their last frequency with the gate closed, so an oscillator does not sweep down when a note ends.
- **Times** are in audio-context seconds (`time` when the note was reported, `onsetTime` the estimated real start).
- **Microphone:** ask for it with echo cancellation, noise suppression and automatic gain **off** (`getUserMedia({ audio: { echoCancellation: false, noiseSuppression: false, autoGainControl: false } })`); they distort the instrument.
- **Sample rate:** create the context at 48123 (or 44100). Other rates are untested.
- **Quality:** `efficient` runs one analysis step every 10.7 ms instead of 5.3 ms, with a coarser pitch search: about 6 ms more delay, much less processor time. Calibration is learned in `full` quality only.
- **Calibration:** `fid.calibrate('start' | 'finish' | 'cancel')`; progress arrives as `calibration` events and the result as a `calibrationResult` event (also `fid.calibrationResult`). Pass it back with `fid.setCalibration(list)` or the `calibration` option.

## Files

| Path | Role |
|---|---|
| `src/fidddle.js` | the page-side library (`Fidddle`, `signals`, `events`) |
| `src/engine.js` | the audio-thread part: detector, signal glide, events (no browser dependencies, also runs in Node) |
| `src/processor.js` | the AudioWorklet processor |
| `dist/fidddle.wasm` | the detector (built by `build.sh`; not in the repository) |
| `wasm/fidddle_c_api.cpp` | the C interface of the module |
| `demo/` | demo page and speed test |
| `test/` | tests |

## Tests

```
node web/test/compare_native.mjs [--efficient] file.wav:profile ...   # same notes as the native tool
node web/test/engine_test.mjs data/synth/cello__open_strings.wav cello # engine and processor (AudioWorklet mocked)
node web/test/calibration_test.mjs data/synth/calibration__guitar.wav
node web/test/reset_test.mjs data/synth/cello__open_strings.wav cello
PUPPETEER_PATH=.../puppeteer.js node web/test/browser_test.mjs cello efficient   # the demo in headless Chrome, a real AudioWorklet
```

The browser test needs `puppeteer` (not a dependency of this repository): install it anywhere and point `PUPPETEER_PATH` at it, or install it next to the test.

## Not verified yet

- Phones and tablets (use the speed page), Firefox and Safari. The audio worklet and WebAssembly features used are standard, but only Chrome has been run.
- Web MIDI output was tested with a fake port, not with a device.
