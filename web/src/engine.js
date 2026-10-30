// The audio-thread part of the web version, with no browser dependencies, so it runs in an AudioWorklet and in Node
// (web/test/engine_test.mjs). It owns one detector (the WebAssembly module, section 3 of WEBAUDIO_DESIGN.md), feeds it
// audio, and turns what the detector reports into
//   1. audio-rate signals: for each voice slot a frequency (Hz), a level (linear) and a gate (0..1), glided between analysis steps, and
//   2. plain-object messages: note events, per-step voice frames (optional) and calibration progress.
// One detector, one analysis; both kinds of result come from the same run.

export const PROFILES = ['bass', 'cello', 'viola', 'violin', 'guitar', 'contrabass'];
const VOICE_FIELDS = 6;   // frequency, level, state, confidence, rank, note (fid_voices)
const ACTIVE = 2, RELEASING = 3;

export class Engine {
  // module: a WebAssembly.Module or its bytes. options: see DEFAULTS.
  constructor(wasm, options = {}) {
    this.o = { ...Engine.DEFAULTS, ...options };
    const mod = wasm instanceof WebAssembly.Module ? wasm : new WebAssembly.Module(wasm);
    this.x = new WebAssembly.Instance(mod, {}).exports;
    this.x._initialize?.();
    this.sampleRate = this.o.sampleRate;
    this.messages = [];          // filled by process(); the caller drains it with takeMessages()
    this.frame0 = this.o.frame0; // context frame at which the first sample arrived (event times are in context seconds)
    this._make(this.o.calibration);
  }

  static get DEFAULTS() {
    return {
      sampleRate: 48000, profile: 'cello', voices: 0, efficient: true, calibration: null,
      glideMs: 5,              // pitch and level glide between analysis steps
      gateAttackMs: 2, gateReleaseMs: 10,
      sorted: false,           // outputs ordered by pitch (rank) instead of stable slots
      trackFrames: false,      // also post a 'frame' message at every analysis step
      frame0: 0,
    };
  }

  _cstr(p) { const m = new Uint8Array(this.x.memory.buffer); let e = p; while (m[e]) e++; return new TextDecoder().decode(m.subarray(p, e)); }

  _make(calibration) {
    const x = this.x, o = this.o;
    const id = typeof o.profile === 'number' ? o.profile : PROFILES.indexOf(o.profile);
    // fid_create reads a calibration from module memory and the module exports no allocator, so a detector is first created
    // without it; its scratch area then holds the list for the creation of the real one.
    let h = x.fid_create(id, this.sampleRate, o.voices, o.efficient ? 1 : 0, 0, 0);
    if (!h) throw new Error('fid_create: ' + this._cstr(x.fid_last_error()));
    if (calibration && calibration.length) {
      const scratch = x.fid_scratch(h);
      if (calibration.length > x.fid_calibration_capacity()) { x.fid_destroy(h); throw new Error('calibration list too long'); }
      new Float64Array(x.memory.buffer, scratch, calibration.length).set(calibration);
      const h2 = x.fid_create(id, this.sampleRate, o.voices, o.efficient ? 1 : 0, scratch, calibration.length);
      x.fid_destroy(h);
      if (!h2) throw new Error('fid_create: ' + this._cstr(x.fid_last_error()));
      h = h2;
    }
    if (this.h) x.fid_destroy(this.h);
    this.h = h;
    this.V = x.fid_voice_count(h);
    this.hop = x.fid_hop_size(h);
    this.scratch = x.fid_scratch(h);
    this.evFields = x.fid_event_fields();
    this.cbFields = x.fid_calib_fields();
    this.outChannels = 3 * this.V;
    // per output index: current and target values for frequency, level, gate
    const V = this.V;
    this.freq = new Float64Array(V); this.freqT = new Float64Array(V);
    this.lev = new Float64Array(V); this.levT = new Float64Array(V);
    this.gate = new Float64Array(V); this.gateT = new Float64Array(V);
    this.slotState = new Int8Array(V);
    this.notes = new Array(V).fill(null);
    this.total = 0;
  }

  get channels() { return this.outChannels; }

  // A new calibration needs a new detector (the detector takes it at construction, as in the Max object).
  setCalibration(list) { this.o.calibration = list; this._make(list); }

  reset(frame0) {
    this.x.fid_reset(this.h);
    this.total = 0;
    if (frame0 !== undefined) this.frame0 = frame0;
    this.freq.fill(0); this.freqT.fill(0); this.lev.fill(0); this.levT.fill(0); this.gate.fill(0); this.gateT.fill(0);
    this.slotState.fill(0);
    this.notes.fill(null);
  }

  configure(patch) { Object.assign(this.o, patch); }
  calibrate(command) { this.x.fid_calibrate(this.h, { start: 0, finish: 1, cancel: 2, finishNow: 3 }[command]); }
  destroy() { if (this.h) { this.x.fid_destroy(this.h); this.h = 0; } }

