// Tests of the audio-thread engine (web/src/engine.js) and the worklet processor (web/src/processor.js) in Node, with the
// browser's AudioWorklet globals mocked. Usage: node web/test/engine_test.mjs file.wav [profile]
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';
import { loadModule, readWav, runEvents } from './wasm_runner.mjs';
import { Engine } from '../src/engine.js';

const here = dirname(fileURLToPath(import.meta.url));
const wasmBytes = readFileSync(join(here, '..', 'dist', 'fidddle.wasm'));
const [file = 'data/synth/cello__open_strings.wav', profile = 'cello'] = process.argv.slice(2);
const { samples, rate } = readWav(file);
let failed = 0;
const check = (ok, what) => { console.log((ok ? 'ok   ' : 'FAIL ') + what); if (!ok) failed++; };

// ---- 1. the engine reports the same notes as the plain module
const x = await loadModule();
const want = runEvents(x, samples, { profile, rate, efficient: true });
const eng = new Engine(wasmBytes, { profile, sampleRate: rate, efficient: true });
const V = eng.V, N = samples.length, B = 128;
const out = Array.from({ length: eng.channels }, () => new Float32Array(N));
const events = [];
const frames = [];
eng.configure({ trackFrames: true });
const blk = Array.from({ length: eng.channels }, () => new Float32Array(B));
const f32 = Float32Array.from(samples);
for (let i = 0; i + B <= N; i += B) {
  eng.process(f32.subarray(i, i + B), blk, B);
  for (let c = 0; c < blk.length; c++) out[c].set(blk[c], i);
  for (const m of eng.takeMessages()) { if (m.type === 'events') events.push(...m.events); else if (m.type === 'frame') frames.push(m); }
}
const got = events.filter(e => true);
const wantOn = want.filter(e => e.ev === 'on').map(e => e.midi + '@' + e.slot);
const gotOn = got.filter(e => e.type === 'noteon').map(e => e.note + '@' + e.slot);
check(wantOn.length > 0 && wantOn.join() === gotOn.join(), `note-ons match the module (${gotOn.length})`);
check(got.filter(e => e.type === 'noteoff').length === want.filter(e => e.ev === 'off').length, 'note-offs match');
check(frames.length > 0 && frames[0].voices !== undefined, `frame messages (${frames.length})`);
// event times are context seconds: sample / rate
const w0 = want.find(e => e.ev === 'on'), g0 = got.find(e => e.type === 'noteon');
check(Math.abs(g0.time - w0.deliver / rate) < 1e-9 && Math.abs(g0.onsetTime - w0.onset / rate) < 1e-9, 'event times are sample / rate');
check(g0.midiFloat > 0 && g0.confidence >= 0 && g0.velocity >= 1, 'event fields filled');

// ---- 2. the signals follow the notes
const hz = m => 440 * Math.pow(2, (m - 69) / 12);
const gate = out[2 * V + g0.slot], freq = out[g0.slot], lev = out[V + g0.slot];
const iOn = Math.round(g0.time * rate);
let firstGate = -1;
for (let i = 0; i < N; i++) if (gate[i] > 0.01) { firstGate = i; break; }
check(firstGate >= 0 && Math.abs(firstGate - iOn) < 2 * B, `gate opens at the note-on (sample ${firstGate} vs ${iOn})`);
check(Math.abs(1200 * Math.log2(freq[firstGate] / hz(g0.midiFloat))) < 100, 'frequency is at the note when the gate opens (no sweep)');
check(lev[firstGate + 4 * B] > 0 && lev[firstGate + 4 * B] < 2, 'level is a linear amplitude');
const off0 = got.find(e => e.type === 'noteoff' && e.slot === g0.slot && e.time > g0.time);
if (off0) {
  const iOff = Math.round(off0.time * rate);
  let closed = -1;
  for (let i = iOff; i < Math.min(N, iOff + rate / 2); i++) if (gate[i] < 0.001) { closed = i; break; }
  check(closed >= 0 && closed - iOff < rate * 0.05, 'gate closes after the note-off');
  const held = freq[Math.min(N - 1, closed + 4 * B)];
  check(held > 20, `frequency is held after the note ends (${held.toFixed(1)} Hz), not swept to 0`);
}
// glide: a step in the target moves the output with the time constant of glideMs
let maxStep = 0;
for (let i = 1; i < N; i++) if (gate[i] > 0.02 && gate[i - 1] > 0.02) maxStep = Math.max(maxStep, Math.abs(freq[i] - freq[i - 1]));
check(maxStep < 5, `no audible frequency jump while a gate is open (largest single-sample step ${maxStep.toFixed(3)} Hz)`);
check(Array.from(gate).every(v => v >= 0 && v <= 1), 'gate stays within 0..1');

