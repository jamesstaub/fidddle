// Loads web/dist/fidddle.wasm in Node and runs a WAV file through it in 128-sample blocks (the render quantum),
// returning the note events in the same shape as `fidddle_cli` prints them.
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

const here = dirname(fileURLToPath(import.meta.url));
export const PROFILES = ['bass', 'cello', 'viola', 'violin', 'guitar', 'contrabass'];

export function readWav(path) {
  const b = readFileSync(path);
  const dv = new DataView(b.buffer, b.byteOffset, b.byteLength);
  let fmt = null, data = null, p = 12;
  while (p + 8 <= b.length) {
    const id = b.toString('latin1', p, p + 4), size = dv.getUint32(p + 4, true);
    if (id === 'fmt ') fmt = { tag: dv.getUint16(p + 8, true), channels: dv.getUint16(p + 10, true), rate: dv.getUint32(p + 12, true), bits: dv.getUint16(p + 22, true) };
    else if (id === 'data') data = { at: p + 8, size: Math.min(size, b.length - p - 8) };
    p += 8 + size + (size & 1);
  }
  if (!fmt || !data) throw new Error('not a WAV file: ' + path);
  const bytes = fmt.bits / 8, n = Math.floor(data.size / bytes / fmt.channels);
  const out = new Float64Array(n);   // channel 0
  for (let i = 0; i < n; i++) {
    const o = data.at + i * fmt.channels * bytes;
    if (fmt.tag === 3) out[i] = fmt.bits === 32 ? dv.getFloat32(o, true) : dv.getFloat64(o, true);
    else if (fmt.bits === 16) out[i] = dv.getInt16(o, true) / 32768;
    else if (fmt.bits === 24) out[i] = ((b[o] | (b[o + 1] << 8) | (b[o + 2] << 16)) << 8 >> 8) / 8388608;
    else if (fmt.bits === 32) out[i] = dv.getInt32(o, true) / 2147483648;
    else throw new Error('unsupported WAV format');
  }
  return { samples: out, rate: fmt.rate };
}

export async function loadModule(wasmPath = join(here, '..', 'dist', 'fidddle.wasm')) {
  const { instance } = await WebAssembly.instantiate(readFileSync(wasmPath), {});
  instance.exports._initialize?.();
  return instance.exports;
}

const cstr = (x, p) => { const m = new Uint8Array(x.memory.buffer); let e = p; while (m[e]) e++; return new TextDecoder().decode(m.subarray(p, e)); };

export function createDetector(x, { profile = 'cello', rate = 48000, voices = 0, efficient = false } = {}) {
  const id = typeof profile === 'number' ? profile : PROFILES.indexOf(profile);
  const h = x.fid_create(id, rate, voices, efficient ? 1 : 0, 0, 0);
  if (!h) throw new Error('fid_create: ' + cstr(x, x.fid_last_error()));
  return h;
}

export function runEvents(x, samples, opts = {}) {
  const h = createDetector(x, opts);
  const block = opts.block ?? 128;
  const evSlots = x.fid_event_fields();
  const events = [];
  const scratch = x.fid_scratch(h);
  const drain = () => {
    while (x.fid_poll_event(h, scratch)) {
      const e = new Float64Array(x.memory.buffer, scratch, evSlots);
      events.push({ ev: e[0] ? 'on' : 'off', id: e[1], slot: e[2], midi: e[3], vel: e[5], onset: e[6], deliver: e[7], flags: e[9] });
    }
  };
  for (let i = 0; i < samples.length; i += block) {
    const n = Math.min(block, samples.length - i);
    new Float64Array(x.memory.buffer, x.fid_input(h), n).set(samples.subarray(i, i + n));
    x.fid_process(h, n);
    drain();
  }
  x.fid_flush(h);
  drain();
  x.fid_destroy(h);
  return events;
}
