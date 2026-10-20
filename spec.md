# Technical Design Document: Real-Time Polyphonic Pitch Detection for String Instruments

Version 1.0 · DSP architecture · Embedded and desktop implementations

## 1. Purpose and scope

This document specifies a real-time polyphonic pitch detector for string instruments, designed to identify several simultaneous pitched voices (at most \(V_{\max}\), bounded by the instrument's string count) and track them over time. Profiles for **bass, cello, viola, violin and guitar** are built in (up to 4 voices, 6 for guitar); all instrument-specific parameters live in an instrument profile (§1.3) so that further string instruments can be added without algorithm changes. The system produces both continuous pitch trajectories and discrete note-on/note-off events.

The design prioritizes low computational cost, bounded memory use, predictable latency, temporal stability, and portability across desktop software and embedded audio platforms such as Max/MSP, Bela, Raspberry Pi, and other ARM-based systems.

The detector is not intended to perform general-purpose audio transcription. It exploits the physical and acoustic characteristics of stringed instruments (harmonic partials, a fixed set of strings, one note per string) to reduce the search space and computation required.

### 1.1 Functional requirements

| Requirement                | Design target                                                 |
| -------------------------- | ------------------------------------------------------------- |
| Maximum polyphony          | Profile-defined, at most the string count; 4, or 6 for guitar                                        |
| Fundamental range          | Profile-defined; cello default 60–1,000 Hz                             |
| Input                      | Mono PCM audio                                                |
| Output                     | Continuous pitch estimates and note events                    |
| Analysis interval          | Approximately 5.33 ms at 48 kHz                               |
| Practical response latency | Target 40–100 ms, workload-dependent                          |
| Runtime                    | Continuous, real-time processing                              |
| Memory                     | Fixed-capacity buffers and bounded candidate sets             |
| Dependencies               | No mandatory ML runtime or external DSP framework             |
| Portability                | Standard C/C++ DSP core with platform-specific audio adapters |

These are initial engineering targets, not guaranteed performance figures. Accuracy, latency, and CPU usage must be established experimentally on the target hardware.

### 1.2 Design principles

1. Separate observation from inference. Spectral analysis generates evidence; pitch estimation and tracking interpret it.
2. Use a constrained model. Search only plausible fundamentals for the configured instrument, and limit the number of simultaneous voices to what its strings can sound.
3. Treat harmonics as shared evidence. A spectral peak may support multiple pitch hypotheses, so individual peaks cannot be assigned independently.
4. Use temporal continuity without suppressing genuine changes. Vibrato and sustained notes should be stable, while attacks and slides remain responsive.
5. Make uncertainty explicit. Confidence and ambiguity must be represented in the output rather than hidden behind a single pitch estimate.
6. Bound every real-time operation. No unbounded searches, dynamic allocation, blocking I/O, or unpredictable work in the audio-processing path.

### 1.3 Instrument profile and polyphony model

The detector core is instrument-agnostic. Everything that depends on the instrument is carried by an `InstrumentProfile`, supplied at initialization and applied to the search range, window sizing, templates, voice limit, and tracking policy. Profiles for bass, cello, viola, violin and guitar are built in (§1.4); further profiles (Appendix A) are data, not new algorithms.

```
constexpr uint32_t MAX_VOICES  = 8;   // compile-time capacity
constexpr uint32_t MAX_STRINGS = 8;

struct InstrumentProfile {
    const char* name;                          // "cello"
    uint32_t string_count;                     // 4
    float    open_string_hz[MAX_STRINGS];      // 65.41, 98.00, 146.83, 220.00
    float    string_tuning_cents[MAX_STRINGS]; // per-string offset, default 0
    float    min_frequency_hz;                 // 60
    float    max_frequency_hz;                 // 1000
    float    window_periods;                   // 10   (see §2.1)
    float    inharmonicity_B;                  // 0    (partials at h*f*sqrt(1+B*h*h))
    float    harmonic_weight_exponent;         // 0.5  (w_h = h^-p)
    uint8_t  excitation;                       // BOWED | PLUCKED | MIXED (cello: MIXED)
    uint8_t  string_constraint;                // OFF | SOFT | HARD (default SOFT)
    float    string_infeasible_penalty;
    float    voice_penalty[MAX_VOICES];        // lambda_V in §7.5
};
```

**Cello profile.**

| Field | Value | Rationale |
| ----- | ----- | --------- |
| Open strings | C2 65.41, G2 98.00, D3 146.83, A3 220.00 Hz | Standard tuning; per-string cent offsets allow scordatura |
| Search range | 60–1,000 Hz | About 1.5 semitones below C2 for detuning, up to high-register notes and harmonics |
| \(V_{\max}\) | 4 | One note per string |
| Excitation | Mixed (arco, pizzicato, col legno) | Release and retrigger logic must handle both sustained and decaying notes (§8.6) |
| \(B\) | 0 | Inharmonicity of cello strings is small enough to ignore initially; the field is kept so plucked instruments can use it |

**Voice limit.** \(V_{\max}\) is bounded by the string count, because a string sounds one note at a time. Sustained bowed polyphony on the cello is realistically one or two voices, with three or four only as rolled chords; pizzicato, strummed chords, and ringing notes can have all four strings sounding. The limit is a runtime setting (`max_voices ≤ MAX_VOICES`), so a lower value can reduce CPU and false activations when the repertoire allows.

**String-feasibility constraint.** A set of pitches is physically playable only if each pitch can be assigned to a distinct string whose open pitch is at or below it (within tolerance). With ascending pitches \(p_1\le\dots\le p_V\) and ascending open pitches \(s_1\le\dots\le s_{S}\), this reduces to \(V\le S\) and \(p_i \ge s_i\) (minus tolerance) for each \(i\). For example, two simultaneous notes both below G2 are infeasible, since only the C string can sound them. The constraint feeds the model-selection penalty (§7.5) and the string index in the output (§9.1).

- `SOFT` (default): infeasible hypotheses incur `string_infeasible_penalty`, since sympathetic resonances, scordatura, and harmonics can violate the nominal assumption.
- `HARD`: infeasible hypotheses are rejected.
- `OFF`: the constraint is ignored (for example, for an unknown tuning).

The upper bound for a string is the profile's `max_frequency_hz`, not a fret limit, because natural and artificial harmonics sound far above the open pitch.

**Sample-rate independence.** The profile is specified in Hz, and window and hop sizes are derived from it and the sample rate (§2.1), so the same profile works at 44.1, 48, and 96 kHz.

### 1.4 Profiles as built, and what the synthetic tests show

| Profile | Open strings (Hz) | Search range (Hz) | Voices | Long window at 44.1 kHz |
| ------- | ----------------- | ----------------- | ------ | ----------------------- |
| bass (5-string) | 30.87, 41.20, 55.00, 73.42, 98.00 | 28–500 | 4 | 16,384 (372 ms; 6 periods of the lowest pitch) |
| cello | 65.41, 98.00, 146.83, 220.00 | 60–1,000 | 4 | 8,192 (186 ms) |
| viola | 130.81, 196.00, 293.66, 440.00 | 120–1,500 | 4 | 4,096 (93 ms) |
| violin | 196.00, 293.66, 440.00, 659.26 | 185–2,800 | 4 | 4,096 (93 ms) |
| guitar | 82.41, 110.00, 146.83, 196.00, 246.94, 329.63 | 70–1,400 | 6 | 8,192 (186 ms) |

The window length follows the lowest searchable pitch (§2.1), so changing `minfreq` changes latency. The partial band used by the fit is `max(4 kHz, 3 x maximum pitch)`, capped at 0.45 of the sample rate. Guitar and bass strings are modelled with inharmonicity (partial h at \(hf\sqrt{1+Bh^2}\), B = 1e-4 and 5e-5).

Measured on synthetic scenes with exact truth (single notes, fifths, chords, strums and arpeggios of 1 to 6 strings; the Python reference, the C++ core agrees event for event):

- **Viola and violin** are essentially solved on synthetic material (note-level F1 1.00).
- **Cello** four-open-string chords (note-level F1 about 0.8) and **bass** four-string chords (about 0.6) remain the weakest cases, because their partials coincide heavily.
- **Guitar** reaches note-level F1 1.00 and frame-level F1 0.93 on chords of up to six notes after two profile-specific changes: no extra evidence is demanded for a voice whose harmonic series nests with another (chords stack octaves such as E2/E3/E4), tracks persist longer through short fit dropouts (prior-pitch gain threshold x0.25, 120 ms hang and 300 ms release instead of 50 and 100), and a new note must show a pluck attack (§8.9).
- **Inharmonicity must be right.** With the synthetic strings' inharmonicity B equal to the profile's value (1e-4), guitar note-level F1 is 0.99; if the real value is 0 or 3e-4 it falls to about 0.5–0.6, and 2e-4 gives 0.83. Widening the partial-match tolerance with harmonic number does not recover this and costs accuracy when B is right; restricting the fit to fewer partials is more robust but loses accuracy overall (F1 about 0.75). Real strings vary in B (wound against plain strings), so the profile value is a guess and a calibration step (§12.3) that measures B (and the tuning offsets) from isolated open-string notes fixes this. Bowed instruments have negligible B and are unaffected.

These results use synthetic strings only; no real guitar, viola, violin or bass recordings have been evaluated.

## 2. System architecture

The implementation is divided into seven processing stages and a platform-independent output interface.

01

Input conditioning

DC rejection, optional filtering, input-level monitoring

02

Frame management

Fixed-capacity ring buffer and hop scheduler

03

Spectral analysis

Long-window and short-window magnitude spectra

04

Candidate generation

Harmonic salience, local maxima, active-track predictions

05

Polyphonic model fitting

Jointly explain the spectrum with one to \(V_{\max}\) pitches

06

Temporal tracking

Voice association, smoothing, onset and release states

07

Output and diagnostics

Continuous estimates, events, confidence and telemetry

Each stage has a defined input, output, state, and computational budget. Platform-specific code is limited to audio acquisition, scheduling, and message delivery.

### 2.1 Processing schedule

Let:

- \(F_s\) = sample rate in samples per second.
- \(N_L\) = long-window size.
- \(N_S\) = short-window size.
- \(H\) = hop size in samples.

The initial configuration is:

| Parameter                     | Default   |
| ----------------------------- | --------- |
| \(F_s\)                     | 48,000 Hz |
| \(N_L\)                     | 8,192     |
| \(N_S\)                     | 2,048     |
| \(H\)                       | 256       |
| Maximum voices                | 4 (cello)         |
| Candidate capacity            | 24        |
| Harmonics per candidate       | 12        |
| Maximum fundamental frequency | 1,000 Hz  |

The analysis interval is:

\[ T_H = \frac{H}{F_s} = 5.333\text{ ms} \]

The window durations are:

\[ T_L = \frac{N_L}{F_s} = 170.667\text{ ms} \]

\[ T_S = \frac{N_S}{F_s} = 42.667\text{ ms} \]

A new analysis frame is generated every hop. The long window supplies frequency evidence; the short window supplies more temporally localized attack evidence.

These parameters are configurable. The implementation must not assume a fixed audio sample rate or block size.

The long-window size is derived from the profile rather than fixed: \(N_L\) is the smallest power of two such that the window contains at least `window_periods` periods of the lowest fundamental,

\[ N_L = \operatorname{nextpow2}\!\left( \frac{P\,F_s}{f_{\min}} \right) \]

For the cello (\(P=10\), \(f_{\min}=60\) Hz, \(F_s=48\) kHz) this gives 8,192. A profile with a lower \(f_{\min}\), such as the double bass, requires a longer window or multi-rate analysis (Appendix A). The short window and hop are set independently from the desired onset resolution. `long_fft_size` in the configuration overrides the derived value.

## 3. Stage 1 — Input conditioning

### 3.1 Input contract

The core receives mono, floating-point PCM samples. A typical internal representation is `float32`, with normalized audio nominally in the range \([-1,1]\).

The audio adapter is responsible for converting platform-specific sample formats and channel layouts into this representation. Stereo input may be downmixed, but phase cancellation can reduce important components. When possible, accept a designated channel or use a phase-safe downmix policy. In the reference setup there are two sensors: a piezo pickup (left channel) and a condenser microphone (right). They have very different spectral envelopes and transient behavior, and a naive sum risks phase cancellation, so the core takes one selected channel (`input_channel`) and each channel is evaluated separately. Combining them (for example, per-channel candidate evidence) is a later experiment.

### 3.2 DC rejection and low-frequency noise

Use a first-order high-pass filter to remove DC offset and very low-frequency handling noise.

A suitable difference equation is:

\[ y[n] = a\left(y[n-1]+x[n]-x[n-1]\right) \]

where:

\[ a = \frac{1}{1 + 2\pi f_c/F_s} \]

Here \(f_c\) is the cutoff frequency. An initial cutoff of 25–35 Hz is appropriate, subject to the instrument's lowest intended fundamental and the recording environment.

Do not use aggressive high-pass filtering to suppress hum: it can remove useful low-frequency evidence or distort the lowest notes. If mains hum is problematic, use an optional narrow notch filter.

### 3.3 Input-level handling

Maintain a slow estimate of signal level and a peak detector for diagnostics. Do not automatically apply fast AGC in the pitch-analysis path: gain modulation changes the apparent envelope and may interfere with onset and voice-amplitude tracking.

Input conditioning must not clip, compress, or otherwise alter the harmonic structure unnecessarily.

### 3.4 State initialization

On startup or reset:

- Clear filter histories.
- Clear ring-buffer state.
- Reset noise-floor and envelope estimators.
- Mark all voices inactive.
- Suppress note events until sufficient valid audio history is available.

## 4. Stage 2 — Frame management

### 4.1 Ring buffer

Use a fixed-size ring buffer large enough for the longest analysis window, with optional extra capacity for implementation convenience.

For each incoming sample:

1. Apply input conditioning.
2. Write the conditioned sample into the ring buffer.
3. Advance the write index.
4. Increment the hop counter.
5. When the hop counter reaches \(H\), schedule one analysis update.

The ring buffer must preserve chronological ordering when extracting frames, including when the read spans the physical end of the buffer.

A single shared audio history can serve both FFT paths. Separate history buffers are unnecessary unless required by the FFT library or concurrency model.

### 4.2 Frame alignment

The long and short windows should end at the same newest sample. This gives the spectral observations a common timestamp.

For a causal implementation, each frame covers only current and past samples. The long-window estimate describes a relatively long history and will naturally respond slowly to changes.

For a centered offline or look-ahead implementation, frames can be aligned to their center, at the cost of future-sample buffering.

The implementation must define one timestamp convention and use it consistently for both continuous estimates and note events.

### 4.3 Startup behavior

Do not analyze uninitialized buffer contents. Options are:

- Wait until the longest window is filled.
- Zero-pad the initial history and mark early estimates as provisional.

The first approach is simpler and safer for live performance.

## 5. Stage 3 — Spectral analysis

### 5.1 Windowing and transform

For each analysis update, construct windowed frames:

\[ x_L[n] = x[n-N_L+1]\,w_L[n] \]

\[ x_S[n] = x[n-N_S+1]\,w_S[n] \]

where \(w_L\) and \(w_S\) are Hann windows.

Compute the discrete Fourier transforms using a real-input FFT implementation where available.

The spectral power is:

\[ P[k] = \Re(X[k])^2 + \Im(X[k])^2 \]

The magnitude is:

\[ M[k] = \sqrt{P[k]} \]

Use the magnitude spectrum for the initial whitening, salience, and template model. Power can be used for energy and level estimation, but the two representations must not be mixed without adjusting the model.

### 5.2 Frequency mapping

For FFT length \(N\), bin \(k\) corresponds to:

\[ f_k = \frac{kF_s}{N} \]

The long-window bin spacing at 48 kHz is approximately 5.86 Hz; the short-window spacing is 23.44 Hz.

These values describe bin spacing, not the precision of a frequency estimate. Interpolation can refine the location of a spectral peak, but cannot recover information that the observation does not contain.

### 5.3 Peak interpolation

For a local maximum at bin \(k\), parabolic interpolation of log magnitude provides a low-cost sub-bin estimate.

Let:

\[ \ell_{-1}=\log(M[k-1]+\epsilon) \]

\[ \ell_0=\log(M[k]+\epsilon) \]

\[ \ell_{+1}=\log(M[k+1]+\epsilon) \]

Then:

\[ \delta = \frac{1}{2} \frac{\ell_{-1}-\ell_{+1}} {\ell_{-1}-2\ell_0+\ell_{+1}} \]

The refined frequency is:

\[ \hat f = (k+\delta)\frac{F_s}{N} \]

Clamp \(\delta\) to a reasonable interval, such as \([-0.5,0.5]\), and reject estimates from flat or invalid peaks.

### 5.4 Spectral whitening and noise-floor handling

Whitening is applied to the **long-window** spectrum only: the \(N_L=8192\) sample Hann-windowed frame. The long window provides the frequency resolution needed to distinguish nearby pitches and resolve harmonic structure, and its whitened magnitude \(W\) is the single spectrum used for candidate generation (§6) and polyphonic model fitting (§7). The short-window spectrum is processed separately for onset detection (§5.5) and never substitutes for \(W\) in the pitch pipeline.

1. Compute the long-window magnitude spectrum \(M[k]\) (§5.1) and its log: \(L[k]=\log(M[k]+\epsilon)\).
2. Estimate the broad spectral envelope by smoothing the log-magnitude across frequency:

   \[ E_L[k]=\operatorname{Smooth}(L[k]) \]

   The smoothing width should scale with frequency, approximating a fraction of an octave rather than a fixed number of bins, so the behavior does not change drastically between low and high frequencies.
3. Subtract the envelope in the log domain, with clipping so low-energy bins are not amplified excessively:

   \[ W[k] = \exp\left( \operatorname{clip}(L[k]-E_L[k],-c,c) \right) \]

   Here \(c\) limits extreme values; 2–3 natural-log units is a reasonable starting range. Dividing \(M[k]\) by \(\exp(E_L[k])\) with a floor on the divisor is an equivalent linear-domain formulation. Because \(W\) is a residual relative to the local envelope, it is approximately unit-scaled without further normalization.
4. Estimate a slow noise floor \(\mathcal{N}[k]\) as the time-smoothed *frequency-median* of \(M[k]\) (a median over about 40 neighbouring bins is robust to sparse harmonic peaks), smoothed with an asymmetric exponential that follows decreases quickly and increases slowly. Applying the asymmetric smoother to \(M[k]\) bin-by-bin instead settles near a very low percentile of the noise distribution and badly overstates the signal-to-noise ratio (the prototype showed spurious voices in pure noise). A spectral peak is significant only if it exceeds a multiple of \(\mathcal{N}[k]\) (default 5). Use it as a **soft gate on evidence** (for example, down-weighting bins where \(M[k]\) does not exceed \(\kappa\,\mathcal{N}[k]\)), not as a subtraction from the spectrum, because genuine quiet harmonics may be important for identifying a weak fundamental.
5. Use the gated \(W\) consistently for candidate scoring and spectral-template fitting.

**Domain consistency.** All templates \(T_i\) in §7 represent expected *magnitude* spectra, and the fitting objective compares them against \(W\) (magnitude), with the noise scale \(\sigma_k\) expressed in the same whitened domain. Candidate scoring (§6.2) also uses \(W\). Magnitude-based candidate scores must not be combined with a power-based fit without an explicit conversion. If a power-domain fit is ever adopted, \(W\) and \(T_i\) must both be squared.

**Physical amplitude.** Whitening discards absolute level. A voice's physical amplitude is recovered after fitting by undoing the envelope at its partials:

\[ A_i = a_i\,\frac{\sum_h w_h \exp(E_L[k_{h,i}])}{\sum_h w_h} \]

where \(k_{h,i}\) is the bin nearest partial \(h\) of voice \(i\). The unwhitened \(M[k]\) is retained for this step, for level monitoring, and for model validation.

### 5.5 Short-window onset evidence

Onset evidence comes from the **short-window** spectrum (\(N_S=2048\)), which has coarser frequency resolution (23.44 Hz bins) but better temporal localization. Whiten it independently using the procedure in §5.4, with envelope smoothing adapted to its bin spacing, to obtain \(W_S[k]\). Then compute spectral flux:

\[ F_t = \sum_k \max(0,W_{S,t}[k]-W_{S,t-1}[k]) \]

Normalize against a rolling baseline to obtain onset strength \(O_t\).

Use onset strength as supporting evidence for new notes. A spectral-flux peak is not itself proof of a new pitch: bow changes, col legno attacks, and other transients can also produce strong flux.

In polyphonic passages a global \(F_t\) can be masked by sustained voices. The same flux can therefore also be accumulated over only the bins near a candidate's partials, giving per-candidate onset support for \(d_{\text{onset}}\) in §8.3.

## 6. Stage 4 — Fundamental candidate generation

### 6.1 Search range

Search the fundamental range defined by the instrument profile (cello: 60–1,000 Hz). The analysis spectrum must extend above the maximum fundamental to capture useful partials.

Use a logarithmic pitch grid with a step of approximately 5 cents:

\[ f(m)=440\cdot 2^{(m-69)/12} \]

where \(m\) is fractional MIDI pitch.

This grid provides an efficient initial search. Final frequencies are refined continuously rather than quantized to the grid.

### 6.2 Harmonic salience

For every candidate fundamental \(f\), estimate its support from its expected partials:

\[ S(f)=\sum_{h=1}^{K} w_h\,Q(hf) \]

where:

- \(K=12\) initially.
- \(w_h=h^{-p}\), with \(p\) from the instrument profile (default 0.5, i.e. \(1/\sqrt{h}\)), optionally tapered at higher harmonics.
- \(Q(hf)\) is the whitened spectral magnitude sampled near the expected partial.

Interpolate between bins, and search a small neighborhood around each expected harmonic. The neighborhood should reflect frequency resolution and observed peak width.

*Prototype finding.* Taking the maximum of the clipped whitened spectrum within ±1 bin of each partial saturates: the whole Hann mainlobe sits at the clip ceiling, so adjacent grid pitches tie across a plateau tens of cents wide and an octave candidate scores the same as the true pitch. Evidence should therefore be taken from interpolated spectral *peaks* (§5.3): the support for an expected partial at frequency \(P\) is the strongest nearby peak amplitude times a Gaussian of the frequency error, with width about one Hann mainlobe (optionally widened with harmonic number for vibrato). Candidates also carry an *interleave* term, the energy found midway between their expected partials \((h+\tfrac12)f\), which is empty for the true pitch and occupied for a candidate an octave above it.

Normalize the score by the sum of the applicable harmonic weights so candidates with fewer available harmonics are not automatically penalized.

Do not require the first harmonic to be present. Missing-fundamental cases should remain valid hypotheses.

### 6.3 Harmonic reliability

Each partial contributes evidence, but not all partials are equally reliable.

Reduce the contribution of:

- Partials outside the useful analysis band.
- Partials with very low signal-to-noise ratio.
- Peaks inconsistent with the expected harmonic neighborhood.
- Isolated peaks likely to originate from transient or non-pitched noise.

The initial implementation can use simple local-contrast and noise-floor weights. More sophisticated reliability estimates can be added later without changing the rest of the architecture.

### 6.4 Octave ambiguity

A note at \(f\) and a note at \(2f\) share many spectral components. To reduce octave errors, evaluate:

- Evidence near the candidate fundamental.
- Evidence at odd harmonics.
- The proportion of spectral support already explained by the octave-related candidate.
- Compatibility with previously active tracks.
- Whether a new attack supports the appearance of a separate higher voice.

This should be a soft penalty, not a hard rule. A genuine cello note may have a weak fundamental or unusually strong even harmonics.

What is already used against ghost octaves (calibrated \(B\) and per-string harmonic profiles, the attack requirement, the octave hold) is in §8.9 and §12.3; a per-track \(B\) and a body response as a function of frequency, which should make the octave test more reliable, are proposed in §17.2 and §17.3.

### 6.5 Local maxima and candidate reduction

Retain local maxima of harmonic salience after non-maximum suppression. Use an initial minimum separation of 20–30 cents and a fixed maximum candidate capacity of 24.

Candidate retention must also preserve predictions from active tracks. If a sustained note temporarily loses harmonic energy, its predicted pitch should remain eligible for model fitting.

The resulting candidate list contains pitch hypotheses, their salience, octave-ambiguity information, and optional onset support. It does not yet declare the actual number of notes.

## 7. Stage 5 — Polyphonic model fitting

### 7.1 Objective

Find the subset of one to \(V_{\max}\) candidate fundamentals that best explains the observed spectrum while avoiding unnecessary voices.

Let \(Y[k]=W[k]\) denote the whitened long-window magnitude spectrum (§5.4) and \(T_i[k]\) the magnitude-domain spectral template for candidate \(i\). In continuous frequency form, the model is:

\[
\hat{Y}(f) = \sum_{i=1}^{V} a_i T_i(f), \qquad V \leq V_{\max},\quad a_i \geq 0
\]

and on the FFT grid:

\[ \hat Y[k]=\sum_{i=1}^{V}a_iT_i[k],\quad a_i\geq0 \]

Here \(T_i(f)\) is the harmonic template for voice \(i\), \(a_i\) is its nonnegative amplitude in the whitened domain, \(V\) is the number of voices in the hypothesis, and \(V_{\max}\) is the configured maximum polyphony (3 by default). Physical amplitudes are recovered afterward as described in §5.4.

The model is an approximation: actual bowed-string spectra vary with bow position, pressure, string, articulation, and instrument construction.

### 7.2 Harmonic templates

Construct each template from weighted peaks near integer multiples of the candidate frequency:

\[ T_i[k]=\sum_{h=1}^{K}w_h G(f_k-hf_i) \]

\(G\) is a compact peak kernel. A Gaussian or triangular kernel is adequate for the first implementation.

Templates may be cached for quantized candidate frequencies, with interpolation or local regeneration for refined frequencies.

For low CPU targets, store only nonzero template entries as sparse lists of bin indices and weights. There is no need to evaluate every candidate across every FFT bin during initial scoring.

### 7.3 Greedy selection

Use the following bounded procedure:

1. Evaluate the best single-note explanations.
2. Select the candidate with the lowest penalized reconstruction loss.
3. Test remaining candidates as possible additions.
4. Select the addition with the greatest loss reduction.
5. Refit all selected amplitudes.
6. Repeat until \(V_{\max}\) voices are selected or no addition provides sufficient improvement.
7. Test local pitch alternatives and octave alternatives around the selected candidates.

The complexity penalty must prevent a third note from being added merely because it explains a small amount of residual noise.

### 7.4 Joint amplitude estimation

For a fixed candidate set, estimate nonnegative amplitudes by minimizing:

\[ D(Y,\hat Y)= \sum_k \rho\left( \frac{Y[k]-\hat Y[k]}{\sigma_k+\epsilon} \right) \]

where \(\rho\) is a robust loss and \(\sigma_k\) represents a local noise or weighting scale.

A squared loss is a useful baseline. A Huber loss can make the fitting less sensitive to isolated transient peaks.

Because there are at most \(V_{\max}\) voices (4 for the bowed profiles, 6 for guitar), a small fixed number of coordinate-descent iterations is sufficient for a prototype. Stop early if the improvement becomes negligible.

### 7.5 Model complexity

Compare models with one up to \(V_{\max}\) voices using:

\[ J_V=D_V+\lambda_V \]

The penalty \(\lambda_V\) comes from the profile's `voice_penalty[]` and should increase with each added voice, so that a third or fourth voice requires stronger evidence than a second. It may also depend on evidence strength. When the string constraint is `SOFT`, add a term for infeasible hypotheses:

\[ J_V = D_V + \lambda_V + \lambda_{\text{str}}\,\mathbb{1}[\text{infeasible}] \]

The per-voice penalties must be calibrated per instrument; with four voices, shared harmonics make a spurious extra note easier to justify, so the penalties matter more than at three.

Do not force the model to use all \(V_{\max}\) voices. Silence, single notes, and double stops must be valid outputs.

### 7.6 Residual interpretation

Use the residual spectrum to propose additional candidates, not as the only evidence for a new note.

After selecting a candidate from the residual, refit the complete model against the whitened spectrum \(W\) (not the residual). This avoids compounding errors from repeatedly subtracting approximate harmonic templates.

A residual that consists mainly of broadband attack energy should not trigger an additional pitch unless harmonic evidence also supports it.

### 7.7 Pitch refinement

Once the best candidate set has been selected, refine each fundamental in a narrow neighborhood around its initial estimate.

One approach is to test small frequency offsets and choose the offset that minimizes the joint reconstruction loss. Another is to use a local parabolic fit to the harmonic-salience curve.

Refinement must be joint or at least iterated across the selected voices, because changing one fundamental can change how shared harmonics are explained.

### 7.8 Prototype findings (Python reference)

Measured on synthetic bowed and plucked chords (1–4 notes, 40 dB and 20 dB SNR) and on mixes made by overlapping real cello clips. These are the settings and lessons the C++ core should inherit.

- **Fit domain.** The fit uses a *peak-rendered* spectrum: interpolated spectral peaks drawn with the same Gaussian kernel as the templates, amplitude \(=(M_p/e^{E_L})^{0.5}\) (unclipped envelope-relative peak height, compressed). Fitting the clipped raw \(W\) failed: its mainlobe plateaus are wider than the templates and the clip erases amplitude relations such as the doubling an octave partner causes.
- **Peak location.** Local maxima must be found on the raw magnitude \(M\), not on \(W\); on a clipped plateau the first bin is not the true peak and low partials were displaced by up to 9 Hz. Fixing this raised candidate and fit quality more than any parameter tuning (fit F1 0.84 to 0.91).
- **Template band.** Templates must cover all partials in a fixed band (4 kHz, up to 64 harmonics), not a fixed count of 12; otherwise higher partials of the same note count as unexplained energy and bias voice selection.
- **Flat template weights.** Whitening flattens partial levels, so the fit uses equal harmonic weights (exponent 0), unlike the salience score.
- **Efficient form.** The loss is quadratic, so each frame needs only \(b_i=\langle T_i,Y\rangle\) and the Gram matrix \(G_{ij}=\langle T_i,T_j\rangle\) over about 24 candidates; amplitude fitting is a tiny NNLS. The Python (NumPy) reference takes about 3 ms per hop including analysis (hop budget 5.8 ms at 44.1 kHz), so the core must be considerably faster than this reference for the Max external.
- **Nested series.** A candidate whose partials are a subset (octave, twelfth) or superset of a chosen voice needs extra explained energy (+0.10 of total) to be added. This removes most octave false positives but makes genuine octave dyads (C2+C3) hard to retain; this is a known trade-off, to be revisited with tracker and onset evidence.
- **Gain thresholds are fractions of peak energy**: 0.05 for the first voice, 0.04 for each added voice.

Remaining weaknesses (as of this prototype): vibrato of ±25 cents lowers synthetic F1 from 0.91 to about 0.77, and widening the kernel with harmonic number did not help; four-voice chords with heavily shared harmonics have recall of about 0.5–0.75 in single frames (temporal tracking, Milestone 4, is expected to recover some of this); a steady low-level tone (about −66 dB) in the piezo "dead air" recording is reported as a voice, so an absolute level gate is required; single-frame fits flicker near thresholds.

## 8. Stage 6 — Temporal tracking

### 8.1 Track state

Maintain \(V_{\max}\) fixed-capacity voice records (storage is allocated for MAX_VOICES). Each record contains:

- Persistent internal track ID.
- Active/inactive state.
- Current frequency and fractional MIDI pitch.
- Predicted pitch and pitch velocity.
- Current amplitude estimate and confidence.
- Candidate confirmation count.
- Time since last reliable spectral support.
- Onset timestamp and release-state information.
- Short history of pitch, amplitude, and confidence estimates.

Use a fixed-size ring buffer for pitch history. A short history of 5–15 frames is sufficient for initial velocity and stability estimates.

### 8.2 Prediction

Predict each active voice's pitch in log-frequency or MIDI units:

\[ \hat m_t=m_{t-1}+v_{t-1}\Delta t \]

where \(v\) is estimated pitch velocity in semitones per second.

Estimate velocity from recent observations using a robust difference or regression. Limit extreme predictions so a single erroneous frame cannot send a track outside the valid range.

When velocity is unreliable, use the previous pitch as the prediction.

### 8.3 Candidate-to-track assignment

For each selected candidate \(i\) and active track \(j\), compute an association cost:

\[ C_{ij}= \alpha\,d_{\text{pitch}} +\beta\,d_{\text{amplitude}} +\gamma\,d_{\text{timbre}} +\delta\,d_{\text{onset}} \]

where:

- \(d_{\text{pitch}}\) measures distance from the predicted pitch.
- \(d_{\text{amplitude}}\) measures a change in the note's estimated spectral contribution.
- \(d_{\text{timbre}}\) measures changes in harmonic shape.
- \(d_{\text{onset}}\) incorporates evidence for a new attack.

Use log amplitude for level comparisons and clamp the resulting costs. Missing amplitude or timbral information should not automatically invalidate an association.

The reference implementation enumerates assignments by dynamic programming over the observation subsets (cheap at these sizes; the Hungarian algorithm is the alternative) (cubic in the voice count, still trivial at this size). Include explicit unmatched states for both tracks and candidates.

### 8.4 Pitch-jump gating

Reject implausible associations, but do not impose a universal maximum pitch jump that prevents legitimate cello passages.

A sustained track should have a tighter gate. A strong onset may justify a larger jump or the creation of a new track.

If two voices cross, keep their persistent IDs independent of their instantaneous pitch ordering. Publish a separate low/middle/high rank if the downstream application needs ordered outputs.

### 8.5 Pitch smoothing

Smooth in fractional MIDI units, equivalent to smoothing log frequency.

A first-order adaptive smoother is:

\[ m_t=m_{t-1}+\eta_t(m_{\text{obs}}-m_{t-1}) \]

Choose a larger \(\eta_t\) during attacks or rapid changes and a smaller value during stable sustained notes.

The output should expose both a stable estimate and, optionally, a faster estimate. This allows the application to choose how much vibrato and pitch fluctuation to preserve.

Do not quantize the tracked frequency to integer MIDI pitch. Quantization belongs in the note-event layer.

### 8.6 State machine

Use the following states:

- `INACTIVE`: no tracked note.
- `PENDING`: a new pitch is being confirmed.
- `ACTIVE`: the pitch is being tracked.
- `RELEASING`: evidence has weakened, but the track is retained temporarily.

A typical initial configuration at a 256-sample hop and 48 kHz is:

| Parameter                    | Starting value                  |
| ---------------------------- | ------------------------------- |
| Candidate confirmation       | 2–3 frames                      |
| Strong-onset confirmation    | 1 frame when confidence is high |
| Release hang time            | 50 ms                           |
| Maximum unsupported duration | 100 ms                          |
| Note pitch-change hysteresis | 40–60 cents                     |
| Maximum active voices        | \(V_{\max}\) (4 for cello)                               |

These thresholds are initial tuning parameters, not fixed properties of the instrument.

A release decision should combine amplitude decay, harmonic support, and track-association evidence. A short dropout should not terminate a note, but a persistent lack of evidence should.

Release behavior depends on the profile's excitation type. A bowed note ends when the bow stops, so evidence collapses relatively quickly. A plucked note decays gradually, and it may ring while other notes are played. For `PLUCKED` and `MIXED` profiles, release should therefore be driven by amplitude falling a configured amount below the track's peak (or below the noise floor) rather than by an absolute hang time, and a new onset near an existing track's pitch should be able to retrigger it (note-off then note-on) without waiting for the old note to decay.

Excitation-event rules that separate a new pluck from energy coupled between strings, and string exclusion to admit legato notes, are proposed in §17.4 and §17.5.

### 8.7 Note events

Generate note-on only when a candidate has been confirmed and has sufficient confidence. Generate note-off when the corresponding active track has passed its release criteria.

For a pitch change within an existing track, distinguish between:

- Continuous pitch motion, such as vibrato or glissando.
- A new discrete note, supported by an onset and sufficient pitch separation.
- An uncertain transition, where the system should retain the track but lower confidence.

A 40–60 cent threshold can be a starting point for detecting substantial pitch changes, but it should not alone trigger note events. The event layer should use onset evidence, pitch persistence, and the configured musical interpretation policy.

If note events are intended for MIDI output, define how repeated notes at the same pitch are represented. A repeated articulation may require a note-off followed by a note-on even when the pitch has not changed.

### 8.8 Confidence estimation

Confidence should combine several independent indicators:

- Harmonic salience relative to competing candidates.
- Improvement in reconstruction loss when the candidate is included.
- Agreement between predicted and observed pitch.
- Signal-to-noise ratio of supporting partials.
- Stability over recent frames.
- Ambiguity with octave-related candidates.

Keep the components available for diagnostics. A single aggregate confidence is convenient for downstream use, but it should not obscure whether uncertainty arises from weak audio, overlapping harmonics, or unstable tracking.

Do not label the result a probability unless calibrated against ground-truth recordings.

### 8.9 Prototype findings (Python reference)

Measured at 44.1 kHz with a 256-sample hop (5.8 ms). Note-level scores use `mir_eval` (onset within tolerance, pitch within 50 cents, offsets ignored).

| Parameter | Value that worked | Notes |
| --------- | ----------------- | ----- |
| Confirmation | 6 frames (35 ms), 4 frames with a strong onset | 2–3 frames (the table above) produced ghost notes at pluck attacks |
| Release hang / timeout | 50 ms / 100 ms of missing support | Release delivery lags the true end by about 100–200 ms because of the 170 ms window |
| Association gate | 1.0 semitone (0.6 while pending) | Hungarian assignment on pitch distance to the prediction |
| Minimum voice separation | 70 cents | Without it the fitter returned two voices on one pitch under vibrato and the tracker spawned a duplicate track |
| Absolute level gate | −58 dBFS | Rejects the steady −66 dB tone in the piezo "dead air" recording |
| Prior persistence | gain thresholds × 0.5 near an active track's predicted pitch | Reduces single-frame flicker |

- **Per-track onset evidence.** The global whitened flux of §5.5 is clipped and sees almost no change when the same pitch is plucked again. Retrigger and onset timing instead use *tonal re-attack evidence*: the short-window energy at the first eight partials of the track's pitch, relative to its minimum over the previous 14 frames, required to exceed the energy midway between partials by 6 dB, so that the broadband attack of a different note does not retrigger a sustained one. Threshold 10 dB. A retrigger is not allowed within 26 frames (about 150 ms) of the previous note-on, so very fast repeated notes (tremolo) are not resolved.
- **Latency.** Synthetic notes were delivered 70–90 ms after the physical onset (retriggers of a ringing pluck about 25 ms) with onset time estimates within about 30 ms.
- **Results.** Synthetic scenes (melody, double stops, plucked arpeggio, strums, repeated pluck): note-level F1 0.99. Real mono and double-stop clips, scored against Basic Pitch on the same clip: F1 about 0.4–0.8 (mean about 0.6). Real overlapped mixes: F1 about 0.3 against Basic Pitch's 0.43, on a reference derived from Basic Pitch itself. Over-segmentation is the main failure: 375 notes reported for 272 reference notes after tuning (578 before).
- **Octave and harmonic ghosts.** Two safeguards were added from guitar and bass reports. (1) *Octave hold*: when a sounding note loses fit support while a candidate appears exactly an octave, twelfth or two octaves from it with no tonal re-attack at that pitch, the note is held for up to 12 frames instead of being released and replaced; this stops fundamental/octave flicker from becoming note events and from flipping the pitch output. On the real cello mixes it cut reported notes from 375 to 304 (272 reference) and raised F1 from 0.29 to 0.32. (2) *Harmonic confirmation guard*: a pending note whose pitch is an integer multiple of another live note (the weaker of the pair, or the higher if within 3 dB) must persist 14 frames before it counts. It removes the short ghost partials that appear at a pluck attack, but it delays genuine octave doubling in chords (a real E3 over E2 took 0.8 s), so it is on by default only for bass, which is nearly monophonic.
- **Attack evidence for plucked instruments.** A real plucked note always starts with an attack, and the fit finds it 60 to 300 ms later. For guitar and bass a pending note is therefore confirmed only if the Hann-weighted short-window energy rose by at least 8 dB (largest jump of a frame above the minimum of the ten before it) within the last 80 frames (470 ms); otherwise it is dropped after 88 frames. This is broadband, so it works for the low strings whose partials the short window cannot resolve (a per-pitch tonal rise and the whitened spectral flux both failed there). The energy history starts with the first hop of audio, not the first analysis frame, because with a 372 ms bass window a note plucked in the first moments would otherwise show no attack. It removes voices that appear mid-decay without a new pluck (sympathetic strings, a sub-octave ghost under a ringing string). It also removes legato notes such as hammer-ons and pull-offs, which have no attack of their own.
- **Real DI recordings** (noisy DI box, noise floor about -63 to -72 dBFS, 60 Hz mains hum; `data/`). Open-string passes have a known truth: guitar (E2 A2 D3 G3 B3 E4) and 5-string bass (B0 E1 A1 D2 G2). With the profile defaults, the bass is detected exactly (5 of 5, no extras) and the guitar finds all six strings plus five phantom octaves and twelfths at the pluck; calibrating on the same pass (all six strings are captured from the noisy signal) and requiring an attack removes all of them (6 of 6, no extras). Chords have no truth: against Basic Pitch (a rough reference) the guitar chords reach precision 0.81 at recall 0.34, up from 0.59 before the attack requirement. Measured by eye on spectrograms, the remaining weakness is low strings in a strummed chord (E2, B2, E3 of an open E major) that ring for seconds while the fit stops reporting them after 0.2 to 1 s, because every partial of the low E coincides with another chord tone, so its only unique evidence is one peak at 82 Hz. A 60 Hz mains line is visible in the recordings but did not cause detections (the B1 notes found are real, about 62.3 Hz); no hum suppression was needed. Restricting the fit to a lower frequency band, or weighting the fit towards low frequencies, made results worse.
- **Open issues.** Ghost short notes at attacks (high-pitched, low velocity), retriggers fired by notes sharing partials, and missed notes in dense chords.

## 9. Stage 7 — Output contract

The core output should be independent of Max, Bela, Raspberry Pi, or any particular message system.

### 9.1 Continuous voice snapshot

Publish one record per voice per analysis update, or one fixed-size structure containing all voice slots.

Recommended fields:

| Field               | Type             | Meaning                                    |
| ------------------- | ---------------- | ------------------------------------------ |
| `frame_index`       | Unsigned integer | Monotonic analysis-frame count             |
| `timestamp_samples` | 64-bit integer   | Sample position associated with the frame  |
| `voice_id`          | Integer          | Persistent track identity                  |
| `active`            | Boolean          | Whether a track is active                  |
| `frequency_hz`      | Float            | Current fundamental estimate               |
| `midi_float`        | Float            | Fractional MIDI pitch                      |
| `confidence`        | Float            | Calibrated or normalized reliability score |
| `amplitude`         | Float            | Estimated contribution of the voice        |
| `voice_rank`        | Integer          | Current low/middle/high rank, if available |
| `state`             | Enum             | Inactive, pending, active, releasing       |
| `string_index`      | Integer          | Assigned string (0 = lowest), −1 if unassigned |

Use sample position as the authoritative clock. Convert to milliseconds using the configured sample rate at the API boundary.

### 9.2 Discrete event records

A note event should include:

- Event type: note-on or note-off.
- Persistent voice ID.
- MIDI note number.
- Velocity or normalized amplitude, if desired.
- Event timestamp in samples.
- Confidence at the event.
- Optional flags for retrigger, uncertain transition, or inferred release.

The MIDI note number is derived from the continuous pitch estimate only when creating the event.

### 9.3 Timing semantics

Specify whether each timestamp refers to:

- The estimated physical onset in the input.
- The analysis-frame time.
- The time at which the detector confirms the event.

These are different quantities. An onset may be estimated retrospectively from buffered audio, while the event is delivered later after confirmation. Preserve both the estimated onset timestamp and the delivery timestamp when practical.

### 9.4 Bounded event delivery

Use a fixed-capacity event queue. If the consumer cannot keep up, record overflow in diagnostics rather than allocating unbounded memory.

The audio-processing code must never block waiting for a message consumer.

## 10. Platform-independent software architecture

Use a portable DSP core with a thin platform adapter. The core should compile without Max headers, operating-system audio APIs, or framework-specific object types.

Recommended module boundaries:

| Module               | Responsibility                                            |
| -------------------- | --------------------------------------------------------- |
| `AudioConditioner`   | Filtering, input validation, level monitoring             |
| `FrameBuffer`        | Ring buffer and hop scheduling                            |
| `SpectralAnalyzer`   | Windowing, FFT, magnitude and power spectra               |
| `SpectralNormalizer` | Envelope estimation, whitening, noise floor               |
| `CandidateGenerator` | Harmonic salience and candidate pruning                   |
| `PolyphonicFitter`   | Template construction, model selection, amplitude fitting |
| `VoiceTracker`       | Prediction, association, smoothing, state transitions     |
| `EventGenerator`     | Note events and timestamps                                |
| `OutputAdapter`      | Platform-specific event and snapshot delivery             |
| `Diagnostics`        | Timing, counters, confidence components and debug data    |

A single public processing interface could look like this:

```

// MAX_VOICES is defined with InstrumentProfile (§1.3)
struct PitchFrame {
    uint64_t timestamp_samples;
    uint32_t frame_index;

    struct Voice {
        uint32_t track_id;
        bool active;
        float frequency_hz;
        float midi_float;
        float confidence;
        float amplitude;
        uint8_t state;
        int8_t string_index;   // -1 if unassigned
    } voices[MAX_VOICES];
};

class StringPitchDetector {
public:
    bool initialize(
        double sample_rate,
        const DetectorConfig& config
    );

    void reset();

    // Called with a bounded block of mono PCM.
    void process(
        const float* input,
        size_t sample_count
    );

    // Read completed frames and events through
    // a bounded, non-blocking interface.
    bool poll_frame(PitchFrame& output);
    bool poll_event(PitchEvent& output);
};

```

The method signatures are illustrative. The production API should define queue ownership, thread safety, and whether `process()` can be called with blocks of arbitrary size.

The core must not assume that the audio callback receives exactly 256 samples. The analysis hop is independent of the host's audio-block size.

### 10.1 FFT backend

Hide the FFT library behind a small interface. Suitable choices include a lightweight portable FFT implementation or an optimized platform library where available.

The rest of the detector should only depend on operations such as:

- Transform real-valued input to complex spectral coefficients.
- Retrieve magnitude or power.
- Reset or reuse preallocated transform buffers.

This allows the same algorithm to use different FFT implementations on desktop and ARM hardware without changing its pitch-estimation logic.

### 10.2 Platform adapters

**Bela.** Integrate the core with Bela's real-time audio callback. Prioritize predictable execution time, preallocated memory, and a bounded audio-to-control interface.

**Raspberry Pi.** Use a native C++ audio backend such as ALSA or an appropriate audio framework. Account for OS scheduling jitter, audio-interface buffering, and contention from other processes.

**Max/MSP.** Wrap the core in a Max external. Expose configuration messages, continuous voice output, note events, and optional diagnostics without exposing internal DSP structures.

The algorithm should remain identical across platforms. Only the audio interface, FFT backend, scheduling integration, and output transport should vary.

### 10.3 Implementation status (C++ core and Max external)

- **Core.** `core/` is a dependency-free C++17 library (`Detector`) with a self-contained radix-2 real FFT behind a small interface (§10.1). It matches the Python reference: on six real clips (about 15,000 frames) the number of fitted voices per frame is identical, pitches agree to better than 0.0001 semitones, and all 572 note events are identical (`tools/compare_cpp.py`). A unit test counts heap allocations while processing several seconds of audio with notes born, retriggered and released: zero.
- **Cost.** About 1 ms per 256-sample hop on an Apple-silicon laptop (roughly 6 times faster than real time; 99.9th percentile 1.3 ms, hop budget 5.8 ms), unoptimised double precision. Occasional spikes of several milliseconds were seen while other processes ran; a worst-case execution budget is still to be established on target hardware.
- **Max 9 external `fidddle~`** (loaded and used live by the author on cello, guitar and bass). Analysis runs inline in the audio thread when a hop completes, so the per-hop cost arrives as a burst every 4th signal vector at a 64-sample vector size. Outputs: six voice-frequency signals and six voice-level signals (held per signal vector; slots are persistent per note, not sorted by pitch), and one list outlet `<midinote> <velocity> <slot>` where velocity 0 is a note-off (a retrigger sends the off, then the on), drained from the lock-free event queue by a 2 ms clock. The internal track id is not exposed. Per-note latency is not output; `info` reports the mean and maximum note-on delay along with analysis timing. The `profile` attribute (`bass cello viola violin guitar`, 0 to 4) sets `voices`, `minfreq` and `maxfreq` to that instrument's defaults; setting any of those three explicitly overrides the default (custom tunings), whatever order the attributes are typed in, and setting `profile` again restores the defaults. Attribute changes build a new detector on the main thread; the audio thread swaps it in at the next vector, and the old one is deleted on the clock thread. If the burst proves too heavy, the same core can run on a worker thread behind a lock-free queue, at the cost of one hop of added latency.
- **Not yet done.** Verification of calibration on instruments other than the one guitar and the one 5-string bass recorded so far; a measured worst-case execution time on target hardware; an offline `buffer~` analysis mode; multichannel (`mc.`) outputs; Windows build; platform FFT backend (Accelerate) and single-precision arithmetic.


### 10.4 Source separation (`didddle`)

`didddle` splits the signal into one signal per voice slot plus a residual, using the detector's pitch tracks, with `voices + residual == input delayed by the reported latency` exactly. It has a Python reference (`didddle/`), a streaming C++ port (`core/include/didddle`, `core/src/didddle`) and a Max external `didddle~`. Design, measurements and open items are in `didddle/README.md`. Its measured limits are why §17.1 asks for per-string stems and labelled chords: on real mixes the separation gain is 7.3 dB with pitches from the isolated sources but only about 3.6 to 4 dB with pitches detected on the mixture (ghost notes and missed onsets), and octave and unison pairs split erratically.

## 11. Low-CPU optimization strategy

The largest computational costs are the FFTs, repeated candidate scoring, and joint spectral fitting. The small voice limit (four to six) makes the latter two tractable.

### 11.1 Prioritize optimizations in this order

1. Precompute static data. Window coefficients, frequency grids, harmonic weights, and configuration-derived lookup tables should be calculated during initialization.
2. Reuse buffers. All FFT, spectral, candidate, template, and fitting buffers should be allocated once.
3. Restrict the search. Only evaluate the configured fundamental range and useful partials.
4. Cache sparse templates. Store the small set of spectral bins each harmonic affects.
5. Prune candidates early. Discard weak candidates before joint fitting, but preserve active-track predictions.
6. Use bounded fitting iterations. Cap the number of candidate combinations and optimization iterations.
7. Avoid redundant transforms. Calculate each FFT only once per hop and reuse its results.
8. Optimize the measured bottleneck. Use profiling before introducing SIMD, fixed-point arithmetic, or more elaborate approximations.

### 11.2 Adaptive computation

A useful optimization is to vary the amount of work according to uncertainty.

When one candidate strongly explains the spectrum and active tracks are stable, use a smaller candidate set and fewer fitting iterations.

When multiple candidates are close in score, a voice appears, or octave ambiguity increases, perform additional local searches and joint refitting.

This preserves computational headroom during ordinary playing while spending more effort on difficult passages. It must still have a hard upper bound on processing time.

Concrete proposals (fewer transcendental calls, a verify-only mode after an onset window, decimation of the per-bin stages, single precision), with the measured cost breakdown, are in §17.6.

### 11.3 Optional lower-cost configurations

| Configuration         | Long FFT    | Candidate capacity | Intended use                               |
| --------------------- | ----------- | ------------------ | ------------------------------------------ |
| Accuracy-oriented     | 8,192       | 24                 | Initial reference implementation           |
| Balanced              | 4,096–8,192 | 12–24              | Tune against target hardware               |
| CPU-constrained       | 4,096       | 8–12               | Shorter windows or narrower pitch range    |
| Specialized low range | 8,192       | 8–16               | Low cello fundamentals with reduced search |

These are alternatives to benchmark, not equivalent configurations. A smaller FFT may increase octave errors or make adjacent low notes harder to separate. If low-register accuracy matters, reducing candidate capacity and optimizing fitting may be preferable to reducing the long FFT size.

### 11.4 Execution-time budget

At 48 kHz with a 256-sample hop, the detector has approximately 5.33 ms between updates. The actual available processing budget is smaller because the host must also handle audio I/O and other work.

Set a target that leaves substantial headroom—ideally the pitch detector consumes no more than a minority of the available audio-processing interval under worst-case candidate ambiguity.

Measure:

- Average processing time per hop.
- 99th-percentile and maximum processing time.
- Deadline misses.
- Queue overflows.
- CPU use during passages with \(V_{\max}\) active voices and high ambiguity.

Average CPU usage alone is not enough for a real-time audio system.

## 12. Configuration and calibration

All thresholds should be centralized in a configuration structure, not scattered through the algorithm.

```

struct DetectorConfig {
    InstrumentProfile profile = InstrumentProfile::cello();  // range, strings, priors (§1.3)
    uint32_t input_channel = 0;   // channel selected from multichannel input

    uint32_t long_fft_size = 0;    // 0 = derive from profile (§2.1); 8192 for cello at 48 kHz
    uint32_t short_fft_size = 2048;
    uint32_t hop_size = 256;

    uint32_t max_voices = 4;       // <= MAX_VOICES; <= profile.string_count unless string_constraint is OFF
    uint32_t max_candidates = 24;
    uint32_t max_harmonics = 12;

    float grid_step_cents = 5.0f;
    float min_candidate_separation_cents = 25.0f;

    float confirmation_threshold = 0.60f;
    float release_hang_ms = 50.0f;
    float unsupported_timeout_ms = 100.0f;

    uint32_t max_fit_iterations = 8;
};

```

The default values should be treated as an initial configuration. In particular, confidence thresholds and model-complexity penalties must be calibrated against representative recordings.

### 12.1 Calibration recordings

Record reference material covering:

- Individual notes across the usable range.
- Open strings and stopped notes.
- Double stops with different intervals.
- Triple stops, where applicable.
- Vibrato, glissando, and rapid pitch changes.
- Soft and loud bowing.
- Noisy attacks, bow changes, col legno, and body taps.
- Quiet passages and background noise.

Use annotated reference pitches wherever possible. An initial dataset can be small; the key is to include the failure cases the detector is expected to handle.

### 12.2 Evaluation metrics

Evaluate each stage independently as well as the complete detector.

| Metric                       | Purpose                                            |
| ---------------------------- | -------------------------------------------------- |
| Candidate recall             | Are the true pitches generated as hypotheses?      |
| Pitch error in cents         | How accurately are fundamentals estimated?         |
| Note precision and recall    | Are note events correct?                           |
| Octave-error rate            | Are harmonics mistaken for fundamentals?           |
| False activations per minute | How often does noise create notes?                 |
| Onset latency                | How quickly are new notes detected?                |
| Release latency              | How long does a voice persist after the note ends? |
| Voice continuity             | Do sustained notes remain stable?                  |
| Processing-time percentiles  | Does the system meet real-time deadlines?          |

Candidate recall is especially important. If the true pitch never enters the candidate pool, neither the joint fitter nor the tracker can recover it reliably.

### 12.3 Open-string calibration

The profile's inharmonicity and harmonic balance are guesses. Synthetic tests (§1.4) show how much that matters: on a guitar whose strings differ in inharmonicity B (3e-5 to 2.5e-4, against a profile constant of 1e-4), a single plucked note produces two or three note-ons (a ghost octave and twelfth, because the misaligned upper partials are explained as extra voices), and note-level F1 over chords is 0.82. A calibration pass fixes this (F1 0.94 to 1.00).

**Procedure.** The player sends `calibrate 1`, then plucks each *open* string on its own, in any order, letting it ring about a second. The detector keeps running normally. For each analysis frame the calibrator asks whether the frame is a clean single note: some fitted voice (the *root*) such that every other voice is an integer multiple of it, or a sub-octave of it (or is much weaker), and which lies within 150 cents of an open string. The fit explains a note with the wrong B as extra octave/twelfth voices and occasionally adds a ghost octave below, so several voices can qualify; they are tried from the lowest up and the first whose partial structure fits is used. Frames in the attack (first 12 frames of a stable pitch) and late decay (after 70) are skipped.

**Measurement.** Peaks are assigned to partials \(h\) progressively (up to 6, 10, 16, 24, 32) and the line \((f_h/h)^2 = f_0^2 + f_0^2 B\,h^2\) is fitted by least squares with weights \(h^2\), giving the string's true pitch \(f_0\) and \(B\). The frame is rejected unless at least six partials match with an RMS error below 0.6 bin, \(B\) is physical, and there is no comparably strong peak at \(f_0/2\), \(f_0/3\) or \(f_0/4\) (which would mean a harmonic was locked onto). The level of each partial relative to the first eight is accumulated, in the same compressed envelope-relative amplitude domain the fit uses. A string is captured after 30 accepted frames; per-string results are medians, and the weight profile is averaged over captured strings. The session finishes by itself when every string is captured, or on `calibrate 0` with what has been captured.

**What it changes.** Per-string \(B\): a candidate pitch \(f\) uses the \(B\) of the highest open string at or below it, scaled by \((f/f_\text{string})^2\) (a fretted string at constant tension has \(B\propto 1/L^2\propto f^2\)); uncaptured strings keep the profile value. The harmonic weights replace the generic \(h^{-p}\) in salience and the fit templates: each string keeps its own profile (on a real guitar they differ by up to about 45% at individual partials, which the fit otherwise explains with an extra octave note), and a pitch uses the profile of the string it would be played on (measured later to generalise badly from open strings to stopped notes, worse than a plain tilt; §17.2 proposes a shared body response instead), falling back to the average over captured strings. Tuning offsets shift the open-string pitches used for string assignment. The result is a flat list of numbers (version 2: string count, \([\text{captured}, B, \text{cents}]\) per string, the average weight count and weights, then a weight count and weights per string; version 1 lists without the per-string part are still read), saved with the patcher.

**Excitation matters.** Plucked strings show their stiffness-induced inharmonicity \(B\); steadily bowed strings are locked to an exactly harmonic series (§17.3), so \(B\) measured from a bowed open string is close to 0 and would be wrong for later plucked notes of the same string. Calibrate by plucking, and treat the value as that of plucked notes only (the calibrator does not yet record or check how the note was excited).

**What the player must do.** Pluck isolated open strings, one at a time. Other playing during the session is ignored rather than harmful, but chords, overlapping notes and fretted notes cannot contribute, because their partials cannot be separated from a single string's. Bowed instruments (negligible \(B\)) gain little from a string calibration.

**Results (real, OrchideaSOL, `tools/eval_orchidea_calibration.py`; 2026-10-20, 8 scenes each, one small run).** A calibration pass assembled from the library's open-string notes, then detection of scenes of stopped notes. Guitar: the calibrator's \(B\) agrees with the stiffness measured directly from the same files within 1 to 6% on three strings (4.24, 7.07 and \(12.4\times10^{-5}\) against 4.00, 6.71 and 12.5); four of six strings were captured (the short one-shots give fewer than the 30 accepted frames needed on the other two); note F1 0.51 uncalibrated, 0.50 calibrated (intervals worse, 0.80 to 0.59, with more extra notes; strums 0.51 to 0.55, chords 0.45 to 0.50). Bass (*pizzicato_secco*, two of four strings captured, \(B\) 1.2 and 1.9 times the direct value): note F1 0.14 uncalibrated (P 0.21, R 0.11) and 0.42 calibrated (P 0.42, R 0.44). The benefit is large where the profile's \(B\) is far off (the library's bass) and absent where it is roughly right (guitar).

