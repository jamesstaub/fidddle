// Windowing helpers, whitening / noise floor, peak picking, onset flux (spec §5).
#pragma once
#include <vector>
#include "fidddle/config.hpp"
#include "fft.hpp"

namespace fidddle {

constexpr double EPS = 1e-9;

std::vector<double> hann(int n);

// Moving-average envelope of log-magnitude with a frequency-scaled width, plus the noise floor.
class Whitener {
public:
    Whitener(const Config& cfg, int n_fft);
    void envelope(const double* L, double* E);          // prefix-sum moving average
    // M: magnitude. Fills W (whitened, gated), E (log envelope), unclipped, snr.
    void process(const double* M);
    int nbins() const { return nbins_; }

    std::vector<double> W, E, unclipped, snr;

private:
    void update_noise(const double* M);
    const Config& cfg_;
    int nbins_;
    std::vector<int> lo_, hi_;
    std::vector<double> noise_, L_, cum_, padded_, med_;
    bool noise_init_ = false;
    double a_down_, a_up_;
};

struct Peaks {
    std::vector<double> freq, amp;   // sorted by frequency
    std::vector<int> k_;             // scratch (kept here so no allocation happens after construction)
    std::vector<char> drop_;
    void clear() { freq.clear(); amp.clear(); }
};

// Local maxima of M gated by W / SNR; sub-bin frequency from the log-|M| parabola.
void spectral_peaks(const double* M, const double* W, const double* amp, const double* snr, int nbins, double df,
                    double min_w, double min_snr, Peaks& out, int sidelobe_bins = 3, double sidelobe_ratio = 3.0);

// Short-window whitened flux, baseline-normalised.
class OnsetFlux {
public:
    explicit OnsetFlux(const Config& cfg);
    double process(const double* short_frame);   // returns normalised flux; last_M holds |X|
    std::vector<double> last_M;
private:
    const Config& cfg_;
    int n_, nbins_;
    std::vector<double> win_, frame_, re_, im_, L_, E_, W_, prev_;
    RealFFT fft_;
    Whitener w_;
    bool have_prev_ = false;
    double baseline_ = 1e-3, beta_ = 0.02;
};

}  // namespace fidddle
