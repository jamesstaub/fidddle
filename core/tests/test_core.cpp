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

static void test_profiles() {
    const int voices[5] = {4, 4, 4, 4, 6};
    const int fft[5] = {16384, 8192, 4096, 4096, 8192};  // at 44.1 kHz (bass: 5-string, lowest pitch 28 Hz)
    for (int id = 0; id < InstrumentProfile::Count; ++id) {
        Config c = Config::for_instrument(id, 44100.0);
        CHECK(c.max_voices == voices[id]);
        CHECK(c.derived_long_fft() == fft[id]);
        CHECK(c.profile.min_frequency_hz < c.profile.open_string_hz[0]);
        CHECK(c.profile.string_count >= c.max_voices);
    }
    CHECK(Config::for_instrument(InstrumentProfile::Violin, 44100.0).derived_fit_band() > 8000.0);
    CHECK(Config::for_instrument(InstrumentProfile::Cello, 44100.0).derived_fit_band() == 4000.0);
    CHECK(Config::for_instrument(InstrumentProfile::Guitar, 44100.0).dup_extra_gain == 0.0);
}

static void test_guitar_six_string_chord() {
    // open E major strummed 30 ms apart: six plucked, slightly inharmonic strings -> six note-ons
    Config cfg = Config::for_instrument(InstrumentProfile::Guitar, 44100.0);
    const double midis[6] = {40, 47, 52, 56, 59, 64};
    int n = 44100 * 3;
    std::vector<float> x(n);
    std::mt19937 rng(5);
    std::uniform_real_distribution<double> ph(0, 2 * M_PI);
    double phase[6][24];
    for (auto& r : phase) for (auto& p : r) p = ph(rng);
    for (int i = 0; i < n; ++i) {
        double t = i / cfg.sample_rate, v = 0;
        for (int k = 0; k < 6; ++k) {
            double tt = t - (0.3 + 0.03 * k);
            if (tt < 0) continue;
            double f0 = 440.0 * std::pow(2.0, (midis[k] - 69.0) / 12.0);
            double env = std::min(1.0, tt / 0.003);
            for (int h = 1; h <= 24; ++h) {
                double fh = f0 * h * std::sqrt(1.0 + cfg.profile.inharmonicity_B * h * h);
                if (fh > 0.45 * cfg.sample_rate) break;
                v += env * std::exp(-tt / (2.5 / (1 + 0.35 * h))) * std::sin(2 * M_PI * fh * tt + phase[k][h - 1]) / h;
            }
        }
        x[i] = (float)(0.1 * v);
    }
    Detector d(cfg);
    d.process(x.data(), x.size());
    NoteEvent e;
    int ons = 0;
    bool slot_used[8] = {false};
    while (d.poll_event(e)) if (e.on) { ++ons; if (e.slot >= 0 && e.slot < 8) slot_used[e.slot] = true; }
    CHECK(ons == 6);
    int distinct = 0;
    for (bool u : slot_used) distinct += u;
    CHECK(distinct == 6);
}

// plucked inharmonic string: partial h at h*f*sqrt(1+B h^2), decaying faster at higher partials
static void add_string(std::vector<float>& x, double sr, double f0, double B, double t0, double dur, unsigned seed) {
    std::mt19937 rng(seed);
    std::uniform_real_distribution<double> ph(0, 2 * M_PI);
    double phase[24];
    for (auto& p : phase) p = ph(rng);
    size_t i0 = (size_t)(t0 * sr), i1 = std::min(x.size(), (size_t)((t0 + dur) * sr));
    for (size_t i = i0; i < i1; ++i) {
        double t = (double)(i - i0) / sr, v = 0;
        for (int h = 1; h <= 24; ++h) {
            double fh = f0 * h * std::sqrt(1.0 + B * h * h);
            if (fh > 0.45 * sr) break;
            v += std::exp(-t / (2.5 / (1 + 0.35 * h))) * std::sin(2 * M_PI * fh * t + phase[h - 1]) / h;
        }
        x[i] += (float)(0.12 * v * std::min(1.0, t / 0.003));
    }
}

