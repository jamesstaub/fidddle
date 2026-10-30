// Plain C interface over fidddle::Detector for the WebAssembly build (WEBAUDIO_DESIGN.md section 3). All memory is
// allocated in fid_create; the exported functions never throw and never allocate while processing.
#include <cmath>
#include <cstring>
#include <new>
#include "fidddle/detector.hpp"
#include "fidddle/settings.hpp"
#include "fidddle/version.hpp"

#ifdef __EMSCRIPTEN__
#include <emscripten.h>
#define FID_EXPORT extern "C" EMSCRIPTEN_KEEPALIVE
#else
#define FID_EXPORT extern "C"
#endif

using namespace fidddle;

namespace {

constexpr int VOICE_FIELDS = 6;     // frequency, level (linear), state, confidence, rank, note
constexpr int EVENT_FIELDS = 11;    // see fid_poll_event
constexpr int CALIB_FIELDS = 10;    // see fid_poll_calib_event
constexpr int MAX_BLOCK = 4096;
const char* g_error = "";

struct Handle {
    Detector det;
    double sample_rate;
    int max_voices;
    double input[MAX_BLOCK];
    double scratch[Calibration::LIST_CAP > 32 ? Calibration::LIST_CAP : 32];   // event and calibration output
    float voices[MAX_VOICES * VOICE_FIELDS];
    explicit Handle(const Config& c) : det(c), sample_rate(c.sample_rate), max_voices(c.max_voices) {
        std::memset(voices, 0, sizeof voices);
    }
};

}  // namespace


FID_EXPORT const char* fid_last_error() { return g_error; }
FID_EXPORT const char* fid_version() { return fidddle::version(); }
FID_EXPORT int fid_voice_fields() { return VOICE_FIELDS; }
FID_EXPORT int fid_event_fields() { return EVENT_FIELDS; }
FID_EXPORT int fid_calib_fields() { return CALIB_FIELDS; }
FID_EXPORT int fid_max_block() { return MAX_BLOCK; }
FID_EXPORT int fid_calibration_capacity() { return Calibration::LIST_CAP; }

// Returns null when the settings are rejected (fid_last_error says why) or memory runs out.
// profile: 0 bass, 1 cello, 2 viola, 3 violin, 4 guitar, 5 contrabass. voices 0 = the profile's default.
// calibration: the flat list from fid_take_calibration (n values), or null/0 for none. The detector takes its
// calibration at construction, as in the Max object; a new calibration means a new detector.
FID_EXPORT void* fid_create(int profile, double sample_rate, int voices, int efficient, const double* calibration, int n) {
    g_error = "";
    if (profile < 0 || profile >= InstrumentProfile::Count) { g_error = "unknown profile"; return nullptr; }
    {
        Settings s;
        s.profile = profile;
        s.efficient = efficient != 0;
        s.apply_profile_defaults(false, MAX_VOICES);
        if (voices > 0) s.voices = voices;
        if (calibration && n > 0) {
            if (n > Calibration::LIST_CAP || !Calibration::from_list(calibration, n, s.cal)) { g_error = "calibration list rejected"; return nullptr; }
            s.cal_on = true;
        }
        Config c = s.detector_config(sample_rate, MAX_VOICES);
        c.string_id = false;
        // The WebAssembly build has no exception support; check() reports what the Detector constructor would throw.
        if (const char* why = c.check()) { g_error = why; return nullptr; }
        return new (std::nothrow) Handle(c);
    }
}

FID_EXPORT void fid_destroy(void* h) { delete static_cast<Handle*>(h); }
FID_EXPORT void fid_reset(void* h) { static_cast<Handle*>(h)->det.reset(); }
FID_EXPORT int fid_hop_size(void* h) { return static_cast<Handle*>(h)->det.config().hop_size; }
FID_EXPORT int fid_voice_count(void* h) { return static_cast<Handle*>(h)->max_voices; }

// The buffer the host copies a block of mono samples into (fid_max_block() doubles).
FID_EXPORT double* fid_input(void* h) { return static_cast<Handle*>(h)->input; }

