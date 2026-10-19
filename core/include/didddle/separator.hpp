// Streaming source separator (reference: didddle/separate.py + shape.py). Takes mono audio and, through tracks(), what a
// pitch detector reports; returns one signal per voice slot plus a residual, all delayed by latency_samples(), with
//     sum(voices) + residual == delayed input     (exactly: the residual is computed as that difference).
// No detector dependency: the host (or didddle::Splitter) pushes detector frames and note events into tracks().
// Fixed buffers, no allocation after construction. Not thread-safe: call from the audio thread only.
#pragma once
#include <cstddef>
#include <cstdint>
#include <memory>
#include "config.hpp"

namespace fidddle { struct VoiceSnapshot; struct NoteEvent; }

namespace didddle {

// Cost of the separation frames (one per hop), for sizing the audio-thread burst.
struct Diagnostics {
    uint64_t frames = 0;
    double last_us = 0, max_us = 0, mean_us = 0;
};

class Separator {
public:
    // detector_half_window: samples between a detector frame's centre and its end (half the detector's long window).
    Separator(const Config& cfg, int detector_half_window);
    ~Separator();
    Separator(const Separator&) = delete;
    Separator& operator=(const Separator&) = delete;

    const Config& config() const;
    int slots() const;
    int latency_samples() const;
    void reset();
    const Diagnostics& diagnostics() const;

    // Pitch information, in input-sample time. The host must push everything the detector delivered up to the
    // current sample *before* the process() call that ends at that sample (Splitter does this).
    void push_frame(int64_t end_sample, const fidddle::VoiceSnapshot* voices);   // one entry per slot
    void push_event(const fidddle::NoteEvent& e);

    // n input samples in; n samples out per voice slot (voices[v], v < slots()) and for the residual (may be null).
    // Segments must end on detector frame boundaries whenever a frame was pushed (Splitter does this).
    void process(const double* in, size_t n, double* const* voices, double* residual);

private:
    struct Impl;
    std::unique_ptr<Impl> p_;
};

}  // namespace didddle