**Results (synthetic).** Inharmonicity recovered to within 0.2% and tuning to better than 0.1 cent on every guitar and bass string; note-level F1 on mismatched guitar strings 0.82 to 0.94 (single notes and 4 to 6-string chords). Chords alone in the session capture nothing, and a chord inserted in a session does not bias the strings that were captured. The learned weights for a synthetic bass whose fundamental is weak were nearly flat, because the fit's amplitude domain (peak height over the local spectral envelope) already removes level differences between partials; a weak fundamental is therefore not itself an octave-error source in this model.

### 12.4 Reference data and baseline

The detector is developed against four sets of material (listed with their limits in §17.1): a local cello corpus, *cello-gestures*, recorded in stereo: left channel is a piezo pickup, right channel is a condenser microphone. It covers arco (sustained double stops, open fifths, glissando, harmonic and triad arpeggios, legato), pizzicato (triads, scales, glissando, harmonics, high register), strummed diads, and non-pitched or hard cases (col legno, jeté, wood percussion, squeals, silence). The two channels are evaluated separately (§3.1).

A recorded corpus has no sample-accurate ground truth. Two additional references are used:

- **Synthetic signals with exact truth**: bowed-like additive tones with vibrato, decaying plucked tones, and overlapping harmonic series, mixed up to four voices. These support stage-level metrics, especially candidate recall (§12.2).
- **Basic Pitch** (the local `basicpitch.cpp` command-line build) as a comparison baseline on the recorded corpus. It is an offline neural transcriber and not ground truth. Disagreements need inspection by ear or against spectrograms before either system is declared wrong. Compare note events with standard transcription metrics (for example `mir_eval`), and report where the two systems disagree in addition to aggregate scores.

