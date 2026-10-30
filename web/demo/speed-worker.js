// Times the detector on this device in a web worker (performance.now is available here, unlike in the audio worklet).
import { Engine } from '../src/engine.js';
import { renderMelody } from './testsignal.js';

self.onmessage = async (ev) => {
  const { profiles, rate, seconds } = ev.data;
  try {
    const bytes = await (await fetch(new URL('../dist/fidddle.wasm', import.meta.url))).arrayBuffer();
    const module = await WebAssembly.compile(bytes);
    for (const profile of profiles) {
      const audio = renderMelody(rate, profile, seconds);
      for (const quality of ['efficient', 'full']) {
        const eng = new Engine(module, { profile, sampleRate: rate, efficient: quality === 'efficient' });
        const out = Array.from({ length: eng.channels }, () => new Float32Array(128));
        const times = [];
        for (let i = 0; i + 128 <= audio.length; i += 128) {
          const t = performance.now();
          eng.process(audio.subarray(i, i + 128), out, 128);
          const dt = performance.now() - t;
          eng.takeMessages();
          if ((i / 128 + 1) % (eng.hop / 128) === 0 && i >= 128 * (eng.hop / 128) * 20) times.push(dt);   // the blocks that complete an analysis step
        }
        times.sort((a, b) => a - b);
        const mean = times.reduce((a, b) => a + b, 0) / times.length;
        const hopMs = 1000 * eng.hop / rate;
        self.postMessage({ profile, quality, steps: times.length, mean, p99: times[Math.floor(times.length * 0.99)], max: times[times.length - 1], hopMs, load: mean / hopMs, quantumMs: 128000 / rate });
        eng.destroy();
        await new Promise((r) => setTimeout(r, 0));
      }
    }
    self.postMessage({ done: true });
  } catch (e) {
    self.postMessage({ error: String(e && e.message || e) });
  }
};
