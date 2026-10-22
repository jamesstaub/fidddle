"""InstrumentProfile and DetectorConfig (spec §1.3, §12).

All instrument-specific numbers live in the profile; the algorithm never
mentions a particular instrument.
"""
from dataclasses import dataclass, field
import math

import numpy as np

BOWED, PLUCKED, MIXED = "bowed", "plucked", "mixed"
OFF, SOFT, HARD = "off", "soft", "hard"
MAX_VOICES = 8
MAX_STRINGS = 8


@dataclass
class InstrumentProfile:
    name: str
    open_string_hz: tuple
    min_frequency_hz: float
    max_frequency_hz: float
    window_periods: float = 10.0
    inharmonicity_B: float = 0.0
    harmonic_weight_exponent: float = 0.5
    excitation: str = MIXED
    string_constraint: str = SOFT
    string_infeasible_penalty: float = 1.0
    voice_penalty: tuple = (0.0, 0.0, 0.5, 1.0, 1.5, 2.0, 2.5, 3.0)
    string_tuning_cents: tuple = ()
    default_voices: int = 4
    # config fields this instrument wants different from the global defaults (name -> value)
    config_overrides: dict = field(default_factory=dict)
    # upper tier: pitches above max_frequency_hz up to this value (0 = none) are accepted only as near-pure tones (harmonics), see DetectorConfig.high_pitch_*
    harmonic_max_frequency_hz: float = 0.0

    @property
    def string_count(self):
        return len(self.open_string_hz)

    @classmethod
    def cello(cls):
        return cls(name="cello", open_string_hz=(65.41, 98.00, 146.83, 220.00),
                   min_frequency_hz=60.0, max_frequency_hz=1000.0, harmonic_max_frequency_hz=2700.0,
                   # soft bowed notes (pp) are quiet in absolute terms: count them when well above the local noise floor
                   config_overrides={"quiet_snr_db": 30.0})

    @classmethod
    def bass(cls):
        # 5-string bass (B0 E1 A1 D2 G2); a 4-string bass simply leaves the B string uncalibrated. Six periods of 28 Hz need a
        # 16384-sample window (372 ms); a shorter one leaves the partials of the low B only ~5 bins apart and lets attack ghosts
        # through. A 4-string bass can raise minfreq (about 38 Hz) to get the 8192-sample window.
        return cls(name="bass", open_string_hz=(30.87, 41.20, 55.00, 73.42, 98.00),
                   min_frequency_hz=28.0, max_frequency_hz=500.0, window_periods=6.0, inharmonicity_B=5e-5,
                   # nearly monophonic: a harmonic of a sounding note needs to persist before it counts as a note
                   config_overrides={"harmonic_confirm_frames": 14, "attack_min_db": 8.0, "birth_hist_frames": 80, "pending_timeout_frames": 88})

    @classmethod
    def viola(cls):
        return cls(name="viola", open_string_hz=(130.81, 196.00, 293.66, 440.00),
                   min_frequency_hz=120.0, max_frequency_hz=1500.0, harmonic_max_frequency_hz=4000.0,
                   # soft bowed notes (pp) are quiet in absolute terms: count them when well above the local noise floor
                   config_overrides={"quiet_snr_db": 30.0})

    @classmethod
    def violin(cls):
        return cls(name="violin", open_string_hz=(196.00, 293.66, 440.00, 659.26),
                   min_frequency_hz=185.0, max_frequency_hz=2800.0, harmonic_max_frequency_hz=4000.0,
                   # soft bowed notes (pp) are quiet in absolute terms: count them when well above the local noise floor
                   config_overrides={"quiet_snr_db": 30.0})

    @classmethod
    def guitar(cls):
        return cls(name="guitar", open_string_hz=(82.41, 110.00, 146.83, 196.00, 246.94, 329.63),
                   min_frequency_hz=70.0, max_frequency_hz=1400.0, harmonic_max_frequency_hz=1800.0, default_voices=6,
                   # chords stack octaves (E2/E3/E4), so no extra evidence is demanded for nested series
                   config_overrides={"string_id": True, "dup_extra_gain": 0.0, "voice_gain": (0.0, 0.03, 0.03, 0.03, 0.03, 0.03, 0.03, 0.03),
                                     # ringing notes should survive short fit dropouts in dense chords
                                     "prior_persist_factor": 0.25, "unsupported_timeout_ms": 300.0, "release_hang_ms": 120.0,
                                     "attack_min_db": 8.0, "birth_hist_frames": 80, "pending_timeout_frames": 88})

    @classmethod
    def contrabass(cls):
        # orchestral double bass, bowed and plucked (E1 A1 D2 G2). minfreq 38 Hz (below the low E, room for tuning) with 6 periods gives the
        # 8192-sample window (186 ms). The maximum covers the artificial harmonics of the library (up to about 1.57 kHz).
        return cls(name="contrabass", open_string_hz=(41.20, 55.00, 73.42, 98.00), min_frequency_hz=38.0, max_frequency_hz=1600.0,
                   window_periods=6.0, excitation=MIXED,
                   # bowed and plucked: a weak attack requirement (3 dB) removes plucked ghosts and costs few bowed notes; a note at a multiple
                   # of a sounding one must persist, because bowed bass notes have strong upper partials that look like octave notes
                   config_overrides={"attack_min_db": 3.0, "birth_hist_frames": 80, "pending_timeout_frames": 88,
                                     "harmonic_confirm_frames": 14})

    # integer values of the Max `profile` attribute (new profiles are appended, so saved patches keep their meaning)
    ORDER = ("bass", "cello", "viola", "violin", "guitar", "contrabass")

    @classmethod
    def by_name(cls, name):
        return getattr(cls, name)()

    @classmethod
    def by_index(cls, i):
        return cls.by_name(cls.ORDER[i])


