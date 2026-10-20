#include "tracker.hpp"
#include <algorithm>
#include <cmath>

namespace fidddle {

VoiceTracker::VoiceTracker(const Config& cfg, int n_long)
    : cfg_(cfg), n_long_(n_long), df_s_(cfg.sample_rate / cfg.short_fft_size), hop_ms_(1000.0 * cfg.hop_size / cfg.sample_rate),
      dt_((double)cfg.hop_size / cfg.sample_rate), nbins_s_(cfg.short_fft_size / 2 + 1),
      ms_cap_(std::max(cfg.onset_hist_frames, cfg.birth_hist_frames) + 1) {
    ms_.assign(ms_cap_, std::vector<double>(nbins_s_, 0.0));
    edb_.assign(ms_cap_, -120.0);
    dp_.resize((size_t)(MAX_VOICES + 1) << (MAX_VOICES + 2));
    choice_.resize(dp_.size());
}

void VoiceTracker::reset() {
    for (auto& t : tracks_) t = Track{};
    next_id_ = 1;
    ms_head_ = ms_count_ = 0;
    edb_head_ = edb_count_ = 0;
}

int VoiceTracker::predictions(double* out, int cap) const {
    int n = 0;
    for (int i = 0; i < cfg_.max_voices && n < cap; ++i) {
        const Track& t = tracks_[i];
        if (t.used && t.state != INACTIVE) out[n++] = std::clamp(t.midi + t.vel * dt_, 0.0, 127.0);
    }
    return n;
}

bool VoiceTracker::is_multiple(double hi_midi, double lo_midi) const {
    double r = std::pow(2.0, (hi_midi - lo_midi) / 12.0);
    double n = std::nearbyint(r);
    return n >= 2 && std::fabs(r / n - 1.0) <= cfg_.harmonic_tol;
}

// A pending note that looks like a partial (or sub-octave ghost) of another live note. Of two harmonically related
// notes the weaker is suspect; if they are within 3 dB the higher one is.
bool VoiceTracker::harmonic_suspect(const Track& t) const {
    for (int i = 0; i < MAX_VOICES; ++i) {
        const Track& o = tracks_[i];
        if (!o.used || &o == &t || o.state == INACTIVE) continue;
        const Track& lo = o.midi < t.midi ? o : t;
        const Track& hi = o.midi < t.midi ? t : o;
        if (!is_multiple(hi.midi, lo.midi)) continue;
        if (std::fabs(t.level_db - o.level_db) > 3.0) {
            if (t.level_db < o.level_db) return true;
        } else if (&t == &hi) {
            return true;
        }
    }
    return false;
}

void VoiceTracker::push_hist(Track& t, double m) {
    if (t.hist_n == 9) {
        for (int i = 1; i < 9; ++i) t.hist[i - 1] = t.hist[i];
        t.hist[8] = m;
    } else {
        t.hist[t.hist_n++] = m;
    }
}

double VoiceTracker::velocity_of(const Track& t) const {
    if (t.hist_n < 4) return 0.0;
    double d[8];
    int n = t.hist_n - 1;
    for (int i = 0; i < n; ++i) d[i] = (t.hist[i + 1] - t.hist[i]) / dt_;
    std::sort(d, d + n);
    double med = (n % 2) ? d[n / 2] : 0.5 * (d[n / 2 - 1] + d[n / 2]);
    return std::clamp(med, -30.0, 30.0);
}

double VoiceTracker::band_energy(const double* Ms, double f_hz, double offset) const {
    double s = 0.0;
    int cnt = 0;
    for (int h = 1; h <= cfg_.rise_harmonics; ++h) {
        double hh = h + offset;
        int k = (int)std::nearbyint(hh * f_hz / df_s_);
        if (!(k < nbins_s_ - 1 && hh * f_hz < 3000.0)) continue;
        double loc = std::max({Ms[k - 1], Ms[k], Ms[k + 1]});
        s += loc * loc;
        ++cnt;
    }
    return cnt ? std::sqrt(s) : 0.0;
}

double VoiceTracker::rise(double f_hz, double offset, int span) const {
    // the newest frame against the minimum over the previous `span` frames (oldest..newest in the ring)
    int count = std::min(ms_count_, span + 1);
    double mn = 1e300, last = 0.0;
    for (int i = 0; i < count; ++i) {
        int idx = (ms_head_ - count + i + 2 * ms_cap_) % ms_cap_;
        double e = band_energy(ms_[idx].data(), f_hz, offset);
        if (i == count - 1) last = e; else mn = std::min(mn, e);
    }
    return 20.0 * std::log10((last + 1e-9) / (mn + 1e-9));
}

// How sharply the overall short-window energy rose within the recent history: the biggest jump of any frame above the
// minimum of the ten frames before it. A plucked note, strummed chord or bow attack gives tens of dB; a sympathetic or
// ghost voice appearing in a decaying ring gives almost none. Broadband, so it works for low strings whose partials the
// short window cannot resolve.
double VoiceTracker::attack_depth() const {
    int cnt = std::min(edb_count_, cfg_.birth_hist_frames + 1);
    double best = 0.0;
    for (int i = 1; i < cnt; ++i) {
        double mn = 1e300;
        for (int j = std::max(0, i - 10); j < i; ++j) mn = std::min(mn, edb_[(edb_head_ - cnt + j + 2 * ms_cap_) % ms_cap_]);
        best = std::max(best, edb_[(edb_head_ - cnt + i + 2 * ms_cap_) % ms_cap_] - mn);
    }
    return best;
}

double VoiceTracker::partial_rise_db(double f_hz, int span) const {
    if (ms_count_ < 3) return 0.0;
    double rp = rise(f_hz, 0.0, span), rm = rise(f_hz, 0.5, span);
    return (rp - rm) >= cfg_.tonal_rise_margin_db ? rp : 0.0;
}

int VoiceTracker::velocity_midi(double level_db) const {
    return (int)std::clamp(std::nearbyint((level_db + 60.0) / 60.0 * 127.0), 1.0, 127.0);
}

void VoiceTracker::push_energy(double e) {
    edb_[edb_head_] = e;
    edb_head_ = (edb_head_ + 1) % ms_cap_;
    edb_count_ = std::min(edb_count_ + 1, ms_cap_);
}

void VoiceTracker::update(int64_t end, const std::vector<FitVoice>& voices, double onset, const double* Ms, double energy_db,
                          std::vector<NoteEvent>& events) {
    push_energy(energy_db);
    if (Ms) {
        std::copy(Ms, Ms + nbins_s_, ms_[ms_head_].begin());
        ms_head_ = (ms_head_ + 1) % ms_cap_;
        ms_count_ = std::min(ms_count_ + 1, ms_cap_);
    }
    const FitVoice* obs[MAX_VOICES + 2];
    int nobs = 0;
    for (const auto& v : voices) if ((v.level_db >= cfg_.min_level_dbfs || (cfg_.quiet_snr_db > 0 && v.level_db >= cfg_.quiet_floor_dbfs && v.snr_db >= cfg_.quiet_snr_db)) && nobs < MAX_VOICES + 2) obs[nobs++] = &v;
    bool strong = onset >= cfg_.onset_strong;

    int live[MAX_VOICES], nl = 0;
    for (int i = 0; i < cfg_.max_voices; ++i) if (tracks_[i].used) live[nl++] = i;

    // association (§8.3): optimal assignment on pitch distance, by DP over observation subsets
    int match[MAX_VOICES];
    for (int i = 0; i < MAX_VOICES; ++i) match[i] = -1;
    if (nl > 0 && nobs > 0) {
        const double BIG = 1e6;
        double C[MAX_VOICES][MAX_VOICES + 2];
        for (int a = 0; a < nl; ++a) {
            const Track& t = tracks_[live[a]];
            double pred = t.midi + t.vel * dt_;
            double gate = t.state == PENDING ? cfg_.assoc_gate_pending : cfg_.assoc_gate_semitones;
            for (int b = 0; b < nobs; ++b) {
                double d = std::fabs(obs[b]->midi - pred);
                C[a][b] = d <= gate ? d + 0.01 * std::fabs(obs[b]->level_db - t.level_db) : BIG;
            }
        }
        int S = 1 << nobs;
        std::fill(dp_.begin(), dp_.begin() + (size_t)(nl + 1) * S, 1e300);
        std::fill(choice_.begin(), choice_.begin() + (size_t)(nl + 1) * S, -2);
        double* dp = dp_.data();
        int* choice = choice_.data();
        dp[0] = 0.0;
        for (int a = 0; a < nl; ++a)
            for (int mask = 0; mask < S; ++mask) {
                double cur = dp[(size_t)a * S + mask];
                if (cur >= 1e299) continue;
                // leave the track unmatched
                if (cur + BIG < dp[(size_t)(a + 1) * S + mask]) { dp[(size_t)(a + 1) * S + mask] = cur + BIG; choice[(size_t)(a + 1) * S + mask] = -1; }
                for (int b = 0; b < nobs; ++b) {
                    if (mask & (1 << b)) continue;
                    int nm = mask | (1 << b);
                    double v = cur + C[a][b];
                    if (v < dp[(size_t)(a + 1) * S + nm]) { dp[(size_t)(a + 1) * S + nm] = v; choice[(size_t)(a + 1) * S + nm] = b; }
                }
            }
        int bm = 0;
        for (int mask = 0; mask < S; ++mask) if (dp[(size_t)nl * S + mask] < dp[(size_t)nl * S + bm]) bm = mask;
        int mask = bm;
        for (int a = nl; a >= 1; --a) {
            int ch = choice[(size_t)a * S + mask];
            if (ch >= 0) {
                if (C[a - 1][ch] < 1e5) match[a - 1] = ch;
                mask &= ~(1 << ch);
            }
        }
    }
    bool used_obs[MAX_VOICES + 2] = {false};
    for (int a = 0; a < nl; ++a) if (match[a] >= 0) used_obs[match[a]] = true;

    // Octave/twelfth ambiguity: a sounding note that loses support while a candidate appears exactly an octave,
    // twelfth or two octaves away, with no re-attack there, is held rather than replaced.
    bool held[MAX_VOICES] = {false}, absorbed[MAX_VOICES + 2] = {false};
    if (cfg_.octave_hold_frames > 0) {
        static const double kOffsets[6] = {-24, -19, -12, 12, 19, 24};
        for (int a = 0; a < nl; ++a) {
            Track& t = tracks_[live[a]];
            if (match[a] >= 0 || !(t.state == ACTIVE || t.state == RELEASING) || t.hold_n >= cfg_.octave_hold_frames) continue;
            for (int b = 0; b < nobs; ++b) {
                if (used_obs[b] || absorbed[b]) continue;
                double d = obs[b]->midi - t.midi;
                bool near = false;
                for (double k : kOffsets) if (std::fabs(d - k) < 0.6) { near = true; break; }
                if (!near) continue;
                double rs = ms_count_ > 0 ? partial_rise_db(midi_to_hz(obs[b]->midi), cfg_.onset_hist_frames) : 0.0;
                if (rs < cfg_.retrigger_rise_db) {
                    absorbed[b] = true; held[a] = true; t.hold_n += 1; t.last_support_end = end;
                    break;
                }
            }
        }
    }
    for (int a = 0; a < nl; ++a) {
        Track& t = tracks_[live[a]];
        if (match[a] >= 0) update_matched(t, *obs[match[a]], end, onset, strong, events);
        else if (!held[a]) update_missed(t, end, events);
    }
    for (int b = 0; b < nobs; ++b) {
        if (used_obs[b] || absorbed[b]) continue;
        int slot = -1;
        for (int i = 0; i < cfg_.max_voices; ++i) if (!tracks_[i].used) { slot = i; break; }
        if (slot < 0) continue;
        Track& t = tracks_[slot];
        t = Track{};
        const FitVoice& o = *obs[b];
        t.used = true; t.id = next_id_++; t.slot = slot; t.state = PENDING;
        t.midi = o.midi; t.vel = 0; t.level_db = o.level_db; t.peak_db = o.level_db; t.conf = o.confidence; t.string = o.string_index;
        t.confirm_n = 1; t.miss_n = 0; t.first_end = end; t.best_onset = onset; t.best_onset_end = end;
        t.has_note = false; t.last_support_end = end;
        t.hist_n = 0; push_hist(t, o.midi);
        t.conf_sum = o.confidence; t.conf_n = 1;
        t.best_rise = 0.0; t.best_rise_end = end; t.age = 1;
        if (ms_count_ > 0) {
            t.best_rise = partial_rise_db(midi_to_hz(o.midi), cfg_.onset_hist_frames);
            t.best_birth_rise = attack_depth();
        }
        maybe_confirm(t, end, strong, events);
    }
}

void VoiceTracker::update_matched(Track& t, const FitVoice& o, int64_t end, double onset, bool strong, std::vector<NoteEvent>& ev) {
    double innov = o.midi - t.midi;
    double eta = cfg_.eta_sustain + (cfg_.eta_attack - cfg_.eta_sustain) * std::min(1.0, std::fabs(innov) / 0.5);
    if (strong) eta = std::max(eta, cfg_.eta_attack);
    double prev_level = t.level_db; (void)prev_level;
    t.age += 1;
    double rs = ms_count_ > 0 ? partial_rise_db(midi_to_hz(o.midi), cfg_.onset_hist_frames) : 0.0;
    double rb = (t.state == PENDING && cfg_.attack_min_db > 0 && ms_count_ > 0) ? attack_depth() : 0.0;
    t.midi += eta * innov;
    push_hist(t, t.midi);
    t.vel = velocity_of(t);
    t.level_db += 0.5 * (o.level_db - t.level_db);
    t.peak_db = std::max(t.peak_db, t.level_db);
    t.conf += 0.3 * (o.confidence - t.conf);
    t.string = o.string_index;
    t.miss_n = 0;
    t.hold_n = 0;
    t.last_support_end = end;
    if (t.state == PENDING) {
        t.confirm_n += 1;
        t.conf_sum += o.confidence; t.conf_n += 1;
        if (onset > t.best_onset) { t.best_onset = onset; t.best_onset_end = end; }
        if (rs > t.best_rise) { t.best_rise = rs; t.best_rise_end = end; }
        t.best_birth_rise = std::max(t.best_birth_rise, rb);
        if (cfg_.attack_min_db > 0 && t.age > cfg_.pending_timeout_frames && t.best_birth_rise < cfg_.attack_min_db) { t = Track{}; return; }
        maybe_confirm(t, end, strong, ev);
    } else {
        if (t.state == RELEASING) t.state = ACTIVE;
        if (t.retrig_hold > 0) {
            t.retrig_hold -= 1;
        } else if (rs >= cfg_.retrigger_rise_db && t.age >= cfg_.retrigger_min_age_frames && t.has_note) {
            NoteEvent off;
            off.on = false; off.track_id = t.id; off.slot = t.slot; off.midi_note = t.note_midi; off.midi_float = (float)t.midi; off.velocity = 0;
            off.onset_est_samples = end; off.deliver_samples = end; off.confidence = (float)t.conf; off.flags = FLAG_RETRIGGER;
            ev.push_back(off);
            t.note_midi = (int)std::nearbyint(o.midi);
            t.peak_db = o.level_db;
            NoteEvent on;
            on.on = true; on.track_id = t.id; on.slot = t.slot; on.midi_note = t.note_midi; on.midi_float = (float)o.midi;
            on.velocity = velocity_midi(o.level_db);
            on.onset_est_samples = end - cfg_.short_fft_size / 2; on.deliver_samples = end;
            on.confidence = (float)o.confidence; on.flags = FLAG_RETRIGGER;
            ev.push_back(on);
            t.retrig_hold = cfg_.retrigger_min_age_frames;
            t.age = 0;
        }
    }
}

void VoiceTracker::maybe_confirm(Track& t, int64_t end, bool strong, std::vector<NoteEvent>& ev) {
    int need = (strong || t.best_onset >= cfg_.onset_strong || t.best_rise >= cfg_.retrigger_rise_db)
                   ? cfg_.strong_confirm_frames : cfg_.confirm_frames;
    if (t.state == PENDING && t.confirm_n >= need && cfg_.harmonic_confirm_frames > need && harmonic_suspect(t)) need = cfg_.harmonic_confirm_frames;
    double mean_conf = t.conf_sum / t.conf_n;
    bool attack_ok = cfg_.attack_min_db <= 0 || t.best_birth_rise >= cfg_.attack_min_db;
    if (t.state == PENDING && t.confirm_n >= need && mean_conf >= cfg_.confirm_min_conf && attack_ok) {
        t.state = ACTIVE;
        t.note_midi = (int)std::nearbyint(t.midi);
        t.has_note = true;
        uint8_t flags = 0;
        int64_t est;
        if (t.best_rise >= cfg_.retrigger_rise_db) est = t.best_rise_end - cfg_.short_fft_size / 2;
        else if (t.best_onset >= 1.5) est = t.best_onset_end - cfg_.short_fft_size / 2;
        else { est = t.first_end - (int64_t)(0.35 * n_long_); flags = FLAG_WEAK_ONSET; }
        NoteEvent e;
        e.on = true; e.track_id = t.id; e.slot = t.slot; e.midi_note = t.note_midi; e.midi_float = (float)t.midi;
        e.velocity = velocity_midi(t.level_db);
        e.onset_est_samples = std::max<int64_t>(est, 0); e.deliver_samples = end;
        e.confidence = (float)mean_conf; e.flags = flags;
        ev.push_back(e);
    }
}

void VoiceTracker::update_missed(Track& t, int64_t end, std::vector<NoteEvent>& ev) {
    t.miss_n += 1;
    push_hist(t, t.midi);
    t.vel *= 0.8;
    t.midi += t.vel * dt_;
    double unsupported_ms = t.miss_n * hop_ms_;
    if (t.state == PENDING) {
        if (t.miss_n >= 2) t = Track{};
        return;
    }
    if (t.state == ACTIVE && unsupported_ms >= cfg_.release_hang_ms) t.state = RELEASING;
    if (t.state == RELEASING && unsupported_ms >= cfg_.unsupported_timeout_ms) {
        NoteEvent e;
        e.on = false; e.track_id = t.id; e.slot = t.slot;
        e.midi_note = t.has_note ? t.note_midi : (int)std::nearbyint(t.midi);
        e.midi_float = (float)t.midi; e.velocity = 0;
        e.onset_est_samples = t.last_support_end; e.deliver_samples = end;
        e.confidence = (float)t.conf; e.flags = FLAG_INFERRED_RELEASE;
        ev.push_back(e);
        t = Track{};
    }
}

void VoiceTracker::flush(int64_t end, std::vector<NoteEvent>& ev) {
    for (int i = 0; i < cfg_.max_voices; ++i) {
        Track& t = tracks_[i];
        if (t.used && (t.state == ACTIVE || t.state == RELEASING) && t.has_note) {
            NoteEvent e;
            e.on = false; e.track_id = t.id; e.slot = t.slot; e.midi_note = t.note_midi; e.midi_float = (float)t.midi;
            e.onset_est_samples = end; e.deliver_samples = end; e.confidence = (float)t.conf; e.flags = FLAG_STREAM_END;
            ev.push_back(e);
            t = Track{};
        }
    }
}

void VoiceTracker::snapshot(VoiceSnapshot* out) const {
    int active_idx[MAX_VOICES], na = 0;
    for (int i = 0; i < MAX_VOICES; ++i) {
        const Track& t = tracks_[i];
        if (t.used && (t.state == ACTIVE || t.state == RELEASING)) active_idx[na++] = i;
    }
    std::sort(active_idx, active_idx + na, [&](int a, int b) { return tracks_[a].midi < tracks_[b].midi; });
    for (int i = 0; i < MAX_VOICES; ++i) {
        const Track& t = tracks_[i];
        VoiceSnapshot s;
        if (t.used) {
            s.track_id = t.id; s.state = t.state; s.midi = (float)t.midi; s.frequency_hz = (float)midi_to_hz(t.midi);
            s.level_db = (float)t.level_db; s.confidence = (float)t.conf; s.string_index = t.string;
            for (int r = 0; r < na; ++r) if (active_idx[r] == i) s.rank = r;
        }
        out[i] = s;
    }
}

}  // namespace fidddle
