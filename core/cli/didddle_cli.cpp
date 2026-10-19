// didddle_cli in.wav out_prefix [--profile bass|cello|viola|violin|guitar|0-4] [--channel N] [--block N]
//                              [--latency MS] [--transient MS] [--voices N] [--set key=value ...]
// Writes out_prefix.voice<N>.wav for every voice slot and out_prefix.residual.wav, all delayed by the reported latency
// (so  sum(voices) + residual == input shifted by `latency` samples), and prints a one-line JSON summary.
#include <chrono>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <string>
#include <vector>
#include "didddle/splitter.hpp"
#include "wav.hpp"

static bool write_wav(const std::string& path, const std::vector<double>& x, int sr) {
    FILE* f = std::fopen(path.c_str(), "wb");
    if (!f) return false;
    uint32_t n = (uint32_t)x.size(), bytes = n * 4, v;
    auto w32 = [&](uint32_t a) { std::fwrite(&a, 4, 1, f); };
    auto w16 = [&](uint16_t a) { std::fwrite(&a, 2, 1, f); };
    std::fwrite("RIFF", 1, 4, f); w32(36 + bytes); std::fwrite("WAVEfmt ", 1, 8, f);
    w32(16); w16(3); w16(1); w32((uint32_t)sr); w32((uint32_t)sr * 4); w16(4); w16(32);
    std::fwrite("data", 1, 4, f); w32(bytes);
    for (double d : x) { float s = (float)d; std::fwrite(&s, 4, 1, f); }
    (void)v;
    std::fclose(f);
    return true;
}

int main(int argc, char** argv) {
    if (argc < 3) { std::fprintf(stderr, "usage: %s in.wav out_prefix [--profile P] [--channel N] [--block N] [--latency MS] [--transient MS] [--voices N]\n", argv[0]); return 2; }
    std::string path = argv[1], prefix = argv[2];
    int channel = 0, block = 512, profile_id = fidddle::InstrumentProfile::Cello, voices = 0;
    double latency_ms = 0.0, transient_ms = -1.0;
    for (int i = 3; i < argc; ++i) {
        std::string a = argv[i];
        if (a == "--channel" && i + 1 < argc) channel = std::atoi(argv[++i]);
        else if (a == "--block" && i + 1 < argc) block = std::atoi(argv[++i]);
        else if (a == "--latency" && i + 1 < argc) latency_ms = std::atof(argv[++i]);
        else if (a == "--transient" && i + 1 < argc) transient_ms = std::atof(argv[++i]);
        else if (a == "--voices" && i + 1 < argc) voices = std::atoi(argv[++i]);
        else if (a == "--profile" && i + 1 < argc) {
            std::string v = argv[++i];
            const char* names[] = {"bass", "cello", "viola", "violin", "guitar"};
            profile_id = -1;
            for (int k = 0; k < 5; ++k) if (v == names[k] || v == std::to_string(k)) profile_id = k;
            if (profile_id < 0) { std::fprintf(stderr, "unknown profile %s\n", v.c_str()); return 2; }
        }
    }
    WavData wav;
    std::string err;
    if (!read_wav(path, wav, err)) { std::fprintf(stderr, "%s\n", err.c_str()); return 1; }
    size_t n = wav.frames();
    std::vector<double> x(n);
    for (size_t i = 0; i < n; ++i) x[i] = wav.samples[i * wav.channels + std::min(channel, wav.channels - 1)];

    didddle::SplitterConfig cfg = didddle::SplitterConfig::for_instrument(profile_id, wav.sample_rate);
    if (voices > 0) { cfg.detector.max_voices = voices; cfg.finalize(); }
    cfg.separator.latency_ms = latency_ms;
    if (transient_ms >= 0) cfg.separator.transient_ms = transient_ms;
    didddle::Splitter sp(cfg);
    int V = sp.slots(), L = sp.latency_samples();
    std::vector<std::vector<double>> out(V, std::vector<double>(n));
    std::vector<double> res(n);
    std::vector<double*> vp(V);
    auto t0 = std::chrono::steady_clock::now();
    for (size_t pos = 0; pos < n; pos += (size_t)block) {
        size_t m = std::min((size_t)block, n - pos);
        for (int v = 0; v < V; ++v) vp[v] = out[v].data() + pos;
        sp.process(x.data() + pos, m, vp.data(), res.data() + pos);
    }
    double secs = std::chrono::duration<double>(std::chrono::steady_clock::now() - t0).count();
    for (int v = 0; v < V; ++v) write_wav(prefix + ".voice" + std::to_string(v) + ".wav", out[v], wav.sample_rate);
    write_wav(prefix + ".residual.wav", res, wav.sample_rate);
    const auto& d = sp.detector().diagnostics();
    std::printf("{\"profile\":%d,\"voices\":%d,\"sample_rate\":%d,\"latency_samples\":%d,\"latency_ms\":%.2f,\"frames\":%zu,"
                "\"seconds\":%.3f,\"realtime_factor\":%.2f,\"detector_mean_us\":%.1f,\"detector_max_us\":%.1f,"
                "\"separator_mean_us\":%.1f,\"separator_max_us\":%.1f,\"separator_period_us\":%.0f}\n",
                profile_id, V, wav.sample_rate, L, 1000.0 * L / wav.sample_rate, n, secs, secs > 0 ? (n / (double)wav.sample_rate) / secs : 0.0,
                d.mean_us, d.max_us, sp.separator_diagnostics().mean_us, sp.separator_diagnostics().max_us,
                1e6 * cfg.separator.derived_hop() / wav.sample_rate);
    return 0;
}
