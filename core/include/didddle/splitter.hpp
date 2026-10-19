// Detector + separator wired together: the one object a host needs. Drives the (unmodified) fidddle::Detector in
// segments that end on its analysis boundaries, feeds what it reports to the separator in time, and returns delayed
// per-voice audio plus the residual. Detector controls (calibration, diagnostics) stay on detector().
#pragma once
#include <atomic>
#include <memory>
#include <vector>
#include "didddle/config.hpp"
#include "didddle/separator.hpp"
#include "fidddle/detector.hpp"

namespace didddle {

struct SplitterConfig {
    fidddle::Config detector;
    Config separator;

    // Stock instrument: detector tuned for it, separator following its profile, voice slots and hop grid.
    static SplitterConfig for_instrument(int profile_id, double sample_rate) {
        SplitterConfig c;
        c.detector = fidddle::Config::for_instrument(profile_id, sample_rate);
        c.finalize();
        return c;
    }
    // Make the separator agree with the detector after the caller changed either (profile, voices, hop, rate).
    void finalize() {
        separator.sample_rate = detector.sample_rate;
        separator.profile = detector.profile;
        separator.max_voices = std::min(detector.max_voices, MAX_VOICES);
        separator.grid = detector.hop_size;
    }
};

class Splitter {
public:
    explicit Splitter(const SplitterConfig& cfg);
    ~Splitter();
    Splitter(const Splitter&) = delete;
    Splitter& operator=(const Splitter&) = delete;

    const SplitterConfig& config() const { return cfg_; }
    int slots() const { return sep_.slots(); }
    int latency_samples() const { return sep_.latency_samples(); }
    const Diagnostics& separator_diagnostics() const { return sep_.diagnostics(); }
    void reset();

    // Mono in; `slots()` voice signals and the residual out, all of n samples, delayed by latency_samples().
    void process(const double* in, size_t n, double* const* voices, double* residual);

    fidddle::Detector& detector() { return det_; }
    const fidddle::Detector& detector() const { return det_; }
    // Note events the detector produced, for hosts that also want them (detector().poll_event is consumed here).
    bool poll_event(fidddle::NoteEvent& out);

private:
    static constexpr size_t QCAP = 512;
    SplitterConfig cfg_;
    fidddle::Detector det_;
    Separator sep_;
    std::vector<fidddle::NoteEvent> q_;
    std::atomic<size_t> qh_{0}, qt_{0};
};

}  // namespace didddle
