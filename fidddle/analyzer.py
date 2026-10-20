"""Offline driver: runs stages 1-4 (and later more) over a signal.

Structured as a per-frame step so the same shape can be ported to the C++
core; the offline loop is only a convenience.
"""
from dataclasses import dataclass, field
import numpy as np

from .frontend import dc_block, frame_ends
from .spectral import hann, magnitude, Whitener, OnsetFlux, spectral_peaks
from .salience import SalienceMap, pick_candidates
from .fitter import Fitter
from .tracker import VoiceTracker, NoteEvent
from .stringid import StringIdentifier


@dataclass
class Frame:
    index: int
    end_sample: int
    t_s: float
    onset: float
    candidates: list
    fit: object = None
    tracks: list = None
    events: list = None
    W: np.ndarray = None
    S: np.ndarray = None


class Analyzer:
    def __init__(self, cfg):
        self.cfg = cfg
        self.n_long = cfg.derived_long_fft()
        self.win_long = hann(self.n_long)
        self.win_short = hann(cfg.short_fft_size)
        self.whitener = Whitener(cfg, self.n_long)
        self.flux = OnsetFlux(cfg)
        self.smap = SalienceMap(cfg, self.n_long)
        self.fitter = Fitter(cfg, self.n_long)
        self.string_id = StringIdentifier(cfg)

    def run(self, x, keep_spectra=False, fit=False, fit_stride=1, track=False, calibrator=None):
        cfg = self.cfg
        x = dc_block(np.asarray(x, dtype=np.float64), cfg.sample_rate, cfg.dc_cutoff_hz)
        out = []
        self.events = []
        tracker = VoiceTracker(cfg, self.n_long) if track else None
        self.string_id.states.clear()
        fit = fit or track or calibrator is not None
        self.calib_events = []
        ns = cfg.short_fft_size
        if tracker:     # energy history for the hops before the first full analysis frame (the tracker's attack evidence)
            for end in range(ns, self.n_long, cfg.hop_size):
                tracker.push_energy(10.0 * np.log10(np.sum((x[end - ns: end] * self.win_short) ** 2) + 1e-12))
        for i, end in enumerate(frame_ends(len(x), self.n_long, cfg.hop_size)):
            long_frame = x[end - self.n_long: end]
            short_frame = x[end - cfg.short_fft_size: end]
            M = magnitude(long_frame, self.win_long)
            W, E, gate = self.whitener.process(M)
            onset, _ = self.flux.process(short_frame)
            S, hit, miss, inter = self.smap.compute(M, W, self.whitener.snr)
            priors = tracker.predictions() if tracker else ()
            cands = pick_candidates(self.smap, S, hit, miss, inter, cfg, forced_midi=priors)
            res = None
            if fit and (track or i % fit_stride == 0):
                peaks = spectral_peaks(M, W, self.smap.df, cfg.peak_min_w, amp=self.whitener.unclipped,
                                       snr=self.whitener.snr, min_snr=cfg.peak_min_snr)
                res = self.fitter.fit(W, E, cands, peaks, M=M, prior_midis=priors, noise=self.whitener.noise)
            if calibrator is not None and res is not None:
                self.calib_events.extend(calibrator.update(res.voices, (peaks[0], peaks[1]), audio=(x, int(end))))
            snaps = evs = None
            if tracker:
                e_short = float(10.0 * np.log10(np.sum((short_frame * self.win_short) ** 2) + 1e-12))
                snaps, evs = tracker.update(int(end), res.voices, onset, self.flux.last_M, e_short)
                self.events.extend(evs)
                sid = self.string_id.update(x, int(end), snaps, lambda k, sn, st, mg: NoteEvent(
                    k, sn.track_id, int(round(sn.midi)), float(sn.midi), 0, int(end), int(end), float(sn.confidence), (), sn.slot, int(st), float(mg)))
                evs = list(evs) + sid
                self.events.extend(sid)
            out.append(Frame(i, int(end), end / cfg.sample_rate, onset, cands, res, snaps, evs,
                             W if keep_spectra else None, S if keep_spectra else None))
        if tracker and out:
            self.events.extend(tracker.flush(out[-1].end_sample))
            self.events.extend(self.string_id.flush(lambda k, sn, st, mg: NoteEvent(
                k, sn.track_id, int(round(sn.midi)), float(sn.midi), 0, out[-1].end_sample, out[-1].end_sample, float(sn.confidence), (), sn.slot, int(st), float(mg))))
        return out
