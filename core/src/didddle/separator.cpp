#include "didddle/separator.hpp"
#include <algorithm>
#include <chrono>
#include <cmath>
#include "didddle/config.hpp"
#include "fft.hpp"
#include "solver.hpp"
#include "track_log.hpp"

namespace didddle {

namespace {
int next_pow2(int x) { int n = 1; while (n < x) n <<= 1; return n; }
constexpr int MAX_RELEVANT = 12;     // spans of one slot that can matter within one output chunk
}

struct Separator::Impl {
    Config cfg;
    int N, hop, L, V, nb, margin, lead, fade, release, tlen;
    std::vector<double> win;
    double norm;
    fidddle::RealFFT fft;
    SinusoidSolver solver;
    TrackLog log;

    int RX, RO;                                   // ring sizes (powers of two)
    std::vector<double> xin, ola;                 // input history; per-voice overlap-add accumulators [v][RO]
    std::vector<double> buf, re, im;
    std::vector<cplx> X;
    std::vector<double> f0, raw, gate, wt, gout;
    int64_t t = 0, next_frame = 0;
    Diagnostics diag;

    Impl(const Config& c, int half_window)
        : cfg(c), N(c.derived_fft()), hop(c.derived_hop()), L(c.latency_samples()), V(std::min(c.max_voices, MAX_VOICES)),
          nb(N / 2 + 1), margin(N / 2), lead(c.ms(c.onset_lead_ms)), fade(std::max(1, c.ms(c.gate_fade_ms))),
          release(std::max(1, c.ms(c.gate_release_ms))), tlen(c.ms(c.transient_ms)),
          win(N), fft(N), solver(cfg), log(V, half_window),
          RX(next_pow2(L + 2 * N + 1024)), RO(next_pow2(L + 2 * N + 1024)),
          xin(RX, 0.0), ola((size_t)V * RO, 0.0), buf(N), re(nb), im(nb), X(nb), f0(V), raw(V), gate(V), wt(V), gout(V) {
        for (int i = 0; i < N; ++i) win[i] = 0.5 - 0.5 * std::cos(2.0 * M_PI * i / N);
        double s = 0;
        for (double w : win) s += w * w;
        norm = s / hop;
    }

    int64_t due(int64_t m) const { return m * hop + (L - N); }

    void reset() {
        std::fill(xin.begin(), xin.end(), 0.0);
        std::fill(ola.begin(), ola.end(), 0.0);
        t = 0; next_frame = 0;
        diag = Diagnostics{};
        log.reset();
    }

    // One analysis/synthesis frame, centred N/2 before its audio ends (time m*hop).
    void frame(int64_t m) {
        auto t0 = std::chrono::steady_clock::now();
        frame_body(m);
        double us = std::chrono::duration<double, std::micro>(std::chrono::steady_clock::now() - t0).count();
        diag.last_us = us;
        diag.max_us = std::max(diag.max_us, us);
        diag.mean_us += (us - diag.mean_us) / (double)(diag.frames + 1);
        ++diag.frames;
    }

    void frame_body(int64_t m) {
        const int64_t start = m * hop - N, centre = m * hop - N / 2;
        bool any = false;
        for (int v = 0; v < V; ++v) { f0[v] = log.f0_at(v, centre, margin); any = any || f0[v] > 0; }
        if (!any) return;
        for (int i = 0; i < N; ++i) {
            int64_t idx = start + i;
            buf[i] = (idx >= 0 ? xin[idx & (RX - 1)] : 0.0) * win[i];
        }
        fft.forward(buf.data(), re.data(), im.data());
        for (int k = 0; k < nb; ++k) X[k] = cplx(re[k], im[k]);
        solver.solve(X.data(), f0.data());
        for (int v = 0; v < V; ++v) {
            if (!solver.active(v)) continue;
            const cplx* S = solver.voice(v);
            for (int k = 0; k < nb; ++k) { re[k] = S[k].real(); im[k] = S[k].imag(); }
            im[0] = 0.0; im[nb - 1] = 0.0;
            fft.inverse(re.data(), im.data(), buf.data());
            double* o = &ola[(size_t)v * RO];
            for (int i = 0; i < N; ++i) {
                int64_t idx = start + i;
                if (idx >= 0) o[idx & (RO - 1)] += buf[i] * win[i] / norm;
            }
        }
    }

