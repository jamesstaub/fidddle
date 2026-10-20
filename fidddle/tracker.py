"""Temporal tracking, state machine and note events (spec §8).

Consumes the per-frame fitted voices and emits (a) per-slot track snapshots and
(b) note-on/note-off events. All state is fixed capacity (V_max tracks).

Timestamps: `onset_est_samples` is the estimated physical onset (from the
short-window flux peak while the note was pending); `deliver_samples` is the
newest sample of the frame at which the event was confirmed (§9.3).
"""
from collections import deque
from dataclasses import dataclass, field
import numpy as np
from scipy.optimize import linear_sum_assignment

INACTIVE, PENDING, ACTIVE, RELEASING = 0, 1, 2, 3
STATE_NAMES = ("inactive", "pending", "active", "releasing")


@dataclass
class NoteEvent:
    kind: str                  # "on" | "off"
    track_id: int
    midi_note: int
    midi_float: float
    velocity: int
    onset_est_samples: int     # estimated physical time of the event
    deliver_samples: int       # frame time at which it was confirmed
    confidence: float
    flags: tuple = ()          # "retrigger", "inferred_release", "weak_onset"
    slot: int = -1             # persistent voice slot of the track


@dataclass
class TrackSnapshot:
    slot: int
    track_id: int
    state: int
    midi: float
    f_hz: float
    level_db: float
    confidence: float
    string_index: int
    rank: int = -1             # 0 = lowest active voice


class _Track:
    __slots__ = ("id", "best_rise", "best_rise_end", "best_birth_rise", "age", "state", "midi", "vel", "level_db", "peak_db", "conf", "string",
                 "confirm_n", "miss_n", "first_end", "best_onset", "best_onset_end", "note_midi",
                 "hist", "last_support_end", "obs_conf", "retrig_hold", "hold_n", "slot")

    def __init__(self, tid, obs, end, onset, short_n):
        self.id = tid
        self.state = PENDING
        self.midi = obs.midi
        self.vel = 0.0
        self.level_db = obs.level_db
        self.peak_db = obs.level_db
        self.conf = obs.confidence
        self.string = obs.string_index
        self.confirm_n = 1
        self.miss_n = 0
        self.first_end = end
        self.best_onset = onset
        self.best_onset_end = end
        self.note_midi = None
        self.hist = deque([obs.midi], maxlen=9)
        self.last_support_end = end
        self.obs_conf = [obs.confidence]
        self.retrig_hold = 0
        self.hold_n = 0
        self.slot = -1
        self.best_rise = 0.0
        self.best_rise_end = end
        self.best_birth_rise = 0.0
        self.age = 0


