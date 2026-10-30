// Cost per analysis step of the WebAssembly module (Node, performance.now). Usage: speed.mjs file.wav [profile] [--efficient]
import { loadModule, readWav, createDetector } from './wasm_runner.mjs';
const [file, profile = 'cello'] = process.argv.slice(2).filter(a => !a.startsWith('--'));
const efficient = process.argv.includes('--efficient');
const x = await loadModule();
const { samples, rate } = readWav(file);
const h = createDetector(x, { profile, rate, efficient });
const hop = x.fid_hop_size(h);
const times = [];
for (let i = 0; i + 128 <= samples.length; i += 128) {
  new Float64Array(x.memory.buffer, x.fid_input(h), 128).set(samples.subarray(i, i + 128));
  const t = performance.now();
  const steps = x.fid_process(h, 128);
  const dt = performance.now() - t;
  if (steps) times.push(dt);
}
times.sort((a, b) => a - b);
const mean = times.reduce((a, b) => a + b, 0) / times.length, hopMs = 1000 * hop / rate;
console.log(`${profile}${efficient ? ' efficient' : ''}: ${times.length} steps, mean ${mean.toFixed(3)} ms, p99 ${times[Math.floor(times.length * .99)].toFixed(3)} ms, max ${times[times.length - 1].toFixed(3)} ms; hop ${hopMs.toFixed(1)} ms, load ${(100 * mean / hopMs).toFixed(1)}%`);
