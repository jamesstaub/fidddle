// A synthetic test melody (plucked-or-bowed-like additive tones) for the demo pages, so they work without a microphone
// or any recording. Not a substitute for real instruments: it is easier than real playing.

const ROOTS = { bass: 28, cello: 48, viola: 60, violin: 67, guitar: 40, contrabass: 40 };   // MIDI note of the melody's first note
// [start s, duration s, semitones above the root ...] : single notes, a fifth, then a triad
const SCORE = [
  [0.3, 0.9, 0], [1.4, 0.9, 4], [2.5, 0.9, 7], [3.6, 0.9, 12], [4.7, 0.9, 7], [5.8, 0.9, 4],
  [7.0, 1.6, 0, 7],
  [9.0, 2.2, 0, 7, 16],
];
export const MELODY_SECONDS = 12;

const hz = (m) => 440 * Math.pow(2, (m - 69) / 12);

export function renderMelody(sampleRate, profile = 'cello', seconds = MELODY_SECONDS) {
  const n = Math.round(seconds * sampleRate), out = new Float32Array(n), root = ROOTS[profile] ?? 48;
  for (const [t0, dur, ...steps] of SCORE) {
    for (const st of steps) {
      const f0 = hz(root + st), a0 = Math.floor(t0 * sampleRate), len = Math.floor((dur + 0.08) * sampleRate);
      const H = Math.min(14, Math.floor(0.45 * sampleRate / f0));
      for (let i = 0; i < len && a0 + i < n; i++) {
        const t = i / sampleRate;
        const env = Math.min(1, t / 0.02) * (t < dur ? 1 : Math.max(0, 1 - (t - dur) / 0.08));
        // 5.5 Hz vibrato of +-0.3% (about 5 cents): the phase is the integral of the frequency
        const phase = 2 * Math.PI * f0 * (t - (0.003 / (2 * Math.PI * 5.5)) * (Math.cos(2 * Math.PI * 5.5 * t) - 1));
        let s = 0;
        for (let h = 1; h <= H; h++) s += Math.sin(h * phase) * Math.pow(h, -0.9);
        out[a0 + i] += 0.12 * env * s;
      }
    }
  }
  return out;
}