These references are not enough to validate the physical-prior proposals of §17: they need stopped-position notes, labelled chords and strums, per-string stems and a clean DI take. The data that exists, its limits and the gaps are listed in §17.1.

## 13. Reference processing algorithm

The complete processing sequence is:

```

process_audio_block(input, count):
    for each sample:
        conditioned = condition_input(sample)
        ring_buffer.write(conditioned)

        if ring_buffer.has_new_hop():
            long_frame = ring_buffer.read_window(LONG_FFT)
            short_frame = ring_buffer.read_window(SHORT_FFT)

            long_spectrum = fft(window(long_frame))
            short_spectrum = fft(window(short_frame))

            update_noise_floor(long_spectrum)
            whitened = normalize_spectrum(long_spectrum)

            onset_strength = compute_spectral_flux(short_spectrum)

            candidates = generate_candidates(
                whitened,
                active_track_predictions
            )

            selected = fit_polyphonic_model(
                whitened_spectrum = whitened,
                candidates = candidates,
                max_voices = config.max_voices
            )

            assignments = associate_tracks(
                selected,
                active_track_predictions
            )

            update_tracks(assignments, onset_strength)
            generate_note_events()
            publish_bounded_outputs()

```

All operations in the real-time path must have bounded memory and computational cost. Configuration changes that require allocation, template regeneration, or other expensive setup should be prepared outside the audio callback and applied safely at a frame boundary.

