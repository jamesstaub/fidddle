import { Fidddle } from '../src/fidddle.js';
import { renderMelody } from './testsignal.js';

const $ = (id) => document.getElementById(id);
const NAMES = ['C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B'];
const noteName = (n) => NAMES[((n % 12) + 12) % 12] + (Math.floor(n / 12) - 1);
const RANGE = { bass: [24, 64], cello: [34, 88], viola: [46, 92], violin: [53, 100], guitar: [36, 88], contrabass: [24, 62] };
const LEVEL_SCALE = 3;          // detector levels are linear amplitudes of about 0.02 to 0.2 for a signal peaking at 0.5

let ctx = null, fid = null, source = null, micStream = null;
let master = null, inputGain = null, monitorGain = null;
let cont = null;                     // { master, links, oscs }
let synth = new Map();               // slot -> { osc, gain }
let midiAccess = null, midiStop = null;
const frames = [];                   // { time, voices } for the trace
const marks = [];                    // note-on times
const delays = [];                   // reported minus estimated onset, seconds
let lastVoices = [];

const setStatus = (t, err) => { const s = $('status'); s.textContent = t; s.classList.toggle('error', !!err); };

// ---------------------------------------------------------------- start and stop
async function start() {
  $('start').disabled = true;
  try {
    await stop(true);
    if (!ctx) {
      try { ctx = new AudioContext({ sampleRate: 48000, latencyHint: 'interactive' }); }   // the browser converts other rates
      catch { ctx = new AudioContext({ latencyHint: 'interactive' }); }
      master = new GainNode(ctx, { gain: 0.8 }); master.connect(ctx.destination);
    }
    await ctx.resume();
    setStatus('Loading the detector…');
    inputGain = new GainNode(ctx, { gain: 1 });
    monitorGain = new GainNode(ctx, { gain: $('monitor').checked ? 0.5 : 0 });
    inputGain.connect(monitorGain).connect(master);
    await buildDetector();
    await startSource();
    $('stop').disabled = false;
  } catch (e) {
    console.error(e);
    setStatus(String(e.message || e), true);
    $('start').disabled = false;
  }
}

async function stop(keepContext) {
  if (source) { try { source.stop?.(); } catch {} source.disconnect(); source = null; }
  if (micStream) { micStream.getTracks().forEach((t) => t.stop()); micStream = null; }
  teardownDetector();
  if (inputGain) { inputGain.disconnect(); inputGain = null; }
  if (monitorGain) { monitorGain.disconnect(); monitorGain = null; }
  $('stop').disabled = true; $('start').disabled = false;
  if (!keepContext) setStatus('Stopped.');
}

async function buildDetector() {
  teardownDetector();
  const profile = $('profile').value, quality = $('quality').value;
  fid = await Fidddle.create(ctx, { profile, quality, trackFrames: true, glideMs: +$('glide').value, sorted: $('sorted').checked });
  inputGain.connect(fid.node);
  fid.events.addEventListener('noteon', onNoteOn);
  fid.events.addEventListener('noteoff', onNoteOff);
  fid.events.addEventListener('frame', onFrame);
  fid.events.addEventListener('error', (e) => setStatus('Detector error: ' + e.detail.message, true));
  buildVoiceBoxes(fid.voices);
  wireContinuous();
  if (midiAccess) connectMidiOutput();
  const hopMs = 1000 * fid.info.hop / ctx.sampleRate;
  setStatus(`Running: ${profile}, ${quality}, ${fid.voices} voices, ${ctx.sampleRate} Hz, one analysis step every ${hopMs.toFixed(1)} ms.`);
}

function teardownDetector() {
  if (midiStop) { midiStop(); midiStop = null; }
  unwireContinuous();
  for (const s of synth.values()) releaseSynth(s, true);
  synth.clear();
  if (fid) { try { fid.destroy(); } catch {} fid = null; }
  frames.length = 0; marks.length = 0; lastVoices = [];
  $('active').textContent = '';
}

