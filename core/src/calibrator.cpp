#include "calibrator.hpp"
#include <algorithm>
#include <cmath>
#include "salience.hpp"

namespace fidddle {

Calibrator::Calibrator(const Config& cfg, int n_long)
    : cfg_(cfg), df_(cfg.sample_rate / n_long), fmax_(cfg.derived_fit_band()), n_(cfg.profile.string_count) {
    for (int i = 0; i < n_; ++i) nominal_[i] = cfg.profile.open_string_hz[i];
    B_list_.assign((size_t)MAX_STRINGS * CAP, 0.0);
    cents_list_.assign((size_t)MAX_STRINGS * CAP, 0.0);
    scratch_.assign(CAP, 0.0);
    reset();
}

void Calibrator::reset() {
    for (int s = 0; s < MAX_STRINGS; ++s) {
        count_[s] = 0; frames_[s] = 0; done_[s] = false;
        for (int h = 0; h < N_WEIGHTS; ++h) { prof_sum_[s][h] = 0.0; prof_cnt_[s][h] = 0.0; }
    }
    run_len_ = 0;
    have_last_ = false;
}

double Calibrator::median(const double* v, int n, double* scratch) {
    std::copy(v, v + n, scratch);
    std::sort(scratch, scratch + n);
    return n % 2 ? scratch[n / 2] : 0.5 * (scratch[n / 2 - 1] + scratch[n / 2]);
}

bool Calibrator::complete() const {
    for (int s = 0; s < n_; ++s) if (!done_[s]) return false;
    return n_ > 0;
}

int Calibrator::captured_count() const {
    int c = 0;
    for (int s = 0; s < n_; ++s) c += done_[s];
    return c;
}

// Peaks matching harmonics 1..hmax of (f0, B). h/p/a arrays have room for 40 entries.
bool Calibrator::assign(double f0, double B, const Peaks& pk, int hmax, int* h, double* p, double* a, int& n) const {
    n = 0;
    const size_t np = pk.freq.size();
    for (int hh = 1; hh <= hmax; ++hh) {
        double ex = f0 * hh * std::sqrt(1.0 + B * hh * hh);
        if (ex > fmax_) break;
        size_t i = std::lower_bound(pk.freq.begin(), pk.freq.end(), ex) - pk.freq.begin();
        double bd = 1e300;
        long bj = -1;
        for (long j : {(long)i - 1, (long)i}) {
            if (j >= 0 && j < (long)np) {
                double d = std::fabs(pk.freq[j] - ex);
                if (bj < 0 || d < bd) { bd = d; bj = j; }
            }
        }
        if (bj >= 0 && bd <= 0.8 * df_ + 0.002 * ex && n < 40) {
            h[n] = hh; p[n] = pk.freq[bj]; a[n] = pk.amp[bj]; ++n;
        }
    }
    return n >= 4;
}

// Progressive weighted fit of (f0_h/h)^2 = f0^2 + f0^2 B h^2 using partials up to 6, 10, 16, 24, 32.
bool Calibrator::estimate(double f0, double B, const Peaks& pk, double& f0o, double& Bo, int* h, double* a, int& n) const {
    double p[40];
    for (int hmax : {6, 10, 16, 24, 32}) {
        if (!assign(f0, B, pk, hmax, h, p, a, n)) return false;
        double S0 = 0, S1 = 0, S2 = 0, T0 = 0, T1 = 0;
        for (int i = 0; i < n; ++i) {
            double x = (double)h[i] * h[i], y = (p[i] / h[i]) * (p[i] / h[i]), w = x;   // weight h^2
            S0 += w; S1 += w * x; S2 += w * x * x; T0 += w * y; T1 += w * x * y;
        }
        double det = S0 * S2 - S1 * S1;
        if (std::fabs(det) < 1e-300) return false;
        double c0 = (T0 * S2 - T1 * S1) / det, c1 = (S0 * T1 - S1 * T0) / det;
        if (c0 <= 0) return false;
        f0 = std::sqrt(c0);
        B = c1 / c0;
        if (B < -5e-5 || B > 2e-3) return false;
        B = std::max(B, 0.0);
    }
    double se = 0;
    for (int i = 0; i < n; ++i) {
        double pred = f0 * h[i] * std::sqrt(1.0 + B * h[i] * h[i]);
        se += (pred - p[i]) * (pred - p[i]);
    }
    double rms = std::sqrt(se / n);
    if (n < 6 || rms > 0.6 * df_) return false;
    // reject a lock onto an upper harmonic: a comparably strong peak at f0/2, f0/3 or f0/4
    double a1 = h[0] == 1 ? a[0] : 0.0;
    for (int k : {2, 3, 4}) {
        size_t lo = std::lower_bound(pk.freq.begin(), pk.freq.end(), f0 / k * 0.97) - pk.freq.begin();
        size_t hi = std::lower_bound(pk.freq.begin(), pk.freq.end(), f0 / k * 1.03) - pk.freq.begin();
        if (hi > lo && a1 > 0) {
            double mx = 0;
            for (size_t j = lo; j < hi; ++j) mx = std::max(mx, pk.amp[j]);
            if (mx > 0.5 * a1) return false;
        }
    }
    f0o = f0; Bo = B;
    return true;
}

void Calibrator::update(const std::vector<FitVoice>& voices, const Peaks& peaks, std::vector<CalibEvent>& out) {
    // A clean single note: some voice (the "root") such that every other voice is a harmonic of it or a sub-octave of it,
    // and which sits near an open string. With the wrong inharmonicity assumed the fit explains misaligned upper partials
    // as extra octave/twelfth voices and sometimes adds a ghost octave below, so several voices can qualify; they are
    // tried from the lowest up (the fit returns voices sorted by pitch) and the first whose partial structure fits is used.
    auto related = [](const FitVoice& root, const FitVoice& o) {
        double r = o.f_hz / root.f_hz;
        for (double q : {r, 1.0 / r}) {
            double n = std::nearbyint(q);
            if (n >= 2 && std::fabs(q / n - 1.0) <= 0.025) return true;
        }
        return &o == &root || o.gain <= 0.25 * root.gain;       // a much weaker stray voice is not a second note
    };
    struct Root { const FitVoice* v; int s; };
    Root valid[MAX_VOICES + 2];
    int nvalid = 0;
    for (const auto& root : voices) {
        if (root.level_db < cfg_.min_level_dbfs + 6.0 || nvalid >= MAX_VOICES + 2) continue;
        bool all = true;
        for (const auto& o : voices) all = all && related(root, o);
        if (!all) continue;
        int bs = 0;
        double best = 1e300;
        for (int i = 0; i < n_; ++i) {
            double c = std::fabs(1200.0 * std::log2(root.f_hz / nominal_[i]));
            if (c < best) { best = c; bs = i; }
        }
        if (best <= 150.0) valid[nvalid++] = {&root, bs};
    }
    if (nvalid == 0) { run_len_ = 0; have_last_ = false; return; }

    const FitVoice* v0 = valid[0].v;
    if (!have_last_ || std::fabs(v0->midi - last_midi_) > 0.3) run_len_ = 0;
    last_midi_ = v0->midi; have_last_ = true;
    ++run_len_;
    if (run_len_ < min_run_ || run_len_ > max_run_) return;       // skip the attack; early decay carries the full spectrum
    if (peaks.freq.size() < 6) return;

    int h[40], n = 0, s = -1;
    double a[40], f0 = 0, B = 0;
    for (int k = 0; k < nvalid; ++k) {
        int ss = valid[k].s;
        double B0 = count_[ss] >= 5 ? median(&B_list_[(size_t)ss * CAP], count_[ss], scratch_.data()) : cfg_.inharm_B(valid[k].v->f_hz);
        if (estimate(valid[k].v->f_hz, B0, peaks, f0, B, h, a, n)) { s = ss; break; }
    }
    if (s < 0) return;

    if (count_[s] < CAP) {
        B_list_[(size_t)s * CAP + count_[s]] = B;
        cents_list_[(size_t)s * CAP + count_[s]] = 1200.0 * std::log2(f0 / nominal_[s]);
        ++count_[s];
    }
    // harmonic profile in the fit's compressed-amplitude domain, relative to the first eight partials
    double y[N_WEIGHTS] = {0};
    bool seen[N_WEIGHTS] = {false};
    int hm = std::min(N_WEIGHTS, h[n - 1]);
    for (int i = 0; i < hm; ++i) seen[i] = true;
    for (int i = 0; i < n; ++i) if (h[i] <= N_WEIGHTS) y[h[i] - 1] = std::pow(std::max(a[i], 0.0), cfg_.fit_compress);
    int ref_n = std::min(8, hm);
    double ref = 0;
    for (int i = 0; i < ref_n; ++i) ref += y[i];
    ref /= ref_n;
    if (ref > 0) {
        for (int i = 0; i < N_WEIGHTS; ++i) if (seen[i]) { prof_sum_[s][i] += y[i] / ref; prof_cnt_[s][i] += 1.0; }
    }
    ++frames_[s];
    if (frames_[s] % 10 == 0 && !done_[s]) {
        CalibEvent e; e.kind = CalibEvent::Progress; e.string = s; e.frames = frames_[s]; e.needed = need_;
        out.push_back(e);
    }
    if (frames_[s] >= need_ && !done_[s]) {
        done_[s] = true;
        double mc = median(&cents_list_[(size_t)s * CAP], count_[s], scratch_.data());
        double mB = median(&B_list_[(size_t)s * CAP], count_[s], scratch_.data());
        CalibEvent e; e.kind = CalibEvent::StringDone; e.string = s; e.frames = frames_[s]; e.needed = need_;
        e.f0_hz = nominal_[s] * std::pow(2.0, mc / 1200.0); e.cents = mc; e.B = mB;
        out.push_back(e);
        if (complete()) {
            CalibEvent c; c.kind = CalibEvent::Complete; c.captured = captured_count(); c.total = n_;
            out.push_back(c);
        }
    }
}

bool Calibrator::finalize(Calibration& cal) const {
    cal = Calibration{};
    cal.n_strings = n_;
    for (int s = 0; s < n_; ++s) {
        if (!done_[s]) continue;
        cal.captured[s] = true;
        cal.B[s] = median(&B_list_[(size_t)s * CAP], count_[s], scratch_.data());
        cal.cents[s] = median(&cents_list_[(size_t)s * CAP], count_[s], scratch_.data());
    }
    if (!cal.any_strings()) return false;
    double sums[N_WEIGHTS] = {0}, cnts[N_WEIGHTS] = {0};
    for (int s = 0; s < n_; ++s)
        if (done_[s]) for (int i = 0; i < N_WEIGHTS; ++i) { sums[i] += prof_sum_[s][i]; cnts[i] += prof_cnt_[s][i]; }
    int m = 0;
    while (m < N_WEIGHTS && cnts[m] >= 20) ++m;
    if (m >= 6) {
        double w[N_WEIGHTS], mean = 0;
        int k = std::min(8, m);
        for (int i = 0; i < m; ++i) w[i] = sums[i] / cnts[i];
        for (int i = 0; i < k; ++i) mean += w[i];
        mean = std::max(mean / k, 1e-9);
        cal.n_weights = m;
        for (int i = 0; i < m; ++i) cal.weights[i] = std::max(w[i] / mean, 0.03);
    }
    // the profile of each captured string (a pitch uses the profile of the string it would be played on)
    for (int s = 0; s < n_; ++s) {
        if (!done_[s]) continue;
        int ms = 0;
        while (ms < N_WEIGHTS && prof_cnt_[s][ms] >= 10) ++ms;
        if (ms < 6) continue;
        double w[N_WEIGHTS], mean = 0;
        int k = std::min(8, ms);
        for (int i = 0; i < ms; ++i) w[i] = prof_sum_[s][i] / prof_cnt_[s][i];
        for (int i = 0; i < k; ++i) mean += w[i];
        mean = std::max(mean / k, 1e-9);
        cal.n_sw[s] = ms;
        for (int i = 0; i < ms; ++i) cal.sw[s][i] = std::max(w[i] / mean, 0.03);
    }
    return true;
}

}  // namespace fidddle
