// Harmonic salience and candidate generation (spec §6).
#pragma once
#include <vector>
#include "fidddle/config.hpp"
#include "spectral.hpp"

namespace fidddle {

inline double midi_to_hz(double m) { return 440.0 * std::pow(2.0, (m - 69.0) / 12.0); }
inline double hz_to_midi(double f) { return 69.0 + 12.0 * std::log2(f / 440.0); }

struct Candidate {
    double f_hz = 0, midi = 0, salience = 0, hit = 0, miss = 0, inter = 0;
};

class SalienceMap {
public:
    SalienceMap(const Config& cfg, int n_fft);
    void compute(const Peaks& peaks);        // fills S, hit, miss, inter
    int grid_size() const { return (int)midi.size(); }
    std::vector<double> midi, f;
    std::vector<double> S, hit, miss, inter;
    double df;

private:
    double support(double P, const Peaks& pk) const;
    const Config& cfg_;
    int K_;
public:
    mutable std::vector<int> order_;      // scratch for candidate NMS
    mutable std::vector<char> taken_;
private:
    std::vector<double> pf_, mf_, w_, wm_;     // [G*K] , [G*(K-1)]
    std::vector<char> valid_, mvalid_;
    std::vector<double> wsum_, wmsum_;
};

// NMS over the salience curve; `forced_midi` are active-track predictions that must stay eligible.
void pick_candidates(const SalienceMap& sm, const Config& cfg, const double* forced_midi, int n_forced,
                     std::vector<Candidate>& out);

}  // namespace fidddle