## 14. Known limitations and failure modes

The detector cannot guarantee a unique interpretation of every spectrum. Important limitations include:

- Shared harmonics: different combinations of fundamentals can explain similar spectral peaks.
- Weak fundamentals: octave errors may persist when independent evidence for the lower pitch is absent.
- Multi-stop ambiguity: three or four simultaneous notes (rolled chords, pizzicato chords, strums) may not be distinguishable from a smaller number of notes with unusual timbres, and the ambiguity grows with each added voice.
- Sympathetic resonance: open strings can ring in response to other notes and be reported as additional voices.
- Transient contamination: bow noise and impacts can temporarily dominate spectral evidence.
- Timbre changes: a note may change spectral shape substantially without changing pitch.
- High-register and rapid passages: the optimal window length becomes a more difficult tradeoff between frequency resolution and temporal response.
- Voice crossings: spectral evidence may not preserve the physical identity of individual strings.
- Microphone placement: room acoustics, resonances, and off-axis pickup can change the relative strength of partials.

The system should report low confidence rather than fabricate certainty when these conditions make the estimate ambiguous.

Several of these limitations are constrained by the physics of strings in ways a general-purpose analyser could not assume. §17 lists the hypotheses worth pursuing, the experiments and the test data needed.

## 15. Recommended implementation milestones