async function startSource() {
  if (source) { try { source.stop?.(); } catch {} source.disconnect(); source = null; }
  if (micStream) { micStream.getTracks().forEach((t) => t.stop()); micStream = null; }
  const kind = document.querySelector('input[name=src]:checked').value;
  if (kind === 'mic') {
    micStream = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: false, noiseSuppression: false, autoGainControl: false, channelCount: 1 } });
    source = ctx.createMediaStreamSource(micStream);
  } else if (kind === 'file') {
    const f = $('file').files[0];
    if (!f) throw new Error('Choose an audio file first.');
    const buf = await ctx.decodeAudioData(await f.arrayBuffer());
    source = new AudioBufferSourceNode(ctx, { buffer: buf, loop: true });
    source.start();
  } else {
    const data = renderMelody(ctx.sampleRate, $('profile').value);
    const buf = new AudioBuffer({ length: data.length, sampleRate: ctx.sampleRate, numberOfChannels: 1 });
    buf.copyToChannel(data, 0);
    source = new AudioBufferSourceNode(ctx, { buffer: buf, loop: true });
    source.start();
  }
  source.connect(inputGain);
}

// ---------------------------------------------------------------- continuous: signals -> oscillators
function wireContinuous() {
  unwireContinuous();
  const V = fid.voices, follow = $('follow').checked;
  const m = new GainNode(ctx, { gain: $('contOn').checked ? 0.5 : 0 });
  m.connect(master);
  const links = [], oscs = [];
  for (let s = 0; s < V; s++) {
    const osc = new OscillatorNode(ctx, { type: $('wave').value, frequency: 0, detune: 1200 * +$('octave').value });
    const gateAmp = new GainNode(ctx, { gain: 0 });
    const levelAmp = new GainNode(ctx, { gain: follow ? 0 : 0.25 });
    osc.connect(gateAmp).connect(levelAmp).connect(m);
    links.push(fid.signals.connectFrequency(s, osc.frequency));      // pitch -> oscillator frequency
    links.push(fid.signals.connectGate(s, gateAmp.gain));            // on/off -> amplifier
    if (follow) links.push(fid.signals.connectLevel(s, levelAmp.gain, { scale: LEVEL_SCALE }));   // loudness -> amplifier
    osc.start();
    oscs.push(osc);
  }
  cont = { master: m, links, oscs };
}

function unwireContinuous() {
  if (!cont) return;
  for (const l of cont.links) l();
  for (const o of cont.oscs) { try { o.stop(); } catch {} o.disconnect(); }
  cont.master.disconnect();
  cont = null;
}

function buildVoiceBoxes(V) {
  const box = $('voices');
  box.textContent = '';
  for (let s = 0; s < V; s++) {
    const d = document.createElement('div');
    d.className = 'voice'; d.id = 'v' + s;
    d.innerHTML = `<span class="muted">voice ${s}</span><br><b>–</b> <span class="muted"></span><div class="bar"><i></i></div>`;
    box.appendChild(d);
  }
}

// ---------------------------------------------------------------- MIDI: note events
function onNoteOn(e) {
  const d = e.detail;
  addLog('on', d);
  if (d.onsetTime !== undefined) { delays.push(d.time - d.onsetTime); if (delays.length > 30) delays.shift(); }
  marks.push({ time: d.time, note: d.midiFloat });
  if ($('synthOn').checked) {
    const old = synth.get(d.slot);
    if (old) releaseSynth(old);
    const osc = new OscillatorNode(ctx, { type: 'triangle', frequency: d.frequency });
    const gain = new GainNode(ctx, { gain: 0 });
    osc.connect(gain).connect(master);
    const v = 0.05 + 0.25 * (d.velocity / 127);
    gain.gain.setTargetAtTime(v, ctx.currentTime, 0.01);
    osc.start();
    synth.set(d.slot, { osc, gain });
  }
}
function onNoteOff(e) {
  const d = e.detail;
  addLog('off', d);
  const s = synth.get(d.slot);
  if (s) { releaseSynth(s); synth.delete(d.slot); }
}
function releaseSynth(s, now) {
  const t = ctx.currentTime;
  s.gain.gain.cancelScheduledValues(t);
  s.gain.gain.setTargetAtTime(0, t, now ? 0.001 : 0.04);
  s.osc.stop(t + (now ? 0.02 : 0.3));
}

