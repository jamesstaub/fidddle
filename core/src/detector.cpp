#include "fidddle/detector.hpp"
#include <chrono>
#include <cmath>
#include "fft.hpp"
#include "calibrator.hpp"
#include "fitter.hpp"
#include "salience.hpp"
#include "spectral.hpp"
#include "tracker.hpp"

namespace fidddle {

struct Detector::Impl {
    Config cfg;
    int n_long, n_short;
    std::vector<double> ring, longbuf, win_long, win_short, shortbuf, frame_l, re_l, im_l, M;
    int64_t total = 0;
    int widx = 0;
    // dc blocker
    double dc_a, dc_x1 = 0, dc_y1 = 0;
    RealFFT fft_l;
    Whitener whitener;
    OnsetFlux flux;
    SalienceMap smap;
    Fitter fitter;
    VoiceTracker tracker;
    Calibrator calib;
    Peaks peaks_sal, peaks_fit;
    std::vector<Candidate> cands;
    FitResult fit;
    std::vector<NoteEvent> frame_events;
    uint32_t frame_index = 0;
    PitchFrame latest;
    Diagnostics diag;
    double priors[MAX_VOICES + 2];
    // SPSC event queue
    static constexpr size_t QCAP = 512;
    std::vector<NoteEvent> q;
    std::atomic<size_t> qh{0}, qt{0};
    // calibration state: commands in, events and the result out
    std::atomic<int> calib_cmd{0};           // 1 start, 2 finish, 3 cancel
    bool calibrating = false;
    Calibration cal_result;
    bool cal_valid = false;
    std::atomic<bool> cal_ready{false};
    std::vector<CalibEvent> cal_scratch, cq;
    static constexpr size_t CQCAP = 64;
    std::atomic<size_t> cqh{0}, cqt{0};

    explicit Impl(const Config& c)
        : cfg(c), n_long(c.derived_long_fft()), n_short(c.short_fft_size),
          ring(n_long, 0.0), longbuf(n_long), win_long(hann(n_long)), win_short(hann(n_short)), shortbuf(n_short),
          frame_l(n_long), re_l(n_long / 2 + 1), im_l(n_long / 2 + 1), M(n_long / 2 + 1),
          fft_l(n_long), whitener(cfg, n_long), flux(cfg), smap(cfg, n_long), fitter(cfg, n_long),
          tracker(cfg, n_long), calib(cfg, n_long), q(QCAP) {
        cal_scratch.reserve(8);
        cq.resize(CQCAP);
        dc_a = 1.0 / (1.0 + 2.0 * M_PI * cfg.dc_cutoff_hz / cfg.sample_rate);
        cands.reserve(cfg.max_candidates + MAX_VOICES + 2);
        frame_events.reserve(16);
        peaks_sal.freq.reserve(n_long / 4); peaks_sal.amp.reserve(n_long / 4);
        peaks_fit.freq.reserve(n_long / 4); peaks_fit.amp.reserve(n_long / 4);
        for (Peaks* pk : {&peaks_sal, &peaks_fit}) { pk->k_.reserve(n_long / 2 + 1); pk->drop_.reserve(n_long / 2 + 1); }
        fit.voices.reserve(MAX_VOICES + 2);
    }

    void push_event(const NoteEvent& e) {
        size_t h = qh.load(std::memory_order_relaxed), t = qt.load(std::memory_order_acquire);
        if (h - t >= QCAP) { ++diag.overflow_events; return; }
        q[h % QCAP] = e;
        qh.store(h + 1, std::memory_order_release);
    }

    // Before the first analysis frame exists (the long window is still filling) the tracker still needs the energy history,
    // or a note plucked in the first moments of audio would show no attack.
    void preroll_energy() {
        double e = 0.0;
        for (int i = 0; i < n_short; ++i) {
            double v = ring[(widx - n_short + i + n_long) % n_long] * win_short[i];
            e += v * v;
        }
        tracker.push_energy(10.0 * std::log10(e + 1e-12));
    }

    void push_cevent(const CalibEvent& e) {
        size_t h = cqh.load(std::memory_order_relaxed), t = cqt.load(std::memory_order_acquire);
        if (h - t >= CQCAP) return;
        cq[h % CQCAP] = e;
        cqh.store(h + 1, std::memory_order_release);
    }

