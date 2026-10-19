// Output types (spec §9). Plain structs, fixed capacity, no allocation.
#pragma once
#include <cstdint>
#include "config.hpp"

namespace fidddle {

enum TrackState : uint8_t { INACTIVE = 0, PENDING = 1, ACTIVE = 2, RELEASING = 3 };

enum EventFlags : uint8_t {
    FLAG_RETRIGGER = 1,
    FLAG_INFERRED_RELEASE = 2,
    FLAG_WEAK_ONSET = 4,
    FLAG_STREAM_END = 8,
};

struct NoteEvent {
    bool on = false;              // true = note-on, false = note-off
    uint32_t track_id = 0;
    int slot = -1;                   // persistent voice slot (0..max_voices-1) of the track
    int midi_note = 0;
    float midi_float = 0.f;
    int velocity = 0;
    int64_t onset_est_samples = 0;   // estimated physical time of the event
    int64_t deliver_samples = 0;     // newest sample of the frame that confirmed it (§9.3)
    float confidence = 0.f;
    uint8_t flags = 0;
};

struct VoiceSnapshot {
    uint32_t track_id = 0;
    TrackState state = INACTIVE;
    float midi = 0.f;
    float frequency_hz = 0.f;
    float level_db = -120.f;
    float confidence = 0.f;
    int string_index = -1;
    int rank = -1;                // 0 = lowest sounding voice
};

struct PitchFrame {
    int64_t timestamp_samples = 0;   // newest sample covered by the frame
    uint32_t frame_index = 0;
    float onset_strength = 0.f;
    int voice_count = 0;             // number of fitted voices this frame (pre-tracking)
    VoiceSnapshot voices[MAX_VOICES];
};

struct Diagnostics {
    uint64_t frames = 0;
    double last_us = 0, max_us = 0, mean_us = 0;
    uint64_t overflow_events = 0;
};

}  // namespace fidddle
