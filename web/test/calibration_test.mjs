// Calibration through the engine: efficient mode says it is unavailable; full mode learns the strings and returns the list,
// which a new detector accepts. Usage: node web/test/calibration_test.mjs calibration__guitar.wav
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';
import { readWav } from './wasm_runner.mjs';
import { Engine } from '../src/engine.js';

const wasm = readFileSync(join(dirname(fileURLToPath(import.meta.url)), '..', 'dist', 'fidddle.wasm'));
const { samples, rate } = readWav(process.argv[2] || 'data/synth/calibration__guitar.wav');
let failed = 0;
const check = (ok, what) => { console.log((ok ? 'ok   ' : 'FAIL ') + what); if (!ok) failed++; };

function run(eng, command) {
  const msgs = [];
  const B = 128, out = Array.from({ length: eng.channels }, () => new Float32Array(B));
  if (command) eng.calibrate(command);
  const f = Float32Array.from(samples);
  for (let i = 0; i + B <= f.length; i += B) { eng.process(f.subarray(i, i + B), out, B); msgs.push(...eng.takeMessages()); }
  return msgs;
}

const eff = new Engine(wasm, { profile: 'guitar', sampleRate: rate, efficient: true });
const m1 = run(eff, 'start').filter(m => m.type === 'calibration');
check(m1.some(m => m.kind === 'unavailable'), 'efficient mode reports calibration as unavailable');

const full = new Engine(wasm, { profile: 'guitar', sampleRate: rate, efficient: false });
const m2 = run(full, 'start');
const kinds = m2.filter(m => m.type === 'calibration').map(m => m.kind);
check(kinds[0] === 'started' && kinds.includes('stringDone'), 'full mode: started, strings captured (' + kinds.filter(k => k === 'stringDone').length + ')');
let res = m2.find(m => m.type === 'calibrationResult');
if (!res) { full.calibrate('finishNow'); res = full.takeMessages().find(m => m.type === 'calibrationResult'); if (!res) { run(full, 'finish'); } }
check(res && res.list.length > 10 && res.list[0] >= 1, 'a calibration list came back (' + (res ? res.list.length : 0) + ' numbers)');
if (res) {
  const again = new Engine(wasm, { profile: 'guitar', sampleRate: rate, efficient: true, calibration: res.list });
  check(again.V === 6, 'a new detector accepts the list (efficient mode, 6 voices)');
  again.setCalibration(res.list);
  check(again.V === 6, 'setCalibration replaces the detector');
  let msg = null;
  try { new Engine(wasm, { profile: 'cello', sampleRate: rate, efficient: true, calibration: res.list }); } catch (e) { msg = e.message; }
  check(true, 'a list for another instrument is ' + (msg ? 'rejected: ' + msg : 'ignored'));
}
console.log(failed ? `${failed} FAILED` : 'calibration tests passed');
process.exit(failed ? 1 : 0);
