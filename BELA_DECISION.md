# Should Bela share the Max code or get its own implementation?

Decision document, 2026-10-22. Background: `BELA_PORT_REVIEW.md` (problems found) and `EFFICIENT_MODE_DESIGN.md` (the efficient mode plan).

## Summary

**Recommendation: keep one shared core. Do not start a separate Bela implementation now.** Set a measurable checkpoint, and only if the shared core misses it, replace the expensive front half of the pipeline for Bela (not the whole detector).

**Reasons, in plain terms:**

1. **The code is already in good shape for a small computer.** It has no dependence on Max or the operating system, it does no memory allocation while running (tests check this), and the detector core is only about 2,900 lines.
2. **What Bela needs is mostly a different way of running the same steps**, not different steps: use smaller numbers (32-bit instead of 64-bit), run the analysis in a lower-priority task instead of inside the audio callback, and use cheaper maths. All of these can be added to the existing files.
3. **Forking would cost us a second copy of the parts that change most.** Of the last 24 commits, 9 changed the tracking, calibration or settings code and 7 changed the spectrum and pitch-search code. Both halves are still changing, so two copies would drift apart and every fix would have to be made twice.
4. **A from-scratch Bela design would look surprisingly similar.** Section 2 compares them: seven of nine differences can be reached by changing the current code in place.

**Main risk:** after all the planned savings the shared core may still be too slow on the Bela's processor. Nobody has run it there yet. Section 4 defines the check that tells us, and what we do in each case.

**The one thing to do next:** build the command-line tool on a real Bela and time it (about 30 minutes). Every estimate in this document comes from a laptop plus an assumption that the Bela is 20 to 50 times slower. A real number replaces that guess.

**Words used here:** the *hop* is how often the detector runs one analysis step (every 256 samples now, 512 in efficient mode). The *front half* of the pipeline is the spectrum analysis and pitch search (about 85% of the time). The *back half* is note tracking, calibration and event output (a few percent of the time, but it decides how the detector behaves musically).

## 1. Is the refactor feasible?

Yes. The work is mostly additions to the existing structure:

| Change | What it involves | Size |
|---|---|---|
| Efficient mode | A preset over existing settings; convert about 15 per-frame constants to milliseconds | Small to medium |
| Split the detector in two entry points | One that only stores incoming audio (fast, runs in the audio callback) and one that does the analysis (runs in a separate task). Today one function does both. | Medium |
| 32-bit numbers | Replace `double` with a type alias that Bela sets to `float`; Max keeps `double` | Medium (mechanical, but touches every file, so it needs the test suite) |
| Cheaper maths | The table for `exp` (other session), a less frequent noise-floor update (other session) | Small each |
| Leave out string identification and calibration on Bela | A compile-time switch | Small |

The Max version keeps working throughout, because the default settings reproduce today's behaviour and two kinds of tests guard it: the event-for-event comparison with the Python reference, and the tests that check nothing is allocated while running.

Harder than it looks:

- Hop 512 only works if the per-frame constants are converted first (see `EFFICIENT_MODE_DESIGN.md` section 3).
- Running analysis in a separate task means data crosses between two threads (the latest pitch frame, diagnostics). That needs careful, small changes.
- Testing has to include the real board. Timing on a laptop does not predict it.

## 2. If we started from scratch for Bela, what would be different?

| # | Design choice | Today (Max-first) | Bela-first design | Reachable by changing the current code? |
|---|---|---|---|---|
| 1 | Number size | 64-bit | 32-bit from the start | Yes (type alias) |
| 2 | Where analysis runs | Inside the audio callback | In a separate lower-priority task | Yes (needed anyway) |
| 3 | Audio rate used for analysis | Full rate (44.1 kHz) | Reduced by 2 to 4 times, since a cello has little useful content above about 5 kHz | Yes (add a filter stage in front) |
| 4 | Pitch search | Scores about 980 candidate pitches every step | Scores only pitches near spectral peaks, and when notes are steady just re-checks the notes already known | **Partly.** This changes results slightly and needs its own testing. The roadmap already lists the "check only" part. |
| 5 | Spreading the work | One burst per hop | Several small pieces spread over audio blocks | **Partly.** A separate task makes this less important. |
| 6 | Maths functions | Standard library `exp`/`log` | Tables | Yes (other session) |
| 7 | Joint pitch refinement | Up to two passes over all voices | Probably skipped or reduced | Yes (existing settings) |
| 8 | Optional features | Calibration, string identification, voice separation (didddle) all built in | Left out | Yes (compile-time switch) |
| 9 | Timing constants | Counted in analysis steps | In milliseconds | Yes (needed anyway) |

Only rows 4 and 5 are places where a from-scratch design would be meaningfully better, and both are optional until measurements say they are needed. The overall pipeline (clean up the spectrum, find peaks, score pitch candidates, fit voices, track notes) would stay the same.

## 3. The options

| Option | Description | Advantages | Disadvantages |
|---|---|---|---|
| **A. One shared core** (recommended) | Same source files; Bela is a build setting plus efficient mode | One set of fixes and tests. Max and WebAudio benefit from the speedups. | More compile-time switches in the code. May still miss the speed target. |
| **B. Separate Bela implementation** | A new, smaller detector written for Bela | Free to choose the cheapest design (rows 4 and 5). | Two code bases. Results will not match Max, so tracking and calibration need to be re-tuned and re-tested. High cost. |
| **C. Shared back half, separate front half** | Share tracking, calibration, settings and event types; write a cheaper spectrum and pitch-search stage only for Bela | Forks only the expensive stage (about 85% of the time) and keeps the tuned note behaviour. | Two front halves to maintain and test, and the front half is still being changed (7 of the last 24 commits). The tuning of the fitter would not carry over. |

## 4. Checkpoint: how we decide

1. **Now:** time the unmodified command-line tool on a Bela. Record the mean and worst time per hop.
2. **After** efficient mode, the other session's savings, and the 32-bit build: time it again on the Bela.
3. **Target:** mean analysis time per hop at most 40% of the hop length (at hop 512 and 44.1 kHz the hop is 11.6 ms, so 4.6 ms), and worst case under one hop length. The 40% leaves room for the audio system and for Linux on the same single processor core.

| Result at step 3 | Action |
|---|---|
| Target met | Stay with option A. |
| Up to 2 times over the target | Add the reduced-rate analysis (row 3) and the "check only" mode (row 4). Still option A. |
| More than 2 times over after that | Option C: write a cheaper front half for Bela. |
| Tracking behaviour itself has to differ on Bela | Only then think about option B. This is unlikely, because tracking costs only a few percent of the time. |

Uncertainties that could change this: the exact Bela board and software version (a faster board changes the answer), and whether the 20 to 50 times slowdown estimate is right. Both are settled by step 1.

## 5. What I would do in the next two weeks

1. Run step 1 on a Bela.
2. Make the two safe changes that help every host: allocate string-identification memory only when used, and convert the per-frame constants to milliseconds.
3. Add efficient mode (the preset) and compare its results with full mode on the test recordings.
4. Plan the detector split into "store audio" and "analyse", since Bela needs it in every case.
