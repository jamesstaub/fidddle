#include "salience.hpp"
#include <algorithm>
#include <cmath>
#include <numeric>

namespace fidddle {

SalienceMap::SalienceMap(const Config& cfg, int n_fft) : cfg_(cfg), K_(cfg.max_harmonics) {
    const auto& p = cfg.profile;
    double fs = cfg.sample_rate;
    df = fs / n_fft;
    double step = cfg.grid_step_cents / 100.0;
    double m0 = hz_to_midi(p.min_frequency_hz), m1 = hz_to_midi(cfg.upper_max_hz());
    int G = (int)std::ceil((m1 + 1e-9 - m0) / step);   // numpy.arange length
    midi.resize(G); f.resize(G);
    for (int g = 0; g < G; ++g) { midi[g] = m0 + g * step; f[g] = midi_to_hz(midi[g]); }
    pf_.resize((size_t)G * K_); valid_.resize((size_t)G * K_); w_.resize((size_t)G * K_);
    mf_.resize((size_t)G * (K_ - 1)); mvalid_.resize((size_t)G * (K_ - 1)); wm_.resize((size_t)G * (K_ - 1));
    wsum_.assign(G, 0.0); wmsum_.assign(G, 0.0);
    std::vector<double> hw(K_);
    const double band = std::min(0.45 * fs, cfg.derived_fit_band());      // partials above the fit band are not probed (the fit cannot use them either)
    for (int g = 0; g < G; ++g) {
        cfg.partial_weights(K_, p.harmonic_weight_exponent, f[g], hw.data());     // per-string profile when calibrated
        cfg.limit_high_partials(hw.data(), K_, f[g]);
        const double Bg = cfg.inharm_B(f[g]);
        for (int h = 1; h <= K_; ++h) {
            size_t i = (size_t)g * K_ + (h - 1);
            double stretch = std::sqrt(1.0 + Bg * h * h);
            pf_[i] = f[g] * h * stretch;
            valid_[i] = pf_[i] < band;
            double w = hw[h - 1];
            w_[i] = valid_[i] ? w : 0.0;
            wsum_[g] += w_[i];
            if (h < K_) {
                size_t j = (size_t)g * (K_ - 1) + (h - 1);
                mf_[j] = f[g] * (h + 0.5);
                mvalid_[j] = mf_[j] < band;
                wm_[j] = mvalid_[j] ? w : 0.0;
                wmsum_[g] += wm_[j];
            }
        }
        wmsum_[g] = std::max(wmsum_[g], 1e-9);
    }
    sig_.resize(pf_.size()); msig_.resize(mf_.size());
    for (int g = 0; g < G; ++g) {
        for (int h = 1; h <= K_; ++h) {
            double P = pf_[(size_t)g * K_ + (h - 1)];
            sig_[(size_t)g * K_ + (h - 1)] = df * cfg_.peak_sigma_bins + P * (cfg_.vibrato_widen_cents / 1200.0) * std::log(2.0) + P * 0.5 * cfg_.inharm_tol_B * h * h;
        }
        for (int h = 1; h < K_; ++h) {
            double P = mf_[(size_t)g * (K_ - 1) + (h - 1)];
            msig_[(size_t)g * (K_ - 1) + (h - 1)] = df * cfg_.peak_sigma_bins + P * (cfg_.vibrato_widen_cents / 1200.0) * std::log(2.0) + P * 0.5 * cfg_.inharm_tol_B * h * h;
        }
    }
    ptr_.assign(K_, 0); mptr_.assign(K_, 0);
    S.resize(G); hit.resize(G); miss.resize(G); inter.resize(G);
    order_.resize(G); taken_.resize(G);
}

// Evidence for a partial at P: the strongest of the two peaks around P, weighted by a Gaussian of the frequency error.
// `cursor` is where the previous probe of this column ended; the search starts there, so the cost is small when probes rise.
double SalienceMap::support_at(double P, double sigma, const Peaks& pk, size_t& cursor) const {
    size_t n = pk.freq.size();
    if (n == 0) return 0.0;
    const double* fr = pk.freq.data();
    size_t i = cursor < n ? cursor : n;
    while (i < n && fr[i] < P) ++i;            // first peak with frequency >= P (what lower_bound returns)
    while (i > 0 && fr[i - 1] >= P) --i;
    cursor = i;
    size_t hi = n > 1 ? std::clamp<size_t>(i, 1, n - 1) : 0;
    size_t lo = n > 1 ? hi - 1 : 0;
    double best = 0.0;
    for (size_t j : {lo, hi}) {
        double d = fr[j] - P;
        if (d >= CUT * sigma || -d >= CUT * sigma) continue;
        double z = d / sigma;
        best = std::max(best, pk.amp[j] * std::exp(-0.5 * z * z));
    }
    return best;
}

void SalienceMap::compute(const Peaks& pk) {
    int G = grid_size();
    std::fill(ptr_.begin(), ptr_.end(), 0);
    std::fill(mptr_.begin(), mptr_.end(), 0);
    for (int g = 0; g < G; ++g) {
        double h_ = 0, m_ = 0, i_ = 0;
        for (int h = 0; h < K_; ++h) {
            size_t i = (size_t)g * K_ + h;
            if (w_[i] == 0.0) continue;
            double Q = support_at(pf_[i], sig_[i], pk, ptr_[h]);
            h_ += w_[i] * Q;
            m_ += w_[i] * std::max(0.0, cfg_.miss_threshold - Q);
        }
        for (int h = 0; h < K_ - 1; ++h) {
            size_t j = (size_t)g * (K_ - 1) + h;
            if (wm_[j] == 0.0) continue;
            i_ += wm_[j] * support_at(mf_[j], msig_[j], pk, mptr_[h]);
        }
        hit[g] = h_ / wsum_[g];
        miss[g] = m_ / wsum_[g];
        inter[g] = i_ / wmsum_[g];
        S[g] = hit[g] - cfg_.miss_weight * miss[g] - cfg_.interleave_weight * inter[g];
    }
}

void pick_candidates(const SalienceMap& sm, const Config& cfg, const double* forced, int n_forced, std::vector<Candidate>& out) {
    out.clear();
    int n = sm.grid_size();
    // Python: sep = int(round(25/5)); round-half-even
    int sep = (int)std::nearbyint(cfg.min_candidate_separation_cents / cfg.grid_step_cents);
    std::vector<int>& order = sm.order_;
    std::vector<char>& taken = sm.taken_;
    std::iota(order.begin(), order.end(), 0);
    // descending salience; index tie-break == stable order, and std::sort does not allocate
    auto by_salience = [&](int a, int b) { return sm.S[a] > sm.S[b] || (sm.S[a] == sm.S[b] && a < b); };
    // The loop below stops after max_candidates picks, which are almost always among the best few dozen pitches: order only those
    // first, and the rest only if the loop gets that far (same order as a full sort, so the same candidates).
    const int head = std::min(n, 96);
    std::partial_sort(order.begin(), order.begin() + head, order.end(), by_salience);
    taken.assign(n, 0);
    for (int idx = 0; idx < n; ++idx) {
        if (idx == head && head < n) std::sort(order.begin() + head, order.end(), by_salience);
        int i = order[idx];
        if ((int)out.size() >= cfg.max_candidates || sm.S[i] <= 0) break;
        bool blocked = false;
        for (int k = std::max(0, i - sep); k < std::min(n, i + sep + 1); ++k) if (taken[k]) { blocked = true; break; }
        if (blocked) continue;
        taken[i] = 1;
        double d = 0.0;
        if (i > 0 && i < n - 1) {
            double den = sm.S[i - 1] - 2 * sm.S[i] + sm.S[i + 1];
            if (den < -1e-12) d = std::clamp(0.5 * (sm.S[i - 1] - sm.S[i + 1]) / den, -0.5, 0.5);
        }
        double m = sm.midi[i] + d * (cfg.grid_step_cents / 100.0);
        out.push_back({midi_to_hz(m), m, sm.S[i], sm.hit[i], sm.miss[i], sm.inter[i]});
    }
    for (int q = 0; q < n_forced; ++q) {
        double fm = forced[q];
        bool near = false;
        for (auto& c : out) if (std::fabs(c.midi - fm) < cfg.min_candidate_separation_cents / 100.0) { near = true; break; }
        if (near) continue;
        int bi = 0;
        double bd = 1e300;
        for (int g = 0; g < n; ++g) { double dd = std::fabs(sm.midi[g] - fm); if (dd < bd) { bd = dd; bi = g; } }
        out.push_back({midi_to_hz(fm), fm, sm.S[bi], sm.hit[bi], sm.miss[bi], sm.inter[bi]});
    }
}

}  // namespace fidddle