class VoiceTracker:
    def __init__(self, cfg, n_long):
        self.cfg = cfg
        cap = max(cfg.onset_hist_frames, cfg.birth_hist_frames) + 1
        self.ms_hist = deque(maxlen=cap)
        self.edb_hist = deque(maxlen=cap)      # short-window energy (dB) per frame
        self.df_s = cfg.sample_rate / cfg.short_fft_size
        self.nbins_s = cfg.short_fft_size // 2 + 1
        self.n_long = n_long
        self.tracks = [None] * cfg.max_voices
        self.next_id = 1
        self.hop_ms = 1000.0 * cfg.hop_size / cfg.sample_rate
        self.dt = cfg.hop_size / cfg.sample_rate

    # ---- priors for the fitter / candidate generator ---------------------
    def predictions(self):
        out = []
        for t in self.tracks:
            if t is not None and t.state != INACTIVE:
                out.append(float(np.clip(t.midi + t.vel * self.dt, 0, 127)))
        return out

    # ---- per-track onset evidence (§5.5, §8.3 d_onset) ----------------------
    def _band_energy(self, Ms, f_hz, offset):
        """Energy near h*f (offset 0) or (h+1/2)*f (offset 0.5), low harmonics only."""
        h = np.arange(1, self.cfg.rise_harmonics + 1) + offset
        k = np.rint(h * f_hz / self.df_s).astype(int)
        k = k[(k < self.nbins_s - 1) & (h * f_hz < 3000.0)]
        if len(k) == 0:
            return 0.0
        loc = np.maximum.reduce([Ms[k - 1], Ms[k], Ms[k + 1]])
        return float(np.sqrt(np.sum(loc ** 2)))

    def _rise(self, f_hz, offset, span):
        # the newest frame against the minimum over the previous `span` frames
        e = [self._band_energy(m, f_hz, offset) for m in list(self.ms_hist)[-(span + 1):]]
        return float(20.0 * np.log10((e[-1] + 1e-9) / (min(e[:-1]) + 1e-9)))

    def attack_depth(self):
        """How sharply the overall short-window energy rose within the recent history: the biggest jump of any frame above
        the minimum of the ten frames before it. A plucked note, strummed chord or bow attack gives tens of dB; a sympathetic
        or ghost voice appearing in a decaying ring gives almost none. Broadband, so it works for low strings whose partials
        the short window cannot resolve."""
        e = list(self.edb_hist)[-(self.cfg.birth_hist_frames + 1):]
        best = 0.0
        for i in range(1, len(e)):
            best = max(best, e[i] - min(e[max(0, i - 10): i]))
        return float(best)

    def partial_rise_db(self, f_hz, span=None):
        """Tonal re-attack evidence for a pitch: short-window energy at its partials rises above
        its recent minimum, and rises more than the energy midway between partials (which a
        broadband attack of some other note would raise as much)."""
        if len(self.ms_hist) < 3:
            return 0.0
        span = self.cfg.onset_hist_frames if span is None else span
        rp = self._rise(f_hz, 0.0, span)
        rm = self._rise(f_hz, 0.5, span)
        return rp if (rp - rm) >= self.cfg.tonal_rise_margin_db else 0.0

    @staticmethod
    def _ev(t, *args):
        """A NoteEvent for track t, carrying the track's voice slot."""
        return NoteEvent(*args, slot=t.slot)

    def _is_multiple(self, hi_midi, lo_midi):
        """True if the higher pitch is (about) an integer multiple n >= 2 of the lower one."""
        r = 2.0 ** ((hi_midi - lo_midi) / 12.0)
        n = round(r)
        return n >= 2 and abs(r / n - 1.0) <= self.cfg.harmonic_tol

    def _harmonic_suspect(self, t):
        """A pending note that looks like a partial (or sub-octave ghost) of another live note.

        Of two harmonically related notes the weaker is suspect; if they are within 3 dB the higher one is."""
        for o in self.tracks:
            if o is None or o is t or o.state == INACTIVE:
                continue
            lo, hi = (o, t) if o.midi < t.midi else (t, o)
            if not self._is_multiple(hi.midi, lo.midi):
                continue
            if abs(t.level_db - o.level_db) > 3.0:
                if t.level_db < o.level_db:
                    return True
            elif t is hi:
                return True
        return False

    # ---- helpers -----------------------------------------------------------
    def _velocity(self, t):
        h = np.array(t.hist)
        if len(h) < 4:
            return 0.0
        d = np.diff(h) / self.dt
        v = float(np.median(d))
        return float(np.clip(v, -30.0, 30.0))   # semitones/s, limited

    def _free_slot(self):
        for i, t in enumerate(self.tracks):
            if t is None:
                return i
        return None

    def _velocity_midi(self, level_db):
        return int(np.clip(round((level_db + 60.0) / 60.0 * 127.0), 1, 127))

    # ---- main --------------------------------------------------------------
    def push_energy(self, energy_db):
        """Pre-roll: short-window energy of a hop before the first analysis frame exists."""
        self.edb_hist.append(float(energy_db))

    def update(self, end_sample, voices, onset, Ms=None, energy_db=None):
        cfg = self.cfg
        if Ms is not None:
            self.ms_hist.append(Ms)
        if energy_db is not None:
            self.edb_hist.append(float(energy_db))
        events = []
        obs = [v for v in voices if v.level_db >= cfg.min_level_dbfs
               or (cfg.quiet_snr_db > 0 and v.level_db >= cfg.quiet_floor_dbfs and v.snr_db >= cfg.quiet_snr_db)]
        strong = onset >= cfg.onset_strong
        live = [(i, t) for i, t in enumerate(self.tracks) if t is not None]

        # association (§8.3): Hungarian on pitch distance to the prediction
        matches = {}
        if live and obs:
            C = np.full((len(live), len(obs)), 1e6)
            for a, (_, t) in enumerate(live):
                pred = t.midi + t.vel * self.dt
                gate = cfg.assoc_gate_pending if t.state == PENDING else cfg.assoc_gate_semitones
                for b, o in enumerate(obs):
                    d = abs(o.midi - pred)
                    if d <= gate:
                        C[a, b] = d + 0.01 * abs(o.level_db - t.level_db)
            ra, cb = linear_sum_assignment(C)
            for a, b in zip(ra, cb):
                if C[a, b] < 1e5:
                    matches[live[a][0]] = obs[b]
        used_obs = {id(o) for o in matches.values()}

        # Octave/twelfth ambiguity: a sounding note that loses support while a candidate appears exactly an
        # octave, twelfth or two octaves away, with no re-attack there, is held rather than replaced.
        held, absorbed = set(), set()
        if cfg.octave_hold_frames > 0:
            for slot, t in live:
                if slot in matches or t.state not in (ACTIVE, RELEASING) or t.hold_n >= cfg.octave_hold_frames:
                    continue
                for o in obs:
                    if id(o) in used_obs or id(o) in absorbed:
                        continue
                    d = o.midi - t.midi
                    if any(abs(d - k) < 0.6 for k in (-24, -19, -12, 12, 19, 24)):
                        rise = self.partial_rise_db(440.0 * 2.0 ** ((o.midi - 69.0) / 12.0)) if self.ms_hist else 0.0
                        if rise < cfg.retrigger_rise_db:
                            absorbed.add(id(o))
                            held.add(slot)
                            t.hold_n += 1
                            t.last_support_end = end_sample
                            break

        for slot, t in live:
            o = matches.get(slot)
            if o is not None:
                self._update_matched(slot, t, o, end_sample, onset, strong, events)
            elif slot in held:
                pass
            else:
                self._update_missed(slot, t, end_sample, events)

        # new observations -> PENDING tracks
        for o in obs:
            if id(o) in used_obs or id(o) in absorbed:
                continue
            slot = self._free_slot()
            if slot is None:
                continue
            t = _Track(self.next_id, o, end_sample, onset, cfg.short_fft_size)
            self.next_id += 1
            self.tracks[slot] = t
            t.slot = slot
            t.age = 1
            if self.ms_hist:
                t.best_rise = self.partial_rise_db(440.0 * 2.0 ** ((o.midi - 69.0) / 12.0))
                t.best_birth_rise = self.attack_depth()
            self._maybe_confirm(slot, t, end_sample, strong, events)
        return self.snapshot(), events

    def _update_matched(self, slot, t, o, end, onset, strong, events):
        cfg = self.cfg
        innov = o.midi - t.midi
        eta = cfg.eta_sustain + (cfg.eta_attack - cfg.eta_sustain) * min(1.0, abs(innov) / 0.5)
        if strong:
            eta = max(eta, cfg.eta_attack)
        prev_level = t.level_db
        t.age += 1
        rise = self.partial_rise_db(440.0 * 2.0 ** ((o.midi - 69.0) / 12.0)) if self.ms_hist else 0.0
        t.midi += eta * innov
        t.hist.append(t.midi)
        t.vel = self._velocity(t)
        t.level_db += 0.5 * (o.level_db - t.level_db)
        t.peak_db = max(t.peak_db, t.level_db)
        t.conf += 0.3 * (o.confidence - t.conf)
        t.string = o.string_index
        t.miss_n = 0
        t.hold_n = 0
        t.last_support_end = end
        if t.state == PENDING:
            t.confirm_n += 1
            t.obs_conf.append(o.confidence)
            if onset > t.best_onset:
                t.best_onset, t.best_onset_end = onset, end
            if rise > t.best_rise:
                t.best_rise, t.best_rise_end = rise, end
            if cfg.attack_min_db > 0 and self.ms_hist:
                t.best_birth_rise = max(t.best_birth_rise, self.attack_depth())
                if t.age > cfg.pending_timeout_frames and t.best_birth_rise < cfg.attack_min_db:
                    self.tracks[slot] = None           # never showed an attack: not a note
                    return
            self._maybe_confirm(slot, t, end, strong, events)
        else:
            if t.state == RELEASING:
                t.state = ACTIVE
            # retrigger: a fresh attack near the same pitch while the note is sounding (§8.7)
            if t.retrig_hold > 0:
                t.retrig_hold -= 1
            elif rise >= cfg.retrigger_rise_db and t.age >= cfg.retrigger_min_age_frames and t.note_midi is not None:
                events.append(self._ev(t, "off", t.id, t.note_midi, t.midi, 0, end, end, t.conf, ("retrigger",)))
                t.note_midi = int(round(o.midi))
                t.peak_db = o.level_db
                events.append(self._ev(t, "on", t.id, t.note_midi, o.midi, self._velocity_midi(o.level_db),
                                        end - cfg.short_fft_size // 2, end, o.confidence, ("retrigger",)))
                t.retrig_hold = cfg.retrigger_min_age_frames
                t.age = 0

    def _maybe_confirm(self, slot, t, end, strong, events):
        cfg = self.cfg
        need = cfg.strong_confirm_frames if (strong or t.best_onset >= cfg.onset_strong or t.best_rise >= cfg.retrigger_rise_db) else cfg.confirm_frames
        if t.state == PENDING and t.confirm_n >= need and cfg.harmonic_confirm_frames > need and self._harmonic_suspect(t):
            need = cfg.harmonic_confirm_frames
        attack_ok = cfg.attack_min_db <= 0 or t.best_birth_rise >= cfg.attack_min_db
        if t.state == PENDING and t.confirm_n >= need and float(np.mean(t.obs_conf)) >= cfg.confirm_min_conf and attack_ok:
            t.state = ACTIVE
            t.note_midi = int(round(t.midi))
            flags = ()
            if t.best_rise >= cfg.retrigger_rise_db:
                est = t.best_rise_end - cfg.short_fft_size // 2
            elif t.best_onset >= 1.5:
                est = t.best_onset_end - cfg.short_fft_size // 2
            else:
                est = t.first_end - int(0.35 * self.n_long)
                flags = ("weak_onset",)
            events.append(self._ev(t, "on", t.id, t.note_midi, t.midi, self._velocity_midi(t.level_db),
                                    max(est, 0), end, float(np.mean(t.obs_conf)), flags))

    def _update_missed(self, slot, t, end, events):
        cfg = self.cfg
        t.miss_n += 1
        t.hist.append(t.midi)            # hold pitch while unsupported
        t.vel *= 0.8
        t.midi += t.vel * self.dt
        unsupported_ms = t.miss_n * self.hop_ms
        if t.state == PENDING:
            if t.miss_n >= 2:
                self.tracks[slot] = None  # never confirmed: drop silently
            return
        if t.state == ACTIVE and unsupported_ms >= cfg.release_hang_ms:
            t.state = RELEASING
        if t.state == RELEASING and unsupported_ms >= cfg.unsupported_timeout_ms:
            events.append(self._ev(t, "off", t.id, t.note_midi if t.note_midi is not None else int(round(t.midi)),
                                    t.midi, 0, t.last_support_end, end, t.conf, ("inferred_release",)))
            self.tracks[slot] = None

    def snapshot(self):
        snaps = []
        active = sorted([t for t in self.tracks if t is not None and t.state in (ACTIVE, RELEASING)], key=lambda t: t.midi)
        rank = {t.id: r for r, t in enumerate(active)}
        for i, t in enumerate(self.tracks):
            if t is None:
                snaps.append(TrackSnapshot(i, 0, INACTIVE, 0.0, 0.0, -120.0, 0.0, -1))
            else:
                f = 440.0 * 2.0 ** ((t.midi - 69.0) / 12.0)
                snaps.append(TrackSnapshot(i, t.id, t.state, float(t.midi), float(f), float(t.level_db),
                                           float(t.conf), int(t.string), rank.get(t.id, -1)))
        return snaps

    def flush(self, end_sample):
        """Close any open notes (end of stream)."""
        events = []
        for i, t in enumerate(self.tracks):
            if t is not None and t.state in (ACTIVE, RELEASING) and t.note_midi is not None:
                events.append(self._ev(t, "off", t.id, t.note_midi, t.midi, 0, end_sample, end_sample, t.conf, ("stream_end",)))
                self.tracks[i] = None
        return events
