// fidddle_cli in.wav [--profile bass|cello|viola|violin|guitar|0-4] [--channel N] [--block N] [--frames] [--set key=value ...]
// Emits JSON lines: one per analysis frame (with --frames) and one per note event, plus a summary.
#include <chrono>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <string>
#include <utility>
#include <vector>
#include "fidddle/detector.hpp"
#include "wav.hpp"

using namespace fidddle;

static bool set_param(Config& c, const std::string& k, double v) {
#define P(name) if (k == #name) { c.name = (decltype(c.name))v; return true; }
    P(confirm_frames) P(strong_confirm_frames) P(first_voice_min_gain) P(dup_extra_gain) P(min_level_dbfs)
    P(retrigger_rise_db) P(peak_min_w) P(peak_min_snr) P(noise_kappa) P(max_voices) P(hop_size) P(confirm_min_conf)
    P(min_voice_sep_cents) P(unsupported_timeout_ms) P(release_hang_ms) P(dup_extra_gain) P(inharm_tol_B) P(fit_band_hz) P(fit_max_harmonics) P(attack_min_db) P(string_id) P(quiet_snr_db) P(quiet_floor_dbfs) P(harmonic_tol) P(birth_hist_frames) P(pending_timeout_frames) P(octave_hold_frames) P(harmonic_confirm_frames)
    if (k == "inharmonicity_B") { c.profile.inharmonicity_B = v; return true; }
    if (k == "window_periods") { c.profile.window_periods = v; return true; }
    if (k == "minfreq") { c.profile.min_frequency_hz = v; return true; }
    if (k == "maxfreq") { c.profile.max_frequency_hz = v; return true; }
    if (k == "voice_gain") { for (auto& g : c.voice_gain) g = v; c.voice_gain[0] = 0.0; return true; }
#undef P
    return false;
}

