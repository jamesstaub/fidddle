"""Minimal Standard MIDI File writer (format 1, one track per voice, 120 bpm), so a scene's truth can be opened in a DAW."""
import struct

PPQ = 480
TEMPO_US = 500000                      # 120 bpm: one second = two beats
VELOCITY = {"ppp": 25, "pp": 40, "p": 55, "mp": 70, "mf": 85, "f": 100, "ff": 115, "fff": 127}


def _vlq(n):
    out = [n & 0x7F]
    n >>= 7
    while n:
        out.append((n & 0x7F) | 0x80)
        n >>= 7
    return bytes(reversed(out))


def _track(events):
    """events: [(tick, order, bytes)] -> track chunk."""
    data, last = b"", 0
    for tick, _, msg in sorted(events):
        data += _vlq(tick - last) + msg
        last = tick
    data += _vlq(0) + b"\xff\x2f\x00"
    return b"MTrk" + struct.pack(">I", len(data)) + data


def write_midi(path, notes):
    """notes: the scene's note dicts (onset, offset, midi, dynamic, voice). Times in seconds."""
    tick = lambda s: int(round(s * 2 * PPQ))
    voices = sorted({n.get("voice", 0) for n in notes}) or [0]
    tracks = [_track([(0, 0, b"\xff\x51\x03" + TEMPO_US.to_bytes(3, "big"))])]
    for v in voices:
        ev = []
        for n in (n for n in notes if n.get("voice", 0) == v):
            vel = VELOCITY.get(n.get("dynamic"), 80)
            ev.append((tick(n["onset"]), 1, bytes([0x90, int(n["midi"]), vel])))
            ev.append((max(tick(n["offset"]), tick(n["onset"]) + 1), 0, bytes([0x80, int(n["midi"]), 0])))
        tracks.append(_track(ev))
    with open(path, "wb") as f:
        f.write(b"MThd" + struct.pack(">IHHH", 6, 1, len(tracks), PPQ))
        for t in tracks:
            f.write(t)
