"""Offline rendering of tracks through the BBCSO VST3 (DawDreamer), plus truth/analysis files."""
import json
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
import numpy as np
import soundfile as sf
from . import catalog, lags, midi, states

ROOT = states.ROOT
OUT_DIR = ROOT / "data" / "bbcso"


# Applied on top of whatever the saved state holds (a state captured in the UI can carry a non-zero reverb); a track's own
# params override these.
DEFAULT_PARAMS = {"Reverb": 0.0}


@dataclass
class Track:
    name: str
    instrument: str                 # catalog.INSTRUMENTS key
    player: str                     # "leader" (one solo player) | "section"
    articulation: str               # catalog.ARTICULATIONS key
    notes: list
    dynamics: int = 127             # 0-127, sets the plugin's Dynamics parameter (MIDI CC1 has no effect through the host)
    params: dict = field(default_factory=dict)   # plugin parameters by name, 0-1 normalised, e.g. {"Vibrato": 0.0}

    def effective_params(self):
        return {**DEFAULT_PARAMS, "Dynamics": self.dynamics / 127, **self.params}


def _param_index(plugin):
    idx = {}
    for d in plugin.get_plugin_parameters_description():
        idx.setdefault(d["name"], d["index"])
    return idx


def render_track(track, sr=44100, settle=3.0, tail=2.5, block=512):
    """-> (N, 2) float32 stereo. Raises if the track has no captured state."""
    import dawdreamer as daw
    sp = states.path(track.instrument, track.player, track.articulation)
    if not states.has_patch(sp):
        raise SystemExit(f"no captured patch for {track.instrument}/{track.player}/{track.articulation}: "
                         f"run  tools/bbcso_render.py capture --instrument {track.instrument} --articulation {track.articulation}")
    engine = daw.RenderEngine(sr, block)
    plugin = engine.make_plugin_processor("bbcso", str(catalog.VST3))
    plugin.load_state(str(sp))
    idx = _param_index(plugin)
    for k, v in track.effective_params().items():
        if k not in idx:
            raise SystemExit(f"unknown plugin parameter {k!r}; see `bbcso_render.py params`")
        plugin.set_parameter(idx[k], float(v))
    time.sleep(settle)                                  # samples stream in on background threads after the state loads
    with tempfile.TemporaryDirectory() as d:
        mp = Path(d) / "t.mid"
        midi.write_midi(str(mp), {track.name: track.notes})
        plugin.load_midi(str(mp), clear_previous=True, beats=False, all_events=True)
        engine.load_graph([(plugin, [])])
        dur = max(n.offset for n in track.notes) + tail
        engine.render(dur)
    return engine.get_audio().T.astype(np.float32)


def envelope(x, sr, win_s=0.005):
    n = max(1, int(win_s * sr))
    return np.convolve(np.abs(x), np.ones(n) / n, mode="same")


def analyse_track(stem, notes, sr, silence_peak=1e-4):
    """Per note: whether it rendered at all (peak of the envelope from note-on to the next onset / note-off + 0.2 s)."""
    env = envelope(stem if stem.ndim == 1 else stem.mean(1), sr)
    ons = sorted(n.onset for n in notes)
    res = []
    for n in notes:
        later = [t for t in ons if t > n.onset + 1e-6]
        end = min(n.offset, later[0] if later else n.offset) + 0.2
        seg = env[int(max(0, n.onset - 0.05) * sr):int(end * sr)]
        peak = float(seg.max()) if len(seg) else 0.0
        res.append({"silent": peak < silence_peak, "peak": peak})
    return res


def render_scene(name, tracks, sr=44100, mono=True, stereo=False, out_dir=None, settle=3.0, tail=2.5, scenario=None):
    """Render each track as its own stem, sum to the mixture, write wav / stems / mid / json. Returns the json dict.

    Files (out_dir/<name>): .wav mixture (mono unless stereo=True), .mid (one MIDI track per stem), .json truth,
    .stems/<track>.wav isolated stems (the exact source of each voice in the mixture).
    The MIDI note times are what was *sent*; the json also carries audio_onset / onset_lag from the calibrated per-patch,
    per-pitch table (lags.py), absent when that patch/pitch is not calibrated.
    """
    out = Path(out_dir or OUT_DIR)
    out.mkdir(parents=True, exist_ok=True)
    stems = {t.name: render_track(t, sr, settle, tail) for t in tracks}
    n = max(len(s) for s in stems.values())
    mix = np.zeros((n, 2), np.float32)
    for s in stems.values():
        mix[:len(s)] += s
    peak = float(np.abs(mix).max())
    scale = 0.95 / peak if peak > 0.95 else 1.0         # one shared gain keeps stem/mix level relationships intact
    mix *= scale
    (out / f"{name}.stems").mkdir(exist_ok=True)
    tr_json, notes_json, warnings = [], [], []
    for t in tracks:
        st = stems[t.name] * scale
        mono_st = st.mean(1)
        sf.write(out / f"{name}.stems" / f"{t.name}.wav", st if stereo else mono_st, sr, subtype="FLOAT")
        ana = analyse_track(mono_st, t.notes, sr)
        tr_json.append({"track": t.name, "instrument": t.instrument, "player": t.player, "articulation": t.articulation,
                        "dynamics": t.dynamics, "params": t.effective_params()})
        for nt, a in zip(t.notes, ana):
            lag = lags.lag_s(t.instrument, t.player, t.articulation, nt.midi)
            audio = {"audio_onset": nt.onset + lag, "onset_lag": lag} if lag is not None else {}
            notes_json.append({"onset": nt.onset, "offset": nt.offset, "midi": nt.midi, "velocity": nt.velocity,
                               "src": t.name, "articulation": t.articulation, **audio, **a})
            if a["silent"]:
                warnings.append(f"{t.name}: note {nt.midi} at {nt.onset:.2f}s rendered silent (patch range? sample streaming?)")
    notes_json.sort(key=lambda d: (d["onset"], d["midi"]))
    midi.write_midi(str(out / f"{name}.mid"), {t.name: t.notes for t in tracks})
    sf.write(out / f"{name}.wav", mix if stereo else mix.mean(1), sr, subtype="PCM_24")
    meta = {"sr": sr, "scenario": scenario, "tracks": tr_json, "notes": notes_json, "gain": scale, "warnings": warnings,
            "caveat": "BBCSO samples; 'section' tracks are many players (phase not like a solo instrument), 'leader' is one player."}
    (out / f"{name}.json").write_text(json.dumps(meta, indent=1))
    for w in warnings:
        print("WARNING:", w)
    return meta