function addLog(kind, d) {
  const tr = document.createElement('tr');
  const delay = kind === 'on' && d.onsetTime !== undefined ? Math.round(1000 * (d.time - d.onsetTime)) + ' ms' : '';
  tr.innerHTML = `<td>${d.time.toFixed(2)}</td><td>${kind === 'on' ? 'note on' : 'note off'}</td><td>${noteName(d.note)} (${d.note})</td><td>${kind === 'on' ? d.velocity : ''}</td><td>${d.slot}</td><td>${delay}</td>`;
  const body = $('log');
  body.prepend(tr);
  while (body.children.length > 80) body.lastChild.remove();
}

async function enableMidi() {
  const st = $('midiStatus');
  if (!navigator.requestMIDIAccess) { st.textContent = 'This browser has no Web MIDI (Chrome, Edge and Opera do). The built-in synth still works.'; return; }
  try {
    midiAccess = await navigator.requestMIDIAccess();
  } catch (e) { st.textContent = 'MIDI access was refused: ' + e.message; return; }
  midiAccess.onstatechange = fillMidiOutputs;
  fillMidiOutputs();
}
function fillMidiOutputs() {
  const sel = $('midiOut'), prev = sel.value;
  sel.textContent = '';
  const none = new Option('none', ''); sel.add(none);
  for (const o of midiAccess.outputs.values()) sel.add(new Option(o.name, o.id));
  sel.disabled = false;
  if ([...sel.options].some((o) => o.value === prev)) sel.value = prev;
  $('midiStatus').textContent = midiAccess.outputs.size ? `${midiAccess.outputs.size} output(s) found. Choose one to send the note events to it.` : 'No MIDI outputs found. On macOS the IAC driver (Audio MIDI Setup) gives a virtual one.';
  connectMidiOutput();
}
function connectMidiOutput() {
  if (midiStop) { midiStop(); midiStop = null; }
  const id = $('midiOut').value;
  $('midiTest').disabled = !id;
  if (!id || !fid || !midiAccess) return;
  const out = midiAccess.outputs.get(id);
  if (out) midiStop = fid.events.connectMidi(out, { channel: +$('midiCh').value });
}
function testNote() {
  const out = midiAccess && midiAccess.outputs.get($('midiOut').value);
  if (!out) return;
  const ch = +$('midiCh').value;
  out.send([0x90 | ch, 60, 90]);
  out.send([0x80 | ch, 60, 0], performance.now() + 400);
}

// ---------------------------------------------------------------- display
function onFrame(e) {
  const d = e.detail;
  frames.push(d);
  lastVoices = d.voices;
}

function drawVoices() {
  if (!fid) return;
  const act = fid.events.activeNotes;
  $('active').innerHTML = act.length ? act.map((n) => `<span class="chip">${noteName(n.note)} ${n.frequency.toFixed(1)} Hz</span>`).join('') : '<span class="muted">nothing</span>';
  const boxes = $('voices').children;
  const bySlot = new Map(lastVoices.map((v) => [v.slot, v]));
  for (let s = 0; s < boxes.length; s++) {
    const v = bySlot.get(s), el = boxes[s], on = v && (v.state === 2 || v.state === 3);
    el.classList.toggle('on', !!on);
    el.querySelector('b').textContent = v && v.state > 0 ? noteName(Math.round(v.midi)) : '–';
    el.querySelector('span:nth-of-type(2)').textContent = v && v.state > 0 ? v.frequency.toFixed(1) + ' Hz' + (v.state === 1 ? ' (pending)' : '') : '';
    el.querySelector('i').style.width = on ? Math.min(100, 100 * Math.sqrt(v.level) * 2) + '%' : '0';
  }
}

