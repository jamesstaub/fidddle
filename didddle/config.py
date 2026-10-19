"""SeparatorConfig: every tunable of the separator in one place (cf. fidddle.profile.DetectorConfig)."""
from dataclasses import dataclass


@dataclass
class SeparatorConfig:
    sample_rate: float = 48000.0
    n_fft: int = 4096               # analysis window; must resolve partials of the lowest fundamental
    hop: int = 1024                 # n_fft / 4 gives constant overlap-add gain for Hann x Hann
    max_partials: int = 64          # partials modelled per voice
    band_frac: float = 0.45         # partials above band_frac * sample_rate are not modelled
    inharmonicity_B: float = 0.0    # partial h at h*f*sqrt(1 + B h^2), from the instrument profile

    # sinusoidal least-squares estimator
    kernel_radius: int = 4          # bins either side of a partial that its window kernel touches
    ridge: float = 1e-3             # Tikhonov weight, relative to the mean column energy
    cluster_gap_bins: float = 1.0   # partials of different voices closer than this are one unknown
    snap_bins: float = 0.0          # >0: isolated partials may move to the local spectral peak (<= this many bins)

    # comb-mask estimator (baseline)
    mask_sigma_bins: float = 1.0

    # time-domain shaping from note spans
    gate_fade_ms: float = 3.0       # voice gate opens over this long at the note start
    gate_release_ms: float = 10.0   # ... and closes this long after the note end
    transient_ms: float = 80.0      # attack handed to the starting voice; 0 = leave attacks in the residual
    onset_lead_ms: float = 40.0     # detector onset estimates run late: pass to f0.spans_from_run to open notes earlier

    method: str = "ls"              # "ls" | "mask"

    @property
    def df(self):
        return self.sample_rate / self.n_fft

    @property
    def band_hz(self):
        return self.band_frac * self.sample_rate

    @classmethod
    def from_profile(cls, profile, sample_rate=48000.0, **overrides):
        """Window sized for the profile's lowest fundamental: a partial pair f0 apart must be resolved
        (Hann main lobe is 4 bins wide), so n_fft >= 4 * fs / f_min, rounded up to a power of two."""
        n = 1 << int(math_ceil_log2(4.0 * sample_rate / profile.min_frequency_hz))
        cfg = cls(sample_rate=sample_rate, n_fft=n, hop=n // 4, inharmonicity_B=profile.inharmonicity_B)
        for k, v in overrides.items():
            setattr(cfg, k, v)
        return cfg


def math_ceil_log2(x):
    import math
    return math.ceil(math.log2(max(x, 1.0)))
