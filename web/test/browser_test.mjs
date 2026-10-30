// Runs the demo page in headless Chrome and checks the whole chain in a real AudioWorklet: the detector starts, finds the
// notes of the built-in melody, the pitch signals drive an oscillator at the right pitch, and the events reach a (fake) MIDI port.
// Needs puppeteer, which is not a dependency of the repository:  npm i puppeteer  somewhere, then
//   PUPPETEER_PATH=/path/to/node_modules/puppeteer/lib/esm/puppeteer/puppeteer.js node web/test/browser_test.mjs [profile]
import http from 'node:http';
import { readFileSync, existsSync, statSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join, extname } from 'node:path';

const root = process.env.WEB_ROOT || join(dirname(fileURLToPath(import.meta.url)), '..');
const types = { '.html': 'text/html', '.js': 'text/javascript', '.mjs': 'text/javascript', '.css': 'text/css', '.wasm': 'application/wasm' };
const server = http.createServer((req, res) => {
  const p = join(root, decodeURIComponent(req.url.split('?')[0]));
  if (!p.startsWith(root) || !existsSync(p) || statSync(p).isDirectory()) { res.writeHead(404); res.end('not found'); return; }
  res.writeHead(200, { 'content-type': types[extname(p)] || 'application/octet-stream' });
  res.end(readFileSync(p));
});
await new Promise((r) => server.listen(0, '127.0.0.1', r));
const base = `http://127.0.0.1:${server.address().port}`;
const profile = process.argv[2] || 'cello';
const quality = process.argv[3] || 'efficient';

const puppeteer = (await import(process.env.PUPPETEER_PATH || 'puppeteer')).default;
const browser = await puppeteer.launch({ headless: 'new', args: ['--autoplay-policy=no-user-gesture-required', '--no-sandbox'] });
let failed = 0;
const check = (ok, what) => { console.log((ok ? 'ok   ' : 'FAIL ') + what); if (!ok) failed++; };
try {
  const page = await browser.newPage();
  const errors = [];
  page.on('console', (m) => { if (m.type() === 'error') errors.push(m.text()); });
  page.on('pageerror', (e) => errors.push(String(e)));
  await page.goto(`${base}/demo/index.html`);
  await page.select('#profile', profile);
  await page.select('#quality', quality);
  await page.click('#start');
  await page.waitForFunction(() => /^Running|error|Error/i.test(document.getElementById('status').textContent), { timeout: 20000 });
  const status = await page.$eval('#status', (e) => e.textContent);
  check(status.startsWith('Running'), 'detector started: ' + status);

  // attach an analyser to the page's output, silence the event synth so only the signal-driven oscillators are heard,
  // and record what a fake MIDI port receives
  await page.evaluate(() => {
    const d = window.__demo;
    document.getElementById('synthOn').checked = false;
    d.an = new AnalyserNode(d.ctx, { fftSize: 8192 });
    d.master.connect(d.an);
    d.midi = [];
    d.stop = d.fid.events.connectMidi({ send: (m) => d.midi.push(Array.from(m)) }, { channel: 2 });
    d.samples = [];
    d.timer = setInterval(() => {
      const a = d.an, buf = new Float32Array(a.fftSize), spec = new Float32Array(a.frequencyBinCount);
      a.getFloatTimeDomainData(buf); a.getFloatFrequencyData(spec);
      let e = 0; for (const v of buf) e += v * v;
      let k = 0; for (let i = 1; i < spec.length; i++) if (spec[i] > spec[k]) k = i;
      const act = d.fid.events.activeNotes;
      d.samples.push({ rms: Math.sqrt(e / buf.length), peak: k * d.ctx.sampleRate / a.fftSize, db: spec[k], notes: act.map((n) => n.frequency) });
    }, 100);
  });
  await new Promise((r) => setTimeout(r, 14000));
  const r = await page.evaluate(() => {
    const d = window.__demo;
    clearInterval(d.timer);
    return { midi: d.midi, samples: d.samples, delays: d.delays, rows: document.getElementById('log').children.length, sorted: d.fid.events.activeNotes.length };
  });

  const ons = r.midi.filter((m) => (m[0] & 0xf0) === 0x90), offs = r.midi.filter((m) => (m[0] & 0xf0) === 0x80);
  check(ons.length >= 5, `MIDI note-ons reached the port (${ons.length}, channel ${(ons[0] || [0])[0] & 15})`);
  check(ons.length > 0 && ons.every((m) => (m[0] & 15) === 2 && m[1] > 20 && m[1] < 110 && m[2] >= 1 && m[2] <= 127), 'MIDI bytes are valid');
  check(offs.length >= ons.length - 4, `note-offs follow (${offs.length})`);
  check(r.rows >= 5, `the event log has rows (${r.rows})`);
  const med = r.delays.length ? [...r.delays].sort((a, b) => a - b)[r.delays.length >> 1] : NaN;
  check(med > 0.02 && med < 0.4, `note-on is reported ${Math.round(1000 * med)} ms after the estimated onset (median of ${r.delays.length})`);

  // signal path: while a note sounds, the oscillator output peaks near its pitch
  const playing = r.samples.filter((s) => s.notes.length === 1 && s.rms > 0.005);
  check(playing.length >= 10, `the oscillators sound while a single note is active (${playing.length} of ${r.samples.length} snapshots)`);
  let good = 0;
  for (const s of playing) { const f = s.notes[0]; if (Math.abs(1200 * Math.log2(s.peak / f)) < 120) good++; }
  check(playing.length > 0 && good / playing.length > 0.6, `the oscillator's strongest frequency matches the detected note (${good} of ${playing.length})`);
  const quiet = r.samples.filter((s) => s.notes.length === 0);
  check(quiet.length > 5 && quiet.filter((s) => s.rms < 0.003).length / quiet.length > 0.7, `silent between notes (${quiet.filter((s) => s.rms < 0.003).length} of ${quiet.length})`);
  check(errors.length === 0, errors.length ? 'page errors: ' + errors.slice(0, 3).join(' | ') : 'no console errors');
} finally {
  await browser.close();
  server.close();
}
console.log(failed ? `${failed} FAILED` : 'browser test passed');
process.exit(failed ? 1 : 0);