static void test_calibration_model() {
    Calibration c;
    c.n_strings = 6;
    for (int i = 0; i < 6; ++i) { c.captured[i] = true; c.B[i] = 1e-5 * (i + 1); c.cents[i] = i - 2.0; }
    c.n_weights = 8;
    for (int i = 0; i < 8; ++i) c.weights[i] = 1.0 - 0.05 * i;
    double v[Calibration::LIST_CAP];
    int n = c.to_list(v);
    Calibration back;
    CHECK(Calibration::from_list(v, n, back));
    CHECK(back.n_strings == 6 && back.captured[5] && std::fabs(back.B[3] - 4e-5) < 1e-15 && back.n_weights == 8);
    v[0] = 3.0;
    CHECK(!Calibration::from_list(v, n, back));      // unknown version

    Config cfg = Config::for_instrument(InstrumentProfile::Guitar, 44100.0);
    CHECK(std::fabs(cfg.inharm_B(82.41) - 1e-4) < 1e-12);              // no calibration: the profile constant
    cfg.calibration = c;
    cfg.use_calibration = true;
    CHECK(std::fabs(cfg.inharm_B(82.41) - 1e-5) < 1e-7);               // open E2 string (1 cent of detuning scales it slightly)
    CHECK(std::fabs(cfg.inharm_B(100.0) - 1e-5 * std::pow(100.0 / (82.41 * std::pow(2.0, -2.0 / 1200.0)), 2)) < 1e-9);   // fretted: B ~ f^2
    double w[12];
    cfg.partial_weights(12, 0.5, 100.0, w);                            // no per-string profile: the learned average
    CHECK(std::fabs(w[0] - 1.0) < 1e-12 && std::fabs(w[7] - 0.65) < 1e-12 && w[11] < w[7]);
    cfg.calibration.n_sw[1] = 7;                                         // string 1 (A2) gets its own profile
    for (int i = 0; i < 7; ++i) cfg.calibration.sw[1][i] = 2.0 + i;
    cfg.partial_weights(9, 0.5, 110.0, w);
    CHECK(std::fabs(w[0] - 2.0) < 1e-12 && std::fabs(w[6] - 8.0) < 1e-12 && std::fabs(w[8] - 8.0 * 7.0 / 9.0) < 1e-9);
    cfg.partial_weights(9, 0.5, 200.0, w);                               // another string: back to the average
    CHECK(std::fabs(w[0] - 1.0) < 1e-12);
    // the per-string profile survives the flat-list round trip
    n = cfg.calibration.to_list(v);
    Calibration again;
    CHECK(Calibration::from_list(v, n, again) && again.n_sw[1] == 7 && std::fabs(again.sw[1][6] - 8.0) < 1e-12 && again.n_sw[0] == 0);
}

static void test_calibration_run() {
    Config cfg = Config::for_instrument(InstrumentProfile::Guitar, 44100.0);
    const double B[3] = {3e-5, 8e-5, 2.5e-4};
    const int strings[3] = {0, 2, 3};
    int n = 44100 * 10;
    std::vector<float> x(n, 0.f);
    for (int k = 0; k < 3; ++k) {
        double f = cfg.profile.open_string_hz[strings[k]] * std::pow(2.0, 5.0 / 1200.0);
        add_string(x, cfg.sample_rate, f, B[k], 0.4 + 3.0 * k, 2.4, 10 + k);
    }
    Detector d(cfg);
    d.calibrate_start();
    for (size_t o = 0; o < x.size(); o += 441) d.process(x.data() + o, std::min<size_t>(441, x.size() - o));
    CHECK(d.calibrating());
    d.calibrate_finish_now();
    CalibEvent e;
    int done = 0;
    bool finished = false;
    while (d.poll_calib_event(e)) { done += e.kind == CalibEvent::StringDone; finished |= e.kind == CalibEvent::Finished; }
    CHECK(done == 3 && finished);
    Calibration got;
    CHECK(d.take_calibration(got));
    CHECK(!d.take_calibration(got));                                    // consumed once
    CHECK(got.captured[0] && got.captured[2] && got.captured[3] && !got.captured[1] && !got.captured[4] && !got.captured[5]);
    for (int k = 0; k < 3; ++k) {
        CHECK(std::fabs(got.B[strings[k]] - B[k]) < 0.05 * B[k]);
        CHECK(std::fabs(got.cents[strings[k]] - 5.0) < 0.5);
    }
    CHECK(got.n_weights >= 6);
}

