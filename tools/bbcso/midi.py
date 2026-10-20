"""Notes <-> MIDI (mido). All times are seconds; the file is written at a fixed 120 bpm so ticks map 1:1 to time."""
from dataclasses import dataclass, asdict
import mido

PPQ = 480
TEMPO = 500000                     # 120 bpm: one beat = 0.5 s


@dataclass
class Note:
    midi: int
    onset: float
    offset: float
    velocity: int = 90
    track: str = ""                # which stem the note belongs to (set by scenes / render)

    def to_dict(self):
        return asdict(self)


def _ticks(t):
    return int(round(t * 2 * PPQ))


def write_midi(path, tracks):
    """tracks: {name: [Note]}. One MIDI track per stem, all on channel 0, so each stem can be re-rendered or opened in a DAW on its own.
    """
    mid = mido.MidiFile(ticks_per_beat=PPQ)
    for name, notes in tracks.items():
        tr = mido.MidiTrack()
        tr.append(mido.MetaMessage("set_tempo", tempo=TEMPO, time=0))
        tr.append(mido.MetaMessage("track_name", name=name, time=0))
        ev = []
        for n in notes:
            ev.append((_ticks(n.onset), 2, mido.Message("note_on", note=n.midi, velocity=n.velocity)))
            ev.append((_ticks(n.offset), 1, mido.Message("note_off", note=n.midi, velocity=0)))
        ev.sort(key=lambda e: (e[0], e[1]))          # at equal ticks: note_off before note_on
        last = 0
        for tick, _, msg in ev:
            tr.append(msg.copy(time=tick - last))
            last = tick
        mid.tracks.append(tr)
    mid.save(path)


def read_midi(path):
    """-> {track_name: [Note]}; CCs ignored. Tempo changes are honoured (mido gives seconds via merge)."""
    mid = mido.MidiFile(path)
    out = {}
    for i, tr in enumerate(mid.tracks):
        name = next((m.name for m in tr if m.type == "track_name"), f"track{i}")
        tempo, t, open_, notes = TEMPO, 0.0, {}, []
        # tempo is usually in track 0 only; take the first set_tempo seen anywhere
        for m in mid.tracks[0]:
            if m.type == "set_tempo":
                tempo = m.tempo
                break
        for m in tr:
            t += mido.tick2second(m.time, mid.ticks_per_beat, tempo)
            if m.type == "note_on" and m.velocity > 0:
                open_.setdefault(m.note, []).append((t, m.velocity))
            elif m.type in ("note_off", "note_on") and m.note in open_ and open_[m.note]:
                on, vel = open_[m.note].pop(0)
                notes.append(Note(m.note, on, t, vel, name))
        if notes:
            out[name] = sorted(notes, key=lambda n: (n.onset, n.midi))
    return out


def transpose(notes, semitones):
    return [Note(n.midi + semitones, n.onset, n.offset, n.velocity, n.track) for n in notes]


def humanize(notes, rng, timing_s=0.01, velocity=8):
    """Gaussian timing / velocity jitter (offsets keep their duration). Seeded rng for reproducibility."""
    out = []
    for n in notes:
        dt = float(rng.normal(0, timing_s))
        v = int(min(127, max(1, n.velocity + rng.normal(0, velocity))))
        out.append(Note(n.midi, max(0.0, n.onset + dt), max(0.0, n.offset + dt), v, n.track))
    return out
