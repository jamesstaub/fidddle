"""Stage-level metrics (spec §12.2). Candidate recall first."""
import numpy as np
from .salience import hz_to_midi


def steady_frames(frames, notes, sr, n_long, margin_s=0.05, plucked_max_age_s=1.2):
    """Frames where every sounding note has been on for the full long window."""
    idx = []
    win_s = n_long / sr
    for f in frames:
        t = f.t_s
        active = [n for n in notes if n.onset_s <= t - win_s - margin_s and t <= n.offset_s - margin_s
                  and (n.kind != 'plucked' or t - n.onset_s <= plucked_max_age_s)]
        starting = [n for n in notes if t - win_s - margin_s < n.onset_s <= t or (n.offset_s < t < n.offset_s + win_s)]
        if active and not starting:
            idx.append((f, active))
    return idx


def candidate_recall(frames, notes, sr, n_long, tol_cents=(25, 50), top_k=None):
    """Fraction of true pitches present within tol of a candidate (+ mean rank)."""
    hits = {t: 0 for t in tol_cents}
    total = 0
    for f, active in steady_frames(frames, notes, sr, n_long):
        cands = f.candidates[:top_k] if top_k else f.candidates
        cm = np.array([c.midi for c in cands]) if cands else np.array([])
        for n in active:
            total += 1
            if len(cm):
                d = np.min(np.abs(cm - n.midi)) * 100.0
                for t in tol_cents:
                    hits[t] += d <= t
    return {t: (hits[t] / total if total else float("nan")) for t in tol_cents}, total


def true_pitch_ranks(frames, notes, sr, n_long, tol_cents=50):
    """Rank (0-based) of each true pitch in the candidate list; missing -> None."""
    ranks = []
    for f, active in steady_frames(frames, notes, sr, n_long):
        cm = np.array([c.midi for c in f.candidates])
        for n in active:
            if len(cm) == 0:
                ranks.append(None)
                continue
            d = np.abs(cm - n.midi) * 100.0
            j = np.nonzero(d <= tol_cents)[0]
            ranks.append(int(j[0]) if len(j) else None)
    return ranks


def fit_scores(frames, notes, sr, n_long, tol_cents=50):
    """Multi-pitch precision/recall/F1 and octave-error counts over steady frames
    that carry a fit result."""
    tp = fp = fn = oct_fp = 0
    count_ok = n = 0
    for f, active in steady_frames(frames, notes, sr, n_long):
        if f.fit is None:
            continue
        est = np.array([v.midi for v in f.fit.voices])
        truth = np.array([a.midi for a in active])
        n += 1
        used = np.zeros(len(est), bool)
        for t in truth:
            if len(est):
                d = np.abs(est - t) * 100
                d[used] = 1e9
                j = int(np.argmin(d))
                if d[j] <= tol_cents:
                    used[j] = True
                    tp += 1
                    continue
            fn += 1
        for j in np.nonzero(~used)[0]:
            fp += 1
            dd = np.abs(est[j] - truth)
            r = np.abs(dd - np.round(dd / 12) * 12)
            if np.any((np.round(dd / 12) >= 1) & (r <= 0.5)) or np.any(np.abs(dd - 7) <= 0.5) or np.any(np.abs(dd - 19) <= 0.5):
                oct_fp += 1
        count_ok += len(est) == len(truth)
    p = tp / max(tp + fp, 1)
    r = tp / max(tp + fn, 1)
    f1 = 2 * p * r / max(p + r, 1e-9)
    return {"P": p, "R": r, "F1": f1, "oct_fp": oct_fp, "fp": fp, "count_acc": count_ok / max(n, 1), "frames": n}