function drawTrace() {
  const c = $('trace'), g = c.getContext('2d');
  const dpr = window.devicePixelRatio || 1, w = c.clientWidth, h = c.clientHeight;
  if (c.width !== Math.round(w * dpr)) { c.width = Math.round(w * dpr); c.height = Math.round(h * dpr); }
  g.setTransform(dpr, 0, 0, dpr, 0, 0);
  g.clearRect(0, 0, w, h);
  const [lo, hi] = RANGE[$('profile').value];
  const y = (m) => h - ((m - lo) / (hi - lo)) * h;
  const style = getComputedStyle(document.body);
  g.strokeStyle = style.getPropertyValue('--line'); g.fillStyle = style.getPropertyValue('--muted'); g.font = '11px system-ui';
  for (let m = Math.ceil(lo / 12) * 12; m <= hi; m += 12) { g.beginPath(); g.moveTo(0, y(m)); g.lineTo(w, y(m)); g.stroke(); g.fillText(noteName(m), 3, y(m) - 2); }
  if (!ctx) return;
  const span = 10, now = ctx.currentTime, x = (t) => w - ((now - t) / span) * w;
  while (frames.length && frames[0].time < now - span) frames.shift();
  while (marks.length && marks[0].time < now - span) marks.shift();
  for (const f of frames) {
    for (const v of f.voices) {
      const on = v.state === 2 || v.state === 3;
      g.fillStyle = `hsl(${(v.slot * 57) % 360} 70% 50% / ${on ? 1 : 0.3})`;
      g.fillRect(x(f.time), y(v.midi) - 1.5, 2.5, 3);
    }
  }
  g.strokeStyle = style.getPropertyValue('--on');
  for (const m of marks) { g.beginPath(); g.moveTo(x(m.time), h); g.lineTo(x(m.time), h - 10); g.stroke(); }
}

function loop() {
  drawVoices();
  drawTrace();
  requestAnimationFrame(loop);
}

// ---------------------------------------------------------------- wiring of the page
for (let i = 0; i < 16; i++) $('midiCh').add(new Option(String(i + 1), String(i)));
$('start').onclick = start;
$('stop').onclick = () => stop(false);
$('midiBtn').onclick = enableMidi;
$('midiOut').onchange = connectMidiOutput;
$('midiCh').onchange = connectMidiOutput;
$('midiTest').onclick = testNote;
$('monitor').onchange = () => { if (monitorGain) monitorGain.gain.setTargetAtTime($('monitor').checked ? 0.5 : 0, ctx.currentTime, 0.02); };
$('contOn').onchange = () => { if (cont) cont.master.gain.setTargetAtTime($('contOn').checked ? 0.5 : 0, ctx.currentTime, 0.02); };
for (const id of ['wave', 'octave', 'follow']) $(id).onchange = () => { if (fid) wireContinuous(); };
$('glide').oninput = () => { $('glideV').textContent = $('glide').value + ' ms'; if (fid) fid.signals.glideMs = +$('glide').value; };
$('sorted').onchange = () => { if (fid) fid.signals.sorted = $('sorted').checked; };
for (const id of ['profile', 'quality']) $(id).onchange = async () => { if (fid && ctx) { try { await buildDetector(); if (document.querySelector('input[name=src]:checked').value === 'melody') await startSource(); } catch (e) { setStatus(String(e.message || e), true); } } };
for (const r of document.querySelectorAll('input[name=src]')) r.onchange = async () => { $('monitor').checked = r.value !== 'mic'; $('monitor').onchange(); if (fid && ctx) { try { await startSource(); } catch (e) { setStatus(String(e.message || e), true); } } };
$('monitor').checked = true;
window.__demo = { get fid() { return fid; }, get ctx() { return ctx; }, get master() { return master; }, delays };   // for the automated browser test
requestAnimationFrame(loop);
