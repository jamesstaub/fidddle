// Dependency-free unit tests for the core building blocks.
#include <cmath>
#include <cstdio>
#include <cstdlib>
#include <new>
#include <random>
#include "fidddle/detector.hpp"
#include "fft.hpp"
#include "fitter.hpp"

using namespace fidddle;
static int failures = 0;

// allocation counter: the realtime path must not allocate (spec §1.2 principle 6)
static bool g_count_allocs = false;
static long g_allocs = 0;
void* operator new(std::size_t n) {
    if (g_count_allocs) ++g_allocs;
    void* p = std::malloc(n ? n : 1);
    if (!p) throw std::bad_alloc();
    return p;
}
void operator delete(void* p) noexcept { std::free(p); }
void operator delete(void* p, std::size_t) noexcept { std::free(p); }
#define CHECK(cond) do { if (!(cond)) { std::printf("FAIL %s:%d  %s\n", __FILE__, __LINE__, #cond); ++failures; } } while (0)

static void test_fft() {
    for (int n : {16, 64, 2048}) {
        RealFFT fft(n);
        std::mt19937 rng(1);
        std::normal_distribution<double> nd;
        std::vector<double> x(n), re(n / 2 + 1), im(n / 2 + 1);
        for (auto& v : x) v = nd(rng);
        fft.forward(x.data(), re.data(), im.data());
        double maxerr = 0;
        for (int k = 0; k <= n / 2; k += (n > 64 ? 37 : 1)) {
            double sr = 0, si = 0;
            for (int t = 0; t < n; ++t) { sr += x[t] * std::cos(2 * M_PI * k * t / n); si -= x[t] * std::sin(2 * M_PI * k * t / n); }
            maxerr = std::max({maxerr, std::fabs(sr - re[k]), std::fabs(si - im[k])});
        }
        CHECK(maxerr < 1e-8);
    }
}

static void test_nnls() {
    // unconstrained optimum has a negative coefficient -> must clamp to zero
    double G[4] = {1.0, 0.9, 0.9, 1.0}, b[2] = {1.0, -0.2}, a[2];
    double red = nnls_qp(G, b, 2, a);
    CHECK(a[1] == 0.0 && std::fabs(a[0] - 1.0) < 1e-6 && std::fabs(red - 1.0) < 1e-6);
    // interior solution
    double G2[4] = {2.0, 0.5, 0.5, 1.0}, b2[2] = {1.0, 1.0};
    nnls_qp(G2, b2, 2, a);
    // solve [2 .5; .5 1] a = [1 1] -> a = [1/3*... ] verify residual of normal equations
    CHECK(std::fabs(2 * a[0] + 0.5 * a[1] - 1) < 1e-6 && std::fabs(0.5 * a[0] + a[1] - 1) < 1e-6);
}

static void test_strings() {
    InstrumentProfile p = InstrumentProfile::cello();
    double ok[4] = {65.41, 98.0, 146.83, 220.0};
    CHECK(strings_feasible(ok, 4, p));
    double bad[2] = {70.0, 71.0};
    CHECK(!strings_feasible(bad, 2, p));
    int s[2];
    double mix[2] = {220.0, 70.0};
    assign_strings(mix, 2, p, s);
    CHECK(s[0] == 1 && s[1] == 0);
}

static void test_detector_blocks() {
    // A steady 220 Hz tone with harmonics must yield exactly one note-on near MIDI 57,
    // identically for different host block sizes.
    Config cfg;
    cfg.sample_rate = 44100.0;
    auto render = [&](int n) {
        std::vector<double> x(n);
        for (int i = 0; i < n; ++i) {
            double t = i / cfg.sample_rate, v = 0;
            for (int h = 1; h <= 20; ++h) v += std::sin(2 * M_PI * 220.0 * h * t + h) / h;
            x[i] = 0.2 * v * std::min(1.0, t / 0.05);
        }
        return x;
    };
    auto x = render(44100 * 2);
    int results[3];
    int bi = 0;
    for (int block : {64, 480, 1000}) {
        Detector d(cfg);
        for (size_t o = 0; o < x.size(); o += block) d.process(x.data() + o, std::min<size_t>(block, x.size() - o));
        int ons = 0, note = 0;
        NoteEvent e;
        while (d.poll_event(e)) if (e.on) { ++ons; note = e.midi_note; }
        CHECK(ons == 1 && note == 57);
        results[bi++] = ons * 1000 + note;
    }
    CHECK(results[0] == results[1] && results[1] == results[2]);
}

static void test_silence() {
    Config cfg;
    cfg.sample_rate = 48000.0;
    Detector d(cfg);
    std::mt19937 rng(0);
    std::normal_distribution<double> nd(0.0, 1e-4);
    std::vector<float> x(48000 * 2);
    for (auto& v : x) v = (float)nd(rng);
    d.process(x.data(), x.size());
    NoteEvent e;
    CHECK(!d.poll_event(e));
}

static void test_no_allocation_in_process() {
    Config cfg;
    cfg.sample_rate = 44100.0;
    Detector d(cfg);
    // staggered plucked chord tones so tracks are born, retriggered and released while counting
    int n = 44100 * 6;
    std::vector<float> x(n);
    for (int i = 0; i < n; ++i) {
        double t = i / cfg.sample_rate, v = 0;
        const double f0[4] = {65.41, 98.0, 146.83, 220.0};
        for (int k = 0; k < 4; ++k) {
            double on = 0.3 + 0.9 * k, tt = t - on;
            if (tt < 0 || tt > 3.0) continue;
            double env = std::exp(-tt / 1.0) * std::min(1.0, tt / 0.005);
            for (int h = 1; h <= 16; ++h) v += env * std::sin(2 * M_PI * f0[k] * h * tt) / h;
        }
        x[i] = (float)(0.2 * v);
    }
    d.process(x.data(), 44100);          // warm-up (first frames)
    g_allocs = 0;
    g_count_allocs = true;
    for (size_t o = 44100; o < x.size(); o += 441) d.process(x.data() + o, std::min<size_t>(441, x.size() - o));
    g_count_allocs = false;
    NoteEvent e;
    int ons = 0;
    while (d.poll_event(e)) ons += e.on;
    CHECK(ons >= 3);
    if (g_allocs) std::printf("  allocations during process(): %ld\n", g_allocs);
    CHECK(g_allocs == 0);
}

int main() {
    test_fft(); test_nnls(); test_strings(); test_detector_blocks(); test_silence(); test_no_allocation_in_process();
    std::printf(failures ? "%d FAILED\n" : "all tests passed\n", failures);
    return failures ? 1 : 0;
}