def nextpow2(x):
    return 1 << int(math.ceil(math.log2(max(x, 1))))


@dataclass
class Calibration:
    """What a calibration pass learns from isolated open-string notes (spec §12.3).

    B[i]            inharmonicity of open string i (partial h at h*f*sqrt(1+B*h^2)); only valid if captured[i]
    cents[i]        tuning offset of open string i from the profile's nominal pitch
    weights         harmonic weight profile averaged over the captured strings (h = 1..), in the compressed-amplitude
                    domain the fit uses, normalised so the first eight average 1. Empty = not learned.
    string_weights  the same profile per string (list of lists; [] where not learned). A pitch uses the profile of the
                    string it would be played on; the average is the fallback.
    """
    n_strings: int
    captured: list = field(default_factory=list)
    B: list = field(default_factory=list)
    cents: list = field(default_factory=list)
    weights: list = field(default_factory=list)
    string_weights: list = field(default_factory=list)
    logb: list = field(default_factory=list)      # log(B / f^2) of each open string by the long-window stiffness fit (-99 = not measured); for string identity

    VERSION = 2

    @classmethod
    def empty(cls, n_strings):
        return cls(n_strings, [False] * n_strings, [0.0] * n_strings, [0.0] * n_strings, [], [[] for _ in range(n_strings)], [-99.0] * n_strings)

    @property
    def has_logb(self):
        return sum(1 for v in self.logb if v > -98.0) >= 2

    @property
    def any_strings(self):
        return any(self.captured)

    def to_list(self):
        """Flat list of numbers (for a Max attribute / preset): version, n, [captured, B, cents]*n, n_weights, weights,
        then [n_string_weights, weights]*n."""
        out = [float(3 if self.has_logb else self.VERSION), float(self.n_strings)]
        for i in range(self.n_strings):
            out += [1.0 if self.captured[i] else 0.0, float(self.B[i]), float(self.cents[i])]
        out.append(float(len(self.weights)))
        out += [float(w) for w in self.weights]
        for i in range(self.n_strings):
            sw = self.string_weights[i] if i < len(self.string_weights) else []
            out.append(float(len(sw)))
            out += [float(w) for w in sw]
        if self.has_logb:
            out += [float(v) for v in self.logb]
        return out

    @classmethod
    def from_list(cls, v):
        v = list(v)
        if len(v) < 3 or int(v[0]) not in (1, 2, 3):
            return None
        n = int(v[1])
        if n < 1 or n > MAX_STRINGS or len(v) < 2 + 3 * n + 1:
            return None
        c = cls.empty(n)
        for i in range(n):
            c.captured[i] = v[2 + 3 * i] > 0.5
            c.B[i] = v[3 + 3 * i]
            c.cents[i] = v[4 + 3 * i]
        nw = int(v[2 + 3 * n])
        pos = 3 + 3 * n
        c.weights = [float(x) for x in v[pos: pos + nw]]
        pos += nw
        if int(v[0]) >= 2:
            for i in range(n):
                if pos >= len(v):
                    break
                m = int(v[pos])
                c.string_weights[i] = [float(x) for x in v[pos + 1: pos + 1 + m]]
                pos += 1 + m
        if int(v[0]) == 3 and len(v) >= pos + n:
            c.logb = [float(x) for x in v[pos: pos + n]]
        return c


