#include "solver.hpp"
#include <algorithm>
#include <cmath>
#include <limits>

namespace didddle {

static constexpr int BAND_MAX = 96;    // coupling beyond this many neighbouring unknowns is ignored (never reached in practice)

SinusoidSolver::SinusoidSolver(const Config& cfg)
    : cfg_(cfg), nb_(cfg.derived_fft() / 2 + 1), n_(cfg.derived_fft()), V_(std::min(cfg.max_voices, MAX_VOICES)),
      R_(cfg.kernel_radius), df_(cfg.sample_rate / cfg.derived_fft()) {
    size_t cap = (size_t)V_ * cfg.max_partials;
    parts_.reserve(cap);
    order_.resize(cap); cid_.resize(cap); first_.resize(cap); last_.resize(cap);
    nu_c_.resize(cap); share_.resize(cap); amp_.resize(cap); lo_.resize(cap);
    A_.resize(cap * (2 * R_ + 1));
    b_.resize(cap); c_.resize(cap); y_.resize(cap);
    gband_.resize(cap * (BAND_MAX + 1));
    env_h_.resize(cap); env_l_.resize(cap); env_n_.resize(V_);
    S_.assign((size_t)V_ * nb_, cplx(0, 0));
    active_.assign(V_, 0);
}

void SinusoidSolver::solve(const cplx* X, const double* f0) {
    std::fill(S_.begin(), S_.end(), cplx(0, 0));
    std::fill(active_.begin(), active_.end(), 0);
    const int W = 2 * R_ + 1;

    // ---- partial table
    parts_.clear();
    const double band = cfg_.band_hz();
    for (int v = 0; v < V_; ++v) {
        double f = f0[v];
        if (!(f > 0.0) || !std::isfinite(f)) continue;
        for (int h = 1; h <= cfg_.max_partials; ++h) {
            double fr = f * h * std::sqrt(1.0 + cfg_.profile.inharmonicity_B * h * h);
            if (!(fr < band)) break;
            parts_.push_back({v, h, fr / df_});
        }
    }
    const int P = (int)parts_.size();
    if (P == 0) return;
    for (int i = 0; i < P; ++i) order_[i] = i;
    std::sort(order_.begin(), order_.begin() + P, [&](int a, int b) { return parts_[a].nu < parts_[b].nu; });

    // ---- clusters: consecutive sorted partials closer than the gap
    int nc = 0;
    for (int j = 0; j < P; ++j) {
        if (j == 0 || parts_[order_[j]].nu - parts_[order_[j - 1]].nu > cfg_.cluster_gap_bins) {
            first_[nc] = j;
            ++nc;
        }
        cid_[j] = nc - 1;
        last_[nc - 1] = j;
    }
    for (int c = 0; c < nc; ++c) {
        double s = 0;
        for (int j = first_[c]; j <= last_[c]; ++j) s += parts_[order_[j]].nu;
        nu_c_[c] = s / (last_[c] - first_[c] + 1);
    }

    // ---- kernels A[c][k] = 0.5 hann_kernel(k - nu_c) on bins within R of the cluster
    for (int c = 0; c < nc; ++c) {
        int lo = (int)std::ceil(nu_c_[c] - R_);
        lo_[c] = lo;
        for (int w = 0; w < W; ++w) {
            int k = lo + w;
            double d = k - nu_c_[c];
            A_[(size_t)c * W + w] = (k >= 0 && k < nb_ && std::fabs(d) <= R_) ? 0.5 * hann_kernel(d, n_) : cplx(0, 0);
        }
    }
    // normal equations G = A^H A (banded), b = A^H X
    int bw = 0;
    {
        int lo_ptr = 0;
        for (int c = 0; c < nc; ++c) {
            while (nu_c_[c] - nu_c_[lo_ptr] > 2 * R_ + 1) ++lo_ptr;
            bw = std::max(bw, c - lo_ptr);
        }
        bw = std::min(bw, BAND_MAX);
    }
    auto g = [&](int i, int j) -> cplx& { return gband_[(size_t)i * (BAND_MAX + 1) + (i - j)]; };   // i >= j
    double trace = 0;
    for (int i = 0; i < nc; ++i) {
        for (int j = std::max(0, i - bw); j <= i; ++j) {
            cplx s(0, 0);
            int off = lo_[i] - lo_[j];               // bin of A_i[w] equals bin of A_j[w + off]
            for (int w = 0; w < W; ++w) {
                int wj = w + off;
                if (wj < 0 || wj >= W) continue;
                s += std::conj(A_[(size_t)i * W + w]) * A_[(size_t)j * W + wj];
            }
            g(i, j) = s;                              // G(i,j) = sum_k conj(A_ki) A_kj
        }
        trace += g(i, i).real();
        cplx r(0, 0);
        for (int w = 0; w < W; ++w) {
            int k = lo_[i] + w;
            if (k >= 0 && k < nb_) r += std::conj(A_[(size_t)i * W + w]) * X[k];
        }
        b_[i] = r;
    }
    const double lam = cfg_.ridge * trace / nc;
    for (int i = 0; i < nc; ++i) g(i, i) += lam;

    // ---- banded Cholesky G = L L^H (in place, lower band), then solve
    for (int j = 0; j < nc; ++j) {
        double s = g(j, j).real();
        for (int k = std::max(0, j - bw); k < j; ++k) s -= std::norm(g(j, k));
        double d = std::sqrt(std::max(s, 1e-300));
        g(j, j) = cplx(d, 0);
        for (int i = j + 1; i <= std::min(nc - 1, j + bw); ++i) {
            cplx t = g(i, j);
            for (int k = std::max(0, i - bw); k < j; ++k) t -= g(i, k) * std::conj(g(j, k));
            g(i, j) = t / d;
        }
    }
    for (int i = 0; i < nc; ++i) {                    // L y = b
        cplx t = b_[i];
        for (int k = std::max(0, i - bw); k < i; ++k) t -= g(i, k) * y_[k];
        y_[i] = t / g(i, i).real();
    }
    for (int i = nc - 1; i >= 0; --i) {               // L^H c = y
        cplx t = y_[i];
        for (int k = i + 1; k <= std::min(nc - 1, i + bw); ++k) t -= std::conj(g(k, i)) * c_[k];
        c_[i] = t / g(i, i).real();
    }
    for (int c = 0; c < nc; ++c) amp_[c] = std::abs(c_[c]);

    // ---- per-voice envelope over harmonic number from uncollided partials (sorted order = increasing harmonic)
    std::fill(env_n_.begin(), env_n_.end(), 0);
    for (int j = 0; j < P; ++j) {
        const Partial& p = parts_[order_[j]];
        if (first_[cid_[j]] != last_[cid_[j]]) continue;
        size_t idx = (size_t)p.voice * cfg_.max_partials + env_n_[p.voice]++;
        env_h_[idx] = p.harm;
        env_l_[idx] = std::log(amp_[cid_[j]] + 1e-12);
    }
    auto envelope = [&](int v, int h) -> double {      // NaN outside the span of the voice's uncollided partials
        int m = env_n_[v];
        if (m < 2) return std::numeric_limits<double>::quiet_NaN();
        const double* H = &env_h_[(size_t)v * cfg_.max_partials];
        const double* L = &env_l_[(size_t)v * cfg_.max_partials];
        if (h < H[0] || h > H[m - 1]) return std::numeric_limits<double>::quiet_NaN();
        int i = 1;
        while (i < m - 1 && H[i] < h) ++i;
        double t = (h - H[i - 1]) / (H[i] - H[i - 1]);
        return std::exp(L[i - 1] + t * (L[i] - L[i - 1]));
    };

    // ---- share of each cluster's fitted amplitude that belongs to each member
    for (int c = 0; c < nc; ++c) {
        int m = last_[c] - first_[c] + 1;
        if (m == 1) { share_[first_[c]] = 1.0; continue; }
        for (int j = MAX_VOICES * 4; j < m; ++j) share_[first_[c] + j] = 0.0;   // pathological cluster: extra members get nothing
        double a[MAX_VOICES * 4], sum_sq = 0, take_sum = 0;
        int known = 0, mm = std::min(m, MAX_VOICES * 4);
        for (int j = 0; j < mm; ++j) {
            const Partial& p = parts_[order_[first_[c] + j]];
            a[j] = envelope(p.voice, p.harm);
            if (std::isfinite(a[j])) { ++known; sum_sq += a[j] * a[j]; }
        }
        for (int j = 0; j < mm; ++j) {
            double s;
            if (known == mm) s = a[j] * a[j] / sum_sq;
            else if (known > 0) {
                if (std::isfinite(a[j])) s = std::min(a[j] / std::max(amp_[c], 1e-12), 1.0);
                else s = 0.0;
            } else s = 1.0 / mm;
            share_[first_[c] + j] = s;
            if (known > 0 && known < mm && std::isfinite(a[j])) take_sum += s;
        }
        if (known > 0 && known < mm) {                 // known voices take their interpolated level, the rest is theirs
            double norm = take_sum > 1.0 ? 1.0 / take_sum : 1.0;
            double rest = (1.0 - std::min(take_sum * norm, 1.0)) / (mm - known);
            for (int j = 0; j < mm; ++j)
                share_[first_[c] + j] = std::isfinite(a[j]) ? share_[first_[c] + j] * norm : rest;
        }
    }

    // ---- voice spectra: sum of cluster kernels weighted by coefficient x share
    for (int j = 0; j < P; ++j) {
        const Partial& p = parts_[order_[j]];
        int c = cid_[j];
        cplx coef = c_[c] * share_[j];
        cplx* S = &S_[(size_t)p.voice * nb_];
        active_[p.voice] = 1;
        for (int w = 0; w < W; ++w) {
            int k = lo_[c] + w;
            if (k >= 0 && k < nb_) S[k] += coef * A_[(size_t)c * W + w];
        }
    }
}

}  // namespace didddle
