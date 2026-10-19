#include "track_log.hpp"
#include <algorithm>
#include <cstdlib>

namespace didddle {

TrackLog::TrackLog(int slots, int half_window)
    : slots_(slots), half_(half_window), frames_((size_t)slots * FRAME_CAP), fr_head_(slots, 0), fr_n_(slots, 0),
      spans_((size_t)slots * SPAN_CAP), spans_head_(slots, 0), spans_n_(slots, 0) {}

void TrackLog::reset() {
    std::fill(fr_head_.begin(), fr_head_.end(), 0);
    std::fill(fr_n_.begin(), fr_n_.end(), 0);
    std::fill(spans_head_.begin(), spans_head_.end(), 0);
    std::fill(spans_n_.begin(), spans_n_.end(), 0);
}

void TrackLog::push_frame(int64_t end, const fidddle::VoiceSnapshot* voices) {
    for (int s = 0; s < slots_; ++s) {
        const auto& v = voices[s];
        if (v.state != fidddle::ACTIVE && v.state != fidddle::RELEASING) continue;
        frames_[(size_t)s * FRAME_CAP + fr_head_[s]] = {end, v.track_id, v.frequency_hz};
        fr_head_[s] = (fr_head_[s] + 1) % FRAME_CAP;
        fr_n_[s] = std::min(fr_n_[s] + 1, FRAME_CAP);
    }
}

void TrackLog::push_event(const fidddle::NoteEvent& e) {
    int s = e.slot;
    if (s < 0 || s >= slots_) return;
    if (e.on) {
        NoteSpan sp;
        sp.track_id = e.track_id; sp.on_est = e.onset_est_samples; sp.on_del = e.deliver_samples;
        spans_[(size_t)s * SPAN_CAP + spans_head_[s]] = sp;
        spans_head_[s] = (spans_head_[s] + 1) % SPAN_CAP;
        spans_n_[s] = std::min(spans_n_[s] + 1, SPAN_CAP);
    } else {
        for (int i = 0; i < spans_n_[s]; ++i) {       // close the newest open span of this track
            NoteSpan& sp = const_cast<NoteSpan&>(span(s, i));
            if (sp.track_id == e.track_id && sp.open()) { sp.off_est = e.onset_est_samples; sp.off_del = e.deliver_samples; break; }
        }
    }
}

double TrackLog::f0_at(int slot, int64_t c, int64_t margin) const {
    int n = fr_n_[slot];
    if (n == 0) return 0.0;
    const int64_t target = c + half_;                  // the end of a frame centred on c
    int lo = 0, hi = n;                                // first frame with end >= target
    while (lo < hi) {
        int mid = (lo + hi) / 2;
        if (frame(slot, mid).end < target) lo = mid + 1; else hi = mid;
    }
    int best = lo;
    if (lo == n) best = n - 1;
    else if (lo > 0 && target - frame(slot, lo - 1).end < frame(slot, lo).end - target) best = lo - 1;
    const Active& f = frame(slot, best);
    for (int i = 0; i < spans_n_[slot]; ++i) {
        const NoteSpan& sp = span(slot, i);
        if (sp.track_id != f.tid) continue;
        if (c >= sp.on_est - margin && (sp.open() || c <= sp.off_est + margin)) return f.f_hz;
    }
    return 0.0;
}

}  // namespace didddle
