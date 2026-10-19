// didddle configuration (mirrors didddle/config.py; keep the two in sync). Instrument-specific numbers come from the
// fidddle InstrumentProfile, so a profile added there is separable here without further work.
#pragma once
#include <algorithm>
#include <cmath>
#include "fidddle/config.hpp"

namespace didddle {

using fidddle::MAX_VOICES;

struct Config {
    double sample_rate = 48000.0;
    fidddle::InstrumentProfile profile;
    int max_voices = 4;              // output slots (<= MAX_VOICES); must match the detector's slot count

    int fft_size = 0;                // analysis window; 0 = derive: a partial pair f_min apart must be resolved
    int hop = 0;                     // 0 = fft_size / 4 (constant overlap-add gain for Hann x Hann)
    int grid = 256;                  // the detector's hop: latency and frame times are multiples of it
    double latency_ms = 0.0;         // total output delay; 0 = as fast as the window allows (fft_size)

    int max_partials = 64;
    double band_frac = 0.45;         // partials above band_frac * sample_rate are not modelled
    int kernel_radius = 4;           // bins either side of a partial that its window kernel touches
    double ridge = 1e-3;             // Tikhonov weight, relative to the mean column energy
    double cluster_gap_bins = 1.0;   // partials of different voices closer than this share one unknown

    // time-domain shaping from detector note spans
    double gate_fade_ms = 3.0;       // a voice gate opens over this long at the note start
    double gate_release_ms = 10.0;   // ... and closes this long after the note end
    double transient_ms = 80.0;      // attack handed to the starting voice; 0 = attacks stay in the residual
    double onset_lead_ms = 40.0;     // detector onsets run late: open notes this much earlier (never before known)

    int derived_fft() const {
        if (fft_size) return fft_size;
        double x = 4.0 * sample_rate / profile.min_frequency_hz;
        int n = 1;
        while (n < x) n <<= 1;
        return std::max(n, 512);
    }
    int derived_hop() const {
        int h = hop ? hop : derived_fft() / 4;
        return std::max(grid, (h + grid - 1) / grid * grid);     // frame times must land on detector boundaries
    }
    // Output delay in samples: at least one window (N/2 for the frame's audio plus N/2 of pitch lookahead), rounded
    // up to the detector grid so every frame falls due exactly when the detector delivers a frame.
    int latency_samples() const {
        int n = derived_fft();
        int want = (int)std::ceil(latency_ms * 1e-3 * sample_rate);
        return n + (std::max(want, n) - n + grid - 1) / grid * grid;
    }
    double latency_seconds() const { return latency_samples() / sample_rate; }
    double band_hz() const { return band_frac * sample_rate; }
    int ms(double v) const { return (int)std::lround(v * 1e-3 * sample_rate); }
};

}  // namespace didddle
