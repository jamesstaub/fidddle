// fidddle for the web: pitch detection for string instruments in an AudioWorklet (WEBAUDIO_DESIGN.md section 2.4).
//
//   const fid = await Fidddle.create(audioContext, { profile: 'cello' });
//   micSource.connect(fid.node);                                  // audio in
//   fid.signals.connectFrequency(0, osc.frequency);               // voice 0 pitch  -> an oscillator
//   fid.signals.connectGate(0, amp.gain);                         // voice 0 on/off -> an amplifier
//   fid.events.addEventListener('noteon', e => console.log(e.detail));
//   fid.events.connectMidi(midiOutput);                           // note events -> a MIDI device
//
// One detector runs once per analysis step; the signals and the events are two views of that single run.

const PROFILE_NAMES = ['bass', 'cello', 'viola', 'violin', 'guitar', 'contrabass'];
const DEFAULT_VOICES = { bass: 4, cello: 4, viola: 4, violin: 4, guitar: 6, contrabass: 4 };
const here = new URL('.', import.meta.url);
const loaded = new WeakSet();   // audio contexts whose worklet scope already has the processor

const midiToHz = (m) => 440 * Math.pow(2, (m - 69) / 12);

export class FidddleSignals {
  constructor(owner, splitter, voices) {
    this._o = owner; this._split = splitter; this.slots = voices;
    this._links = new Set();
  }
  // Which splitter output carries a signal: [frequency 0..V-1][level 0..V-1][gate 0..V-1]
  _channel(kind, slot) {
    const k = { frequency: 0, level: 1, gate: 2 }[kind];
    if (k === undefined) throw new Error('unknown signal ' + kind);
    if (!(slot >= 0 && slot < this.slots)) throw new RangeError(`slot must be 0..${this.slots - 1}`);
    return k * this.slots + slot;
  }
  // Connects a signal to an AudioParam (its own value is set to 0 so that the signal is the value) or to an AudioNode input.
  // options: scale (multiply the signal), keepValue (leave the parameter's own value alone). Returns a function that disconnects.
  connect(kind, slot, destination, { scale = 1, keepValue = false } = {}) {
    const ch = this._channel(kind, slot), ctx = this._o.context;
    const isParam = typeof AudioParam !== 'undefined' && destination instanceof AudioParam;
    if (isParam && !keepValue) destination.value = 0;
    let source = this._split, outIndex = ch, gain = null;
    if (scale !== 1) {
      gain = new GainNode(ctx, { gain: scale });
      this._split.connect(gain, ch);
      source = gain; outIndex = 0;
    }
    if (isParam) source.connect(destination, outIndex); else source.connect(destination, outIndex, 0);
    const link = () => {
      try { source.disconnect(destination, outIndex); } catch {}
      if (gain) { try { this._split.disconnect(gain, ch); } catch {} }
      this._links.delete(link);
    };
    this._links.add(link);
    return link;
  }
  connectFrequency(slot, destination, options) { return this.connect('frequency', slot, destination, options); }
  connectLevel(slot, destination, options) { return this.connect('level', slot, destination, options); }
  connectGate(slot, destination, options) { return this.connect('gate', slot, destination, options); }

  // Order the outputs by pitch (output 0 = lowest sounding voice) instead of keeping a note on its slot.
  get sorted() { return this._o._settings.sorted; }
  set sorted(v) { this._o._configure({ sorted: !!v }); }
  // Pitch and level glide between analysis steps, in milliseconds.
  get glideMs() { return this._o._settings.glideMs; }
  set glideMs(v) { this._o._configure({ glideMs: +v }); }
  _disconnectAll() { for (const l of [...this._links]) l(); }
}

export class FidddleEvents extends EventTarget {
  constructor() {
    super();
    this._active = new Map();      // slot -> note
    this._queue = []; this._waiters = [];
    this._midi = new Set();
  }
  // Sounding notes right now, sorted by pitch: { note, midiFloat, frequency, velocity, slot, since, confidence }
  get activeNotes() { return [...this._active.values()].sort((a, b) => a.midiFloat - b.midiFloat); }

  _emit(type, detail) {
    this.dispatchEvent(new CustomEvent(type, { detail }));
    this._push({ type, ...detail });
  }
  _push(item) {
    const w = this._waiters.shift();
    if (w) w({ value: item, done: false }); else if (this._queue.length < 10000) this._queue.push(item);
  }
  // for await (const e of fid.events.stream()) { ... }   events: noteon, noteoff (and frame when trackFrames is on)
  stream() {
    const self = this;
    return {
      [Symbol.asyncIterator]() { return this; },
      next() { return self._queue.length ? Promise.resolve({ value: self._queue.shift(), done: false }) : new Promise((r) => self._waiters.push(r)); },
    };
  }

  _handle(m) {
    switch (m.type) {
      case 'events':
        for (const e of m.events) {
          const d = { note: e.note, midiFloat: e.midiFloat, frequency: midiToHz(e.midiFloat), velocity: e.velocity, slot: e.slot,
                      confidence: e.confidence, time: e.time, onsetTime: e.onsetTime, retrigger: !!(e.flags & 1), flags: e.flags, id: e.id };
          if (e.type === 'noteon') this._active.set(e.slot, { note: d.note, midiFloat: d.midiFloat, frequency: d.frequency, velocity: d.velocity, slot: d.slot, since: d.time, confidence: d.confidence });
          else this._active.delete(e.slot);
          this._emit(e.type, d);
        }
        break;
      case 'frame':
        for (const v of m.voices) {
          const a = this._active.get(v.slot);
          if (a && (v.state === 2 || v.state === 3)) { a.midiFloat = v.midi; a.frequency = v.frequency; a.confidence = v.confidence; }
        }
        this._emit('frame', { time: m.time, voices: m.voices });
        break;
      case 'calibration': this._emit('calibration', m); break;
      case 'calibrationResult': this._emit('calibrationResult', { list: m.list }); break;
    }
  }

