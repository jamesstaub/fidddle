// Open-string calibration (spec §12.3). Learns, from isolated open-string notes, each string's inharmonicity and
// tuning offset and the typical harmonic weight profile. Mirrors fidddle/calibrate.py. Fixed buffers, no allocation
// after construction.
#pragma once
#include <vector>
#include "fidddle/config.hpp"
#include "fidddle/types.hpp"
#include "fitter.hpp"
#include "spectral.hpp"
#include "stringid.hpp"

namespace fidddle {

class Calibrator {
public:
    Calibrator(const Config& cfg, int n_long);
    void reset();
    // One analysis frame: the fitted voices and the (frequency, unclipped amplitude) peaks the fit used.
    // Events are appended to `out` (capacity reserved by the caller).
    // `audio`/`measure`/`end`: the input history and sample count, for the string-identity stiffness values (may be null).
    void update(const std::vector<FitVoice>& voices, const Peaks& peaks, std::vector<CalibEvent>& out,
                const stringid::History* audio = nullptr, stringid::Measure* measure = nullptr, int64_t end = 0);
    bool complete() const;
    int captured_count() const;
    int frames(int s) const { return frames_[s]; }
    bool done(int s) const { return done_[s]; }
    // Calibration from the strings completed so far; false if none is complete.
    bool finalize(Calibration& cal) const;

    static constexpr int CAP = 512;        // per-string estimate history
    static constexpr int N_WEIGHTS = Calibration::MAX_WEIGHTS;

private:
    bool assign(double f0, double B, const Peaks& pk, int hmax, int* h, double* p, double* a, int& n) const;
    bool estimate(double f0, double B, const Peaks& pk, double& f0o, double& Bo, int* h, double* a, int& n) const;
    static double median(const double* v, int n, double* scratch);

    const Config& cfg_;
    double df_, fmax_;
    int n_;
    int need_ = 30, min_run_ = 12, max_run_ = 70;
    double nominal_[MAX_STRINGS];
    std::vector<double> B_list_, cents_list_;       // [n_][CAP]
    int count_[MAX_STRINGS];
    double prof_sum_[MAX_STRINGS][N_WEIGHTS];
    double prof_cnt_[MAX_STRINGS][N_WEIGHTS];
    int frames_[MAX_STRINGS];
    static constexpr int LB_CAP = 8;
    double lb_list_[MAX_STRINGS][LB_CAP];
    int lb_count_[MAX_STRINGS];
    int64_t lb_last_[MAX_STRINGS];
    bool done_[MAX_STRINGS];
    int run_len_ = 0;
    bool have_last_ = false;
    double last_midi_ = 0;
    mutable std::vector<double> scratch_;
};

}  // namespace fidddle