Status: milestones 1 to 4 are done in the Python reference and the C++ core (matching event for event); milestone 5 is partly done (no allocation in the audio path, measured cost per hop, a review for Bela in `BELA_PORT_REVIEW.md`, no on-target measurement yet); milestone 6 is done as the open-string calibration (§12.3) and profile tuning on synthetic and real DI recordings, for the instruments recorded so far.

1. Milestone 1 — Spectral foundation

   Implement ring buffering, dual FFT analysis, peak interpolation, whitening, and harmonic-salience plots. Verify isolated-note estimates against reference recordings.
2. Milestone 2 — Candidate generation

   Add local maxima, missing-fundamental support, octave-ambiguity scoring, and active-track predictions. Measure candidate recall before proceeding.
3. Milestone 3 — Polyphonic fitting

   Implement one-to-\(V_{\max}\)-note model selection, nonnegative amplitude fitting, and residual-guided candidate addition. Test overlapping harmonic series.
4. Milestone 4 — Temporal tracking

   Add persistent voice IDs, pitch prediction, adaptive smoothing, onset confirmation, release hysteresis, and note events.
5. Milestone 5 — Embedded optimization

   Profile on the actual target hardware, reduce allocations and redundant computation, and establish worst-case execution-time limits.
6. Milestone 6 — Cello-specific calibration

   Use annotated recordings to tune spectral priors, confidence calibration, onset behavior, and complexity penalties. Keep the generic DSP core independent of the calibration data.