    void finish_calibration() {
        Calibration c;
        bool ok = calib.finalize(c);
        calibrating = false;
        if (ok) cal_result = c;
        cal_valid = ok;
        cal_ready.store(true, std::memory_order_release);
        CalibEvent e;
        e.kind = CalibEvent::Finished;
        e.captured = calib.captured_count();
        e.total = cfg.profile.string_count;
        push_cevent(e);
    }

    void run_calibration() {
        int cmd = calib_cmd.exchange(0, std::memory_order_acq_rel);
        if (cmd == 1) {
            calib.reset();
            calibrating = true;
            cal_ready.store(false, std::memory_order_relaxed);
            CalibEvent e; e.kind = CalibEvent::Started; e.total = cfg.profile.string_count;
            push_cevent(e);
        } else if (cmd == 3 && calibrating) {
            calibrating = false;
            CalibEvent e; e.kind = CalibEvent::Cancelled;
            push_cevent(e);
        } else if (cmd == 2 && calibrating) {
            finish_calibration();
        }
        if (!calibrating) return;
        cal_scratch.clear();
        calib.update(fit.voices, peaks_fit, cal_scratch);
        for (const auto& e : cal_scratch) push_cevent(e);
        if (calib.complete()) finish_calibration();
    }

    void analyze() {
        auto t0 = std::chrono::steady_clock::now();
        // chronological copy of the last n_long samples (ring write index = oldest)
        for (int i = 0; i < n_long; ++i) longbuf[i] = ring[(widx + i) % n_long];
        for (int i = 0; i < n_long; ++i) frame_l[i] = longbuf[i] * win_long[i];
        fft_l.forward(frame_l.data(), re_l.data(), im_l.data());
        int nb = n_long / 2 + 1;
        for (int k = 0; k < nb; ++k) M[k] = std::sqrt(re_l[k] * re_l[k] + im_l[k] * im_l[k]);
        whitener.process(M.data());
        for (int i = 0; i < n_short; ++i) shortbuf[i] = longbuf[n_long - n_short + i];
        double onset = flux.process(shortbuf.data());
        double df = cfg.sample_rate / n_long;
        spectral_peaks(M.data(), whitener.W.data(), whitener.W.data(), whitener.snr.data(), nb, df, cfg.peak_min_w, cfg.peak_min_snr, peaks_sal);
        spectral_peaks(M.data(), whitener.W.data(), whitener.unclipped.data(), whitener.snr.data(), nb, df, cfg.peak_min_w, cfg.peak_min_snr, peaks_fit);
        smap.compute(peaks_sal);
        int npri = tracker.predictions(priors, MAX_VOICES + 2);
        pick_candidates(smap, cfg, priors, npri, cands);
        fitter.fit(whitener.E.data(), M.data(), cands, peaks_fit, priors, npri, fit);
        run_calibration();
        frame_events.clear();
        double e_short = 0.0;                            // Hann-weighted short-window energy: the tracker's attack evidence
        for (int i = 0; i < n_short; ++i) { double v = shortbuf[i] * win_short[i]; e_short += v * v; }
        tracker.update(total, fit.voices, onset, flux.last_M.data(), 10.0 * std::log10(e_short + 1e-12), frame_events);
        for (const auto& e : frame_events) push_event(e);

        latest.timestamp_samples = total;
        latest.frame_index = frame_index;
        latest.onset_strength = (float)onset;
        latest.voice_count = (int)fit.voices.size();
        tracker.snapshot(latest.voices);

        double us_now = std::chrono::duration<double, std::micro>(std::chrono::steady_clock::now() - t0).count();
        if (debug_hook_ptr && *debug_hook_ptr) {
            FrameDebug d;
            d.frame_index = frame_index;
            d.end_sample = total;
            d.onset = onset;
            for (const auto& v : fit.voices) d.fit_voices.push_back({v.f_hz, v.midi, v.gain, v.confidence, v.level_db, v.string_index});
            d.tracks = latest.voices;
            d.events = frame_events.data();
            d.n_events = (int)frame_events.size();
            d.n_peaks = (int)peaks_fit.freq.size(); d.n_cands = (int)cands.size(); d.us = us_now;
            (*debug_hook_ptr)(d);
        }
        ++frame_index;
        double us = std::chrono::duration<double, std::micro>(std::chrono::steady_clock::now() - t0).count();
        diag.last_us = us;
        diag.max_us = std::max(diag.max_us, us);
        diag.mean_us += (us - diag.mean_us) / (double)(diag.frames + 1);
        ++diag.frames;
    }

