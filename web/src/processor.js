// AudioWorklet processor: one detector (engine.js) behind one node.
//   input 0:  any number of channels, added together to mono
//   output 0: 3 x V mono channels = [frequency slot 0..V-1][level slot 0..V-1][gate slot 0..V-1]
//   messages (port): { type: 'events' | 'frame' | 'calibration' | 'calibrationResult' | 'ready' | 'error' }
// Load engine.js with audioWorklet.addModule first (it registers the engine for this scope), then this file.

class FidddleProcessor extends AudioWorkletProcessor {
  constructor(options) {
    super();
    const po = options.processorOptions;
    this.mix = null;
    try {
      this.engine = new globalThis.FidddleEngine(po.module, { ...po.settings, sampleRate, frame0: currentFrame });
    } catch (e) {
      this.engine = null;
      this.port.postMessage({ type: 'error', message: String(e && e.message || e) });
      return;
    }
    this.port.onmessage = (ev) => this.onMessage(ev.data);
    this.port.postMessage({ type: 'ready', channels: this.engine.channels, voices: this.engine.V, hop: this.engine.hop, sampleRate });
  }

  onMessage(m) {
    const e = this.engine;
    if (!e) return;
    try {
      switch (m.type) {
        case 'configure': e.configure(m.settings); break;                 // glideMs, sorted, trackFrames, gate times
        case 'reset': e.reset(currentFrame); break;
        case 'calibrate': e.calibrate(m.command); break;
        case 'setCalibration': e.setCalibration(m.list); break;
        case 'destroy': e.destroy(); this.engine = null; break;
      }
    } catch (err) {
      this.port.postMessage({ type: 'error', message: String(err && err.message || err) });
    }
  }

  process(inputs, outputs) {
    const e = this.engine;
    if (!e) return false;
    const out = outputs[0];
    const n = out[0].length;
    let mono = null;
    const input = inputs[0];
    if (input && input.length) {
      if (input.length === 1) mono = input[0];
      else {
        if (!this.mix || this.mix.length < n) this.mix = new Float32Array(Math.max(n, 128));
        this.mix.fill(0, 0, n);
        for (const ch of input) for (let i = 0; i < n; i++) this.mix[i] += ch[i];
        mono = this.mix;
      }
    }
    e.process(mono, out, n);
    const msgs = e.takeMessages();
    for (const m of msgs) this.port.postMessage(m);
    return true;
  }
}

registerProcessor('fidddle-processor', FidddleProcessor);
