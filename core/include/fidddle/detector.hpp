// Public interface of the portable core (spec §10): no Max, no OS audio headers.
#pragma once
#include <atomic>
#include <cstddef>
#include <functional>
#include <memory>
#include <vector>
#include "config.hpp"
#include "types.hpp"

namespace fidddle {

struct FitVoiceInfo {
    double f_hz, midi, gain, confidence, level_db;
    int string_index;
};

// Per-analysis-frame debug view (CLI / tests only; null hook in realtime use).
struct FrameDebug {
    uint32_t frame_index;
    int64_t end_sample;
    double onset;
    std::vector<FitVoiceInfo> fit_voices;
    const VoiceSnapshot* tracks;      // MAX_VOICES entries
    const NoteEvent* events;
    int n_events;
    int n_peaks, n_cands;
    double us;                        // analysis time of this frame
};

class Detector {
public:
    explicit Detector(const Config& cfg);
    ~Detector();
    Detector(const Detector&) = delete;
    Detector& operator=(const Detector&) = delete;

    const Config& config() const;
    int long_fft_size() const;
    void reset();

    // Mono PCM, any block size. Runs analysis inline each time a hop completes.
    void process(const double* in, size_t n);
    void process(const float* in, size_t n);
    void flush();   // close open notes (end of stream)

    // Bounded, non-blocking output (single producer = process(), single consumer).
    bool poll_event(NoteEvent& out);
    // The string a note was played on, a little after its note-on (guitar profile with a calibration that has string values).
    bool poll_string(StringEvent& out);

    // ---- open-string calibration (spec §12.3) -----------------------------------------------------------------
    // Commands may be sent from any thread; the audio thread acts on them at the next analysis frame. While
    // calibrating, only clean single notes near an open string contribute; other playing is ignored.
    void calibrate_start();
    void calibrate_finish();                    // use the strings captured so far
    void calibrate_cancel();
    void calibrate_finish_now();                // offline/non-realtime: finish immediately on the calling thread
    bool calibrating() const;
    bool poll_calib_event(CalibEvent& out);     // progress, string captured, complete, finished
    bool take_calibration(Calibration& out);    // true once after a successful finish; apply it via Config::calibration
    const PitchFrame& latest() const;
    const Diagnostics& diagnostics() const;
    int64_t samples_processed() const;

    std::function<void(const FrameDebug&)> debug_hook;

private:
    struct Impl;
    std::unique_ptr<Impl> p_;
};

}  // namespace fidddle
