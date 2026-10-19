// InstrumentProfile and Config (spec §1.3, §12). Defaults mirror the Python reference
// (fidddle/profile.py); keep the two in sync.
#pragma once
#include <algorithm>
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
    int default_voices = 4;

    // Values of the Max `profile` attribute: bass, cello, viola, violin, guitar
    enum Id : int { Bass = 0, Cello = 1, Viola = 2, Violin = 3, Guitar = 4, Count = 5 };

    static InstrumentProfile bass() {
        // 5-string bass (B0 E1 A1 D2 G2); a 4-string bass simply leaves the B string uncalibrated. Six periods of 28 Hz need
        // a 16384-sample window (372 ms); a shorter one leaves the partials of the low B only ~5 bins apart and lets attack
        // ghosts through. A 4-string bass can raise minfreq (about 38 Hz) to get the 8192-sample window.
        InstrumentProfile p;
        p.name = "bass"; p.string_count = 5;
        p.open_string_hz = {{30.87, 41.20, 55.00, 73.42, 98.00, 0, 0, 0}};
        p.min_frequency_hz = 28.0; p.max_frequency_hz = 500.0; p.window_periods = 6.0; p.inharmonicity_B = 5e-5;
        return p;
    }
    static InstrumentProfile cello() { return InstrumentProfile{}; }
    static InstrumentProfile viola() {
        InstrumentProfile p;
        p.name = "viola"; p.string_count = 4;
        p.open_string_hz = {{130.81, 196.00, 293.66, 440.00, 0, 0, 0, 0}};
        p.min_frequency_hz = 120.0; p.max_frequency_hz = 1500.0;
        return p;
    }
    static InstrumentProfile violin() {
        InstrumentProfile p;
        p.name = "violin"; p.string_count = 4;
        p.open_string_hz = {{196.00, 293.66, 440.00, 659.26, 0, 0, 0, 0}};
        p.min_frequency_hz = 185.0; p.max_frequency_hz = 2800.0;
        return p;
    }
    static InstrumentProfile guitar() {
        InstrumentProfile p;
        p.name = "guitar"; p.string_count = 6;
        p.open_string_hz = {{82.41, 110.00, 146.83, 196.00, 246.94, 329.63, 0, 0}};
        p.min_frequency_hz = 70.0; p.max_frequency_hz = 1400.0; p.inharmonicity_B = 1e-4; p.default_voices = 6;
        return p;
    }
    static InstrumentProfile by_id(int id) {
        switch (id) {
            case Bass: return bass();
            case Viola: return viola();
            case Violin: return violin();
            case Guitar: return guitar();
            default: return cello();
        }
    }
};

// What a calibration pass learns from isolated open-string notes (spec §12.3). Plain data: copyable, no allocation.
struct Calibration {
    static constexpr int MAX_WEIGHTS = 24;
    static constexpr int LIST_CAP = 2 + 3 * MAX_STRINGS + 1 + MAX_WEIGHTS + MAX_STRINGS * (1 + MAX_WEIGHTS);   // flat-list capacity
    int n_strings = 0;
    bool captured[MAX_STRINGS] = {};
    double B[MAX_STRINGS] = {};          // inharmonicity of each open string
    double cents[MAX_STRINGS] = {};      // tuning offset of each open string
    int n_weights = 0;                   // harmonic weights averaged over the captured strings (0 = not learned)
    double weights[MAX_WEIGHTS] = {};
    int n_sw[MAX_STRINGS] = {};          // per-string harmonic weights (0 = not learned for that string)
    double sw[MAX_STRINGS][MAX_WEIGHTS] = {};

    bool any_strings() const {
        for (int i = 0; i < n_strings; ++i) if (captured[i]) return true;
        return false;
    }
    // Flat list for a Max attribute or preset: version, n, [captured B cents]*n, n_weights, weights..., [n_sw, sw...]*n
    int to_list(double* out) const {
        int k = 0;
        out[k++] = 2.0;
        out[k++] = n_strings;
        for (int i = 0; i < n_strings; ++i) { out[k++] = captured[i] ? 1.0 : 0.0; out[k++] = B[i]; out[k++] = cents[i]; }
        out[k++] = n_weights;
        for (int i = 0; i < n_weights; ++i) out[k++] = weights[i];
        for (int s = 0; s < n_strings; ++s) {
            out[k++] = n_sw[s];
            for (int i = 0; i < n_sw[s]; ++i) out[k++] = sw[s][i];
        }
        return k;
    }
    // Accepts version 1 (no per-string weights) and 2.
    static bool from_list(const double* v, int n, Calibration& c) {
        if (n < 3) return false;
        int ver = (int)v[0];
        if (ver != 1 && ver != 2) return false;
        int ns = (int)v[1];
        if (ns < 1 || ns > MAX_STRINGS || n < 2 + 3 * ns + 1) return false;
        c = Calibration{};
        c.n_strings = ns;
        for (int i = 0; i < ns; ++i) { c.captured[i] = v[2 + 3 * i] > 0.5; c.B[i] = v[3 + 3 * i]; c.cents[i] = v[4 + 3 * i]; }
        int pos = 2 + 3 * ns;
        int nw = std::min(std::max((int)v[pos], 0), MAX_WEIGHTS);
        nw = std::min(nw, n - (pos + 1));
        c.n_weights = std::max(nw, 0);
        for (int i = 0; i < c.n_weights; ++i) c.weights[i] = v[pos + 1 + i];
        pos += 1 + c.n_weights;
        if (ver == 2) {
            for (int s = 0; s < ns && pos < n; ++s) {
                int m = std::min(std::max((int)v[pos], 0), MAX_WEIGHTS);
                m = std::min(m, n - (pos + 1));
                c.n_sw[s] = std::max(m, 0);
                for (int i = 0; i < c.n_sw[s]; ++i) c.sw[s][i] = v[pos + 1 + i];
                pos += 1 + c.n_sw[s];
            }
        }
        return true;
    }
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
    double inharm_tol_B = 0.0;
    double interleave_weight = 0.5;
    double miss_threshold = 0.5;
    double miss_weight = 0.5;

