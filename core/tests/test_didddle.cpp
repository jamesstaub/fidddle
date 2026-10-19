// Tests for the didddle separator core: transform round trip, exact complementarity and latency, separation of
// synthetic voices, and no allocation in the realtime path.
#include <cmath>
#include <cstdio>
#include <cstdlib>
#include <new>
#include <random>
#include <vector>
#include "didddle/splitter.hpp"
#include "fft.hpp"

using namespace didddle;
static int failures = 0;

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

constexpr double SR = 48000.0;

static void test_fft_round_trip() {
    for (int n : {16, 64, 2048, 4096}) {
        fidddle::RealFFT fft(n);
        std::mt19937 rng(3);
        std::normal_distribution<double> nd;
        std::vector<double> x(n), y(n), re(n / 2 + 1), im(n / 2 + 1);
        for (auto& v : x) v = nd(rng);
        fft.forward(x.data(), re.data(), im.data());
        fft.inverse(re.data(), im.data(), y.data());
        double err = 0;
        for (int i = 0; i < n; ++i) err = std::max(err, std::fabs(x[i] - y[i]));
        CHECK(err < 1e-12);
    }
}

// bowed-like additive tone: partials h^-1, vibrato, linear attack
static std::vector<double> tone(double f0, double on_s, double off_s, double total_s, double vib_cents = 12.0, unsigned seed = 1) {
    std::mt19937 rng(seed);
    std::uniform_real_distribution<double> ph(0, 2 * M_PI);
    size_t n = (size_t)(total_s * SR);
    std::vector<double> x(n, 0.0);
    double phase[40];
    for (auto& p : phase) p = ph(rng);
    double cum = 0;
    for (size_t i = (size_t)(on_s * SR); i < std::min(n, (size_t)(off_s * SR)); ++i) {
        double t = (double)i / SR - on_s;
        double f = f0 * std::pow(2.0, vib_cents * std::sin(2 * M_PI * 5.5 * t) / 1200.0);
        cum += 2 * M_PI * f / SR;
        double env = std::min(1.0, t / 0.05) * std::min(1.0, (off_s - on_s - t) / 0.05);
        double y = 0;
        for (int h = 1; h <= 30; ++h) if (f0 * h < 0.45 * SR) y += std::sin(h * cum + phase[h]) / h;
        x[i] = 0.2 * env * y;
    }
    return x;
}

static double si_sdr(const std::vector<double>& est, const std::vector<double>& ref, size_t a, size_t b) {
    double er = 0, ee = 0, dot = 0;
    for (size_t i = a; i < b; ++i) { er += ref[i] * ref[i]; dot += est[i] * ref[i]; }
    double g = dot / (er + 1e-20);
    for (size_t i = a; i < b; ++i) { double d = est[i] - g * ref[i]; ee += d * d; }
    return 10 * std::log10((g * g * er + 1e-20) / (ee + 1e-20));
}

struct Run {
    std::vector<std::vector<double>> voices;
    std::vector<double> residual;
    int latency = 0;
};

static Run run(Splitter& sp, const std::vector<double>& x, size_t block) {
    int V = sp.slots();
    Run r;
    r.latency = sp.latency_samples();
    r.voices.assign(V, std::vector<double>(x.size()));
    r.residual.assign(x.size(), 0.0);
    std::vector<double*> vp(V);
    for (size_t pos = 0; pos < x.size(); pos += block) {
        size_t n = std::min(block, x.size() - pos);
        for (int v = 0; v < V; ++v) vp[v] = r.voices[v].data() + pos;
        sp.process(x.data() + pos, n, vp.data(), r.residual.data() + pos);
    }
    return r;
}

static std::vector<double> mix(const std::vector<std::vector<double>>& parts) {
    std::vector<double> m(parts[0].size(), 0.0);
    for (auto& p : parts) for (size_t i = 0; i < m.size(); ++i) m[i] += p[i];
    return m;
}

static void test_complementary_and_delayed() {
    // two notes plus noise; voices + residual must equal the input delayed by the reported latency, whatever was detected,
    // and for any host block size
    auto a = tone(130.81, 0.3, 3.0, 4.0), b = tone(196.0, 0.3, 3.0, 4.0, 12.0, 2);
    auto x = mix({a, b});
    std::mt19937 rng(9);
    std::normal_distribution<double> nd;
    for (auto& v : x) v += 0.002 * nd(rng);
    for (size_t block : {64, 500, 4096}) {
        Splitter sp(SplitterConfig::for_instrument(fidddle::InstrumentProfile::Cello, SR));
        Run r = run(sp, x, block);
        double err = 0, sound = 0;
        for (size_t i = 0; i < x.size(); ++i) {
            double s = 0;
            for (auto& v : r.voices) s += v[i];
            double want = (long)i >= r.latency ? x[i - r.latency] : 0.0;
            err = std::max(err, std::fabs(s + r.residual[i] - want));
            sound = std::max(sound, std::fabs(s));
        }
        CHECK(err < 1e-12);
        CHECK(sound > 0.05);     // notes were actually routed into voices
    }
}