// A buffer the host passes to fid_poll_event, fid_poll_calib_event and fid_take_calibration (fid_calibration_capacity() doubles).
FID_EXPORT double* fid_scratch(void* h) { return static_cast<Handle*>(h)->scratch; }

// Processes n samples from the input buffer. Returns the number of analysis steps completed.
FID_EXPORT int fid_process(void* h, int n) {
    Handle* s = static_cast<Handle*>(h);
    if (n < 0) n = 0;
    if (n > MAX_BLOCK) n = MAX_BLOCK;
    uint64_t seen = s->det.diagnostics().frames;
    s->det.process(s->input, (size_t)n);
    return (int)(s->det.diagnostics().frames - seen);
}

FID_EXPORT void fid_flush(void* h) { static_cast<Handle*>(h)->det.flush(); }

// Latest analysis step, per voice slot: frequency Hz, level (linear amplitude), state (0 inactive, 1 pending,
// 2 active, 3 releasing), confidence, rank (0 = lowest sounding voice, -1 none), midi note (float).
FID_EXPORT const float* fid_voices(void* h) {
    Handle* s = static_cast<Handle*>(h);
    const PitchFrame& f = s->det.latest();
    for (int i = 0; i < s->max_voices; ++i) {
        const VoiceSnapshot& v = f.voices[i];
        float* o = s->voices + i * VOICE_FIELDS;
        o[0] = v.frequency_hz;
        o[1] = v.state == INACTIVE ? 0.f : std::pow(10.f, v.level_db / 20.f);
        o[2] = (float)v.state;
        o[3] = v.confidence;
        o[4] = (float)v.rank;
        o[5] = v.midi;
    }
    return s->voices;
}

// Writes one note event: on (1/0), track id, slot, note, midiFloat, velocity, onset sample (low, high words are not
// needed below 2^53, so a double), deliver sample, confidence, flags. Returns 1 if an event was written.
FID_EXPORT int fid_poll_event(void* h, double* out) {
    NoteEvent e;
    if (!static_cast<Handle*>(h)->det.poll_event(e)) return 0;
    out[0] = e.on ? 1 : 0;
    out[1] = e.track_id;
    out[2] = e.slot;
    out[3] = e.midi_note;
    out[4] = e.midi_float;
    out[5] = e.velocity;
    out[6] = (double)e.onset_est_samples;
    out[7] = (double)e.deliver_samples;
    out[8] = e.confidence;
    out[9] = e.flags;
    out[10] = 0;
    return 1;
}

// kind (Started 0, Progress 1, StringDone 2, Complete 3, Finished 4, Cancelled 5, Unavailable 6), string, frames,
// needed, f0 Hz, cents, B, captured, total, 0.
FID_EXPORT int fid_poll_calib_event(void* h, double* out) {
    CalibEvent e;
    if (!static_cast<Handle*>(h)->det.poll_calib_event(e)) return 0;
    out[0] = e.kind; out[1] = e.string; out[2] = e.frames; out[3] = e.needed; out[4] = e.f0_hz;
    out[5] = e.cents; out[6] = e.B; out[7] = e.captured; out[8] = e.total; out[9] = 0;
    return 1;
}

// command: 0 start, 1 finish (use the strings captured so far), 2 cancel, 3 finish now (offline).
FID_EXPORT void fid_calibrate(void* h, int command) {
    Detector& d = static_cast<Handle*>(h)->det;
    switch (command) {
        case 0: d.calibrate_start(); break;
        case 1: d.calibrate_finish(); break;
        case 2: d.calibrate_cancel(); break;
        case 3: d.calibrate_finish_now(); break;
    }
}

// Writes the finished calibration as the flat list (fid_calibration_capacity() doubles). Returns the number of
// values written, 0 if there is none.
FID_EXPORT int fid_take_calibration(void* h, double* out) {
    Calibration c;
    if (!static_cast<Handle*>(h)->det.take_calibration(c)) return 0;
    return c.to_list(out);
}