## 16. Final engineering recommendation

Build the reference implementation in portable C++ with a small FFT abstraction, fixed-capacity data structures, and no mandatory machine-learning dependencies. Validate it first on desktop recordings, then run the same core on the target embedded hardware.

The most important early decision is to keep candidate recall, polyphonic model selection, and temporal tracking separately measurable. That gives you a clear way to diagnose errors and prevents a large, tangled algorithm from becoming difficult to improve.

Start with the 8,192-point long FFT, 2,048-point short FFT, 256-sample hop, 24 candidates, and a maximum of four voices for the cello. Once the reference implementation works, optimize the candidate search and fitting stages before sacrificing low-frequency resolution.

The resulting system should provide a stable foundation for real-time cello interaction while remaining small enough to port and tune for constrained hardware.

## 17. Physical priors and optimizations to pursue

A general-purpose polyphonic analyser can assume little about its sources. This system can assume that every source is a string on a known instrument. Several of those facts are already used: near-harmonic partials with an inharmonicity \(B\) per string (§7), one note per string and the string-feasibility check (§1.3), per-string tuning, \(B\) and harmonic profiles learned by calibration (§12.3), a bounded pitch range, an attack requirement for plucked notes (§8.9) and the whitening envelope that absorbs a static body response (§5.4).

Each item states the physics, what has been measured so far (mostly on the OrchideaSOL recordings, 2026-10-20, `tools/eval_physics.py`), what remains to be done and what would pass it. Items are marked *supported*, *rejected* or *untested*. Apart from the quiet-note gate of §17.1, none of the detector-side items (§17.2 to §17.5) is implemented yet. Ideas that were tested or considered and set aside, with the reasons, are in §17.8 so that they are not proposed again without new evidence.

The measured weak points these items target (from §7.8, §8.9 and `didddle/README.md`):

- ghost notes (phantom octaves and twelfths) when the model's \(B\) or harmonic balance does not match the string, and missed or late notes in strummed chords;
- notes played on a different string than the model assumes, and fretted notes whose partials fall in a different body region than the open string's;
- on mixtures, separation gain drops from 7.3 dB with pitches taken from the isolated sources to about 3.6 to 4 dB with detected pitches;
- detector cost (about 0.9 ms per hop for the cello profile, 1.5 to 2 ms for guitar, against about 60 µs for the separator).

### 17.1 Test data

What exists, and what each set can and cannot show:

| Set | Content | Good for | Cannot show |
| --- | ------- | -------- | ----------- |
| Corpus (`data/channels`, `data/basicpitch`) | *cello-gestures* (stereo piezo and condenser) with Basic Pitch notes as a proxy truth | regression baseline; articulations | exact truth; anything but cello |
| Synthetic (`fidddle/synth.py`, `data/synth`, `data/mixes`) | additive strings with exact truth; overlapped real clips with proxy truth | stage-level metrics; fast experiments | phase, decay coupling and body behaviour (random per-partial phases and independent decays); the per-string \(B\) values are guesses, and the ordering of \(B\) across strings differs between the two real guitars measured (§17.3), so no ordering can be assumed |
| Real DI (`data/guitar-*.wav`, `data/5string-bass-*.wav`) | one acoustic guitar and one 5-string bass through a noisy DI box (floor about -63 to -72 dBFS, 60 Hz hum, a 13 kHz line), dual-mono; the open-string passes have a known truth, the chord passes have none | the real target (a dry single-instrument DI); noise robustness; calibration | stopped notes, labelled chords, a second instrument, a clean take |
| OrchideaSOL one-shots (`tools/orchidea`, `tools/eval_physics.py`, `tools/eval_orchidea*.py`) | real studio recordings of single notes: violin, viola, cello and bass (four strings), and guitar; pitch, string, technique and dynamic from the file name; bowed (*ordinario*) and plucked (*pizzicato_secco*, guitar *ordinario*); about 1,000 sounds per instrument | stiffness, mode locking, the \(f^2\) law, the same pitch on different strings, phase structure, the body response and held-out prediction of stopped notes from open strings; exact-truth mixtures | polyphonic performance (vibrato, legato, bow changes), a noisy DI; the orchestral pizzicato lasts under a second |
| BBCSO renders (`tools/bbcso_render.py`, `data/bbcso`) | Spitfire BBC Symphony Orchestra Discover: exact notes, onsets (`audio_onset`), per-voice stems, bowed, pizzicato, spiccato and tremolo patches of violin, viola, cello and bass; the single-player "leader" patches are the closest to one instrument | note logic, onsets and articulation handling, separation under controlled overlap, pairs at known intervals | phase, inharmonicity and dispersion of a single instrument (a sampled library with a baked-in hall, even with its reverb at 0; section patches add chorus; multi-mic phase relations; no intonation error or drift; vibrato on by default); the rendered audio is also not a noisy DI |

Sampled-orchestra results are reported as such. The target signals are dry close-mic or DI recordings of a single instrument; stereo ensemble mixes are expected to work reasonably, not best (reverb tails and section chorus violate the single-note model), and are measured separately.

OrchideaSOL answers the questions about stopped notes and bowed against plucked strings on *its* instruments (§17.2, §17.3, §17.5). What it cannot supply is the target chain: the user's own instruments through a DI, legato, and real chords with written voicings. Remaining gaps, in priority order (each unblocks the item named):

1. **Stopped-position plucks on the DI guitar and bass** on every string at several frets (for example 0, 2, 5, 7, 12), steady notes of at least 2 s, reference pitch to within 1 cent (strobe tuner or a high-resolution monophonic analysis). The library cannot stand in for them: its guitar has a different ordering of \(B\) across strings from the DI guitar (§17.3). Confirms the \(B\propto f^2\) law and the body response on the target instrument (§17.2, §17.3), including the same pitch on two strings.
2. **Cleaner DI takes** of the same guitar and bass (low noise floor, no hum), recorded together with the noisy chain if possible, so that the effect of noise can be separated from model errors; an electric guitar through a DI as well.
3. **Chords with written voicings** (string and fret per note), strums, arpeggios and rolled chords, with sample-accurate onset labels; ideally a per-string (hexaphonic) pickup for true per-string stems.
4. **Legato**: hammer-ons, pull-offs and slides with labelled times (§17.4, §17.5).
5. **Bowed against plucked on the user's own cello or violin**: the same open string bowed and plucked, with reference pitch, to confirm on the target instrument what the library shows (mode locking, and the size of the pizzicato tolerance, §17.3).
6. **Negatives**: open strings ringing sympathetically while other strings play, let-ring against damped notes, noise-only and hum-only passages.
7. **Bowed DI**: a dry close-mic or piezo cello and violin with labelled notes, including legato slurs and fast changes, to check the transition ghosts below on a real instrument.