    // polyphonic fit (§7)
    double fit_band_hz = 0.0;           // 0 = max(4 kHz, 3 x max pitch), capped at 0.45 fs
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
    int harmonic_confirm_frames = 0;    // >0: a new note at an integer multiple of another live note must persist this long
    double harmonic_tol = 0.03;
    int octave_hold_frames = 12;        // hold an unsupported note while an octave/twelfth candidate appears without a re-attack
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
    double attack_min_db = 0.0;         // >0: a new note must show a tonal attack of at least this many dB (plucked instruments)
    int birth_hist_frames = 28;         // history over which that attack is looked for (the fit lags a pluck by 60-90 ms)
    int pending_timeout_frames = 36;    // a pending note that never shows the attack is dropped after this long

    Calibration calibration;            // applies when calibration.any_strings() or learned weights exist
    bool use_calibration = false;

    // Open-string pitches with calibrated tuning offsets applied.
    void string_freqs(double* out) const {
        for (int i = 0; i < profile.string_count; ++i) {
            double f = profile.open_string_hz[i];
            if (use_calibration && i < calibration.n_strings && calibration.captured[i]) f *= std::pow(2.0, calibration.cents[i] / 1200.0);
            out[i] = f;
        }
    }

    // Index (into the profile's strings) of the highest open string at or below f (within 60 cents); the lowest if none.
    int string_index(double f, double* f_string = nullptr) const {
        int n = profile.string_count;
        double fs[MAX_STRINGS];
        string_freqs(fs);
        int ord[MAX_STRINGS];
        for (int i = 0; i < n; ++i) ord[i] = i;
        std::sort(ord, ord + n, [&](int a, int b) { return fs[a] < fs[b]; });
        double lim = std::pow(2.0, 60.0 / 1200.0);
        int k = 0;
        for (int j = 0; j < n; ++j) if (fs[ord[j]] <= f * lim) k = j;
        if (f_string) *f_string = fs[ord[k]];
        return ord[k];
    }

    // Inharmonicity at fundamental f: the profile's constant, or (calibrated) the B of the highest open string at or
    // below f, scaled by (f / f_string)^2 because a fretted string at the same tension has B proportional to f^2.
    double inharm_B(double f) const {
        double base = profile.inharmonicity_B;
        if (!use_calibration || !calibration.any_strings()) return base;
        double fstr;
        int s = string_index(f, &fstr);
        double Bo = (s < calibration.n_strings && calibration.captured[s]) ? calibration.B[s] : base;
        double r = std::clamp(f / fstr, 0.5, 8.0);
        return Bo * r * r;
    }

    // Weights for partials 1..n of a note at pitch f: the learned profile of the string it would be played on, else
    // the learned average, else h^-exponent.
    void partial_weights(int n, double exponent, double f, double* out) const {
        const double* src = nullptr;
        int m = 0;
        if (use_calibration) {
            int s = string_index(f);
            if (s < calibration.n_strings && calibration.n_sw[s] >= 6) { src = calibration.sw[s]; m = calibration.n_sw[s]; }
            else if (calibration.n_weights >= 3) { src = calibration.weights; m = calibration.n_weights; }
        }
        for (int h = 1; h <= n; ++h)
            out[h - 1] = !src ? std::pow((double)h, -exponent) : (h <= m ? src[h - 1] : src[m - 1] * m / (double)h);
    }

    double derived_fit_band() const {
        if (fit_band_hz > 0) return std::min(fit_band_hz, 0.45 * sample_rate);
        return std::min(std::max(4000.0, 3.0 * profile.max_frequency_hz), 0.45 * sample_rate);
    }

    // Config for a stock instrument: profile, its default voice count and any instrument-specific tuning.
    static Config for_instrument(int profile_id, double sample_rate) {
        Config c;
        c.sample_rate = sample_rate;
        c.profile = InstrumentProfile::by_id(profile_id);
        c.max_voices = c.profile.default_voices;
        if (profile_id == InstrumentProfile::Bass || profile_id == InstrumentProfile::Guitar) {
            // plucked: every real note starts with an attack, so a voice that appears in a decaying ring without one (sympathetic
            // resonance, a ghost octave under a ringing string) is not a note. The fit finds a new note up to a few hundred ms
            // after the pluck, hence the long look-back.
            c.attack_min_db = 8.0;
            c.birth_hist_frames = 80;
            c.pending_timeout_frames = 88;
        }
        if (profile_id == InstrumentProfile::Bass) {
            // nearly monophonic: a harmonic of a sounding note needs to persist before it counts as a note
            c.harmonic_confirm_frames = 14;
        }
        if (profile_id == InstrumentProfile::Guitar) {
            // chords stack octaves (E2/E3/E4): no extra evidence for nested series
            c.dup_extra_gain = 0.0;
            c.voice_gain = {{0.0, 0.03, 0.03, 0.03, 0.03, 0.03, 0.03, 0.03}};
            // ringing notes should survive short fit dropouts in dense chords
            c.prior_persist_factor = 0.25;
            c.unsupported_timeout_ms = 300.0;
            c.release_hang_ms = 120.0;
        }
        return c;
    }

    int derived_long_fft() const {
        if (long_fft_size) return long_fft_size;
        double x = profile.window_periods * sample_rate / profile.min_frequency_hz;
        int n = 1;
        while (n < x) n <<= 1;
        return n;
    }
};

}  // namespace fidddle