@dataclass
class DetectorConfig:
    sample_rate: float = 48000.0
    profile: InstrumentProfile = field(default_factory=InstrumentProfile.cello)
    input_channel: int = 0
    calibration: object = None            # Calibration or None (profile defaults)

    long_fft_size: int = 0          # 0 = derive from profile (spec §2.1)
    short_fft_size: int = 2048
    hop_size: int = 256

    max_voices: int = 4
    max_candidates: int = 24
    max_harmonics: int = 12
    grid_step_cents: float = 5.0
    min_candidate_separation_cents: float = 25.0

    # DC blocker
    dc_cutoff_hz: float = 30.0

    # whitening / noise floor (spec §5.4)
    whiten_octave_fraction: float = 0.5   # envelope smoothing width, octaves
    whiten_min_width_hz: float = 0.0      # 0 = 3 * profile.min_frequency_hz
    whiten_clip: float = 2.5              # c, natural-log units
    noise_kappa: float = 4.0              # gate: bins below kappa*floor are down-weighted
    noise_down_tau_s: float = 0.2
    noise_up_tau_s: float = 10.0
    noise_init_median_bins: int = 41

    # salience (spec §6.2)
    peak_min_snr: float = 5.0             # peak must exceed this multiple of the tracked noise floor
    peak_min_w: float = 2.0               # minimum whitened peak height to be a peak
    peak_sigma_bins: float = 0.6          # kernel width at h=1, in bins (Hann mainlobe)
    vibrato_widen_cents: float = 0.0      # extra kernel width per harmonic, cents of f0
    inharm_tol_B: float = 0.0             # partial-match tolerance for string inharmonicity mismatch (B units)
    interleave_weight: float = 0.5        # penalty for energy midway between partials

    # polyphonic fit (spec §7). Costs are fractions of the spectral peak energy.
    fit_band_hz: float = 0.0              # fit and templates cover partials below this; 0 = max(4 kHz, 3 x max pitch)
    fit_max_harmonics: int = 64
    fit_weight_exponent: float = 0.0      # template weights h^-p in the fit; whitening flattens partial levels
    fit_compress: float = 0.5             # peak amplitudes enter the fit as (W_peak)^gamma
    first_voice_min_gain: float = 0.05    # explained fraction needed for any voice
    voice_gain: tuple = (0.0, 0.04, 0.04, 0.04, 0.04, 0.04, 0.04, 0.04)  # extra gain for the nth voice
    gain_relative: bool = False           # judge voice gains against the remaining residual, not total energy
    dup_extra_gain: float = 0.10          # extra gain needed for a voice harmonically related (x2,x3,..) to a chosen voice
    dup_tol_cents: float = 30.0
    # tracking (spec §8)
    confirm_min_conf: float = 0.3         # mean fit confidence required to confirm a new note
    rise_harmonics: int = 8               # partials used by the tonal re-attack test
    harmonic_confirm_frames: int = 0      # >0: a new note at an integer multiple of another live note must persist this long (off by default)
    harmonic_tol: float = 0.03            # relative tolerance for 'integer multiple' (covers inharmonic stretch)
    attack_min_db: float = 0.0            # >0: a new note must show a rise of at least this many dB in the short-window energy (plucked instruments)
    birth_hist_frames: int = 28           # history over which that attack is looked for (the fit lags a pluck by 60-90 ms)
    pending_timeout_frames: int = 36      # a pending note that never shows the attack is dropped after this long
    octave_hold_frames: int = 12          # frames an unsupported note is held when an octave/twelfth candidate appears without a re-attack
    confirm_frames: int = 6               # frames a new pitch must persist before note-on
    strong_confirm_frames: int = 4        # ... when a strong onset coincides
    onset_strong: float = 3.0             # normalised flux counted as a strong onset
    release_hang_ms: float = 50.0
    unsupported_timeout_ms: float = 100.0
    assoc_gate_semitones: float = 1.0     # sustained-track association gate
    assoc_gate_pending: float = 0.6
    string_id: bool = False               # identify the string of plucked notes (guitar profile; needs a calibration with string values)
    min_level_dbfs: float = -58.0         # absolute level gate on observed voices
    high_pitch_partials: int = 2          # pitches above the profile's normal range are modelled with this many partials (natural and artificial harmonics are near-pure tones)
    high_pitch_extra_gain: float = 0.20   # ... and must explain this much more of the spectrum than a normal note
    quiet_snr_db: float = 0.0             # >0: a voice below the level gate still counts if this far above the local noise floor ...
    quiet_floor_dbfs: float = -80.0       # ... and at least this loud
    prior_persist_factor: float = 0.5     # gain threshold multiplier near an active track's pitch
    retrigger_rise_db: float = 10.0       # per-track partial-energy rise (short window) that re-attacks a note
    onset_hist_frames: int = 14           # history used as the 'before' level for the rise
    retrigger_min_age_frames: int = 26
    tonal_rise_margin_db: float = 6.0
    min_voice_sep_cents: float = 70.0     # two voices closer than this are one pitch
    eta_sustain: float = 0.15
    eta_attack: float = 0.6
    refine_cents: float = 20.0            # +/- pitch refinement range
    refine_step_cents: float = 5.0
    max_fit_iterations: int = 8
    miss_threshold: float = 0.5           # W below this counts as an absent partial
    miss_weight: float = 0.5              # gamma

    # ---- calibration-aware model parameters ------------------------------------------------
    def string_freqs(self):
        """Open-string pitches in Hz, with any calibrated tuning offsets applied."""
        f = np.array(self.profile.open_string_hz, dtype=float)
        c = self.calibration
        if c is not None and c.n_strings == len(f):
            f = f * 2.0 ** (np.array(c.cents) * np.array(c.captured, float) / 1200.0)
        return f

    def _string_index(self, f):
        """For each pitch in f: index into the profile's strings of the highest open string at or below it
        (within 60 cents), or the lowest string if none; plus that string's pitch. Used for B and the weights."""
        f = np.asarray(f, dtype=float)
        fs = self.string_freqs()
        order = np.argsort(fs)
        fs_sorted = fs[order]
        k = np.clip(np.searchsorted(fs_sorted * 2.0 ** (-60.0 / 1200.0), f, side="right") - 1, 0, len(fs) - 1)
        return order[k], fs_sorted[k]

    def inharm_B(self, f):
        """Inharmonicity at fundamental(s) f. Without a string calibration: the profile's constant.
        With one: the B of the highest open string at or below f, scaled by (f / f_string)^2 because a
        fretted (shortened) string at the same tension has B proportional to 1/L^2, i.e. to f^2."""
        f = np.asarray(f, dtype=float)
        base = self.profile.inharmonicity_B
        c = self.calibration
        if c is None or not c.any_strings:
            return np.full(f.shape, base)
        idx, fstr = self._string_index(f)
        B_open = np.array([c.B[i] if c.captured[i] else base for i in range(len(self.profile.open_string_hz))])
        r = np.clip(f / fstr, 0.5, 8.0)
        return B_open[idx] * r ** 2

    def upper_max_hz(self):
        """Highest pitch searched: the normal range, or the harmonic tier above it."""
        return max(self.profile.max_frequency_hz, self.profile.harmonic_max_frequency_hz)

    def limit_high_partials(self, w, f):
        """Zero the weights of partials beyond `high_pitch_partials` for fundamentals above the normal range (in place; w is (..., H), f broadcasts over rows)."""
        if self.profile.harmonic_max_frequency_hz > self.profile.max_frequency_hz:
            hi = np.asarray(f) > self.profile.max_frequency_hz * (1.0 + 1e-9)
            if np.ndim(w) == 1:
                if hi:
                    w[self.high_pitch_partials:] = 0.0
            else:
                w[hi, self.high_pitch_partials:] = 0.0
        return w

    def partial_weights(self, n, default_exponent, f=None):
        """Harmonic weights for partials 1..n: the learned profile of the string a pitch would be played on, else the
        learned average, else h^-p. With f a scalar the result has shape (n,); with an array it has shape (len(f), n)."""
        h = np.arange(1, n + 1, dtype=float)
        c = self.calibration
        fa = None if f is None else np.atleast_1d(np.asarray(f, dtype=float))

        def extend(w):
            w = np.asarray(w, dtype=float)
            out = np.empty(n)
            m = len(w)
            out[: min(n, m)] = w[: min(n, m)]
            if n > m:
                out[m:] = w[-1] * m / h[m:]
            return out
        default = h ** (-default_exponent)
        glob = extend(c.weights) if (c is not None and len(c.weights) >= 3) else default
        if fa is None:
            return glob
        out = np.tile(glob, (len(fa), 1))
        if c is not None and any(len(sw) >= 6 for sw in c.string_weights):
            idx, _ = self._string_index(fa)
            for j, s in enumerate(idx):
                sw = c.string_weights[s] if s < len(c.string_weights) else []
                if len(sw) >= 6:
                    out[j] = extend(sw)
        return out[0] if np.isscalar(f) or np.ndim(f) == 0 else out

    def derived_fit_band(self):
        if self.fit_band_hz:
            return min(self.fit_band_hz, 0.45 * self.sample_rate)
        return min(max(4000.0, 3.0 * self.profile.max_frequency_hz), 0.45 * self.sample_rate)

    @classmethod
    def for_instrument(cls, name, sample_rate=48000.0, **overrides):
        """Config with the profile's voice count and any profile-specific tuning applied."""
        prof = InstrumentProfile.by_name(name) if isinstance(name, str) else name
        cfg = cls(sample_rate=sample_rate, profile=prof, max_voices=prof.default_voices)
        for k, v in prof.config_overrides.items():
            setattr(cfg, k, v)
        for k, v in overrides.items():
            setattr(cfg, k, v)
        return cfg

    def derived_long_fft(self):
        if self.long_fft_size:
            return self.long_fft_size
        p = self.profile
        return nextpow2(p.window_periods * self.sample_rate / p.min_frequency_hz)