**BBCSO baseline** (`tools/eval_bbcso.py eval`; dry set = `Release=0`, 97 scenes, 695 reference notes; onset ±0.1 s on `audio_onset`, pitch ±50 cents). Overall P 0.42, R 0.76, F1 0.54, median delivery latency 95 ms; the reverb-tail set gives the same (P 0.39, R 0.70), so tails are not what limits it. With real DI noise mixed in at 40, 30 and 20 dB SNR: F1 0.53, 0.52, 0.48 (recall 0.74 to 0.71, precision 0.42 to 0.37), a graceful decline. Precision is the weakness: about one extra note per real note on a monophonic bowed line. Inspected on `cello_long_random1`, every true note is found with the right onset, and the extras are 50-300 ms bursts at note transitions an octave below, an octave or a twelfth above. The signal has nothing at those pitches (for a D#3 at 155.6 Hz, the level at the sub-octave 77.8 Hz is 53 dB below the fundamental, and the render is digitally silent before the first note), so they are fit errors in transitions, not content. Bowed profiles have no attack requirement, which is why they are not removed as on guitar and bass. A candidate sub-octave guard (reject a lower pitch whose non-shared partials have little support) raised P from 0.42 to 0.44 at R 0.76 to 0.75 and did nothing for octave pairs, so it was not adopted. Other weaknesses: repeated notes (R about 0.25, late or merged detections), double bass (R about 0.13, late detection), the upper voice of an octave pair, and overlapping staggered lines. These are sampled, vibrato-laden bowed notes with no noisy chain: do not tune to them at the expense of the DI results, and treat the transition ghosts as an open problem for bowed instruments that needs clean bowed DI data (gap 7).

**Tracker on OrchideaSOL single notes** (`tools/eval_orchidea.py tracker`, `orchidea_errors.py`, `orchidea_scene_report.py`; 2026-10-20; one voice at a time, *ordinario*, notes inside the profile's range, 6 to 10 scenes per instrument, so directional only). Dry studio notes are far cleaner than the BBCSO renders, yet precision is about 0.35 to 0.5 with recall 0.56 to 0.78 (cello 0.35/0.68, violin 0.50/0.68, viola 0.47/0.56, bass 0.41/0.60, guitar 0.49/0.78 before the change below). Three findings:

- **Soft notes were missed because of the absolute level gate.** The library's *pp* bowed notes peak at -42 (cello) to -48 dBFS (violin) and swell over 0.3 to 0.5 s, against a -58 dBFS gate: 36 of 41 violin *pp* notes had no note-on within 150 ms. A fixed lower gate recovers them (-72: 8 missed) but costs the noisy guitar DI (chord precision 0.81 to 0.56 at -72), so the gate is now also passed by a voice at least 30 dB over the local noise floor at its partials (`quiet_snr_db`, floor `quiet_floor_dbfs` -80; on for cello, viola and violin, off for guitar and bass whose attack requirement and noisy DIs already decide). Notes without a note-on over all dynamics: cello 14 to 5, violin 15 to 6, viola 19 to 3 of about 40; detections rise by 4 to 14 (short extras). The noisy real DI scorecard, the corpus solo and dead-air clips and the synthetic suites are unchanged. Python and C++ agree (538 of 538 events).
- **A prior \(B\) that is too high costs far more than one that is too low.** Bowed notes with \(B=3\times10^{-4}\) instead of 0: detections 38 to 63 (violin), 40 to 65 (viola), 85 to 132 (cello), confirming that bowed profiles keep \(B=0\). Orchestral pizzicato with \(B=0\) against \(3\times10^{-4}\): about the same notes found (misses 0 to 2) and fewer extras, so the fitted-\(B\) route is not needed there either. Guitar notes (*ordinario* mf and ff, 54 notes): detections 90, 113, 137 and 159 for a prior of 0, \(3\times10^{-5}\), \(10^{-4}\) (the profile default) and \(3\times10^{-4}\), recall flat (49, 49, 44, 46 right); a prior growing as \(f^2\) is no better than 0 (84, 90 and 113 for \(c=0.3\), 1 and \(2\times10^{-9}\)). The real guitar DI uncalibrated agrees (chord precision 0.95 with 0, 0.83 with \(10^{-4}\)); the real bass prefers its \(5\times10^{-5}\). But a six-note chord needs the prior to *match* the true \(B\) (synthetic: the open E chord is resolved 3 of 3 times when prior equals truth, 0 of 3 for a factor 3 off in either direction). So single notes favour a low default, chords need the right value: this supports calibration and a per-track \(B\) (§17.3) for chords and leaves the profile default unchanged for now.
- **What is left on clean single notes is mostly the high register and soft attacks, not the model.** Extras on the cello cluster on notes above G5, where vibrato smears each partial over about 35 cents and the second partial is stronger than the fundamental; the fit then prefers a series at 1/2 or 2/3 of the pitch. A sub-harmonic uniqueness guard (reject a candidate at \(f/n\) or \(2f/3\) whose non-shared partials carry little support) changed nothing there (82 to 80 to 83 detections) and was dropped, as on the BBCSO set. Whether a different window or vibrato handling for notes above about 700 Hz on the cello helps is untested.

Annotating onsets and strings by hand on a few of the existing recordings (the guitar and bass chord files) is a cheap first step and should precede any tuning against them.

Common evaluation: note precision, recall and F1 with onset tolerance (§12.2); ghost notes and false activations per minute; for separation the per-stem SI-SDR and its gain over the mixture (`tools/eval_separation.py`); always against the baseline recorded at the time of the experiment.

### 17.2 Body response as a function of absolute frequency

*Physics.* The body and pickup apply the same filter to every string, and that filter is a function of absolute frequency. A bow at fractional position \(\beta\) gives an amplitude about \(\sin(\pi h\beta)/h\) per partial and a pluck about \(\sin(\pi h\beta)/h^2\); damping tilts the upper partials.

*What is wrong now.* Calibration stores a harmonic profile per string indexed by partial *number* (§12.3). That is the product of the body response and the excitation, sampled at the open string's partial frequencies. A fretted note on the same string has its partials at different absolute frequencies, so the open string's profile is the wrong one for it.

*Hypothesis (supported by the measurement below).* Model a partial's weight as a smooth body response of absolute frequency (shared by all strings, learned from the open-string calibration, whose partials sample many frequencies) times a per-note excitation shape of about three parameters (position, tilt, decay). This should generalise from open strings to stopped notes and reduce the extra octave notes that an amplitude mismatch causes.

*Measured* (OrchideaSOL, `tools/eval_physics.py body`; 2026-10-20). Partial levels (dB) of stopped notes predicted from the open strings of the same instrument and dynamic; rms error over the partials after fitting a per-note offset (and tilt), median over notes (violin 124, viola 149, cello 132, bass 200, guitar 93):

| Model | violin | viola | cello | bass | guitar |
| ----- | ------ | ----- | ----- | ---- | ------ |
| tilt only (\(h^{-\alpha}\), no profile) | 5.25 | 5.86 | 4.41 | 4.33 | 5.71 |
| per-string profile by partial number (what calibration stores), with tilt | 7.06 | 7.77 | 6.65 | 6.69 | 7.59 |
| body response of absolute frequency, with tilt | 4.07 | 3.94 | 3.76 | 4.17 | 5.23 |
| body response trained on 3 of 4 strings | 4.17 | 3.96 | 3.73 | 4.04 | 5.27 |

The per-string profile by partial number is *worse than no profile at all* on stopped notes (by 1.4 to 2.5 dB), and the shared body response is the best model, by 0.3 to 1.9 dB over tilt alone and about 3 dB over the profile; three strings suffice. The hypothesis is supported. The residual of 4 to 5 dB is large: single-partial levels are noisy. For the *separator* the gain is small: predicting one hidden partial (the case of a coinciding partial) from the others has an error of 5.0 to 5.4 dB by interpolation of its neighbours and 4.4 to 5.2 dB with the body model (`collide` mode), so no model recovers a hidden partial's level to better than about 5 dB, which also explains why coinciding partials are split erratically. The body model is therefore a detector-side improvement (salience and fit weights, ghost notes), not a separator one.

*Where.* §12.3 (what calibration stores), §6.2 and §7.2 (weights in salience and templates).

*Remaining experiment.* The held-out prediction is done (above). What is left is the detector test: replace the per-string profiles in the salience and fit weights by the body response plus a per-note tilt, and compare ghost rate and note F1 on the OrchideaSOL scenes, the chord files and the DI open-string passes; and confirm on the DI guitar and bass with stopped-position takes (gap 1) that three calibrated strings suffice.

*Pass.* Fewer ghost notes on stopped notes with note F1 not lower, and no loss when only some strings are calibrated.

### 17.3 Inharmonicity per track, and the excitation dependence of \(B\)

*Physics.* A plucked string vibrates freely, so its partials sit at the stiff-string frequencies \(hf_0\sqrt{1+Bh^2}\). A steadily bowed string is driven by a periodic stick-slip motion that locks its modes to an exactly harmonic series, so for steady arco notes the right template has \(B\approx 0\); the lock-in takes a few tens of milliseconds at the attack and may not hold for the highest partials of a stiff string. At \(B = 5\times10^{-5}\) the stretch at \(h=20\) is about 1%, roughly 17 cents.

*What is wrong now.* (1) A calibrated or profile \(B\) is applied regardless of how the note was excited. (2) The string a pitch belongs to is guessed as the highest open string at or below it, scaled by \((f/f_\text{string})^2\) (which assumes constant tension; the finger's boundary condition adds a small correction). The player may be using a lower string in a higher position, and the same pitch on two strings can have different \(B\). (3) The calibration instructions said "pluck (or bow)": a bowed calibration measures \(B\approx 0\) and would mis-model later plucked notes. The instructions now say to pluck, and calibration is for plucked instruments (guitar, bass); bowed instruments need little of it.

*Measured on OrchideaSOL* (`tools/eval_physics.py inharm`, `bstring`, `string`; 2026-10-20; the same stiffness fit as the calibrator, unclamped, on steady frames):

- **Mode locking is confirmed on every bowed instrument.** Median \(B\) of *ordinario* notes is 0.03, 0.03, 0.02 and \(0.00\times10^{-5}\) for violin, viola, cello and bass (36 to 47 notes each, every string), and the exact-harmonic series fits as well as the stiff one (rms 1.2 to 3.1 cents). On the earlier *cello-gestures* clips also 0.0 to \(0.1\times10^{-5}\) at every pitch.
- **Plucked guitar is a clean stiff string and follows the \(f^2\) law.** Within a string, log-log slopes of \(B\) against pitch of 1.96, 2.00, 1.62 and 2.49 (strings 1 to 4, correlations 0.74 to 1.00); a free exponent over all 86 stopped notes fits at 1.68. \(B\) is consistent between the early and late part of a note (pitch drift under 1.3 cents, fit rms 2.3 to 2.6 cents).
- **The string matters far more than the pitch.** The same guitar pitch on different strings has \(B\) differing by up to 23 times (MIDI 55: 10.8, 0.46, 3.2 and 6.4 \(\times10^{-5}\) on strings 3 to 6). Predicting a stopped note's \(B\) from its true string's open value and \(f^2\) is good to a factor 1.7 (rms of \(\ln\) ratio 0.55); with the current pitch-only rule (highest open string at or below the pitch) it is good to a factor 2.9 (rms 1.06), and the rule names the wrong string for 49 of 84 stopped notes.
- **\(B/f^2\) identifies the string.** For the 135 guitar notes whose pitch is playable on two or more strings, nearest-centroid classification on \(B/f^2\) alone (trained on other pitches) names the string correctly for 83% (chance 29%). The inverse use is therefore available: estimate \(B\) from the note's own partials and infer the string.
- **Orchestral-string pizzicato is not a clean stiff string.** Medians of 4 to \(20\times10^{-5}\) (cello 4, bass 13, violin 15, viola 20) with fit rms of 6 to 10 cents against 1 to 3 cents for bowed notes and a stiff fit barely better than the exact series; \(B\) differs between the early and late part of the same note (bass *mf*: 12.4 then \(-1.5\)). Whatever distorts these partials (body-resonance pulling, tension modulation of large plucks, coupling) is not modelled by one \(B\). A tolerance on the partial positions (the `inharm_tol_B` mechanism; about 8 cents rms at the seventh partial) is the right model for them, not a fitted \(B\). The tracker sweep of §17.1 agrees: orchestral pizzicato is found equally well with \(B=0\) and with \(3\times10^{-4}\), with fewer extras at 0.
- **No ordering of \(B\) across strings transfers between instruments.** The library's guitar has the plain G string most inharmonic and the wound D, A and E strings least (open strings \(\times10^{-5}\), high to low: 4.0, 6.7, 10.8, 0.56, 0.99, 1.6), the opposite of the DI guitar (E2 to E4: 13, 9.5, 7.0, 3.8, 7.0, 2.5) and of the assumption that wound strings are lower. \(B\) must be measured per instrument, which is what calibration does; and a calibrated value is a per-string constant (\(B/f^2\)), so one open-string pass is enough to predict the stopped notes of that string.

*Consequences (supported).* (1) For bowed profiles use \(B=0\) (confirmed; the bass profile's \(5\times10^{-5}\) suits the plucked DI bass but not an arco one); for guitar and bass estimate \(B\) per confirmed track with the calibrated or profile value as a strong prior; (2) infer the string from \(B/f^2\) as well as from the pitch, instead of the highest open string; (3) treat orchestral pizzicato with a position tolerance rather than a fitted \(B\). For `didddle` none of this matters: with true pitches on OrchideaSOL scenes the separation gain moves by less than 0.3 dB for plausible separator \(B\) (bowed bass: 23.0 dB at \(B=0\), 22.7 at the profile's \(5\times10^{-5}\), 22.0 at \(2\times10^{-4}\); plucked bass 19.0 to 19.1; guitar 19.6 to 19.8; cello 20.4 down to 19.2 only at \(3\times10^{-4}\)), so a per-voice \(B\) is not worth adding to the separator.

*Sanity check: is per-instrument calibration worth more than a robust default?* (`tools/eval_defaults.py`, `tools/eval_real.py`; 2026-10-21). Note-level F1 on OrchideaSOL scenes of stopped notes (lines, chords, strums, intervals; 6 scenes each), and on the real DI recordings, for the profile default, a flat \(B=0\), a flat \(3\times10^{-5}\) and the calibration learned from that library's open strings:

| Task | profile default | \(B=0\) | \(B=3\times10^{-5}\) | calibrated |
| ---- | --------------- | -------- | -------------------- | ---------- |
| guitar, all scene kinds (F1) | 0.44 | 0.68 | 0.59 | 0.67 |
| bass plucked, all kinds (F1) | 0.25 | 0.29 | 0.24 | **0.57** |
| bass bowed, all kinds (F1) | 0.28 | 0.35 | 0.31 | 0.38 |
| real guitar chords (P/R vs Basic Pitch) | 0.83/0.31 | **0.95**/0.33 | 0.91/0.31 | 0.81/0.34 |
| real guitar open strings (extra notes) | 5 | 2 | 3 | 0 (in-sample) |
| real bass chords (P/R) | 0.52/0.14 | 0.50/0.14 | | **0.68**/0.17 |

Calibration was never worse than the best flat value, and it is decisive where the profile is far off (plucked bass: 0.57 against 0.25 to 0.29). For the guitar a flat \(B=0\) matches calibration on both the library and the real chords, and the current default of \(10^{-4}\) is the worst of the four on all three guitar tasks, so a lower guitar default is the robust choice. It was left unchanged for a decision because the synthetic six-note chord only resolves when the prior \(B\) matches the truth (it fails with 0 whether the string is exactly harmonic or stiff). String identity adds no risk to this: it only reports, it does not change the fit, and it needs a calibration with string values and the guitar profile.

*To do.* Robustness to a wrong string or excitation guess, at low cost, by:

1. estimating \(B\) per confirmed track, with the calibrated or profile value as a strong prior, updated slowly from confirmed frames that have at least six matching partials (the calibrator's partial fit applied to a track), and kept constant otherwise;
2. deciding births on a lower partial band (about 1.5 kHz), where a wrong \(B\) matters little, then widening the band once \(B\) is refined (a narrow band alone loses accuracy, §7.8);
3. trying alternative priors (for example \(B\) scaled by 0.5 and 2, or 0 for a bowed profile) only at a note's birth, and only when the fit explains little.

This costs one regression per track per few frames, not several template sets per candidate per frame.

*Where.* `Config::inharm_B`, `Fitter` (a per-voice \(B\)), §8.1 (track state), §12.3 (record that the calibration was plucked).

*Remaining experiment.* (a) Done on OrchideaSOL (above); repeat on the DI guitar and bass when stopped-position takes exist (gap 1). (b) On synthetic and real data, set the prior \(B\) wrong by factors of 0.5 to 3 and compare note F1 and ghost rate with the per-track estimate. (c) Check that it does not pull pitch to a wrong octave on weak-fundamental notes.

*Pass.* Note F1 with a wrong prior within 0.05 of the right-prior value (today 0.5 to 0.8 against 0.99), cost per frame less than doubled, no increase in octave errors.

### 17.4 Excitation events

*Physics.* A pluck adds energy over all partials at once, and a bow stroke has a finite attack. Energy at an individual partial can also *rise* without a new excitation: strings are coupled through the bridge (a ringing low E sets the A and high E strings sounding, as on the real recording), the two polarisations of a string beat, and the body stores energy.

*Hypothesis.* Broadband energy is the reliable excitation evidence (already used: §8.9), and a per-partial rise is not. A decay-curve model per track (how fast the track's broadband and partial energy should fall) would separate a new excitation, an energy jump above the extrapolated decay, from coupling and beating, with fewer false retriggers than the fixed 10 dB threshold.

*Where.* §8.6 (release and retrigger), §5.5.

*Experiment.* Compare the decay-curve test with the threshold on repeated plucks of one string, strings struck while ringing, finger-damped against let-ring notes, and sympathetic ringing (gaps 4 and 6; the repeated-pluck and spiccato scenes of the BBCSO renders for the logic).

*Pass.* Retrigger F1 (onset within 50 ms) above the current detector's on the same set, and false retriggers on sympathetic ringing below the current rate.

### 17.5 String identity

*Physics.* A string sounds one pitch at a time, never below its open pitch, and a new pitch on a sounding string ends the previous note. Each string has its own timbre and \(B\).

*What it is for.* Outputting the string as the voice slot, and per-string priors for \(B\) and timbre. It is *not* a ghost remedy on its own: with five free strings almost any ghost pitch is reachable by some string. On the real guitar recording the ghosts were removed by calibration (attack-time ones) and by the attack requirement (those that appeared mid-ring).

*Where it can help the detector.* String exclusion gives a principled way to admit legato notes that the attack requirement now rejects: a new pitch with no attack is accepted if it replaces a note that could be on the same string and that ends at the same time (hammer-on, pull-off, slide).

*Measured.* On the real guitar, \(B/f^2\) alone names the string of a pitch-ambiguous note for 83% of 135 notes (chance 29%), see §17.3: timbre-like evidence does carry the string, which makes string exclusion for legato (and the string as the voice slot) feasible. 

*Measured on the detector's own tracks* (`tools/eval_string_id.py`, `fidddle/stringid.py`; guitar *ordinario* mf and ff, one voice at a time, 162 notes; 2026-10-20). String values learned from the open-string notes only (the calibration protocol) name the string as well as values learned from other stopped notes (112 of 135 either way with the clean-note measurement), so no extra player step is needed. What matters is how \(B\) is measured:

- \(B\) from the detector's per-frame partial positions (the calibrator's fit on 186 ms frames, median over the note) is at chance level (7 of 21, chance 0.32): too few high partials and too coarse a frame.
- \(B\) from a separate stiffness fit on long Hann frames (6 periods of the pitch) starting 0.2 s into the note: 82 of 114 correct (0.72, chance 0.33) for notes playable on two or more strings, answered for 72% of the true notes (the rest have no track or too few partials). The margin to the second-best string is a usable confidence: margin at least 0.6 gives 41 of 47 (0.87) for 41% of those notes, margin at least 1.0 gives 25 of 25 for 22%. Window timing matters (starting at the onset 0.54, 0.4 s in 0.50-0.53, 0.2 s in 0.64-0.72).
- Three-note chords: 11 of 16 correct, but only 16 of 36 notes yield a measurement, since coinciding partials spoil the fit.
- Spectral shape (tilt, even/odd balance, centroid) does not carry the string, on guitar (below chance with leave-one-pitch-out) or on cello and violin (0.33 to 0.46 against chance 0.38 to 0.41), so for bowed instruments no cheap evidence exists.

*Implemented (guitar profile, 2026-10-21).* `fidddle/stringid.py` and `core/src/stringid.cpp`, identical results (`tools/compare_stringid.py`). Calibration measures the same stiffness value for each open string (stored as a version-3 list, `logb`; a calibration without it is the unchanged version 2). A confirmed track is measured twice (windows of 6 periods, 2048 to 4096 samples at guitar pitches, starting 0.2 s after the note-on) and the median names the string; when the gap to the second-best string is under 0.3 (log units) the pitch rule answers instead and the margin is reported as 0, a guess. It is a separate `string` event (Python: kind "string"; C++: `poll_string`; Max: `string <slot> <string number> <margin>` on the info outlet, strings numbered as on a guitar, 1 = the highest), so note events are unchanged, and it only runs on a profile with `string_id` (guitar) and a calibration that has string values. Measured on OrchideaSOL guitar lines (162 notes, 123 answers for pitches on two or more strings): 106 correct (0.86) against 92 (0.75) for the pitch rule alone, with all 47 answers that had a margin of at least 0.3 correct (the rule gets 33 of them). Chords and strums: no gain (26 of 30 against 27 of 30; only 18% to 53% of notes yield a measurement), so the string of a chord note is as good as the pitch rule. Cost: about 35 us per hop on average (3 to 4%), worst hop unchanged within the noise, no allocation in `process()`.

*Experiment.* Add a voice-to-string assignment to the tracker and test legato recall (gap 4) and string identity on the OrchideaSOL guitar and, later, the DI stopped-position takes, including the same pitch on two strings: if timbre alone cannot tell the strings apart, report the ambiguity rather than guess.

*Pass.* Legato notes recovered without more ghost notes on the negatives (gap 6); string identity correct on at least 90% of notes where the pitch is playable on two strings, otherwise reported as ambiguous.

### 17.6 Computation

*Measured* (`BELA_PORT_REVIEW.md`, desktop profile of the cello profile): transcendental calls (`exp`, `log`) are about a third of the cost; the salience grid is about 23% (980 grid pitches times 23 partial probes, each an `exp`); the noise-floor median is about 12%; the fit about 11%; the FFT only about 7%.

*Proposals.*

1. Fewer transcendental calls: tabulate the peak kernel and the partial lookups, and evaluate the salience incrementally.
2. Update the noise floor every 4 to 8 hops (its time constants are 0.2 s and 10 s).
3. Verify-only mode: while all tracks are stable and no onset is detected, check the predicted pitches; run the full search for a few hundred milliseconds after each detected onset (the fit finds a new note up to about 300 ms after the pluck) and on a loss of support (§11.2).
4. Decimate the input by 4 before the long FFT: the per-bin stages (whitener, median, peaks, flux) shrink about 4 times and the Nyquist (about 5.5 kHz) stays above the 4 kHz fit band, but the fixed salience and fit costs do not shrink and the FFT itself is a small share, so this alone is not enough. Decimation by 8 would cut the fit band.
5. Single precision for the hot loops (loses exact parity with the Python reference).

*Pass.* Detector time per hop reduced at least 3 times on sustained material with note F1 changed by less than 0.01 and no increase in worst-case time; the separator's accuracy unchanged. Faster separator mathematics is not worth pursuing: the banded solver already costs about 60 µs per frame.

### 17.7 Lower priority, conditional

- **Playability priors.** A bow sounds at most two strings at once (triple and quadruple stops are rolled), a strum has a monotone onset order, and hand span bounds fingered intervals. These can only be soft priors: the exceptions (pizzicato, col legno, fingerstyle patterns) are common, and the prior needs the excitation type, which the detector would have to classify. Worth trying only with labelled chords and strums (gap 3) and score statistics for the thresholds.
- **Natural and artificial harmonics.** Touching a node leaves the partials that have a node there, so the sound is the harmonic series of the sounding pitch (a multiple of the open string's), with few strong partials and a steep decay. A steep-weight template with candidates at the open strings' harmonics may help the harmonic clips, but first run the fit with the oracle pitch, with and without the template, to learn whether the failure is the model or the detection threshold. The library supplies labelled material (guitar *harmonic_fingering*, the strings' *artificial_harmonic*), which this test can use; natural harmonics on the DI instruments would still be needed to confirm it.

### 17.8 Considered and set aside

- **Phase-locked separation of coinciding partials (rejected by measurement).** Predicting a partial's phase from the others needs the phase pattern \(\psi_h=\varphi_h-h\varphi_1\) of a note to be stable and smooth across partial number. On OrchideaSOL (`tools/eval_physics.py phase`, `phase-repro`) it is moderately stable over time for bowed notes (circular std 0.39, 0.42, 0.51 and 0.91 rad for violin, viola, bass and cello) and nearly random for plucked ones (1.0 to 1.55 rad), but it is not smooth across \(h\): a prediction from its neighbours is right within 0.5 rad for 0.17 to 0.20 of partials (chance 0.16), and from the two adjacent partials (the octave-collision pattern) 0.2 to 0.4 modulo \(\pi\) (chance 0.32). Between two recordings of the same string and pitch the pattern agrees within 0.5 rad for 37 to 59% of partials (1 to 10 pairs, indicative only), so a table would have to be learned per pitch and cannot come from open strings. Needs also a pitch accurate to about 0.7 cent. Do not revisit without per-string stems of real dyads.
- **Beat-envelope estimation of coinciding partials.** Tuned unisons and octaves beat at about 1 Hz or slower, a period longer than the analysis window; it applies to deliberately detuned pairs such as the courses of a mandolin. Revisit with that profile.
- **Several \(B\) hypotheses per candidate in every frame.** It multiplies the cost of the dominant stage (§17.6); §17.3 replaces it.
- **A fitted \(B\) for orchestral pizzicato.** Not a clean stiff string (fit rms 6 to 10 cents, \(B\) inconsistent within a note): use a position tolerance (§17.3).
- **A per-voice \(B\) in the separator.** With true pitches on OrchideaSOL scenes the gain moves by less than 0.3 dB for plausible values and by at most 1.4 dB when \(B\) is six times too high (§17.3).
- **A body-response prior to split coinciding partials in the separator.** A hidden partial's level cannot be predicted to better than about 5 dB by any model; the body model beats interpolation of the neighbours by 0.2 to 0.9 dB only (§17.2). Its value is in the detector.
- **Per-string harmonic profiles indexed by partial number as the model of stopped notes.** Worse than no profile on stopped notes by 1.4 to 2.5 dB; the body response replaces them (§17.2).
- **"Any rise in a partial's energy is a new excitation."** False for coupled strings and polarisation beating (§17.4).
- **The string constraint as the main ghost remedy.** Free strings can reach almost any ghost pitch (§17.5).

### 17.9 Order of work

1. **Detector, supported by measurement:** (a) body response of absolute frequency in place of per-string profiles (§17.2); (b) per-track \(B\) with the string inferred from \(B/f^2\), \(B=0\) for bowed profiles, and a position tolerance for orchestral pizzicato (§17.3). Test on the OrchideaSOL scenes and chord files first, then on the DI recordings; keep Python and C++ identical.
2. **Data:** stopped-position takes on the DI guitar and bass (gap 1) to confirm (a) and (b) on the target instruments, and a clean DI take (gap 2); hand-annotate the chord files; run the BBCSO and OrchideaSOL benchmarks as the baseline for the note logic.
3. §17.4 and §17.5 (excitation events, string exclusion for legato), which are untested.
4. §17.6 in parallel; it needs no new audio, only a target device.
5. §17.7 only if the earlier items leave a measured gap.

`didddle` needs no change from this section: its measured limits are detection on mixtures and the information content of coinciding partials, not the partial model.

## Appendix A. Instrument profiles

Profiles marked *built in* are implemented (§1.4) with the values shown; the others are indicative values to guide a future profile, not validated settings. Each should be calibrated and tested as its own profile.

| Instrument | Open strings (Hz) | Fundamental range searched (Hz) | Voice limit | Status and main concerns |
| ---------- | ----------------- | ------------------------------- | ----------- | ------------------------ |
| Cello | 65.41, 98.00, 146.83, 220.00 | 60–1,000 | 4 | Built in. Bowed and plucked; vibrato smears upper partials |
| Viola | 130.81, 196.00, 293.66, 440.00 | 120–1,500 | 4 | Built in |
| Violin | 196.00, 293.66, 440.00, 659.26 | 185–2,800 | 4 | Built in. High fundamentals need an adaptive harmonic count near Nyquist; wide vibrato |
| Bass (5-string) | 30.87, 41.20, 55.00, 73.42, 98.00 | 28–500 | 4 | Built in. A semitone at 41 Hz is only 2.4 Hz, so the window is 372 ms (a 4-string bass can raise `minfreq` to about 38 Hz for 186 ms); polyphony is rare |
| Guitar | 82.41, 110.00, 146.83, 196.00, 246.94, 329.63 | 70–1,400 | 6 | Built in. Plucked decay and let-ring; chord partials overlap heavily; low strings in a chord are dropped early (§8.9) |
| Mandolin | 196.00, 293.66, 440.00, 659.26 (courses) | 190–1,500 | 4 | Planned. Double-strung courses beat against each other and must count as one voice; tremolo causes rapid retriggers |
| Banjo (5-string) | 392.00 (short 5th), 146.83, 196.00, 246.94, 293.66 | 140–1,200 | 5 | Planned. Bright transient, plucked decay, drone string |

Plucked profiles use inharmonicity \(B\), the attack requirement and the persistent-track settings; bowed profiles use \(B=0\). Instruments with doubled strings need an additional course model so a pair of near-unison partials is treated as one voice.
