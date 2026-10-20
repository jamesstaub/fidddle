#include "stringid.hpp"
#include <algorithm>
#include <cmath>
#include "spectral.hpp"

namespace fidddle {
namespace stringid {

int window_len(double sr, double f_hz) {
    int n = 1 << (int)std::ceil(std::log2(6.0 * sr / f_hz));
    return std::min(std::max(n, MIN_WIN), MAX_WIN);
}

Measure::Measure(double sr) : sr_(sr) {
    for (int n = MIN_WIN; n <= MAX_WIN; n <<= 1) sizes_.push_back({n, RealFFT(n), hann(n)});
    int nb = MAX_WIN / 2 + 1;
    seg_.resize(MAX_WIN); re_.resize(nb); im_.resize(nb); M_.resize(nb); noise_.resize(nb); pf_.resize(nb); win41_.resize(41);
    pk_.reserve(nb);
}

bool Measure::log_b(const History& h, int n, double f_nom, double& out) {
    h.last(n, seg_.data());
    double f0, B;
    if (!stiffness(n, f_nom, f0, B) || B <= B_MIN) return false;
    out = std::log(B / (f0 * f0));
    return true;
}

bool Measure::stiffness(int n, double f_nom, double& f0o, double& Bo) {
    Size* sz = nullptr;
    for (auto& s : sizes_) if (s.n == n) sz = &s;
    if (!sz) return false;
    for (int i = 0; i < n; ++i) seg_[i] *= sz->win[i];
    sz->fft.forward(seg_.data(), re_.data(), im_.data());
    const int nb = n / 2 + 1;
    const double df = sr_ / n;
    double mx = 0;
    for (int k = 0; k < nb; ++k) { M_[k] = std::sqrt(re_[k] * re_[k] + im_[k] * im_[k]); mx = std::max(mx, M_[k]); }
    if (mx <= 0) return false;
    // noise floor: 41-bin running median, edge-replicated (scipy mode="nearest")
    for (int k = 0; k < nb; ++k) {
        for (int j = 0; j < 41; ++j) win41_[j] = M_[std::min(std::max(k + j - 20, 0), nb - 1)];
        std::nth_element(win41_.begin(), win41_.begin() + 20, win41_.end());
        noise_[k] = win41_[20];
    }
    // interpolated peaks above 6x the noise and 75 dB under the maximum
    const double floor_lin = mx * std::pow(10.0, -75.0 / 20.0);
    int np = 0;
    for (int k = 1; k < nb - 1; ++k) {
        if (!(M_[k] > M_[k - 1] && M_[k] >= M_[k + 1] && M_[k] > 6.0 * noise_[k] && M_[k] > floor_lin)) continue;
        double lm = std::log(M_[k - 1] + 1e-12), l0 = std::log(M_[k] + 1e-12), lp = std::log(M_[k + 1] + 1e-12);
        double den = lm - 2 * l0 + lp, d = 0.0;
        if (den < -1e-12) d = std::min(std::max(0.5 * (lm - lp) / den, -0.5), 0.5);
        pf_[np++] = (k + d) * df;
    }
    if (np < 4) return false;
    double f0 = f_nom, B = 0.0;
    int hs[HMAX], nh = 0;
    double ps[HMAX];
    for (int hmax : {6, 10, 16, 24, HMAX}) {
        nh = 0;
        for (int h = 1; h <= hmax; ++h) {
            double e = f0 * h * std::sqrt(1.0 + B * h * h);
            if (e > FMAX) break;
            int i = (int)(std::lower_bound(pf_.begin(), pf_.begin() + np, e) - pf_.begin());
            int j = -1;
            double bd = 1e300;
            for (int c : {i - 1, i}) {
                if (c < 0 || c >= np) continue;
                double dd = std::fabs(pf_[c] - e);
                if (dd < bd) { bd = dd; j = c; }
            }
            if (j >= 0 && bd <= 0.8 * df + 0.002 * e) { hs[nh] = h; ps[nh] = pf_[j]; ++nh; }
        }
        if (nh < 4) return false;
        // weighted least squares of (p/h)^2 on [1, h^2] with weights h^2
        double S0 = 0, S1 = 0, S2 = 0, T0 = 0, T1 = 0;
        for (int i = 0; i < nh; ++i) {
            double w = (double)hs[i] * hs[i], x = w, y = (ps[i] / hs[i]) * (ps[i] / hs[i]);
            S0 += w; S1 += w * x; S2 += w * x * x; T0 += w * y; T1 += w * x * y;
        }
        double det = S0 * S2 - S1 * S1;
        if (std::fabs(det) < 1e-30) return false;
        double c0 = (T0 * S2 - T1 * S1) / det, c1 = (S0 * T1 - S1 * T0) / det;
        if (c0 <= 0) return false;
        f0 = std::sqrt(c0);
        B = std::min(std::max(c1 / c0, -2e-4), 3e-3);
    }
    if (nh < 6) return false;
    f0o = f0; Bo = B;
    return true;
}

int classify(double value, double f_hz, const double* centroids, const double* open_hz, int n, double& margin) {
    margin = 0.0;
    int rule = -1;
    double best = 1e300, second = 1e300;
    int bi = -1, known = 0;
    for (int s = 0; s < n; ++s) {
        double semis = 12.0 * std::log2(f_hz / open_hz[s]) + 0.5;
        if (!(semis >= 0 && semis <= 24.0)) continue;
        rule = s;                                   // open_hz ascending: the last is the highest string that can sound it
        if (centroids[s] <= NO_VALUE + 1) continue;
        double d = std::fabs(value - centroids[s]);
        ++known;
        if (d < best) { second = best; best = d; bi = s; } else if (d < second) second = d;
    }
    if (rule < 0) return -1;
    if (known < 2) return rule;
    double m = second - best;
    if (m >= MARGIN_MIN) { margin = m; return bi; }
    return rule;
}

Identifier::Identifier(const Config& cfg, Measure& m) : cfg_(cfg), m_(m) { reset(); }
void Identifier::reset() { for (auto& s : st_) s = St{}; }

bool Identifier::enabled() const {
    const Calibration& c = cfg_.calibration;
    return cfg_.string_id && cfg_.use_calibration && c.has_logb();
}

void Identifier::finish(St& s, int64_t end, std::vector<StringEvent>& out) {
    s.done = true;
    double v[N_MEAS + 1];
    std::copy(s.vals, s.vals + s.nvals, v);
    std::sort(v, v + s.nvals);
    double med = s.nvals % 2 ? v[s.nvals / 2] : 0.5 * (v[s.nvals / 2 - 1] + v[s.nvals / 2]);
    double margin;
    int str = classify(med, s.f, cfg_.calibration.logb, cfg_.profile.open_string_hz.data(), cfg_.profile.string_count, margin);
    if (str < 0) return;
    StringEvent e;
    e.track_id = s.id; e.slot = s.slot; e.midi_note = (int)std::nearbyint(s.midi); e.string = str; e.margin = (float)margin;
    e.deliver_samples = end;
    out.push_back(e);
}

void Identifier::update(const History& h, int64_t end, const VoiceSnapshot* snaps, int n, std::vector<StringEvent>& out) {
    if (!enabled()) return;
    bool live[MAX_VOICES + 2] = {false};
    for (int i = 0; i < n; ++i) {
        const VoiceSnapshot& v = snaps[i];
        if (v.state != ACTIVE) continue;
        int idx = -1, free_i = -1;
        for (int j = 0; j < MAX_VOICES + 2; ++j) {
            if (st_[j].used && st_[j].id == v.track_id) idx = j;
            else if (!st_[j].used && free_i < 0) free_i = j;
        }
        if (idx < 0) {
            if (free_i < 0) continue;
            idx = free_i;
            st_[idx] = St{};
            st_[idx].used = true; st_[idx].id = v.track_id; st_[idx].birth = end;
        }
        live[idx] = true;
        St& s = st_[idx];
        s.f = v.frequency_hz; s.midi = v.midi; s.conf = v.confidence; s.slot = i;
        if (s.done) continue;
        int w = window_len(cfg_.sample_rate, s.f);
        if ((double)(end - s.birth) < DELAY_S * cfg_.sample_rate + w || end < w) continue;
        if (s.last >= 0 && end - s.last < w / 2) continue;
        s.last = end;
        double lb;
        if (m_.log_b(h, w, s.f, lb) && s.nvals < N_MEAS) s.vals[s.nvals++] = lb;
        if (s.nvals >= N_MEAS) finish(s, end, out);
    }
    for (int j = 0; j < MAX_VOICES + 2; ++j) {
        if (st_[j].used && !live[j]) {
            if (!st_[j].done && st_[j].nvals > 0) finish(st_[j], end, out);
            st_[j] = St{};
        }
    }
}

void Identifier::flush(int64_t end, std::vector<StringEvent>& out) {
    if (!enabled()) return;
    for (auto& s : st_) if (s.used && !s.done && s.nvals > 0) finish(s, end, out);
    reset();
}

}  // namespace stringid
}  // namespace fidddle