  // Sends note events to a Web MIDI output (a MIDIOutput from navigator.requestMIDIAccess()). Returns a function that stops
  // sending and switches off the notes that are still sounding.
  connectMidi(output, { channel = 0, velocityScale = 1 } = {}) {
    const ch = channel & 15, sounding = new Set();
    const on = (e) => {
      const d = e.detail, v = Math.max(1, Math.min(127, Math.round(d.velocity * velocityScale)));
      output.send([0x90 | ch, d.note, v]); sounding.add(d.note);
    };
    const off = (e) => { output.send([0x80 | ch, e.detail.note, 0]); sounding.delete(e.detail.note); };
    this.addEventListener('noteon', on); this.addEventListener('noteoff', off);
    const stop = () => {
      this.removeEventListener('noteon', on); this.removeEventListener('noteoff', off);
      for (const n of sounding) output.send([0x80 | ch, n, 0]);
      sounding.clear(); this._midi.delete(stop);
    };
    this._midi.add(stop);
    return stop;
  }
  _stopAll() { for (const s of [...this._midi]) s(); }
}

export class Fidddle {
  // options: profile ('cello'...), voices (0 = the profile's default), quality ('efficient' | 'full'; default efficient),
  // calibration (list), glideMs (5), sorted, trackFrames, wasmUrl
  static async create(context, options = {}) {
    const o = { profile: 'cello', voices: 0, quality: 'efficient', calibration: null, glideMs: 5, sorted: false, trackFrames: false, ...options };
    if (!PROFILE_NAMES.includes(o.profile)) throw new Error('unknown profile ' + o.profile);
    if (!context.audioWorklet) throw new Error('This browser has no AudioWorklet (or the page is not served over HTTPS or from localhost).');
    const voices = o.voices > 0 ? o.voices : DEFAULT_VOICES[o.profile];
    const wasmUrl = o.wasmUrl ? new URL(o.wasmUrl, location.href) : new URL('../dist/fidddle.wasm', here);
    const resp = await fetch(wasmUrl);
    if (!resp.ok) throw new Error(`could not load ${wasmUrl}: ${resp.status}`);
    const bytes = await resp.arrayBuffer();
    const module = await WebAssembly.compile(bytes);
    if (!loaded.has(context)) {
      await context.audioWorklet.addModule(new URL('engine.js', here));
      await context.audioWorklet.addModule(new URL('processor.js', here));
      loaded.add(context);
    }
    const settings = { profile: o.profile, voices, efficient: o.quality !== 'full', calibration: o.calibration, glideMs: o.glideMs, sorted: o.sorted, trackFrames: o.trackFrames };
    const node = new AudioWorkletNode(context, 'fidddle-processor', {
      numberOfInputs: 1, numberOfOutputs: 1, outputChannelCount: [3 * voices],
      channelCount: 1, channelCountMode: 'explicit', channelInterpretation: 'speakers',
      processorOptions: { module, settings },
    });
    const fid = new Fidddle(context, node, voices, settings);
    await fid._ready;
    return fid;
  }

  constructor(context, node, voices, settings) {
    this.context = context; this.node = node; this.voices = voices; this._settings = settings;
    this.events = new FidddleEvents();
    this._split = new ChannelSplitterNode(context, { numberOfOutputs: 3 * voices });
    this.signals = new FidddleSignals(this, this._split, voices);
    node.connect(this._split);
    // A node that reaches no output is not run by the browser: keep it running with a muted path to the destination,
    // so a page that uses only the note events still gets them.
    this._keep = new GainNode(context, { gain: 0 });
    node.connect(this._keep).connect(context.destination);
    this.calibrationResult = null;
    this.info = null;
    this._ready = new Promise((resolve, reject) => {
      node.port.onmessage = (ev) => {
        const m = ev.data;
        if (m.type === 'ready') { this.info = m; node.port.onmessage = (e2) => this._message(e2.data); resolve(); }
        else if (m.type === 'error') reject(new Error(m.message));
      };
    });
    node.onprocessorerror = (e) => this.events.dispatchEvent(new CustomEvent('error', { detail: { message: 'processor error' } }));
  }

  _message(m) {
    if (m.type === 'error') this.events.dispatchEvent(new CustomEvent('error', { detail: { message: m.message } }));
    else {
      if (m.type === 'calibrationResult') this.calibrationResult = m.list;
      this.events._handle(m);
    }
  }
  _configure(patch) { Object.assign(this._settings, patch); this.node.port.postMessage({ type: 'configure', settings: patch }); }

  // Connect an audio source (microphone, element, oscillator ...): fid.connectInput(source)
  connectInput(source) { source.connect(this.node); return this; }

  // Forget everything (as after creation), for example after the microphone was stopped and started again.
  reset() { this.events._active.clear(); this.node.port.postMessage({ type: 'reset' }); }

  // Calibration is learned in full quality only (the Unavailable message says so otherwise): fid.calibrate('start' | 'finish' | 'cancel')
  calibrate(command) { this.node.port.postMessage({ type: 'calibrate', command }); }
  // A calibration list from an earlier run (or from the Bela web app). Replaces the detector inside the worklet.
  setCalibration(list) { this.node.port.postMessage({ type: 'setCalibration', list }); }

  destroy() {
    this.events._stopAll();
    this.signals._disconnectAll();
    this.node.port.postMessage({ type: 'destroy' });
    try { this.node.disconnect(); this._split.disconnect(); this._keep.disconnect(); } catch {}
    this.node.port.close();
  }
}