    struct Rel { double start, end; };            // a note as the gate sees it at emission time

    // Output samples for input times [t0, t1): sample n = tau - L. Gate each voice to its notes, hand the attack
    // residual to the voice that starts, and take the residual as the difference.
    void emit(int64_t t0, int64_t t1, double* const* voices, double* residual, size_t off) {
        Rel rel[MAX_VOICES][MAX_RELEVANT];
        int nrel[MAX_VOICES] = {0};
        const int64_t n_first = t0 - L, n_last = t1 - L;
        for (int v = 0; v < V; ++v) {
            for (int i = 0; i < log.span_count(v) && nrel[v] < MAX_RELEVANT; ++i) {
                const NoteSpan& sp = log.span(v, i);
                double s = (double)std::max(sp.on_est - lead, sp.on_del - L);
                double e = sp.open() ? INFINITY : (double)std::max(sp.off_est, sp.off_del - L);
                if (s > (double)n_last || (e + release < (double)n_first && s + tlen < (double)n_first)) continue;
                rel[v][nrel[v]++] = {s, e};
            }
        }
        for (int64_t tau = t0; tau < t1; ++tau) {
            const int64_t n = tau - L;
            const size_t o = off + (size_t)(tau - t0);
            if (n < 0) {
                for (int v = 0; v < V; ++v) voices[v][o] = 0.0;
                if (residual) residual[o] = 0.0;
                continue;
            }
            const double x = xin[n & (RX - 1)];
            double gated_sum = 0.0, wsum = 0.0;
            for (int v = 0; v < V; ++v) {
                double g = 0.0, w = 0.0;
                for (int i = 0; i < nrel[v]; ++i) {
                    const double s = rel[v][i].start, e = rel[v][i].end, d = (double)n - s;
                    if (d < 0) continue;
                    double gin = std::min(1.0, d / fade);
                    double gout_ = (double)n < e ? 1.0 : std::max(0.0, 1.0 - ((double)n - e) / release);
                    g = std::max(g, gin * gout_);
                    if (tlen > 0 && d < tlen) w = std::max(w, 0.5 + 0.5 * std::cos(M_PI * d / tlen));
                }
                double* slot = &ola[(size_t)v * RO + (n & (RO - 1))];
                raw[v] = g * *slot;
                *slot = 0.0;
                wt[v] = w;
                gated_sum += raw[v];
                wsum += w;
            }
            const double rest = x - gated_sum, tot = std::max(wsum, 1.0);
            double sum = 0.0;
            for (int v = 0; v < V; ++v) {
                double y = raw[v] + wt[v] / tot * rest;
                voices[v][o] = y;
                sum += y;
            }
            if (residual) residual[o] = x - sum;
        }
    }

    void process(const double* in, size_t n, double* const* voices, double* residual) {
        size_t pos = 0;
        while (pos < n) {
            while (t >= due(next_frame)) frame(next_frame++);
            size_t take = (size_t)std::min<int64_t>((int64_t)(n - pos), due(next_frame) - t);
            for (size_t i = 0; i < take; ++i) xin[(t + (int64_t)i) & (RX - 1)] = in[pos + i];
            emit(t, t + (int64_t)take, voices, residual, pos);
            t += (int64_t)take;
            pos += take;
        }
        while (t >= due(next_frame)) frame(next_frame++);
    }
};

Separator::Separator(const Config& cfg, int half_window) : p_(new Impl(cfg, half_window)) {}
Separator::~Separator() = default;
const Config& Separator::config() const { return p_->cfg; }
int Separator::slots() const { return p_->V; }
int Separator::latency_samples() const { return p_->L; }
void Separator::reset() { p_->reset(); }
const Diagnostics& Separator::diagnostics() const { return p_->diag; }
void Separator::push_frame(int64_t end, const fidddle::VoiceSnapshot* v) { p_->log.push_frame(end, v); }
void Separator::push_event(const fidddle::NoteEvent& e) { p_->log.push_event(e); }
void Separator::process(const double* in, size_t n, double* const* voices, double* residual) { p_->process(in, n, voices, residual); }

}  // namespace didddle
