#include "spectral.hpp"
#include <algorithm>
#include <cmath>

namespace fidddle {

std::vector<double> hann(int n) {
    std::vector<double> w(n);
    for (int i = 0; i < n; ++i) w[i] = 0.5 - 0.5 * std::cos(2.0 * M_PI * i / n);
    return w;
}

Whitener::Whitener(const Config& cfg, int n_fft) : cfg_(cfg), nbins_(n_fft / 2 + 1) {
    double fs = cfg.sample_rate;
    double df = fs / n_fft;
    // Nothing above the fit band is read. The margin keeps the envelope (about +-20% in frequency) and the 41-bin median of every bin
    // inside the band exactly as they would be over the whole spectrum.
    nuse_ = std::min(nbins_, (int)std::ceil(1.4 * cfg.derived_fit_band() / df) + 64);
    double min_w = cfg.whiten_min_width_hz > 0 ? cfg.whiten_min_width_hz : 3.0 * cfg.profile.min_frequency_hz;
    double span = std::pow(2.0, cfg.whiten_octave_fraction / 2) - std::pow(2.0, -cfg.whiten_octave_fraction / 2);
    lo_.resize(nbins_);
    hi_.resize(nbins_);
    for (int k = 0; k < nbins_; ++k) {
        double f = k * df;
        double half = 0.5 * std::max(f * span, min_w);
        double hb = half / df;
        lo_[k] = std::clamp((int)std::floor(k - hb), 0, nbins_ - 1);
        hi_[k] = std::clamp((int)std::ceil(k + hb) + 1, 1, nbins_);
    }
    double hop_s = cfg.hop_size / fs;
    a_down_ = 1.0 - std::exp(-hop_s / cfg.noise_down_tau_s);
    a_up_ = 1.0 - std::exp(-hop_s / cfg.noise_up_tau_s);
    W.resize(nbins_); E.resize(nbins_); unclipped.resize(nbins_); snr.resize(nbins_);
    noise_.resize(nbins_); L_.resize(nbins_); cum_.resize(nbins_ + 1);
    med_.resize(nbins_);
    padded_.resize(nbins_ + cfg.noise_median_bins);
}

void Whitener::envelope(const double* L, double* Eout, int n) {
    if (n < 0) n = nbins_;
    cum_[0] = 0.0;
    for (int k = 0; k < n; ++k) cum_[k + 1] = cum_[k] + L[k];
    for (int k = 0; k < n; ++k) { int hi = std::min(hi_[k], n); Eout[k] = (cum_[hi] - cum_[lo_[k]]) / (hi - lo_[k]); }
}

void Whitener::update_noise(const double* M, int nb) {
    // median over `noise_median_bins` neighbouring bins, edge-replicated (scipy mode="nearest")
    int w = cfg_.noise_median_bins, half = w / 2;
    for (int i = 0; i < half; ++i) padded_[i] = M[0];
    for (int k = 0; k < nb; ++k) padded_[half + k] = M[k];
    for (int i = 0; i < half; ++i) padded_[half + nb + i] = M[nb - 1];
    double win[64];
    for (int i = 0; i < w; ++i) win[i] = padded_[i];
    std::sort(win, win + w);
    for (int k = 0; k < nb; ++k) {
        med_[k] = win[half];
        if (k + 1 < nb) {
            double out = padded_[k], in = padded_[k + w];
            if (out != in) {
                double* p = std::lower_bound(win, win + w, out);
                // remove `out`, insert `in`, keep sorted
                if (in > out) {
                    double* q = p;
                    while (q + 1 < win + w && *(q + 1) < in) { *q = *(q + 1); ++q; }
                    *q = in;
                } else {
                    double* q = p;
                    while (q > win && *(q - 1) > in) { *q = *(q - 1); --q; }
                    *q = in;
                }
            }
        }
    }
    if (!noise_init_) {
        for (int k = 0; k < nb; ++k) noise_[k] = med_[k];
        noise_init_ = true;
        return;
    }
    for (int k = 0; k < nb; ++k) {
        double a = med_[k] < noise_[k] ? a_down_ : a_up_;
        noise_[k] += a * (med_[k] - noise_[k]);
    }
}

void Whitener::process(const double* M) {
    const int nb = nuse_;
    for (int k = 0; k < nb; ++k) L_[k] = std::log(M[k] + EPS);
    envelope(L_.data(), E.data(), nb);
    update_noise(M, nb);
    // W = exp(clamp(L - E)) * gate. exp(L - E) is (M + EPS) / exp(E), so one exp per bin serves W and `unclipped`; the clamp ends
    // are constants. The gate is 0 below the noise and 1 above kappa times the noise: the log is needed only in between.
    const double kappa = cfg_.noise_kappa, lk = std::log(kappa), c = cfg_.whiten_clip;
    const double exp_c = std::exp(c), exp_mc = std::exp(-c);
    for (int k = 0; k < nb; ++k) {
        const double ex = std::exp(E[k]);
        const double d = L_[k] - E[k];
        const double ew = d > c ? exp_c : (d < -c ? exp_mc : (M[k] + EPS) / ex);
        const double ratio = (M[k] + EPS) / (noise_[k] + EPS);
        const double gate = ratio <= 1.0 ? 0.0 : (ratio >= kappa ? 1.0 : std::min(std::log(ratio) / lk, 1.0));
        W[k] = ew * gate;
        unclipped[k] = M[k] / ex;
        snr[k] = M[k] / (noise_[k] + EPS);
    }
}

void spectral_peaks(const double* M, const double* W, const double* amp, const double* snr, int nbins, double df,
                    double min_w, double min_snr, Peaks& out, int sidelobe_bins, double sidelobe_ratio) {
    out.clear();
    std::vector<int>& k = out.k_;
    std::vector<char>& drop = out.drop_;
    k.clear();
    for (int i = 1; i < nbins - 1; ++i)
        if (M[i] > M[i - 1] && M[i] >= M[i + 1] && W[i] > min_w && snr[i] >= min_snr) k.push_back(i);
    if (k.empty()) return;
    if (sidelobe_bins > 0 && k.size() > 1) {
        drop.assign(k.size(), 0);
        for (size_t j = 1; j < k.size(); ++j) {
            if (k[j] - k[j - 1] <= sidelobe_bins) {
                double m0 = M[k[j - 1]], m1 = M[k[j]];
                if (m0 >= sidelobe_ratio * m1) drop[j] = 1;
                if (m1 >= sidelobe_ratio * m0) drop[j - 1] = 1;
            }
        }
        size_t w = 0;
        for (size_t j = 0; j < k.size(); ++j) if (!drop[j]) k[w++] = k[j];
        k.resize(w);
        if (k.empty()) return;
    }
    for (int i : k) {
        double lm = std::log(M[i - 1] + EPS), l0 = std::log(M[i] + EPS), lp = std::log(M[i + 1] + EPS);
        double den = lm - 2 * l0 + lp;
        double d = den < -1e-12 ? 0.5 * (lm - lp) / den : 0.0;
        d = std::clamp(d, -0.5, 0.5);
        out.freq.push_back((i + d) * df);
        out.amp.push_back(amp[i]);
    }
}

OnsetFlux::OnsetFlux(const Config& cfg)
    : cfg_(cfg), n_(cfg.short_fft_size), nbins_(cfg.short_fft_size / 2 + 1), win_(hann(cfg.short_fft_size)),
      frame_(cfg.short_fft_size), re_(nbins_), im_(nbins_), L_(nbins_), E_(nbins_), W_(nbins_), prev_(nbins_),
      fft_(cfg.short_fft_size), w_(cfg, cfg.short_fft_size) {
    last_M.resize(nbins_);
}

double OnsetFlux::process(const double* x) {
    for (int i = 0; i < n_; ++i) frame_[i] = x[i] * win_[i];
    fft_.forward(frame_.data(), re_.data(), im_.data());
    for (int k = 0; k < nbins_; ++k) {
        last_M[k] = std::sqrt(re_[k] * re_[k] + im_[k] * im_[k]);
        L_[k] = std::log(last_M[k] + EPS);
    }
    w_.envelope(L_.data(), E_.data());
    double c = cfg_.whiten_clip, F = 0.0;
    for (int k = 0; k < nbins_; ++k) {
        W_[k] = std::exp(std::clamp(L_[k] - E_[k], -c, c));
        if (have_prev_) F += std::max(0.0, W_[k] - prev_[k]);
    }
    prev_ = W_;
    have_prev_ = true;
    baseline_ += beta_ * (F - baseline_);
    return F / (baseline_ + 1e-6);
}

}  // namespace fidddle