int main(int argc, char** argv) {
    if (argc < 2) { std::fprintf(stderr, "usage: %s in.wav [--channel N] [--block N] [--frames] [--set k=v]\n", argv[0]); return 2; }
    std::string path = argv[1];
    int channel = 0, block = 512, profile_id = InstrumentProfile::Cello;
    bool frames = false, calibrate = false;
    std::string calibration_csv;
    std::vector<std::pair<std::string, double>> overrides;
    for (int i = 2; i < argc; ++i) {
        std::string a = argv[i];
        if (a == "--channel" && i + 1 < argc) channel = std::atoi(argv[++i]);
        else if (a == "--block" && i + 1 < argc) block = std::atoi(argv[++i]);
        else if (a == "--frames") frames = true;
        else if (a == "--calibrate") calibrate = true;
        else if (a == "--minfreq" && i + 1 < argc) overrides.emplace_back("minfreq", std::atof(argv[++i]));
        else if (a == "--maxfreq" && i + 1 < argc) overrides.emplace_back("maxfreq", std::atof(argv[++i]));
        else if (a == "--voices" && i + 1 < argc) overrides.emplace_back("max_voices", std::atof(argv[++i]));
        else if (a == "--calibration" && i + 1 < argc) calibration_csv = argv[++i];
        else if (a == "--profile" && i + 1 < argc) {
            std::string v = argv[++i];
            const char* names[] = {"bass", "cello", "viola", "violin", "guitar"};
            profile_id = -1;
            for (int k = 0; k < 5; ++k) if (v == names[k] || v == std::to_string(k)) profile_id = k;
            if (profile_id < 0) { std::fprintf(stderr, "unknown profile %s\n", v.c_str()); return 2; }
        }
        else if (a == "--set" && i + 1 < argc) {
            std::string kv = argv[++i];
            auto eq = kv.find('=');
            if (eq == std::string::npos) { std::fprintf(stderr, "bad --set %s\n", kv.c_str()); return 2; }
            overrides.emplace_back(kv.substr(0, eq), std::atof(kv.c_str() + eq + 1));
        }
    }
    WavData w;
    std::string err;
    if (!read_wav(path, w, err)) { std::fprintf(stderr, "%s\n", err.c_str()); return 1; }
    if (channel >= w.channels) { std::fprintf(stderr, "channel out of range\n"); return 1; }
    Config cfg = Config::for_instrument(profile_id, w.sample_rate);
    for (auto& kv : overrides)
        if (!set_param(cfg, kv.first, kv.second)) { std::fprintf(stderr, "bad --set %s\n", kv.first.c_str()); return 2; }
    std::vector<double> x(w.frames());
    for (size_t i = 0; i < x.size(); ++i) x[i] = w.samples[i * w.channels + channel];

    if (!calibration_csv.empty()) {
        double v[Calibration::LIST_CAP];
        int n = 0;
        const char* c = calibration_csv.c_str();
        while (*c && n < Calibration::LIST_CAP) { char* end; v[n++] = std::strtod(c, &end); if (end == c) break; c = end; if (*c == ',') ++c; }
        if (!Calibration::from_list(v, n, cfg.calibration)) { std::fprintf(stderr, "bad --calibration list\n"); return 2; }
        cfg.use_calibration = true;
    }
    Detector det(cfg);
    if (calibrate) det.calibrate_start();
    auto jevent = [](const NoteEvent& e) {
        std::printf("{\"ev\":\"%s\",\"id\":%u,\"midi\":%d,\"vel\":%d,\"onset\":%lld,\"deliver\":%lld,\"flags\":%d}\n", e.on ? "on" : "off",
                    e.track_id, e.midi_note, e.velocity, (long long)e.onset_est_samples, (long long)e.deliver_samples, e.flags);
    };
    if (frames) {
        det.debug_hook = [&](const FrameDebug& d) {
            if (d.n_events == 0 && d.end_sample == 0) return;
            std::printf("{\"f\":%u,\"end\":%lld,\"onset\":%.6f,\"us\":%.0f,\"peaks\":%d,\"cands\":%d,\"fit\":[", d.frame_index, (long long)d.end_sample, d.onset, d.us, d.n_peaks, d.n_cands);
            for (size_t i = 0; i < d.fit_voices.size(); ++i)
                std::printf("%s[%.6f,%.6f,%.6f]", i ? "," : "", d.fit_voices[i].midi, d.fit_voices[i].level_db, d.fit_voices[i].confidence);
            std::printf("],\"tracks\":[");
            bool first = true;
            for (int i = 0; i < MAX_VOICES; ++i)
                if (d.tracks[i].state != INACTIVE) {
                    std::printf("%s[%u,%d,%.6f]", first ? "" : ",", d.tracks[i].track_id, (int)d.tracks[i].state, d.tracks[i].midi);
                    first = false;
                }
            std::printf("]}\n");
        };
    }
    auto jstring = [](const StringEvent& e) {
        std::printf("{\"ev\":\"string\",\"id\":%u,\"slot\":%d,\"midi\":%d,\"string\":%d,\"margin\":%.3f,\"deliver\":%lld}\n", e.track_id, e.slot,
                    e.midi_note, e.string, (double)e.margin, (long long)e.deliver_samples);
    };
    auto t0 = std::chrono::steady_clock::now();
    for (size_t off = 0; off < x.size(); off += block) {
        det.process(x.data() + off, std::min<size_t>(block, x.size() - off));
        NoteEvent e;
        while (det.poll_event(e)) jevent(e);
        StringEvent se;
        while (det.poll_string(se)) jstring(se);
    }
    if (calibrate) det.calibrate_finish_now();
    det.flush();
    NoteEvent e;
    while (det.poll_event(e)) jevent(e);
    StringEvent se;
    while (det.poll_string(se)) jstring(se);
    CalibEvent ce;
    while (det.poll_calib_event(ce)) {
        const char* names[] = {"started", "progress", "string", "complete", "finished", "cancelled"};
        std::printf("{\"cal\":\"%s\",\"string\":%d,\"frames\":%d,\"f0\":%.6f,\"cents\":%.6f,\"B\":%.9g,\"captured\":%d,\"total\":%d}\n",
                    names[ce.kind], ce.string, ce.frames, ce.f0_hz, ce.cents, ce.B, ce.captured, ce.total);
    }
    Calibration cal;
    if (calibrate && det.take_calibration(cal)) {
        double v[Calibration::LIST_CAP];
        int n = cal.to_list(v);
        std::printf("{\"calibration\":[");
        for (int i = 0; i < n; ++i) std::printf("%s%.9g", i ? "," : "", v[i]);
        std::printf("]}\n");
    }
    double secs = std::chrono::duration<double>(std::chrono::steady_clock::now() - t0).count();
    const auto& dg = det.diagnostics();
    std::printf("{\"summary\":true,\"sr\":%d,\"samples\":%zu,\"frames\":%llu,\"mean_us\":%.1f,\"max_us\":%.1f,\"hop_us\":%.1f,\"overflow\":%llu,\"realtime_x\":%.1f}\n",
                w.sample_rate, x.size(), (unsigned long long)dg.frames, dg.mean_us, dg.max_us, 1e6 * cfg.hop_size / cfg.sample_rate,
                (unsigned long long)dg.overflow_events, (x.size() / (double)w.sample_rate) / secs);
    return 0;
}
