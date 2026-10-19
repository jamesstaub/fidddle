// Small self-contained real FFT (radix-2, double). The rest of the detector only needs
// "real input -> N/2+1 complex bins", so this can be swapped for vDSP/pffft (spec §10.1).
#pragma once
#include <cmath>
#include <vector>

namespace fidddle {

class RealFFT {
public:
    explicit RealFFT(int n) : n_(n), h_(n / 2), re_(n / 2), im_(n / 2), rev_(n / 2), cs_(n / 2), sn_(n / 2), wr_(n / 2 + 1), wi_(n / 2 + 1) {
        int bits = 0;
        while ((1 << bits) < h_) ++bits;
        for (int i = 0; i < h_; ++i) {
            int r = 0;
            for (int b = 0; b < bits; ++b) if (i & (1 << b)) r |= 1 << (bits - 1 - b);
            rev_[i] = r;
        }
        for (int i = 0; i < h_ / 2 + 1 && i < h_; ++i) {
            cs_[i] = std::cos(-2.0 * M_PI * i / h_);
            sn_[i] = std::sin(-2.0 * M_PI * i / h_);
        }
        for (int k = 0; k <= h_; ++k) {
            wr_[k] = std::cos(-2.0 * M_PI * k / n_);
            wi_[k] = std::sin(-2.0 * M_PI * k / n_);
        }
    }

    int size() const { return n_; }

    // x: n real samples. out_re/out_im: n/2+1 bins.
    void forward(const double* x, double* out_re, double* out_im) {
        for (int i = 0; i < h_; ++i) {
            int r = rev_[i];
            re_[r] = x[2 * i];
            im_[r] = x[2 * i + 1];
        }
        for (int len = 2; len <= h_; len <<= 1) {
            int half = len / 2, step = h_ / len;
            for (int base = 0; base < h_; base += len) {
                for (int k = 0; k < half; ++k) {
                    double c = cs_[k * step], s = sn_[k * step];
                    int a = base + k, b = a + half;
                    double tr = re_[b] * c - im_[b] * s;
                    double ti = re_[b] * s + im_[b] * c;
                    re_[b] = re_[a] - tr;
                    im_[b] = im_[a] - ti;
                    re_[a] += tr;
                    im_[a] += ti;
                }
            }
        }
        // split the half-length complex transform into the real transform
        for (int k = 0; k <= h_; ++k) {
            int k1 = k % h_, k2 = (h_ - k) % h_;
            double zr = re_[k1], zi = im_[k1];
            double cr = re_[k2], ci = -im_[k2];            // conj(Z[h-k])
            double er = 0.5 * (zr + cr), ei = 0.5 * (zi + ci);
            double dr = 0.5 * (zr - cr), di = 0.5 * (zi - ci);
            // (D) / i  = (di, -dr)
            double or_ = di, oi = -dr;
            double tr = or_ * wr_[k] - oi * wi_[k];
            double ti = or_ * wi_[k] + oi * wr_[k];
            out_re[k] = er + tr;
            out_im[k] = ei + ti;
        }
    }

private:
    int n_, h_;
    std::vector<double> re_, im_;
    std::vector<int> rev_;
    std::vector<double> cs_, sn_, wr_, wi_;
};

}  // namespace fidddle