// ---- 3. stable slots, and sorted output
const noSorted = [...new Set(got.filter(e => e.type === 'noteon').map(e => e.slot))];
check(noSorted.every(s => s >= 0 && s < V), 'slots are within range');

// ---- 4. any block size
const eng2 = new Engine(wasmBytes, { profile, sampleRate: rate, efficient: true });
let n2 = 0;
const odd = Array.from({ length: eng2.channels }, () => new Float32Array(1000));
for (let i = 0; i + 333 <= N; i += 333) { eng2.process(f32.subarray(i, i + 333), odd, 333); for (const m of eng2.takeMessages()) if (m.type === 'events') n2 += m.events.filter(e => e.type === 'noteon').length; }
check(n2 === gotOn.length, `block size 333 gives the same note-ons (${n2})`);

// ---- 5. reset equals fresh
eng.reset(0);
let n3 = 0;
for (let i = 0; i + B <= N; i += B) { eng.process(f32.subarray(i, i + B), blk, B); for (const m of eng.takeMessages()) if (m.type === 'events') n3 += m.events.filter(e => e.type === 'noteon').length; }
check(n3 === gotOn.length, `after reset the same note-ons (${n3})`);

// ---- 6. sorted outputs: output 0 is the lowest sounding voice
const eng3 = new Engine(wasmBytes, { profile, sampleRate: rate, efficient: true, sorted: true });
const sortedOut = Array.from({ length: eng3.channels }, () => new Float32Array(B));
let sortedOk = true, seen = 0;
for (let i = 0; i + B <= N; i += B) {
  eng3.process(f32.subarray(i, i + B), sortedOut, B);
  eng3.takeMessages();
  const gs = []; for (let v = 0; v < V; v++) gs.push(sortedOut[2 * V + v][B - 1] > 0.5 ? sortedOut[v][B - 1] : 0);
  const up = gs.filter(f => f > 0);
  if (up.length > 1) { seen++; for (let k = 1; k < up.length; k++) if (up[k] < up[k - 1]) sortedOk = false; }
}
check(sortedOk, `sorted mode: frequencies rise with output index (${seen} multi-voice blocks)`);

// ---- 7. the worklet processor, with the AudioWorklet globals mocked
let registered = null;
globalThis.AudioWorkletProcessor = class { constructor() { this.port = { posted: [], postMessage(m) { this.posted.push(m); }, onmessage: null }; } };
globalThis.registerProcessor = (name, cls) => { registered = { name, cls }; };
globalThis.sampleRate = rate;
globalThis.currentFrame = 0;
await import('../src/processor.js');
check(registered && registered.name === 'fidddle-processor', 'processor registered');
const mod = new WebAssembly.Module(wasmBytes);
const proc = new registered.cls({ processorOptions: { module: mod, settings: { profile, voices: 0, efficient: true, calibration: null, glideMs: 5, sorted: false, trackFrames: false } } });
const ready = proc.port.posted.find(m => m.type === 'ready');
check(ready && ready.channels === 3 * V && ready.hop === 512, `ready message: ${ready && ready.channels} channels, hop ${ready && ready.hop}`);
const outs = [Array.from({ length: 3 * V }, () => new Float32Array(B))];
let onsFromProc = 0;
for (let i = 0; i + B <= N; i += B) {
  globalThis.currentFrame = i;
  proc.process([[f32.subarray(i, i + B)]], outs);
  for (const m of proc.port.posted.splice(0)) if (m.type === 'events') onsFromProc += m.events.filter(e => e.type === 'noteon').length;
}
check(onsFromProc === gotOn.length, `processor posts the same note-ons (${onsFromProc})`);
proc.onMessage({ type: 'configure', settings: { sorted: true, glideMs: 20 } });
check(proc.engine.o.sorted === true && proc.engine.o.glideMs === 20, 'configure message applied');
proc.process([[]], outs);   // no input connected: silence, must not throw
proc.onMessage({ type: 'destroy' });
check(proc.process([[f32.subarray(0, B)]], outs) === false, 'destroyed processor stops');

// ---- 8. bad settings are reported, not crashed
let msg = null;
try { new Engine(wasmBytes, { profile, sampleRate: 100, efficient: true }); } catch (e) { msg = e.message; }
check(msg && msg.includes('sample_rate'), 'unusable settings throw with the reason: ' + msg);

console.log(failed ? `${failed} FAILED` : 'all engine tests passed');
process.exit(failed ? 1 : 0);
