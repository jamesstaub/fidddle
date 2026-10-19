// InstrumentProfile and Config (spec §1.3, §12). Defaults mirror the Python reference
// (fidddle/profile.py); keep the two in sync.
#pragma once
#include <array>
#include <cmath>
#include <cstdint>

namespace fidddle {

constexpr int MAX_VOICES = 8;   // compile-time capacity
constexpr int MAX_STRINGS = 8;

enum class StringConstraint : uint8_t { Off, Soft, Hard };

struct InstrumentProfile {
    const char* name = "cello";
    int string_count = 4;
    std::array<double, MAX_STRINGS> open_string_hz{{65.41, 98.00, 146.83, 220.00, 0, 0, 0, 0}};
    double min_frequency_hz = 60.0;
    double max_frequency_hz = 1000.0;
    double window_periods = 10.0;
    double inharmonicity_B = 0.0;
    double harmonic_weight_exponent = 0.5;
    StringConstraint string_constraint = StringConstraint::Soft;

    static InstrumentProfile cello() { return InstrumentProfile{}; }
};

struct Config {
    double sample_rate = 48000.0;
    InstrumentProfile profile = InstrumentProfile::cello();

    int long_fft_size = 0;    // 0 = derive from profile (spec §2.1)
    int short_fft_size = 2048;
    int hop_size = 256;

    int max_voices = 4;       // <= MAX_VOICES
    int max_candidates = 24;
    int max_harmonics = 12;
    double grid_step_cents = 5.0;
    double min_candidate_separation_cents = 25.0;

    double dc_cutoff_hz = 30.0;

    // whitening / noise floor (§5.4)
    double whiten_octave_fraction = 0.5;
    double whiten_min_width_hz = 0.0;   // 0 = 3 * profile.min_frequency_hz
    double whiten_clip = 2.5;
    double noise_kappa = 4.0;
    double noise_down_tau_s = 0.2;
    double noise_up_tau_s = 10.0;
    int noise_median_bins = 41;

    // salience (§6.2)
    double peak_min_snr = 5.0;
    double peak_min_w = 2.0;
    double peak_sigma_bins = 0.6;
    double vibrato_widen_cents = 0.0;
    double interleave_weight = 0.5;
    double miss_threshold = 0.5;
    double miss_weight = 0.5;

    // polyphonic fit (§7)
    double fit_band_hz = 4000.0;
    int fit_max_harmonics = 64;
    double fit_weight_exponent = 0.0;
    double fit_compress = 0.5;
    double first_voice_min_gain = 0.05;
    std::array<double, MAX_VOICES> voice_gain{{0.0, 0.04, 0.04, 0.04, 0.04, 0.04, 0.04, 0.04}};
    bool gain_relative = false;
    double dup_extra_gain = 0.10;
    double dup_tol_cents = 30.0;
    double min_voice_sep_cents = 70.0;
    double refine_cents = 20.0;
    double refine_step_cents = 5.0;
    int max_fit_iterations = 8;
    double prior_persist_factor = 0.5;

    // tracking (§8)
    double confirm_min_conf = 0.3;
    int rise_harmonics = 8;
    int confirm_frames = 6;
    int strong_confirm_frames = 4;
    double onset_strong = 3.0;
    double release_hang_ms = 50.0;
    double unsupported_timeout_ms = 100.0;
    double assoc_gate_semitones = 1.0;
    double assoc_gate_pending = 0.6;
    double min_level_dbfs = -58.0;
    double retrigger_rise_db = 10.0;
    int onset_hist_frames = 14;
    int retrigger_min_age_frames = 26;
    double tonal_rise_margin_db = 6.0;
    double eta_sustain = 0.15;
    double eta_attack = 0.6;

    int derived_long_fft() const {
        if (long_fft_size) return long_fft_size;
        double x = profile.window_periods * sample_rate / profile.min_frequency_hz;
        int n = 1;
        while (n < x) n <<= 1;
        return n;
    }
};

}  // namespace fidddle
