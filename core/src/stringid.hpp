// Which string played a note (spec §17.5). Mirrors fidddle/stringid.py: stiffness (B) of a settled note from a long Hann frame,
// compared with the log(B / f^2) of each string learned during calibration. Fixed buffers, no allocation after construction.
#pragma once
#include <cstdint>
#include <vector>
#include "fft.hpp"
#include "fidddle/config.hpp"
#include "fidddle/types.hpp"

namespace fidddle {

namespace stringid {

constexpr double FMAX = 6000.0, B_MIN = 1e-6, DELAY_S = 0.2, NO_VALUE = -99.0, MARGIN_MIN = 0.3;
constexpr int HMAX = 40, N_MEAS = 2, MAX_WIN = 16384, MIN_WIN = 2048;

int window_len(double sr, double f_hz);

// Last MAX_WIN samples of the (DC-blocked) input, chronological on request.
class History {
public:
    History() : buf_(MAX_WIN, 0.0) {}
    void push(double x) { buf_[w_] = x; w_ = (w_ + 1) & (MAX_WIN - 1); }
    void clear() { std::fill(buf_.begin(), buf_.end(), 0.0); w_ = 0; }
    void last(int n, double* out) const { for (int i = 0; i < n; ++i) out[i] = buf_[(w_ - n + i + MAX_WIN) & (MAX_WIN - 1)]; }
private:
    std::vector<double> buf_;
    int w_ = 0;
};

// The stiffness fit, with its FFTs, windows and scratch preallocated for every window length.
class Measure {
public:
    explicit Measure(double sr);
    // log(B / f0^2) of the note in the last `n` samples of `h`, false if there is no usable measurement.
    bool log_b(const History& h, int n, double f_nom, double& out);
private:
    bool stiffness(int n, double f_nom, double& f0, double& B);
    double sr_;
    struct Size { int n; RealFFT fft; std::vector<double> win; };
    std::vector<Size> sizes_;
    std::vector<double> seg_, re_, im_, M_, noise_, pf_, win41_;
    std::vector<int> pk_;
};

// -> string index (or -1) and margin; open_hz ascending. See fidddle/stringid.py classify().
int classify(double value, double f_hz, const double* centroids, const double* open_hz, int n, double& margin);

// Streaming: watches the confirmed tracks and answers once per note.
class Identifier {
public:
    Identifier(const Config& cfg, Measure& m);
    void reset();
    // `snaps`: this frame's track snapshots. Events are appended to `out`.
    void update(const History& h, int64_t end, const VoiceSnapshot* snaps, int n, std::vector<StringEvent>& out);
    void flush(int64_t end, std::vector<StringEvent>& out);
    bool enabled() const;
private:
    struct St {
        bool used = false, done = false;
        uint32_t id = 0;
        int64_t birth = 0, last = -1;
        double vals[N_MEAS + 1];
        int nvals = 0;
        double f = 0, midi = 0, conf = 0;
        int slot = -1;
    };
    void finish(St& s, int64_t end, std::vector<StringEvent>& out);
    const Config& cfg_;
    Measure& m_;
    St st_[MAX_VOICES + 2];
};

}  // namespace stringid
}  // namespace fidddle