static void test_no_allocation_while_calibrating() {
    Config cfg = Config::for_instrument(InstrumentProfile::Guitar, 44100.0);
    int n = 44100 * 7;
    std::vector<float> x(n, 0.f);
    add_string(x, cfg.sample_rate, 82.41, 3e-5, 0.4, 2.4, 1);
    add_string(x, cfg.sample_rate, 196.0, 2.5e-4, 3.4, 2.4, 2);
    Detector d(cfg);
    d.process(x.data(), 44100);
    d.calibrate_start();
    d.process(x.data() + 44100, 441);                                    // the start command is consumed here
    g_allocs = 0;
    g_count_allocs = true;
    for (size_t o = 44100 + 441; o < x.size() - 4410; o += 441) d.process(x.data() + o, 441);
    d.calibrate_finish();
    d.process(x.data() + x.size() - 4410, 4410);                         // the finish command runs finalize on the audio thread
    g_count_allocs = false;
    if (g_allocs) std::printf("  allocations while calibrating: %ld\n", g_allocs);
    CHECK(g_allocs == 0);
    Calibration got;
    CHECK(d.take_calibration(got));
}

static void test_attack_requirement_and_preroll() {
    // a plucked bass note 0.1 s into the audio, before the 372 ms analysis window has filled, must still be reported
    {
        Config cfg = Config::for_instrument(InstrumentProfile::Bass, 44100.0);
        std::vector<float> x(44100 * 4, 0.f);
        add_string(x, cfg.sample_rate, 41.2, 5e-5, 0.1, 3.0, 3);
        Detector d(cfg);
        d.process(x.data(), x.size());
        NoteEvent e;
        int ons = 0, note = 0;
        while (d.poll_event(e)) if (e.on) { ++ons; note = e.midi_note; }
        CHECK(ons == 1 && note == 28);
    }
    // a plucked E2 rings; a quieter C3 swells in underneath over 0.8 s. Nothing is plucked, so the plucked guitar profile does
    // not report it; with the requirement switched off it is reported.
    for (int off = 0; off < 2; ++off) {
        Config cfg = Config::for_instrument(InstrumentProfile::Guitar, 44100.0);
        if (off) cfg.attack_min_db = 0.0;
        std::vector<float> x(44100 * 5, 0.f);
        add_string(x, cfg.sample_rate, 82.41, 1e-4, 0.3, 4.2, 4);
        for (size_t i = 0; i < x.size(); ++i) {
            double t = (double)i / cfg.sample_rate;
            if (t < 1.2) continue;
            double ramp = std::min(1.0, (t - 1.2) / 0.8), v = 0;
            for (int h = 1; h <= 20; ++h) v += std::sin(2 * M_PI * 130.81 * h * std::sqrt(1.0 + 1e-4 * h * h) * t + h) / h;
            x[i] += (float)(0.05 * ramp * v);
        }
        Detector d(cfg);
        d.process(x.data(), x.size());
        NoteEvent e;
        bool low = false, swell = false;
        while (d.poll_event(e)) if (e.on) { low |= e.midi_note == 40; swell |= e.midi_note == 48; }
        CHECK(low);
        CHECK(swell == (off == 1));
    }
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
    test_fft(); test_nnls(); test_strings(); test_detector_blocks(); test_silence(); test_profiles(); test_guitar_six_string_chord(); test_calibration_model(); test_calibration_run(); test_attack_requirement_and_preroll(); test_no_allocation_in_process();
    test_no_allocation_while_calibrating();
    std::printf(failures ? "%d FAILED\n" : "all tests passed\n", failures);
    return failures ? 1 : 0;
}
