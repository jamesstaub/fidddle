// A detector that was reset must give the same events as a fresh one (WEBAUDIO_DESIGN.md section 8, test 4), and a
// bad configuration must be refused with a reason.
import { loadModule, readWav, createDetector, runEvents } from './wasm_runner.mjs';
const x = await loadModule();
const file = process.argv[2];
if (!file) { console.error('usage: reset_test.mjs file.wav [profile]'); process.exit(2); }
const profile = process.argv[3] || 'cello';
const { samples, rate } = readWav(file);
const key = e => `${e.ev} ${e.id} ${e.midi} ${e.deliver} ${e.flags}`;
const fresh = runEvents(x, samples, { profile, rate }).map(key);

const h = createDetector(x, { profile, rate });
const scratch = x.fid_scratch(h);
const run = () => {
  const out = [];
  const drain = () => { while (x.fid_poll_event(h, scratch)) { const e = new Float64Array(x.memory.buffer, scratch, 11); out.push(`${e[0] ? 'on' : 'off'} ${e[1]} ${e[3]} ${e[7]} ${e[9]}`); } };
  for (let i = 0; i < samples.length; i += 128) {
    const n = Math.min(128, samples.length - i);
    new Float64Array(x.memory.buffer, x.fid_input(h), n).set(samples.subarray(i, i + n));
    x.fid_process(h, n); drain();
  }
  x.fid_flush(h); drain();
  return out;
};
run();                 // dirty it with a full run, then restart
x.fid_reset(h);
const again = run();
let ok = JSON.stringify(again) === JSON.stringify(fresh);
console.log(`${ok ? 'ok  ' : 'FAIL'} reset detector reproduces a fresh one (${fresh.length} events)`);
x.fid_destroy(h);

const bad = x.fid_create(1, 4000, 0, 0, 0, 0);
const msg = (() => { const m = new Uint8Array(x.memory.buffer); let p = x.fid_last_error(), e = p; while (m[e]) e++; return new TextDecoder().decode(m.subarray(p, e)); })();
const refused = bad === 0 && msg.length > 0;
console.log(`${refused ? 'ok  ' : 'FAIL'} sample rate 4000 refused (${msg})`);
process.exit(ok && refused ? 0 : 1);
