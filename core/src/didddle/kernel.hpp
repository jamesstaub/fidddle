// Complex DTFT of a periodic Hann window (didddle/estimate.py: hann_kernel).
#pragma once
#include <cmath>
#include <complex>

namespace didddle {

using cplx = std::complex<double>;

// Window of length n starting at sample 0, evaluated at a bin offset `delta` from a sinusoid's frequency:
// 0.5 D(d) - 0.25 D(d-1) - 0.25 D(d+1), D the Dirichlet kernel. Peak value n / 2 at delta = 0.
inline cplx hann_kernel(double delta, int n) {
    auto dirichlet = [n](double d) -> cplx {
        if (std::fabs(d) < 1e-9) return cplx((double)n, 0.0);
        double ratio = std::sin(M_PI * d) / std::sin(M_PI * d / n);
        double ph = -M_PI * d * (n - 1) / n;
        return cplx(ratio * std::cos(ph), ratio * std::sin(ph));
    };
    return 0.5 * dirichlet(delta) - 0.25 * dirichlet(delta - 1.0) - 0.25 * dirichlet(delta + 1.0);
}

}  // namespace didddle
