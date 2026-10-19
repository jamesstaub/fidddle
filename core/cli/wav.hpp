// Minimal WAV reader (PCM 16/24/32, float 32/64, WAVE_FORMAT_EXTENSIBLE) for the CLI and tests.
#pragma once
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <string>
#include <vector>

struct WavData {
    int channels = 0, sample_rate = 0;
    std::vector<double> samples;   // interleaved, scaled to [-1,1)
    size_t frames() const { return channels ? samples.size() / channels : 0; }
};

inline bool read_wav(const std::string& path, WavData& out, std::string& err) {
    FILE* f = std::fopen(path.c_str(), "rb");
    if (!f) { err = "cannot open " + path; return false; }
    auto rd32 = [&](uint32_t& v) { return std::fread(&v, 4, 1, f) == 1; };
    char id[4];
    uint32_t sz;
    if (std::fread(id, 1, 4, f) != 4 || std::memcmp(id, "RIFF", 4) || !rd32(sz) || std::fread(id, 1, 4, f) != 4 || std::memcmp(id, "WAVE", 4)) {
        err = "not a RIFF/WAVE file"; std::fclose(f); return false;
    }
    int fmt_tag = 0, bits = 0;
    bool have_fmt = false;
    std::vector<uint8_t> data;
    while (std::fread(id, 1, 4, f) == 4 && rd32(sz)) {
        if (!std::memcmp(id, "fmt ", 4)) {
            std::vector<uint8_t> b(sz);
            if (std::fread(b.data(), 1, sz, f) != sz) break;
            fmt_tag = b[0] | (b[1] << 8);
            out.channels = b[2] | (b[3] << 8);
            out.sample_rate = b[4] | (b[5] << 8) | (b[6] << 16) | (b[7] << 24);
            bits = b[14] | (b[15] << 8);
            if (fmt_tag == 0xFFFE && sz >= 26) fmt_tag = b[24] | (b[25] << 8);
            have_fmt = true;
        } else if (!std::memcmp(id, "data", 4)) {
            data.resize(sz);
            size_t got = std::fread(data.data(), 1, sz, f);
            data.resize(got);
            break;
        } else {
            std::fseek(f, (long)sz, SEEK_CUR);
        }
        if (sz & 1) std::fseek(f, 1, SEEK_CUR);
    }
    std::fclose(f);
    if (!have_fmt || data.empty()) { err = "missing fmt/data"; return false; }
    int bps = bits / 8;
    size_t n = data.size() / bps;
    out.samples.resize(n);
    for (size_t i = 0; i < n; ++i) {
        const uint8_t* p = &data[i * bps];
        double v = 0;
        if (fmt_tag == 1) {
            if (bits == 16) v = (int16_t)(p[0] | (p[1] << 8)) / 32768.0;
            else if (bits == 24) { int32_t s = (p[0] << 8) | (p[1] << 16) | ((int32_t)p[2] << 24); v = (s >> 8) / 8388608.0; }
            else if (bits == 32) { int32_t s; std::memcpy(&s, p, 4); v = s / 2147483648.0; }
            else { err = "unsupported PCM depth"; return false; }
        } else if (fmt_tag == 3) {
            if (bits == 32) { float x; std::memcpy(&x, p, 4); v = x; }
            else if (bits == 64) { double x; std::memcpy(&x, p, 8); v = x; }
            else { err = "unsupported float depth"; return false; }
        } else { err = "unsupported WAV format"; return false; }
        out.samples[i] = v;
    }
    return true;
}