static void test_all_profiles_and_rates() {
    // every stock instrument at both common rates: window/hop derived from the profile, latency on the detector grid,
    // exact complementarity, and no NaN/inf anywhere
    for (int id = 0; id < fidddle::InstrumentProfile::Count; ++id) {
        for (double sr : {44100.0, 48000.0}) {
            SplitterConfig cfg = SplitterConfig::for_instrument(id, sr);
            Splitter sp(cfg);
            CHECK(sp.slots() == std::min(cfg.detector.max_voices, MAX_VOICES));
            CHECK(sp.latency_samples() % cfg.detector.hop_size == 0 || (sp.latency_samples() - cfg.separator.derived_fft()) % cfg.detector.hop_size == 0);
            double f = cfg.detector.profile.open_string_hz[1];
            size_t n = (size_t)(3.0 * sr) + 20000;
            std::vector<double> x(n, 0.0);
            std::mt19937 rng(id);
            std::normal_distribution<double> nd;
            for (size_t i = 0; i < n; ++i) {
                double t = i / sr, env = t > 0.3 ? 1.0 : 0.0;
                x[i] = env * 0.2 * (std::sin(2 * M_PI * f * t) + 0.5 * std::sin(2 * M_PI * 2 * f * t) + 0.33 * std::sin(2 * M_PI * 3 * f * t)) + 0.002 * nd(rng);
            }
            int V = sp.slots();
            std::vector<std::vector<double>> out(V, std::vector<double>(n));
            std::vector<double> res(n);
            std::vector<double*> vp(V);
            for (size_t pos = 0; pos < n; pos += 333) {
                size_t m = std::min<size_t>(333, n - pos);
                for (int v = 0; v < V; ++v) vp[v] = out[v].data() + pos;
                sp.process(x.data() + pos, m, vp.data(), res.data() + pos);
            }
            double err = 0, peak = 0;
            bool finite = true;
            for (size_t i = 0; i < n; ++i) {
                double s = 0;
                for (int v = 0; v < V; ++v) { s += out[v][i]; finite = finite && std::isfinite(out[v][i]); }
                double want = (long)i >= sp.latency_samples() ? x[i - sp.latency_samples()] : 0.0;
                err = std::max(err, std::fabs(s + res[i] - want));
                peak = std::max(peak, std::fabs(s));
            }
            CHECK(finite);
            CHECK(err < 1e-12);
            if (err >= 1e-12 || !finite) std::printf("  profile %d sr %.0f: err %.2e\n", id, sr, err);
            std::printf("  profile %d @ %.0f Hz: window %d, latency %d samples (%.0f ms), peak voice %.2f\n", id, sr,
                        cfg.separator.derived_fft(), sp.latency_samples(), 1000.0 * sp.latency_samples() / sr, peak);
        }
    }
}

static void test_latency_modes() {
    SplitterConfig fast = SplitterConfig::for_instrument(fidddle::InstrumentProfile::Cello, SR);
    SplitterConfig fixed = fast;
    fixed.separator.latency_ms = 200.0;
    Splitter a(fast), b(fixed);
    CHECK(a.latency_samples() == 4096);                       // one window of the cello profile at 48 kHz (85 ms)
    CHECK(b.latency_samples() >= 9600 && b.latency_samples() < 9600 + 256);
    CHECK(b.latency_samples() % 256 == 0);
}

static void test_separates_a_third() {
    auto a = tone(130.81, 0.3, 3.4, 4.0), b = tone(130.81 * std::pow(2.0, 4 / 12.0), 0.3, 3.4, 4.0, 12.0, 2);
    auto x = mix({a, b});
    for (size_t block : {256, 4096}) {
        Splitter sp(SplitterConfig::for_instrument(fidddle::InstrumentProfile::Cello, SR));
        Run r = run(sp, x, block);
        // compare against the stems delayed by the latency; channel-to-stem matching by best SI-SDR
        size_t lo = (size_t)(1.0 * SR) + r.latency, hi = (size_t)(3.0 * SR) + r.latency;
        auto delayed = [&](const std::vector<double>& s) { std::vector<double> d(s.size(), 0.0); for (size_t i = r.latency; i < s.size(); ++i) d[i] = s[i - r.latency]; return d; };
        auto da = delayed(a), db = delayed(b);
        double best_a = -99, best_b = -99;
        for (auto& v : r.voices) { best_a = std::max(best_a, si_sdr(v, da, lo, hi)); best_b = std::max(best_b, si_sdr(v, db, lo, hi)); }
        std::printf("  third: stem SI-SDR %.1f / %.1f dB (block %zu)\n", best_a, best_b, block);
        CHECK(best_a > 8.0 && best_b > 8.0);
    }
}

static void test_no_allocation_in_process() {
    auto x = mix({tone(130.81, 0.3, 2.5, 3.0), tone(196.0, 0.8, 2.5, 3.0, 12.0, 2)});
    Splitter sp(SplitterConfig::for_instrument(fidddle::InstrumentProfile::Cello, SR));
    int V = sp.slots();
    std::vector<std::vector<double>> out(V, std::vector<double>(512));
    std::vector<double> res(512);
    std::vector<double*> vp(V);
    for (int v = 0; v < V; ++v) vp[v] = out[v].data();
    g_allocs = 0;
    g_count_allocs = true;
    for (size_t pos = 0; pos + 512 <= x.size(); pos += 512) sp.process(x.data() + pos, 512, vp.data(), res.data());
    g_count_allocs = false;
    CHECK(g_allocs == 0);
    if (g_allocs) std::printf("  %ld allocations in process()\n", g_allocs);
}

int main() {
    test_fft_round_trip();
    test_complementary_and_delayed();
    test_all_profiles_and_rates();
    test_latency_modes();
    test_separates_a_third();
    test_no_allocation_in_process();
    if (failures) { std::printf("%d failure(s)\n", failures); return 1; }
    std::printf("all didddle tests passed\n");
    return 0;
}
