// Per-frame voice spectra (didddle/estimate.py: SinusoidLS). Every partial of every active voice is one complex
// sinusoid, fitted by ridge least squares against the frame spectrum with the exact Hann kernel. Partials of different
// voices closer than cluster_gap_bins share one unknown, split by each voice's envelope over its uncollided partials.
// The normal equations are banded (a partial only touches 2R+1 bins), so they are solved with a banded Cholesky.
// All buffers are sized at construction.
#pragma once
#include <vector>
#include "didddle/config.hpp"
#include "kernel.hpp"

namespace didddle {

class SinusoidSolver {
public:
    explicit SinusoidSolver(const Config& cfg);

    // X: frame spectrum (n/2+1 bins). f0[v] <= 0 or NaN = voice inactive. On return voice(v) holds that voice's
    // spectrum; active(v) tells whether it is nonzero.
    void solve(const cplx* X, const double* f0);
    const cplx* voice(int v) const { return &S_[(size_t)v * nb_]; }
    bool active(int v) const { return active_[v]; }

private:
    struct Partial { int voice, harm; double nu; };

    const Config& cfg_;
    int nb_, n_, V_, R_;
    double df_;
    std::vector<Partial> parts_;
    std::vector<int> order_, cid_, first_, last_;     // sorted order; cluster of each sorted partial; member range
    std::vector<double> nu_c_, share_, amp_;
    std::vector<int> lo_;                             // first bin of each cluster's kernel
    std::vector<cplx> A_, b_, c_, gband_, y_;         // kernels [cluster][2R+1], rhs, solution, banded G, scratch
    std::vector<double> env_h_, env_l_;               // per-voice envelope points [voice][partial]
    std::vector<int> env_n_;
    std::vector<cplx> S_;
    std::vector<char> active_;
};

}  // namespace didddle
