// Polyphonic model fitting (spec §7): greedy selection over a Gram matrix with a tiny NNLS,
// then joint pitch refinement. All buffers are sized at construction.
#pragma once
#include <vector>
#include "fidddle/config.hpp"
#include "salience.hpp"
#include "spectral.hpp"

namespace fidddle {

struct FitVoice {
    double f_hz = 0, midi = 0, amp_w = 0, amp = 0, gain = 0, confidence = 0, level_db = -120.0, snr_db = 0.0;
    int string_index = -1;
};

struct FitResult {
    std::vector<FitVoice> voices;
    double unexplained = 1.0, explained = 0.0, e0 = 0.0;
};

bool strings_feasible(const double* pitches_hz, int n, const InstrumentProfile& p, double tol_cents = 50.0);
void assign_strings(const double* pitches_hz, int n, const InstrumentProfile& p, int* out, double tol_cents = 50.0);

// min a'(G+jit)a - 2 b'a over a >= 0 for the m x m sub-problem; returns E0-D reduction (2b.a - a'Ga).
double nnls_qp(const double* G, const double* b, int m, double* a);

class Fitter {
public:
    Fitter(const Config& cfg, int n_fft);
    void fit(const double* E_L, const double* M, const std::vector<Candidate>& cands, const Peaks& peaks,
             const double* priors, int n_priors, FitResult& out, const double* noise = nullptr);

private:
    struct Row { std::vector<int> idx; std::vector<double> val; };
    void build_row(double f, Row& row);
    void render_peaks(const Peaks& pk);
    double dot(const Row& r, const std::vector<double>& dense) const;
    double dup_penalty(const std::vector<double>& fs, const std::vector<int>& sel, int j) const;
    double sub_nnls(const double* G, int ld, const double* b, const int* idx, int m, double* a) const;
    void gram(int n, double* Gm, double* bm);   // rows_[0..n) vs Y_

    const Config& cfg_;
    int nb_;
    double df_, fmax_, win_gain_;
    const double* weights_for(double f) const;
    mutable std::vector<double> hw_tier_;       // weights of a note in the upper tier (few partials)
    std::vector<double> hw_;                  // default / averaged weights
    std::vector<std::vector<double>> hw_s_;   // per-string weights (empty where not learned)
    std::vector<double> Y_, scratch_;
    std::vector<char> mark_;
    std::vector<int> touched_;
    std::vector<Row> rows_;
    std::vector<double> fs_, b_, G_;
    std::vector<int> sel_;
};

}  // namespace fidddle