  takeMessages() { const m = this.messages; this.messages = []; return m; }

  // input: Float32Array|Float64Array of n mono samples (or null for silence); out: array of 3V Float32Array(n), laid out as
  // [frequency slot 0..V-1][level slot 0..V-1][gate slot 0..V-1]. Any block size works.
  process(input, out, n) {
    const x = this.x, max = x.fid_max_block();
    for (let at = 0; at < n; at += max) {
      const m = Math.min(max, n - at);
      const buf = new Float64Array(x.memory.buffer, x.fid_input(this.h), m);
      if (input) for (let i = 0; i < m; i++) buf[i] = input[at + i]; else buf.fill(0);
      const steps = x.fid_process(this.h, m);
      this.total += m;
      if (steps) this._step(steps);
      this._render(out, at, m);
      this._events();
    }
  }

  // One or more analysis steps finished: new targets for the signals.
  _step(steps) {
    const x = this.x, V = this.V;
    const v = new Float32Array(x.memory.buffer, x.fid_voices(this.h), V * VOICE_FIELDS);
    const sorted = this.o.sorted;
    const frame = this.o.trackFrames ? [] : null;
    this.gateT.fill(0);
    for (let s = 0; s < V; s++) {
      const b = s * VOICE_FIELDS, state = v[b + 2];
      if (frame && state > 0) frame.push({ slot: s, state, frequency: v[b], level: v[b + 1], confidence: v[b + 3], rank: v[b + 4], midi: v[b + 5] });
      if (state !== ACTIVE && state !== RELEASING) continue;
      const o = sorted ? Math.min(Math.max(v[b + 4] | 0, 0), V - 1) : s;
      if (sorted && v[b + 4] < 0) continue;
      this.gateT[o] = 1;
      this.freqT[o] = v[b];
      this.levT[o] = v[b + 1];
    }
    // a gate that opens takes its pitch at once (no sweep from the previous note)
    for (let o = 0; o < V; o++) {
      if (this.gateT[o] && this.gate[o] <= 0.001) { this.freq[o] = this.freqT[o]; this.lev[o] = this.levT[o]; }
      if (!this.gateT[o]) this.levT[o] = 0;      // a closed gate lets the level fall to 0; the frequency is held
    }
    if (frame) this.messages.push({ type: 'frame', time: this._time(this.total), voices: frame });
  }

  _render(out, at, m) {
    const V = this.V, sr = this.sampleRate;
    const g = 1 - Math.exp(-1 / Math.max(this.o.glideMs * 1e-3 * sr, 1e-6));
    const up = 1 / Math.max(this.o.gateAttackMs * 1e-3 * sr, 1), down = 1 / Math.max(this.o.gateReleaseMs * 1e-3 * sr, 1);
    for (let o = 0; o < V; o++) {
      const F = out[o], L = out[V + o], G = out[2 * V + o];
      let f = this.freq[o], l = this.lev[o], ga = this.gate[o];
      const ft = this.freqT[o], lt = this.levT[o], gt = this.gateT[o];
      for (let i = 0; i < m; i++) {
        f += g * (ft - f);
        l += g * (lt - l);
        ga = gt > ga ? Math.min(gt, ga + up) : Math.max(gt, ga - down);
        F[at + i] = f; L[at + i] = l; G[at + i] = ga;
      }
      this.freq[o] = f; this.lev[o] = l; this.gate[o] = ga;
    }
  }

  _time(sample) { return (this.frame0 + sample) / this.sampleRate; }

  _events() {
    const x = this.x, sc = this.scratch;
    const e = new Float64Array(x.memory.buffer, sc, this.evFields);
    let batch = null;
    while (x.fid_poll_event(this.h, sc)) {
      (batch || (batch = [])).push({
        type: e[0] ? 'noteon' : 'noteoff', id: e[1], slot: e[2], note: e[3], midiFloat: e[4], velocity: e[5],
        onsetTime: this._time(e[6]), time: this._time(e[7]), confidence: e[8], flags: e[9],
      });
    }
    if (batch) this.messages.push({ type: 'events', events: batch });
    const c = new Float64Array(x.memory.buffer, sc, this.cbFields);
    const kinds = ['started', 'progress', 'stringDone', 'complete', 'finished', 'cancelled', 'unavailable'];
    while (x.fid_poll_calib_event(this.h, sc)) {
      const kind = kinds[c[0]] || 'unknown';
      this.messages.push({ type: 'calibration', kind, string: c[1], frames: c[2], needed: c[3], f0: c[4], cents: c[5], B: c[6], captured: c[7], total: c[8] });
      if (kind === 'finished') {
        const n = x.fid_take_calibration(this.h, sc);
        if (n) this.messages.push({ type: 'calibrationResult', list: Array.from(new Float64Array(x.memory.buffer, sc, n)) });
      }
    }
  }
}

globalThis.FidddleEngine = Engine;   // for processor.js, loaded as a second module in the same worklet scope
