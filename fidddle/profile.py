"""InstrumentProfile and DetectorConfig (spec §1.3, §12).

All instrument-specific numbers live in the profile; the algorithm never
mentions a particular instrument.
"""
from dataclasses import dataclass, field
import math

BOWED, PLUCKED, MIXED = "bowed", "plucked", "mixed"
OFF, SOFT, HARD = "off", "soft", "hard"
MAX_VOICES = 8


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

    @property
    def string_count(self):
        return len(self.open_string_hz)

    @classmethod
    def cello(cls):
        return cls(name="cello", open_string_hz=(65.41, 98.00, 146.83, 220.00),
                   min_frequency_hz=60.0, max_frequency_hz=1000.0)

    @classmethod
    def bass(cls):
        # 4-string double bass / bass guitar. A shorter window (6 periods) keeps latency near 190 ms
        # at the cost of low-register frequency resolution.
        return cls(name="bass", open_string_hz=(41.20, 55.00, 73.42, 98.00),
                   min_frequency_hz=35.0, max_frequency_hz=500.0, window_periods=6.0, inharmonicity_B=5e-5)

    @classmethod
    def viola(cls):
        return cls(name="viola", open_string_hz=(130.81, 196.00, 293.66, 440.00),
                   min_frequency_hz=120.0, max_frequency_hz=1500.0)

    @classmethod
    def violin(cls):
        return cls(name="violin", open_string_hz=(196.00, 293.66, 440.00, 659.26),
                   min_frequency_hz=185.0, max_frequency_hz=2800.0)

    @classmethod
    def guitar(cls):
        return cls(name="guitar", open_string_hz=(82.41, 110.00, 146.83, 196.00, 246.94, 329.63),
                   min_frequency_hz=70.0, max_frequency_hz=1400.0, inharmonicity_B=1e-4, default_voices=6,
                   # chords stack octaves (E2/E3/E4), so no extra evidence is demanded for nested series
                   config_overrides={"dup_extra_gain": 0.0, "voice_gain": (0.0, 0.03, 0.03, 0.03, 0.03, 0.03, 0.03, 0.03),
                                     # ringing notes should survive short fit dropouts in dense chords
                                     "prior_persist_factor": 0.25, "unsupported_timeout_ms": 300.0, "release_hang_ms": 120.0})

    # integer values of the Max `profile` attribute
    ORDER = ("bass", "cello", "viola", "violin", "guitar")

    @classmethod
    def by_name(cls, name):
        return getattr(cls, name)()

    @classmethod
    def by_index(cls, i):
        return cls.by_name(cls.ORDER[i])


def nextpow2(x):
    return 1 << int(math.ceil(math.log2(max(x, 1))))


@dataclass
class DetectorConfig:
    sample_rate: float = 48000.0
    profile: InstrumentProfile = field(default_factory=InstrumentProfile.cello)
    input_channel: int = 0

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
    confirm_frames: int = 6               # frames a new pitch must persist before note-on
    strong_confirm_frames: int = 4        # ... when a strong onset coincides
    onset_strong: float = 3.0             # normalised flux counted as a strong onset
    release_hang_ms: float = 50.0
    unsupported_timeout_ms: float = 100.0
    assoc_gate_semitones: float = 1.0     # sustained-track association gate
    assoc_gate_pending: float = 0.6
    min_level_dbfs: float = -58.0         # absolute level gate on observed voices
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
