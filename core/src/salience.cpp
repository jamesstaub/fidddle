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
    double m0 = hz_to_midi(p.min_frequency_hz), m1 = hz_to_midi(p.max_frequency_hz);
    int G = (int)std::ceil((m1 + 1e-9 - m0) / step);   // numpy.arange length
    midi.resize(G); f.resize(G);
    for (int g = 0; g < G; ++g) { midi[g] = m0 + g * step; f[g] = midi_to_hz(midi[g]); }
    pf_.resize((size_t)G * K_); valid_.resize((size_t)G * K_); w_.resize((size_t)G * K_);
    mf_.resize((size_t)G * (K_ - 1)); mvalid_.resize((size_t)G * (K_ - 1)); wm_.resize((size_t)G * (K_ - 1));
    wsum_.assign(G, 0.0); wmsum_.assign(G, 0.0);
    std::vector<double> hw(K_);
    for (int g = 0; g < G; ++g) {
        cfg.partial_weights(K_, p.harmonic_weight_exponent, f[g], hw.data());     // per-string profile when calibrated
        const double Bg = cfg.inharm_B(f[g]);
        for (int h = 1; h <= K_; ++h) {
            size_t i = (size_t)g * K_ + (h - 1);
            double stretch = std::sqrt(1.0 + Bg * h * h);
            pf_[i] = f[g] * h * stretch;
            valid_[i] = pf_[i] < 0.45 * fs;
            double w = hw[h - 1];
            w_[i] = valid_[i] ? w : 0.0;
            wsum_[g] += w_[i];
            if (h < K_) {
                size_t j = (size_t)g * (K_ - 1) + (h - 1);
                mf_[j] = f[g] * (h + 0.5);
                mvalid_[j] = mf_[j] < 0.45 * fs;
                wm_[j] = mvalid_[j] ? w : 0.0;
                wmsum_[g] += wm_[j];
            }
        }
        wmsum_[g] = std::max(wmsum_[g], 1e-9);
    }
    S.resize(G); hit.resize(G); miss.resize(G); inter.resize(G);
    order_.resize(G); taken_.resize(G);
}

double SalienceMap::support(double P, double h, const Peaks& pk) const {
    size_t n = pk.freq.size();
    if (n == 0) return 0.0;
    double sigma = df * cfg_.peak_sigma_bins + P * (cfg_.vibrato_widen_cents / 1200.0) * std::log(2.0)
                   + P * 0.5 * cfg_.inharm_tol_B * h * h;
    size_t i = std::lower_bound(pk.freq.begin(), pk.freq.end(), P) - pk.freq.begin();
    size_t hi = n > 1 ? std::clamp<size_t>(i, 1, n - 1) : 0;
    size_t lo = n > 1 ? hi - 1 : 0;
    double best = 0.0;
    for (size_t j : {lo, hi}) {
        double z = (pk.freq[j] - P) / sigma;
        best = std::max(best, pk.amp[j] * std::exp(-0.5 * z * z));
    }
    return best;
}

void SalienceMap::compute(const Peaks& pk) {
    int G = grid_size();
    for (int g = 0; g < G; ++g) {
        double h_ = 0, m_ = 0, i_ = 0;
        for (int h = 0; h < K_; ++h) {
            size_t i = (size_t)g * K_ + h;
            if (w_[i] == 0.0) continue;
            double Q = support(pf_[i], h + 1, pk);
            h_ += w_[i] * Q;
            m_ += w_[i] * std::max(0.0, cfg_.miss_threshold - Q);
        }
        for (int h = 0; h < K_ - 1; ++h) {
            size_t j = (size_t)g * (K_ - 1) + h;
            if (wm_[j] == 0.0) continue;
            i_ += wm_[j] * support(mf_[j], h + 1, pk);
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
    std::sort(order.begin(), order.end(), [&](int a, int b) { return sm.S[a] > sm.S[b] || (sm.S[a] == sm.S[b] && a < b); });
    taken.assign(n, 0);
    for (int idx = 0; idx < n; ++idx) {
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
