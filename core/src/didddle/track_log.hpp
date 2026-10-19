// What the pitch detector has reported so far, kept just long enough for the separator (didddle/f0.py:
// tracks_from_run / spans_from_run). Everything stored has already been delivered, so "what could be known at time T" is
// simply "what is in the log". Fixed rings, no allocation after construction.
#pragma once
#include <cstdint>
#include <limits>
#include <vector>
#include "fidddle/types.hpp"

namespace didddle {

constexpr int64_t NEVER = std::numeric_limits<int64_t>::max();

struct NoteSpan {
    uint32_t track_id = 0;
    int64_t on_est = 0, on_del = 0;        // estimated physical onset; frame time at which the note was confirmed
    int64_t off_est = NEVER, off_del = NEVER;   // NEVER while the note is still open
    bool open() const { return off_del == NEVER; }
};

class TrackLog {
public:
    // half_window: samples between a detector frame's centre and its end (half the detector's long window).
    TrackLog(int slots, int half_window);
    void reset();

    void push_frame(int64_t end_sample, const fidddle::VoiceSnapshot* voices);   // one entry per slot
    void push_event(const fidddle::NoteEvent& e);

    // Pitch of `slot` around sample c, or 0 if it has no note there. Uses the analysis frame nearest in time to c among
    // those where the slot was sounding, if c lies within `margin` samples of that note's estimated span.
    double f0_at(int slot, int64_t c, int64_t margin) const;

    // Note spans of a slot, newest first.
    int span_count(int slot) const { return spans_n_[slot]; }
    const NoteSpan& span(int slot, int i) const { return spans_[(size_t)slot * SPAN_CAP + (spans_head_[slot] - 1 - i + SPAN_CAP) % SPAN_CAP]; }

    static constexpr int FRAME_CAP = 1024;   // ~5 s of detector frames at 256-sample hops, 48 kHz
    static constexpr int SPAN_CAP = 32;

private:
    struct Active { int64_t end; uint32_t tid; float f_hz; };
    const Active& frame(int slot, int i) const { return frames_[(size_t)slot * FRAME_CAP + (fr_head_[slot] - fr_n_[slot] + i + FRAME_CAP) % FRAME_CAP]; }

    int slots_, half_;
    std::vector<Active> frames_;
    std::vector<int> fr_head_, fr_n_;
    std::vector<NoteSpan> spans_;
    std::vector<int> spans_head_, spans_n_;
};

}  // namespace didddle
