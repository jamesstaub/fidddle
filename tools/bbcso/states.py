"""Plugin state files: one per (instrument, player, articulation).

A state is what the plugin saves for a loaded patch (a few KB; it references the library, not the samples). They are
created once with `bbcso_render.py capture`, which opens the plugin editor so a human can pick the patch.
Stored in data/bbcso/states/ (gitignored: machine specific).
"""
from pathlib import Path
from . import catalog

ROOT = Path(__file__).resolve().parent.parent.parent
STATE_DIR = ROOT / "data" / "bbcso" / "states"
EMPTY_STATE_BYTES = 502          # size of the state with no patch loaded; anything bigger has a patch


def key(instrument, player, articulation):
    return f"{instrument}__{player}__{articulation}"


def path(instrument, player, articulation):
    return STATE_DIR / f"{key(instrument, player, articulation)}.state"


def has_patch(p):
    return p.exists() and p.stat().st_size > EMPTY_STATE_BYTES + 16


def captured():
    """[(instrument, player, articulation)] with a state on disk."""
    out = []
    for f in sorted(STATE_DIR.glob("*.state")) if STATE_DIR.exists() else []:
        parts = f.stem.split("__")
        if len(parts) == 3 and has_patch(f):
            out.append(tuple(parts))
    return out


def wanted(instruments=None, players=("leader",), articulations=None):
    out = []
    for inst in instruments or catalog.CORE_INSTRUMENTS:
        for player in players:
            for art in articulations or catalog.CORE_ARTICULATIONS:
                if catalog.patch_name(inst, art, player):
                    out.append((inst, player, art))
    return out


def capture(instrument, player, articulation):
    """Open the plugin editor; the human loads the patch and closes the window, and the state is saved.

    Returns True if a patch state was kept. Ctrl-C skips this patch (returns False); a second Ctrl-C within 2 s raises
    KeyboardInterrupt to stop the whole run. Closing the window without loading a patch also skips.
    """
    import subprocess
    import sys
    import time
    name = catalog.patch_name(instrument, articulation, player)
    if not name:
        print(f"skip {instrument}/{player}/{articulation}: not in this library")
        return False
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    p = path(instrument, player, articulation)
    tmp = p.with_suffix(".tmp")
    tmp.unlink(missing_ok=True)
    print(f"\n>>> In the plugin window pick:  {name}")
    print("    wait for it to finish loading, then close the window.  Ctrl-C skips this one (twice quickly = quit)")
    # own session: the terminal's Ctrl-C reaches only this process, not the editor
    child = subprocess.Popen([sys.executable, "-m", "tools.bbcso.editor", str(tmp)], cwd=ROOT, start_new_session=True)
    try:
        child.wait()
    except KeyboardInterrupt:
        child.kill()
        child.wait()
        print("    skipped")
        try:
            time.sleep(2.0)
        except KeyboardInterrupt:
            raise KeyboardInterrupt from None
        return False
    if not has_patch(tmp):
        tmp.unlink(missing_ok=True)
        print("    window closed with no patch loaded: skipped")
        return False
    tmp.replace(p)
    print(f"    saved {p.relative_to(ROOT)}")
    ok, msg = check(instrument, player, articulation)
    print(f"    probe: {msg}")
    if not ok:
        print("    !! this does not look like the patch named above: run capture --force for it again")
    return True


# A held 3 s note: bowed / tremolo patches keep sounding, plucked / spiccato patches die away.
EXPECT_SUSTAIN = {"long": True, "legato": True, "long_cs": True, "marcato": True, "long_marcato": True, "tremolo": True,
                  "sul_tasto": True, "sul_pont": True, "flautando": True, "harmonics": True,
                  "pizzicato": False, "pizz_bartok": False, "spiccato": False, "staccato": False, "col_legno": False}
_PROBE_MIDI = {"violin": 69, "violin2": 69, "viola": 60, "cello": 48, "bass": 36}


def probe(instrument, player, articulation):
    """Render one held note and report (sustains, rms_early, rms_late). Cheap sanity check that a state holds the patch
    it is named for; it cannot tell two bowed patches apart, but catches bowed-vs-plucked mix-ups and silent states."""
    import numpy as np
    from .midi import Note
    from .render import Track, render_track
    x = render_track(Track("probe", instrument, player, articulation, [Note(_PROBE_MIDI[instrument], 0.5, 3.5)]), settle=2.0, tail=1.0).mean(1)
    rms = lambda a, b: float(np.sqrt((x[int(a * 44100):int(b * 44100)] ** 2).mean()))
    early, late = max(rms(0.5, 1.0), rms(1.0, 1.5)), rms(2.5, 3.0)
    return late > 0.25 * early and late > 1e-4, early, late


def check(instrument, player, articulation):
    """-> (ok, message) comparing the probe with the articulation's expected behaviour."""
    sustains, early, late = probe(instrument, player, articulation)
    want = EXPECT_SUSTAIN.get(articulation)
    msg = f"{'sustains' if sustains else 'dies away'} (rms {early*1000:.1f} -> {late*1000:.1f} e-3)"
    if early < 1e-4:
        return False, "SILENT: " + msg
    if want is not None and want != sustains:
        return False, f"UNEXPECTED, expected it to {'sustain' if want else 'die away'}: " + msg
    return True, msg
