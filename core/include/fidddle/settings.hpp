// Host-facing detector settings: the handful of user-adjustable values every host (Max, Pd, Bela, web) exposes as
// attributes, and how they turn into a Config. Mirrors the attribute logic of the fidddle~ external so that other hosts
// do not reimplement it; header-only, no host dependencies.
#pragma once
#include <algorithm>
#include "config.hpp"

namespace fidddle {

struct Settings {
    int profile = InstrumentProfile::Cello;
    int voices = 4;
    double minfreq = 60.0, maxfreq = 1000.0;
    bool user_voices = false, user_minfreq = false, user_maxfreq = false;   // set explicitly: profile changes keep them
    double min_level_dbfs = -58.0;
    int confirm_frames = 6;
    double release_ms = 0.0;           // 0 = the profile's own value
    double retrigger_db = 10.0;
    Calibration cal;                   // learned open-string calibration, applied when it matches the profile
    bool cal_on = false;

    Settings() {
        Config d;
        min_level_dbfs = d.min_level_dbfs;
        confirm_frames = d.confirm_frames;
        retrigger_db = d.retrigger_rise_db;
        apply_profile_defaults(false, MAX_VOICES);
    }

    // Selecting an instrument sets voices/minfreq/maxfreq to its defaults, except values the user set explicitly when
    // keep_user is true (an object box with explicit attributes: they win whatever their order).
    void apply_profile_defaults(bool keep_user, int slot_cap) {
        InstrumentProfile p = InstrumentProfile::by_id(profile);
        if (!keep_user || !user_voices) voices = std::min(p.default_voices, slot_cap);
        if (!keep_user || !user_minfreq) minfreq = p.min_frequency_hz;
        if (!keep_user || !user_maxfreq) maxfreq = p.max_frequency_hz;
        if (!keep_user) user_voices = user_minfreq = user_maxfreq = false;
    }

    void clear_calibration() { cal = Calibration{}; cal_on = false; }

    // slot_cap: how many voice slots the host can output. *clamped is set when maxfreq had to be raised.
    Config detector_config(double sample_rate, int slot_cap, bool* clamped = nullptr) const {
        Config c = Config::for_instrument(profile, sample_rate);
        c.max_voices = std::min(std::max(voices, 1), std::min(slot_cap, MAX_VOICES));
        c.profile.min_frequency_hz = minfreq;
        c.profile.max_frequency_hz = maxfreq;
        bool raised = c.profile.max_frequency_hz < 1.5 * c.profile.min_frequency_hz;
        if (raised) c.profile.max_frequency_hz = 1.5 * c.profile.min_frequency_hz;
        if (clamped) *clamped = raised;
        if (cal_on && cal.n_strings == c.profile.string_count) {
            c.calibration = cal;
            c.use_calibration = true;
        }
        c.min_level_dbfs = min_level_dbfs;
        c.confirm_frames = confirm_frames;
        c.strong_confirm_frames = std::max(2, confirm_frames * 2 / 3);
        if (release_ms > 0.0) c.unsupported_timeout_ms = std::max(50.0, release_ms);
        c.retrigger_rise_db = retrigger_db;
        return c;
    }
};

}  // namespace fidddle
