#include "fitter.hpp"
#include <algorithm>
#include <cmath>

namespace cellostop {

// ---- strings (spec §1.3) ----------------------------------------------------
bool strings_feasible(const double* p_in, int n, const InstrumentProfile& prof, double tol_cents) {
    if (n > prof.string_count) return false;
    double p[MAX_VOICES + 2], s[MAX_STRINGS];
    for (int i = 0; i < n; ++i) p[i] = p_in[i];
    for (int i = 0; i < prof.string_count; ++i) s[i] = prof.open_string_hz[i];
    std::sort(p, p + n);
    std::sort(s, s + prof.string_count);
    double tol = std::pow(2.0, -tol_cents / 1200.0);
    for (int i = 0; i < n; ++i) if (!(p[i] >= s[i] * tol)) return false;
    return true;
}

void assign_strings(const double* p, int n, const InstrumentProfile& prof, int* out, double tol_cents) {
    for (int i = 0; i < n; ++i) out[i] = -1;
    if (!strings_feasible(p, n, prof, tol_cents)) return;
    int ord[MAX_VOICES + 2];
    for (int i = 0; i < n; ++i) ord[i] = i;
    std::sort(ord, ord + n, [&](int a, int b) { return p[a] < p[b] || (p[a] == p[b] && a < b); });
    for (int r = 0; r < n; ++r) out[ord[r]] = r;
}

// ---- tiny NNLS (Lawson-Hanson on the normal equations) -----------------------
static bool solve_spd(double* A, double* x, int m) {   // in-place Gaussian elimination with pivoting; A is m x m, x holds rhs
    for (int c = 0; c < m; ++c) {
        int piv = c;
        for (int r = c + 1; r < m; ++r) if (std::fabs(A[r * m + c]) > std::fabs(A[piv * m + c])) piv = r;
        if (std::fabs(A[piv * m + c]) < 1e-300) return false;
        if (piv != c) {
            for (int k = 0; k < m; ++k) std::swap(A[c * m + k], A[piv * m + k]);
            std::swap(x[c], x[piv]);
        }
        for (int r = c + 1; r < m; ++r) {
            double f = A[r * m + c] / A[c * m + c];
            for (int k = c; k < m; ++k) A[r * m + k] -= f * A[c * m + k];
            x[r] -= f * x[c];
        }
    }
    for (int c = m - 1; c >= 0; --c) {
        double s = x[c];
        for (int k = c + 1; k < m; ++k) s -= A[c * m + k] * x[k];
        x[c] = s / A[c * m + c];
    }
    return true;
}

double nnls_qp(const double* G, const double* b, int m, double* a) {
    const double jit = 1e-9;
    bool P[16] = {false};
    for (int i = 0; i < m; ++i) a[i] = 0.0;
    auto Gj = [&](int i, int j) { return G[i * m + j] + (i == j ? jit : 0.0); };
    for (int outer = 0; outer < 3 * m + 8; ++outer) {
        int best = -1;
        double bw = 1e-10;
        for (int j = 0; j < m; ++j) {
            if (P[j]) continue;
            double w = b[j];
            for (int k = 0; k < m; ++k) w -= Gj(j, k) * a[k];
            if (w > bw) { bw = w; best = j; }
        }
        if (best < 0) break;
        P[best] = true;
        for (int inner = 0; inner < m + 3; ++inner) {
            int idx[16], np = 0;
            for (int i = 0; i < m; ++i) if (P[i]) idx[np++] = i;
            double A[16 * 16], z[16];
            for (int r = 0; r < np; ++r) {
                z[r] = b[idx[r]];
                for (int c = 0; c < np; ++c) A[r * np + c] = Gj(idx[r], idx[c]);
            }
            if (!solve_spd(A, z, np)) { P[best] = false; break; }
            bool all_pos = true;
            for (int r = 0; r < np; ++r) if (z[r] <= 1e-14) { all_pos = false; break; }
            if (all_pos) {
                for (int i = 0; i < m; ++i) a[i] = 0.0;
                for (int r = 0; r < np; ++r) a[idx[r]] = z[r];
                break;
            }
            double alpha = 1e300;
            for (int r = 0; r < np; ++r)
                if (z[r] <= 1e-14) {
                    double ai = a[idx[r]];
                    alpha = std::min(alpha, ai / (ai - z[r]));
                }
            for (int r = 0; r < np; ++r) a[idx[r]] += alpha * (z[r] - a[idx[r]]);
            for (int r = 0; r < np; ++r) if (a[idx[r]] <= 1e-14) { a[idx[r]] = 0.0; P[idx[r]] = false; }
        }
    }
    double red = 0.0;
    for (int i = 0; i < m; ++i) {
        red += 2.0 * b[i] * a[i];
        for (int j = 0; j < m; ++j) red -= a[i] * G[i * m + j] * a[j];
    }
    return red;
}

// ---- Fitter -------------------------------------------------------------------
Fitter::Fitter(const Config& cfg, int n_fft)
    : cfg_(cfg), nb_(n_fft / 2 + 1), df_(cfg.sample_rate / n_fft), win_gain_(n_fft / 4.0) {
    fmax_ = std::min(cfg.fit_band_hz, 0.45 * cfg.sample_rate);
    hw_.resize(cfg.fit_max_harmonics);
    stretch_.resize(cfg.fit_max_harmonics);
    for (int h = 1; h <= cfg.fit_max_harmonics; ++h) {
        hw_[h - 1] = std::pow((double)h, -cfg.fit_weight_exponent);
        stretch_[h - 1] = std::sqrt(1.0 + cfg.profile.inharmonicity_B * h * h);
    }
    Y_.assign(nb_, 0.0);
    scratch_.assign(nb_, 0.0);
    mark_.assign(nb_, 0);
    touched_.reserve(cfg.fit_max_harmonics * 11);
    int cap = cfg.max_candidates + MAX_VOICES + 2;
    rows_.resize(cap);
    fs_.resize(cap); b_.resize(cap); G_.resize((size_t)cap * cap);
    sel_.reserve(MAX_VOICES + 2);
    for (auto& r : rows_) { r.idx.reserve(cfg.fit_max_harmonics * 11); r.val.reserve(cfg.fit_max_harmonics * 11); }
}

void Fitter::build_row(double f, Row& row) {
    constexpr int HALF = 5;
    touched_.clear();
    for (int h = 1; h <= cfg_.fit_max_harmonics; ++h) {
        double pf = f * h * stretch_[h - 1];
        if (!(pf < fmax_)) continue;
        double sig = df_ * cfg_.peak_sigma_bins + pf * (cfg_.vibrato_widen_cents / 1200.0) * std::log(2.0);
        int c = (int)std::nearbyint(pf / df_);
        for (int o = -HALF; o <= HALF; ++o) {
            int idx = c + o;
            if (idx < 0 || idx >= nb_) continue;
            double z = (idx * df_ - pf) / sig;
            double v = hw_[h - 1] * std::exp(-0.5 * z * z);
            if (!mark_[idx]) { mark_[idx] = 1; touched_.push_back(idx); }
            scratch_[idx] += v;
        }
    }
    row.idx.assign(touched_.begin(), touched_.end());
    row.val.resize(touched_.size());
    for (size_t i = 0; i < touched_.size(); ++i) {
        row.val[i] = scratch_[touched_[i]];
        scratch_[touched_[i]] = 0.0;
        mark_[touched_[i]] = 0;
    }
}

void Fitter::gram(int n, double* Gm, double* bm) {
    for (int i = 0; i < n; ++i) bm[i] = dot(rows_[i], Y_);
    for (int j = 0; j < n; ++j) {
        for (size_t k = 0; k < rows_[j].idx.size(); ++k) scratch_[rows_[j].idx[k]] = rows_[j].val[k];
        for (int i = 0; i <= j; ++i) { double s = dot(rows_[i], scratch_); Gm[i * n + j] = s; Gm[j * n + i] = s; }
        for (size_t k = 0; k < rows_[j].idx.size(); ++k) scratch_[rows_[j].idx[k]] = 0.0;
    }
}

void Fitter::render_peaks(const Peaks& pk) {
    constexpr int HALF = 5;
    std::fill(Y_.begin(), Y_.end(), 0.0);
    double sig = df_ * cfg_.peak_sigma_bins;
    for (size_t p = 0; p < pk.freq.size(); ++p) {
        double pf = pk.freq[p];
        if (!(pf < fmax_)) continue;
        double amp = std::pow(std::max(pk.amp[p], 0.0), cfg_.fit_compress);
        int c = (int)std::nearbyint(pf / df_);
        for (int o = -HALF; o <= HALF; ++o) {
            int idx = c + o;
            if (idx < 0 || idx >= nb_) continue;
            double z = (idx * df_ - pf) / sig;
            Y_[idx] = std::max(Y_[idx], std::exp(-0.5 * z * z) * amp);
        }
    }
}

double Fitter::dot(const Row& r, const std::vector<double>& dense) const {
    double s = 0.0;
    for (size_t i = 0; i < r.idx.size(); ++i) s += r.val[i] * dense[r.idx[i]];
    return s;
}

double Fitter::dup_penalty(const std::vector<double>& fs, const std::vector<int>& sel, int j) const {
    double tol = cfg_.dup_tol_cents / 1200.0;
    for (int i : sel) {
        double r = fs[j] / fs[i];
        for (double q : {r, 1.0 / r}) {
            double n = std::nearbyint(q);
            if (n >= 2 && std::fabs(std::log2(q / n)) <= tol) return cfg_.dup_extra_gain;
        }
    }
    return 0.0;
}

double Fitter::sub_nnls(const double* G, int ld, const double* b, const int* idx, int m, double* a) const {
    double Gs[MAX_VOICES * MAX_VOICES + 64], bs[MAX_VOICES + 8];
    for (int i = 0; i < m; ++i) {
        bs[i] = b[idx[i]];
        for (int j = 0; j < m; ++j) Gs[i * m + j] = G[(size_t)idx[i] * ld + idx[j]];
    }
    return nnls_qp(Gs, bs, m, a);
}

void Fitter::fit(const double* E_L, const double* M, const std::vector<Candidate>& cands, const Peaks& peaks,
                 const double* priors, int n_priors, FitResult& out) {
    out.voices.clear();
    out.unexplained = 1.0; out.explained = 0.0;
    render_peaks(peaks);
    double e0 = 0.0;
    for (double y : Y_) e0 += y * y;
    out.e0 = e0;
    int C = (int)cands.size();
    if (e0 <= 1e-6 || C == 0) return;

    std::vector<double>& fs = fs_;
    for (int c = 0; c < C; ++c) { fs[c] = cands[c].f_hz; build_row(fs[c], rows_[c]); }
    double* b = b_.data();
    double* G = G_.data();
    for (int c = 0; c < C; ++c) b[c] = dot(rows_[c], Y_);
    for (int j = 0; j < C; ++j) {   // Gram via scatter of one row at a time
        for (size_t k = 0; k < rows_[j].idx.size(); ++k) scratch_[rows_[j].idx[k]] = rows_[j].val[k];
        for (int i = 0; i <= j; ++i) {
            double s = dot(rows_[i], scratch_);
            G[(size_t)i * C + j] = s;
            G[(size_t)j * C + i] = s;
        }
        for (size_t k = 0; k < rows_[j].idx.size(); ++k) scratch_[rows_[j].idx[k]] = 0.0;
    }

    // greedy forward selection (§7.3)
    int V = std::min(cfg_.max_voices, MAX_VOICES);
    std::vector<int>& sel = sel_;
    sel.clear();
    double last_red = 0.0;
    while ((int)sel.size() < V) {
        int bj = -1;
        double bred = 0, badj = 0;
        double ba[MAX_VOICES + 2] = {0};
        for (int j = 0; j < C; ++j) {
            bool skip = false;
            for (int i : sel) {
                if (i == j || std::fabs(cands[j].midi - cands[i].midi) * 100.0 < cfg_.min_voice_sep_cents) { skip = true; break; }
            }
            if (skip) continue;
            int idx[MAX_VOICES + 2], m = 0;
            for (int i : sel) idx[m++] = i;
            idx[m++] = j;
            double a[MAX_VOICES + 2];
            double red = sub_nnls(G, C, b, idx, m, a);
            double adj = red - dup_penalty(fs, sel, j) * e0;
            if (bj < 0 || adj > badj) {
                bj = j; bred = red; badj = adj;
                for (int q = 0; q < m; ++q) ba[q] = a[q];
            }
        }
        if (bj < 0) break;
        int m = (int)sel.size() + 1;
        double gain = (badj - last_red) / (cfg_.gain_relative ? (e0 - last_red) : e0);
        double need = sel.empty() ? cfg_.first_voice_min_gain
                                  : cfg_.voice_gain[std::min<size_t>(sel.size(), cfg_.voice_gain.size() - 1)];
        if (n_priors > 0) {
            double md = 1e300;
            for (int q = 0; q < n_priors; ++q) md = std::min(md, std::fabs(priors[q] - cands[bj].midi));
            if (md < 0.5) need *= cfg_.prior_persist_factor;
        }
        if (gain < need || ba[m - 1] <= 0) break;
        sel.push_back(bj);
        last_red = bred;
    }
    if (sel.empty()) return;

    // joint pitch refinement (§7.7)
    int n = (int)sel.size();
    double f_sel[MAX_VOICES + 2];
    for (int i = 0; i < n; ++i) f_sel[i] = fs[sel[i]];
    int passes = std::min(2, cfg_.max_fit_iterations);
    int ntrial = (int)std::floor((2 * cfg_.refine_cents) / cfg_.refine_step_cents + 1e-9) + 1;
    double Gm[MAX_VOICES * MAX_VOICES], bm[MAX_VOICES], a[MAX_VOICES + 2];
    int idx_all[MAX_VOICES + 2];
    for (int i = 0; i < n; ++i) idx_all[i] = i;
    for (int pass = 0; pass < passes; ++pass) {
        bool changed = false;
        for (int vi = 0; vi < n; ++vi) {
            int no = n - 1;   // rows 0..no-1 = other voices, row `no` = trial
            for (int q = 0, r = 0; q < n; ++q) if (q != vi) build_row(f_sel[q], rows_[r++]);
            double best_red = -1, best_f = f_sel[vi];
            for (int t = 0; t < ntrial; ++t) {
                double off = -cfg_.refine_cents + t * cfg_.refine_step_cents;
                double tf = f_sel[vi] * std::pow(2.0, off / 1200.0);
                build_row(tf, rows_[no]);
                gram(n, Gm, bm);
                double red = sub_nnls(Gm, n, bm, idx_all, n, a);
                if (red > best_red) { best_red = red; best_f = tf; }
            }
            if (std::fabs(best_f - f_sel[vi]) > 1e-9) { f_sel[vi] = best_f; changed = true; }
        }
        if (!changed) break;
    }

    // final amplitudes and per-voice diagnostics
    for (int i = 0; i < n; ++i) build_row(f_sel[i], rows_[i]);
    gram(n, Gm, bm);
    double red = sub_nnls(Gm, n, bm, idx_all, n, a);

    int strings[MAX_VOICES + 2];
    if (cfg_.profile.string_constraint != StringConstraint::Off) assign_strings(f_sel, n, cfg_.profile, strings);
    else for (int i = 0; i < n; ++i) strings[i] = -1;

    for (int i = 0; i < n; ++i) {
        int keep[MAX_VOICES + 2], m = 0;
        for (int k = 0; k < n; ++k) if (k != i) keep[m++] = k;
        double red_wo = 0.0;
        if (m > 0) { double aw[MAX_VOICES + 2]; red_wo = sub_nnls(Gm, n, bm, keep, m, aw); }
        double marg = (red - red_wo) / e0;

        double env_num = 0, env_den = 0, lvl_sum = 0;
        int nok = 0;
        for (int h = 1; h <= cfg_.fit_max_harmonics; ++h) {
            double pf = f_sel[i] * h * stretch_[h - 1];
            int kh = (int)std::nearbyint(pf / df_);
            if (!(kh < nb_ && pf < fmax_)) continue;
            env_num += hw_[h - 1] * std::exp(E_L[kh]);
            env_den += hw_[h - 1];
            if (M) {
                double loc = std::max({M[std::clamp(kh - 1, 0, nb_ - 1)], M[std::clamp(kh, 0, nb_ - 1)], M[std::clamp(kh + 1, 0, nb_ - 1)]});
                lvl_sum += (loc / win_gain_) * (loc / win_gain_);
            }
            ++nok;
        }
        FitVoice v;
        v.f_hz = f_sel[i];
        v.midi = hz_to_midi(v.f_hz);
        v.amp_w = a[i];
        double env = nok ? env_num / std::max(env_den, 1e-9) : 0.0;
        v.amp = a[i] * env;
        v.gain = marg;
        v.confidence = std::clamp(marg / std::max(cfg_.first_voice_min_gain * 3, 1e-9), 0.0, 1.0);
        v.level_db = (M && nok) ? 20.0 * std::log10(std::sqrt(lvl_sum / 2.0) + 1e-12) : -120.0;
        v.string_index = strings[i];
        out.voices.push_back(v);
    }
    std::sort(out.voices.begin(), out.voices.end(), [](const FitVoice& a, const FitVoice& b) { return a.f_hz < b.f_hz; });
    out.unexplained = 1.0 - red / e0;
    out.explained = red / e0;
}

}  // namespace cellostop