    std::function<void(const FrameDebug&)>* debug_hook_ptr = nullptr;

    template <class T>
    void run(const T* in, size_t n) {
        for (size_t i = 0; i < n; ++i) {
            double x = (double)in[i];
            double y = dc_a * (dc_y1 + x - dc_x1);   // y[n] = a (y[n-1] + x[n] - x[n-1])
            dc_x1 = x; dc_y1 = y;
            ring[widx] = y;
            widx = (widx + 1) % n_long;
            ++total;
            if (total >= n_long && (total - n_long) % cfg.hop_size == 0) analyze();
            else if (total >= n_short && total < n_long && total % cfg.hop_size == 0) preroll_energy();
        }
    }
};

Detector::Detector(const Config& cfg) : p_(new Impl(cfg)) { p_->debug_hook_ptr = &debug_hook; }
Detector::~Detector() = default;
const Config& Detector::config() const { return p_->cfg; }
int Detector::long_fft_size() const { return p_->n_long; }

void Detector::reset() {
    Impl& s = *p_;
    std::fill(s.ring.begin(), s.ring.end(), 0.0);
    s.total = 0; s.widx = 0; s.dc_x1 = s.dc_y1 = 0; s.frame_index = 0;
    s.tracker.reset();
    s.qh = 0; s.qt = 0;
    s.calibrating = false; s.calib_cmd = 0; s.cal_ready = false; s.cqh = 0; s.cqt = 0;
    s.latest = PitchFrame{};
    s.diag = Diagnostics{};
}

void Detector::process(const double* in, size_t n) { p_->run(in, n); }
void Detector::process(const float* in, size_t n) { p_->run(in, n); }

void Detector::flush() {
    Impl& s = *p_;
    std::vector<NoteEvent> ev;
    s.tracker.flush(s.latest.timestamp_samples, ev);   // frame time of the last analysis, as in the reference
    for (auto& e : ev) s.push_event(e);
    if (debug_hook && !ev.empty()) {
        FrameDebug d{s.frame_index, s.total, 0.0, {}, s.latest.voices, ev.data(), (int)ev.size(), 0, 0, 0.0};
        debug_hook(d);
    }
}

bool Detector::poll_event(NoteEvent& out) {
    Impl& s = *p_;
    size_t t = s.qt.load(std::memory_order_relaxed), h = s.qh.load(std::memory_order_acquire);
    if (t == h) return false;
    out = s.q[t % Impl::QCAP];
    s.qt.store(t + 1, std::memory_order_release);
    return true;
}

void Detector::calibrate_start() { p_->calib_cmd.store(1, std::memory_order_release); }
void Detector::calibrate_finish() { p_->calib_cmd.store(2, std::memory_order_release); }
void Detector::calibrate_cancel() { p_->calib_cmd.store(3, std::memory_order_release); }
void Detector::calibrate_finish_now() { if (p_->calibrating) p_->finish_calibration(); }
bool Detector::calibrating() const { return p_->calibrating; }

bool Detector::poll_calib_event(CalibEvent& out) {
    Impl& s = *p_;
    size_t t = s.cqt.load(std::memory_order_relaxed), h = s.cqh.load(std::memory_order_acquire);
    if (t == h) return false;
    out = s.cq[t % Impl::CQCAP];
    s.cqt.store(t + 1, std::memory_order_release);
    return true;
}

bool Detector::take_calibration(Calibration& out) {
    Impl& s = *p_;
    if (!s.cal_ready.exchange(false, std::memory_order_acq_rel) || !s.cal_valid) return false;
    out = s.cal_result;
    return true;
}

const PitchFrame& Detector::latest() const { return p_->latest; }
const Diagnostics& Detector::diagnostics() const { return p_->diag; }
int64_t Detector::samples_processed() const { return p_->total; }

}  // namespace fidddle
