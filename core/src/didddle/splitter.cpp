#include "didddle/splitter.hpp"
#include <algorithm>

namespace didddle {

Splitter::Splitter(const SplitterConfig& cfg)
    : cfg_(cfg), det_(cfg.detector), sep_(cfg.separator, det_.long_fft_size() / 2), q_(QCAP) {}

Splitter::~Splitter() = default;

void Splitter::reset() {
    det_.reset();
    sep_.reset();
    qh_ = 0; qt_ = 0;
}

void Splitter::process(const double* in, size_t n, double* const* voices, double* residual) {
    const int64_t n_long = det_.long_fft_size(), hop = cfg_.detector.hop_size;
    const int V = sep_.slots();
    double* vp[MAX_VOICES];
    size_t pos = 0;
    while (pos < n) {
        const int64_t tot = det_.samples_processed();
        const int64_t next = tot < n_long ? n_long : tot + hop - (tot - n_long) % hop;   // next analysis boundary
        const size_t take = (size_t)std::min<int64_t>((int64_t)(n - pos), next - tot);
        det_.process(in + pos, take);
        if (det_.samples_processed() == next) {
            sep_.push_frame(next, det_.latest().voices);
            fidddle::NoteEvent e;
            while (det_.poll_event(e)) {
                sep_.push_event(e);
                size_t h = qh_.load(std::memory_order_relaxed), t = qt_.load(std::memory_order_acquire);
                if (h - t < QCAP) { q_[h % QCAP] = e; qh_.store(h + 1, std::memory_order_release); }
            }
        }
        for (int v = 0; v < V; ++v) vp[v] = voices[v] + pos;
        sep_.process(in + pos, take, vp, residual ? residual + pos : nullptr);
        pos += take;
    }
}

bool Splitter::poll_event(fidddle::NoteEvent& out) {
    size_t t = qt_.load(std::memory_order_relaxed), h = qh_.load(std::memory_order_acquire);
    if (t == h) return false;
    out = q_[t % QCAP];
    qt_.store(t + 1, std::memory_order_release);
    return true;
}

}  // namespace didddle
