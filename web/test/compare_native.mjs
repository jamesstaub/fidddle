// Runs WAV files through the WebAssembly module and through the native fidddle_cli (same profile, string
// identification off) and requires identical note events. Usage: node web/test/compare_native.mjs [--efficient] file.wav[:profile] ...
import { execFileSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';
import { loadModule, readWav, runEvents } from './wasm_runner.mjs';

const root = join(dirname(fileURLToPath(import.meta.url)), '..', '..');
const cli = process.env.FIDDDLE_CLI || join(root, 'core', 'build', 'fidddle_cli');
const args = process.argv.slice(2);
const efficient = args.includes('--efficient');
const files = args.filter(a => !a.startsWith('--'));
if (!files.length) { console.error('no files'); process.exit(2); }

const x = await loadModule();
let total = 0, bad = 0;
for (const spec of files) {
  const [file, profile = 'cello'] = spec.split(':');
  const wav = readWav(file);
  const got = runEvents(x, wav.samples, { profile, rate: wav.rate, efficient });
  const out = execFileSync(cli, [file, '--profile', profile, '--set', 'string_id=0', ...(efficient ? ['--efficient'] : [])], { encoding: 'utf8', maxBuffer: 1 << 26 });
  const want = out.split('\n').filter(l => l.startsWith('{"ev"')).map(l => JSON.parse(l));
  const key = e => `${e.ev} ${e.id} ${e.midi} ${e.deliver} ${e.flags}`;
  const a = got.map(key), b = want.map(key);
  let miss = 0;
  for (let i = 0; i < Math.max(a.length, b.length); i++) if (a[i] !== b[i]) { if (miss++ < 3) console.log(`  differs at ${i}: wasm [${a[i]}] native [${b[i]}]`); }
  total += b.length; bad += miss;
  console.log(`${miss ? 'FAIL' : 'ok  '} ${file} (${profile}${efficient ? ', efficient' : ''}): ${b.length - Math.min(miss, b.length)} of ${b.length} events match${a.length !== b.length ? `, wasm has ${a.length}` : ''}`);
}
console.log(`${total - bad} of ${total} events match`);
process.exit(bad ? 1 : 0);
