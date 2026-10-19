// Temporal tracking, state machine and note events (spec §8).
#pragma once
#include <array>
#include <vector>
#include "fidddle/config.hpp"
#include "fidddle/types.hpp"
#include "fitter.hpp"

namespace fidddle {

class VoiceTracker {
public:
    VoiceTracker(const Config& cfg, int n_long);
    void reset();
    // Predicted pitches of live tracks (priors for candidate generation and fitting).
    int predictions(double* out, int cap) const;
    // One analysis frame. `Ms` = short-window magnitude. Events appended to `events`.
    void update(int64_t end_sample, const std::vector<FitVoice>& voices, double onset, const double* Ms,
                std::vector<NoteEvent>& events);
    void flush(int64_t end_sample, std::vector<NoteEvent>& events);
    void snapshot(VoiceSnapshot* out) const;   // MAX_VOICES entries

private:
    struct Track {
        bool used = false;
        uint32_t id = 0;
        int slot = -1;
        TrackState state = INACTIVE;
        double midi = 0, vel = 0, level_db = 0, peak_db = 0, conf = 0;
        int string = -1;
        int confirm_n = 0, miss_n = 0, age = 0, retrig_hold = 0, hold_n = 0;
        int64_t first_end = 0, best_onset_end = 0, best_rise_end = 0, last_support_end = 0;
        double best_onset = 0, best_rise = 0;
        bool has_note = false;
        int note_midi = 0;
        double hist[9];
        int hist_n = 0;
        double conf_sum = 0;
        int conf_n = 0;
    };

    bool is_multiple(double hi_midi, double lo_midi) const;
    bool harmonic_suspect(const Track& t) const;
    void push_hist(Track& t, double m);
    double velocity_of(const Track& t) const;
    double band_energy(const double* Ms, double f_hz, double offset) const;
    double rise(double f_hz, double offset) const;
    double partial_rise_db(double f_hz) const;
    void update_matched(Track& t, const FitVoice& o, int64_t end, double onset, bool strong, std::vector<NoteEvent>& ev);
    void update_missed(Track& t, int64_t end, std::vector<NoteEvent>& ev);
    void maybe_confirm(Track& t, int64_t end, bool strong, std::vector<NoteEvent>& ev);
    int velocity_midi(double level_db) const;

    const Config& cfg_;
    int n_long_;
    double df_s_, hop_ms_, dt_;
    int nbins_s_;
    std::array<Track, MAX_VOICES> tracks_;
    uint32_t next_id_ = 1;
    std::vector<double> dp_;      // assignment DP scratch
    std::vector<int> choice_;
    // short-window magnitude history (ring)
    std::vector<std::vector<double>> ms_;
    int ms_head_ = 0, ms_count_ = 0, ms_cap_;
};

}  // namespace fidddle
