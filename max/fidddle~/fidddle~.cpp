/**
    @file
    fidddle~ : real-time polyphonic pitch detector for string instruments (bass, cello, viola, violin, guitar).

    Inlet 0 (signal): mono audio.
    Outlets (left to right):
        0-5   signal  frequency in Hz of voice slot 0..5 (0 when the slot is silent). Slots are persistent per note.
        6-11  signal  linear level of voice slot 0..5 (0 when silent)
        12    list    <midinote> <velocity> <slot>  (velocity 0 = note off; a retrigger sends the off, then the on)
        13    messages  replies to "info" (profile, analysis, timing, latency)

    The detector runs in the audio thread (no allocation, no locks). Attribute changes build a fresh
    detector on the main thread and swap it in at the next signal vector.

    Calibration: send [calibrate] then pluck each OPEN string (not bowed: bowing measures no inharmonicity) on its own and let it ring about a second. Strings
    can be played in any order; anything that is not a single clean open-string note is ignored (chords, overlapping or
    fretted notes contribute nothing), so playing other things in between is harmless but does not help. The object learns each
    string's inharmonicity and tuning and the typical balance of the harmonics, applies them at once, and stores them in the
    saved @calibration attribute. [calibrate done] uses the strings captured so far, [calibrate cancel] abandons, and
    [calibrate clear] returns to the profile defaults.

    @profile selects an instrument and sets @voices, @minfreq and @maxfreq to its defaults. Setting any of
    those three afterwards overrides it (custom tunings); setting @profile again restores the defaults.
    In an object box, explicit attributes always win over profile defaults regardless of their order.
*/
#include "ext.h"
#include "ext_obex.h"
#include "z_dsp.h"

#include <algorithm>
#include <cmath>
#include <cstring>

#include "fidddle/detector.hpp"

using namespace fidddle;

constexpr int kSlots = 6;      // guitar: one voice per string
constexpr int kGrave = 4;
static const char* kProfileNames[InstrumentProfile::Count] = {"bass", "cello", "viola", "violin", "guitar"};

struct t_fidddle {
    t_pxobject ob;
    void* out_events;
    void* out_info;
    t_clock* clock;

    // main-thread configuration (attributes)
    double sr;
    long a_profile;
    long a_voices;
    double a_minfreq, a_maxfreq;
    double a_min_level;
    long a_confirm;
    double a_release_ms;
    double a_retrigger_db;
    long a_poll_ms;
    bool loading;                         // true while attributes from the object box are being applied
    bool user_voices, user_minfreq, user_maxfreq;

    // calibration (main-thread state; the detector holds its own copy)
    Calibration cal;                      // applied calibration
    bool cal_on;
    double a_cal[Calibration::LIST_CAP];  // flat list backing the saved @calibration attribute
    long a_cal_n;
    Calibration pending_cal;              // handed from the clock thread to the main thread
    long pending_cal_ready;

    // note-on latency statistics (clock thread writes, info reads; display only)
    double lat_sum, lat_max;
    long lat_count;

    // handed between threads with atomic pointer exchanges
    Detector* active;      // owned by the audio thread's view; deleted by the clock thread after a swap
    Detector* pending;     // built on the main thread, adopted by perform
    Detector* grave[kGrave];
};

// Same mechanism the SDK uses for CLASS_ATTR_LABEL: a sub-attribute on the attribute. Max uses these
// for tooltips and attribute documentation; keep the text in sync with docs/fidddle~.maxref.xml.
#define CLASS_ATTR_DIGEST(c, attrname, flags, str) \
    CLASS_ATTR_ATTR_FORMAT(c, attrname, "digest", USESYM(symbol), flags, "s", gensym_tr(str))
#define CLASS_ATTR_DESCRIPTION(c, attrname, flags, str) \
    CLASS_ATTR_ATTR_FORMAT(c, attrname, "description", USESYM(symbol), flags, "s", gensym_tr(str))

static t_class* s_class = nullptr;

void* fidddle_new(t_symbol* s, long argc, t_atom* argv);
void fidddle_free(t_fidddle* x);
void fidddle_assist(t_fidddle* x, void* b, long m, long a, char* s);
void fidddle_dsp64(t_fidddle* x, t_object* dsp64, short* count, double samplerate, long maxvectorsize, long flags);
void fidddle_perform64(t_fidddle* x, t_object* dsp64, double** ins, long numins, double** outs, long numouts, long sampleframes, long flags, void* userparam);
void fidddle_tick(t_fidddle* x);
void fidddle_reset(t_fidddle* x);
void fidddle_info(t_fidddle* x);
t_max_err fidddle_set_profile(t_fidddle* x, t_object* attr, long argc, t_atom* argv);
t_max_err fidddle_set_voices(t_fidddle* x, t_object* attr, long argc, t_atom* argv);
t_max_err fidddle_set_minfreq(t_fidddle* x, t_object* attr, long argc, t_atom* argv);
t_max_err fidddle_set_maxfreq(t_fidddle* x, t_object* attr, long argc, t_atom* argv);
t_max_err fidddle_attr_set(t_fidddle* x, t_object* attr, long argc, t_atom* argv);
t_max_err fidddle_set_calibration(t_fidddle* x, t_object* attr, long argc, t_atom* argv);
void fidddle_calibrate(t_fidddle* x, t_symbol* s, long argc, t_atom* argv);
void fidddle_apply_calibration(t_fidddle* x);
static void rebuild(t_fidddle* x);

static inline Detector* aload(Detector** p) { return __atomic_load_n(p, __ATOMIC_ACQUIRE); }
static inline Detector* axchg(Detector** p, Detector* v) { return __atomic_exchange_n(p, v, __ATOMIC_ACQ_REL); }

void ext_main(void* r) {
    t_class* c = class_new("fidddle~", (method)fidddle_new, (method)fidddle_free, (long)sizeof(t_fidddle), 0L, A_GIMME, 0);

    class_addmethod(c, (method)fidddle_dsp64, "dsp64", A_CANT, 0);
    class_addmethod(c, (method)fidddle_assist, "assist", A_CANT, 0);
    class_addmethod(c, (method)fidddle_reset, "reset", 0);
    class_addmethod(c, (method)fidddle_info, "info", 0);
    class_addmethod(c, (method)fidddle_calibrate, "calibrate", A_GIMME, 0);

    // --- instrument ---------------------------------------------------------------------------
    CLASS_ATTR_LONG(c, "profile", 0, t_fidddle, a_profile);
    CLASS_ATTR_ENUMINDEX(c, "profile", 0, "bass cello viola violin guitar");
    CLASS_ATTR_LABEL(c, "profile", 0, "Instrument profile");
    CLASS_ATTR_ACCESSORS(c, "profile", NULL, fidddle_set_profile);

    CLASS_ATTR_LONG(c, "voices", 0, t_fidddle, a_voices);
    CLASS_ATTR_FILTER_CLIP(c, "voices", 1, kSlots);
    CLASS_ATTR_LABEL(c, "voices", 0, "Maximum simultaneous voices");
    CLASS_ATTR_ACCESSORS(c, "voices", NULL, fidddle_set_voices);

    CLASS_ATTR_DOUBLE(c, "minfreq", 0, t_fidddle, a_minfreq);
    CLASS_ATTR_FILTER_CLIP(c, "minfreq", 20., 2000.);
    CLASS_ATTR_LABEL(c, "minfreq", 0, "Lowest pitch (Hz)");
    CLASS_ATTR_ACCESSORS(c, "minfreq", NULL, fidddle_set_minfreq);

    CLASS_ATTR_DOUBLE(c, "maxfreq", 0, t_fidddle, a_maxfreq);
    CLASS_ATTR_FILTER_CLIP(c, "maxfreq", 100., 6000.);
    CLASS_ATTR_LABEL(c, "maxfreq", 0, "Highest pitch (Hz)");
    CLASS_ATTR_ACCESSORS(c, "maxfreq", NULL, fidddle_set_maxfreq);

    // --- detection ----------------------------------------------------------------------------
    CLASS_ATTR_DOUBLE(c, "minlevel", 0, t_fidddle, a_min_level);
    CLASS_ATTR_FILTER_CLIP(c, "minlevel", -90., -20.);
    CLASS_ATTR_LABEL(c, "minlevel", 0, "Level gate (dBFS)");
    CLASS_ATTR_ACCESSORS(c, "minlevel", NULL, fidddle_attr_set);

    CLASS_ATTR_LONG(c, "confirm", 0, t_fidddle, a_confirm);
    CLASS_ATTR_FILTER_CLIP(c, "confirm", 2, 24);
    CLASS_ATTR_LABEL(c, "confirm", 0, "Confirmation frames");
    CLASS_ATTR_ACCESSORS(c, "confirm", NULL, fidddle_attr_set);

    CLASS_ATTR_DOUBLE(c, "release", 0, t_fidddle, a_release_ms);
    CLASS_ATTR_FILTER_CLIP(c, "release", 0., 1000.);
    CLASS_ATTR_LABEL(c, "release", 0, "Release time (ms)");
    CLASS_ATTR_ACCESSORS(c, "release", NULL, fidddle_attr_set);

    CLASS_ATTR_DOUBLE(c, "retrigger", 0, t_fidddle, a_retrigger_db);
    CLASS_ATTR_FILTER_CLIP(c, "retrigger", 3., 30.);
    CLASS_ATTR_LABEL(c, "retrigger", 0, "Retrigger threshold (dB)");
    CLASS_ATTR_ACCESSORS(c, "retrigger", NULL, fidddle_attr_set);

    // learned calibration (saved with the patcher; also settable from a stored list)
    CLASS_ATTR_DOUBLE_VARSIZE(c, "calibration", 0, t_fidddle, a_cal, a_cal_n, Calibration::LIST_CAP);
    CLASS_ATTR_LABEL(c, "calibration", 0, "Learned calibration");
    CLASS_ATTR_ACCESSORS(c, "calibration", NULL, fidddle_set_calibration);

    // inspector grouping, saving with the patcher, and a stable order
    for (const char* n : {"profile", "voices", "minfreq", "maxfreq"}) CLASS_ATTR_CATEGORY(c, n, 0, "Instrument");
    for (const char* n : {"minlevel", "confirm", "release", "retrigger"}) CLASS_ATTR_CATEGORY(c, n, 0, "Detection");
    CLASS_ATTR_CATEGORY(c, "calibration", 0, "Calibration");
    CLASS_ATTR_SAVE(c, "calibration", 0);
    int order = 1;
    for (const char* n : {"profile", "voices", "minfreq", "maxfreq", "minlevel", "confirm", "release", "retrigger"}) {
        char buf[8];
        snprintf(buf, sizeof buf, "%d", order++);
        CLASS_ATTR_SAVE(c, n, 0);
        CLASS_ATTR_ORDER(c, n, 0, buf);
    }

    CLASS_ATTR_DIGEST(c, "profile", 0, "Instrument profile");
    CLASS_ATTR_DESCRIPTION(c, "profile", 0,
        "Selects the instrument: 0 bass, 1 cello, 2 viola, 3 violin, 4 guitar. Sets voices, minfreq and maxfreq to that instrument's defaults and adapts the analysis window and harmonic model. Default 1 (cello).");
    CLASS_ATTR_DIGEST(c, "voices", 0, "Maximum simultaneous voices");
    CLASS_ATTR_DESCRIPTION(c, "voices", 0,
        "The most notes tracked at once, 1 to 6. The profile sets this (4 for bass, cello, viola and violin, 6 for guitar). A lower value uses less CPU and gives fewer false extra notes.");
    CLASS_ATTR_DIGEST(c, "minfreq", 0, "Lowest pitch (Hz)");
    CLASS_ATTR_DESCRIPTION(c, "minfreq", 0,
        "The lowest fundamental frequency searched, 20 to 2000 Hz. The profile sets this (set it a little below your lowest string for a down-tuning). A lower value needs a longer analysis window and so adds latency.");
    CLASS_ATTR_DIGEST(c, "maxfreq", 0, "Highest pitch (Hz)");
    CLASS_ATTR_DESCRIPTION(c, "maxfreq", 0,
        "The highest fundamental frequency searched, 100 to 6000 Hz. The profile sets this. Set it just above the highest note you play to reduce false notes.");
    CLASS_ATTR_DIGEST(c, "calibration", 0, "Learned string calibration");
    CLASS_ATTR_DESCRIPTION(c, "calibration", 0,
        "A list of numbers produced by the calibrate message: per-open-string inharmonicity and tuning and the harmonic weights. Saved with the patcher so the calibration is restored when the patch opens. Send calibrate clear to remove it.");
    CLASS_ATTR_DIGEST(c, "minlevel", 0, "Level gate (dBFS)");
    CLASS_ATTR_DESCRIPTION(c, "minlevel", 0,
        "Notes quieter than this level are ignored, -90 to -20 dBFS. Raise it to reject room noise and ringing. Default -58.");
    CLASS_ATTR_DIGEST(c, "confirm", 0, "Frames before a note-on");
    CLASS_ATTR_DESCRIPTION(c, "confirm", 0,
        "How many analysis frames (about 5.8 ms each at 44.1 kHz) a new pitch must persist before a note-on is sent, 2 to 24. Higher values reject short false notes but add latency. Default 6.");
    CLASS_ATTR_DIGEST(c, "release", 0, "Time before a note-off (ms, 0 = profile)");
    CLASS_ATTR_DESCRIPTION(c, "release", 0,
        "How long a note may go unsupported by the analysis before its note-off is sent, 50 to 1000 ms. Higher values bridge dropouts but delay note-offs. 0 (default) uses the profile's own value: 100 ms, or 300 ms for guitar.");
    CLASS_ATTR_DIGEST(c, "retrigger", 0, "Re-attack threshold (dB)");
    CLASS_ATTR_DESCRIPTION(c, "retrigger", 0,
        "How much louder (in dB) the partials of a ringing note must become for a repeated pluck to retrigger it, 3 to 30. Lower values retrigger more easily but may split sustained notes. Default 10.");

    class_dspinit(c);
    class_register(CLASS_BOX, c);
    s_class = c;
}

static void apply_profile_defaults(t_fidddle* x, bool keep_user_values) {
    InstrumentProfile p = InstrumentProfile::by_id((int)x->a_profile);
    if (!keep_user_values || !x->user_voices) x->a_voices = std::min<long>(p.default_voices, kSlots);
    if (!keep_user_values || !x->user_minfreq) x->a_minfreq = p.min_frequency_hz;
    if (!keep_user_values || !x->user_maxfreq) x->a_maxfreq = p.max_frequency_hz;
    if (!keep_user_values) x->user_voices = x->user_minfreq = x->user_maxfreq = false;
}

void* fidddle_new(t_symbol* s, long argc, t_atom* argv) {
    t_fidddle* x = (t_fidddle*)object_alloc(s_class);
    if (!x) return nullptr;
    dsp_setup((t_pxobject*)x, 1);
    // outlets are created right to left
    x->out_info = outlet_new(x, NULL);
    x->out_events = outlet_new(x, NULL);
    for (int i = kSlots - 1; i >= 0; --i) outlet_new(x, "signal");   // level 5..0
    for (int i = kSlots - 1; i >= 0; --i) outlet_new(x, "signal");   // frequency 5..0

    Config defaults;
    x->sr = sys_getsr() > 0 ? sys_getsr() : 44100.0;
    x->a_profile = InstrumentProfile::Cello;
    x->user_voices = x->user_minfreq = x->user_maxfreq = false;
    apply_profile_defaults(x, false);
    x->a_min_level = defaults.min_level_dbfs;
    x->a_confirm = defaults.confirm_frames;
    x->a_release_ms = 0.0;               // 0 = the profile's own value
    x->a_retrigger_db = defaults.retrigger_rise_db;
    x->a_poll_ms = 2;
    x->lat_sum = 0.0; x->lat_max = 0.0; x->lat_count = 0;
    x->cal = Calibration{}; x->cal_on = false; x->a_cal_n = 0; x->pending_cal_ready = 0;
    x->active = nullptr;
    x->pending = nullptr;
    for (auto& g : x->grave) g = nullptr;

    // Apply the object-box attributes. Setters only record values while `loading`; afterwards the profile
    // fills in whatever the user did not set explicitly, so the order of the attributes does not matter.
    x->clock = nullptr;
    x->loading = true;
    attr_args_process(x, (short)argc, argv);
    x->loading = false;
    apply_profile_defaults(x, true);

    x->clock = (t_clock*)clock_new((t_object*)x, (method)fidddle_tick);
    rebuild(x);
    clock_fdelay(x->clock, (double)x->a_poll_ms);
    return x;
}

void fidddle_free(t_fidddle* x) {
    dsp_free((t_pxobject*)x);
    if (x->clock) { clock_unset(x->clock); object_free(x->clock); }
    delete x->active;
    delete x->pending;
    for (auto g : x->grave) delete g;
}

void fidddle_assist(t_fidddle* x, void* b, long m, long a, char* s) {
    if (m == ASSIST_INLET) {
        snprintf_zero(s, ASSIST_MAX_STRING_LEN, "(signal) mono audio input; messages: reset, info");
    } else if (a < kSlots) {
        snprintf_zero(s, ASSIST_MAX_STRING_LEN, "(signal) voice %ld frequency in Hz (0 = silent)", a);
    } else if (a < 2 * kSlots) {
        snprintf_zero(s, ASSIST_MAX_STRING_LEN, "(signal) voice %ld level (linear)", a - kSlots);
    } else if (a == 2 * kSlots) {
        snprintf_zero(s, ASSIST_MAX_STRING_LEN, "list: midinote velocity slot (velocity 0 = note off)");
    } else {
        snprintf_zero(s, ASSIST_MAX_STRING_LEN, "replies to info: profile, analysis, timing_us, latency_ms");
    }
}

// Build a detector from the current attributes on the main thread; perform adopts it.
static void rebuild(t_fidddle* x) {
    Config c = Config::for_instrument((int)x->a_profile, x->sr);
    c.max_voices = (int)std::min<long>(std::max<long>(x->a_voices, 1), std::min<long>(kSlots, MAX_VOICES));
    c.profile.min_frequency_hz = x->a_minfreq;
    c.profile.max_frequency_hz = x->a_maxfreq;
    if (c.profile.max_frequency_hz < 1.5 * c.profile.min_frequency_hz) {
        c.profile.max_frequency_hz = 1.5 * c.profile.min_frequency_hz;
        object_warn((t_object*)x, "maxfreq must be at least 1.5 x minfreq; using %.1f Hz", c.profile.max_frequency_hz);
    }
    if (x->cal_on && x->cal.n_strings == c.profile.string_count) {
        c.calibration = x->cal;
        c.use_calibration = true;
    }
    c.min_level_dbfs = x->a_min_level;
    c.confirm_frames = (int)x->a_confirm;
    c.strong_confirm_frames = std::max(2, (int)x->a_confirm * 2 / 3);
    if (x->a_release_ms > 0.0) c.unsupported_timeout_ms = std::max(50.0, x->a_release_ms);
    c.retrigger_rise_db = x->a_retrigger_db;
    x->lat_sum = 0.0; x->lat_max = 0.0; x->lat_count = 0;
    Detector* d = new Detector(c);
    Detector* old = axchg(&x->pending, d);
    delete old;   // never adopted; the audio thread never saw it
}

static long profile_from_atoms(long argc, t_atom* argv, long fallback) {
    if (argc < 1) return fallback;
    if (atom_gettype(argv) == A_SYM) {
        const char* name = atom_getsym(argv)->s_name;
        for (int i = 0; i < InstrumentProfile::Count; ++i) if (!strcmp(name, kProfileNames[i])) return i;
        return fallback;
    }
    return std::min<long>(std::max<long>(atom_getlong(argv), 0), InstrumentProfile::Count - 1);
}

t_max_err fidddle_set_profile(t_fidddle* x, t_object* attr, long argc, t_atom* argv) {
    x->a_profile = profile_from_atoms(argc, argv, x->a_profile);
    if (!x->loading && x->clock) {
        apply_profile_defaults(x, false);   // switching instrument restores that instrument's defaults
        x->cal = Calibration{}; x->cal_on = false; x->a_cal_n = 0;   // a calibration belongs to one instrument's strings
        object_attr_touch((t_object*)x, gensym("voices"));
        object_attr_touch((t_object*)x, gensym("minfreq"));
        object_attr_touch((t_object*)x, gensym("maxfreq"));
        rebuild(x);
    }
    return MAX_ERR_NONE;
}

t_max_err fidddle_set_voices(t_fidddle* x, t_object* attr, long argc, t_atom* argv) {
    if (argc < 1) return MAX_ERR_NONE;
    x->a_voices = std::min<long>(std::max<long>(atom_getlong(argv), 1), kSlots);
    x->user_voices = true;
    if (!x->loading && x->clock) rebuild(x);
    return MAX_ERR_NONE;
}

t_max_err fidddle_set_minfreq(t_fidddle* x, t_object* attr, long argc, t_atom* argv) {
    if (argc < 1) return MAX_ERR_NONE;
    x->a_minfreq = std::min(std::max(atom_getfloat(argv), 20.0), 2000.0);
    x->user_minfreq = true;
    if (!x->loading && x->clock) rebuild(x);
    return MAX_ERR_NONE;
}

t_max_err fidddle_set_maxfreq(t_fidddle* x, t_object* attr, long argc, t_atom* argv) {
    if (argc < 1) return MAX_ERR_NONE;
    x->a_maxfreq = std::min(std::max(atom_getfloat(argv), 100.0), 6000.0);
    x->user_maxfreq = true;
    if (!x->loading && x->clock) rebuild(x);
    return MAX_ERR_NONE;
}

t_max_err fidddle_attr_set(t_fidddle* x, t_object* attr, long argc, t_atom* argv) {
    t_symbol* name = (t_symbol*)object_method(attr, gensym("getname"));
    if (argc < 1) return MAX_ERR_NONE;
    double v = atom_getfloat(argv);
    const char* n = name->s_name;
    if (!strcmp(n, "minlevel")) x->a_min_level = std::min(std::max(v, -90.0), -20.0);
    else if (!strcmp(n, "confirm")) x->a_confirm = std::min<long>(std::max<long>((long)v, 2), 24);
    else if (!strcmp(n, "release")) x->a_release_ms = v <= 0.0 ? 0.0 : std::min(std::max(v, 50.0), 1000.0);
    else if (!strcmp(n, "retrigger")) x->a_retrigger_db = std::min(std::max(v, 3.0), 30.0);
    if (!x->loading && x->clock) rebuild(x);
    return MAX_ERR_NONE;
}

void fidddle_reset(t_fidddle* x) { rebuild(x); }

void fidddle_info(t_fidddle* x) {
    Detector* d = aload(&x->active);
    t_atom a[5];
    atom_setsym(a + 0, gensym(kProfileNames[std::min<long>(std::max<long>(x->a_profile, 0), InstrumentProfile::Count - 1)]));
    atom_setlong(a + 1, x->a_voices);
    atom_setfloat(a + 2, x->a_minfreq);
    atom_setfloat(a + 3, x->a_maxfreq);
    outlet_anything(x->out_info, gensym("profile"), 4, a);   // name, voices, minfreq, maxfreq
    if (x->cal_on) {
        long got = 0;
        for (int i = 0; i < x->cal.n_strings; ++i) got += x->cal.captured[i];
        atom_setlong(a + 0, got);
        atom_setlong(a + 1, x->cal.n_strings);
        atom_setlong(a + 2, x->cal.n_weights > 0 ? 1 : 0);
        outlet_anything(x->out_info, gensym("calibration"), 3, a);   // strings captured, strings, harmonic weights learned (0/1)
    } else {
        atom_setsym(a, gensym("none"));
        outlet_anything(x->out_info, gensym("calibration"), 1, a);
    }
    if (!d) { atom_setsym(a, gensym("inactive")); outlet_anything(x->out_info, gensym("state"), 1, a); return; }
    const Diagnostics& g = d->diagnostics();
    atom_setfloat(a + 0, d->config().sample_rate);
    atom_setlong(a + 1, d->long_fft_size());
    atom_setfloat(a + 2, 1000.0 * d->long_fft_size() / d->config().sample_rate);
    outlet_anything(x->out_info, gensym("analysis"), 3, a);   // sample rate, window size, window length in ms
    atom_setfloat(a + 0, g.mean_us);
    atom_setfloat(a + 1, g.max_us);
    atom_setfloat(a + 2, 1e6 * d->config().hop_size / d->config().sample_rate);
    atom_setlong(a + 3, (long)g.overflow_events);
    outlet_anything(x->out_info, gensym("timing_us"), 4, a);   // mean, max, hop budget, event-queue overflows
    // note-on latency: delivery time minus the estimated physical onset, over notes since the last reset
    if (x->lat_count > 0) {
        atom_setfloat(a + 0, x->lat_sum / (double)x->lat_count);
        atom_setfloat(a + 1, x->lat_max);
        atom_setlong(a + 2, x->lat_count);
        outlet_anything(x->out_info, gensym("latency_ms"), 3, a);   // mean, max, number of notes
    } else {
        atom_setsym(a, gensym("no_notes_yet"));
        outlet_anything(x->out_info, gensym("latency_ms"), 1, a);
    }
}

static void post_cal(t_fidddle* x, const char* what, long argc, t_atom* argv) {
    t_atom a[8];
    atom_setsym(a, gensym(what));
    for (long i = 0; i < argc && i < 7; ++i) a[1 + i] = argv[i];
    outlet_anything(x->out_info, gensym("calibrate"), 1 + std::min<long>(argc, 7), a);
}

// [calibrate], [calibrate done], [calibrate cancel], [calibrate clear]
void fidddle_calibrate(t_fidddle* x, t_symbol* s, long argc, t_atom* argv) {
    const char* cmd = (argc > 0 && atom_gettype(argv) == A_SYM) ? atom_getsym(argv)->s_name : "start";
    Detector* d = aload(&x->active);
    if (!strcmp(cmd, "clear")) {
        x->cal = Calibration{}; x->cal_on = false; x->a_cal_n = 0;
        object_attr_touch((t_object*)x, gensym("calibration"));
        rebuild(x);
        post_cal(x, "cleared", 0, nullptr);
        return;
    }
    if (!d) { object_warn((t_object*)x, "calibrate: start audio first (the detector runs with the signal)"); return; }
    if (!strcmp(cmd, "start")) d->calibrate_start();
    else if (!strcmp(cmd, "done") || !strcmp(cmd, "stop") || !strcmp(cmd, "finish")) d->calibrate_finish();
    else if (!strcmp(cmd, "cancel")) d->calibrate_cancel();
    else object_warn((t_object*)x, "calibrate: unknown argument %s (use start, done, cancel or clear)", cmd);
}

// Main thread: adopt the calibration the audio thread finished (handed over by the clock thread).
void fidddle_apply_calibration(t_fidddle* x) {
    if (!__atomic_exchange_n(&x->pending_cal_ready, 0, __ATOMIC_ACQ_REL)) return;
    x->cal = x->pending_cal;
    x->cal_on = true;
    x->a_cal_n = x->cal.to_list(x->a_cal);
    object_attr_touch((t_object*)x, gensym("calibration"));
    rebuild(x);
    t_atom a[Calibration::LIST_CAP + 1];
    for (long i = 0; i < x->a_cal_n; ++i) atom_setfloat(a + i, x->a_cal[i]);
    post_cal(x, "applied", 0, nullptr);
    outlet_anything(x->out_info, gensym("calibration_data"), (short)x->a_cal_n, a);
}

t_max_err fidddle_set_calibration(t_fidddle* x, t_object* attr, long argc, t_atom* argv) {
    Calibration c;
    double v[Calibration::LIST_CAP];
    long n = std::min<long>(argc, Calibration::LIST_CAP);
    for (long i = 0; i < n; ++i) v[i] = atom_getfloat(argv + i);
    if (n > 0 && Calibration::from_list(v, (int)n, c)) {
        x->cal = c; x->cal_on = true;
        for (long i = 0; i < n; ++i) x->a_cal[i] = v[i];
        x->a_cal_n = n;
    } else {
        x->cal = Calibration{}; x->cal_on = false; x->a_cal_n = 0;
        if (n > 0) object_warn((t_object*)x, "calibration: unrecognised list ignored");
    }
    if (!x->loading && x->clock) rebuild(x);
    return MAX_ERR_NONE;
}

void fidddle_dsp64(t_fidddle* x, t_object* dsp64, short* count, double samplerate, long maxvectorsize, long flags) {
    if (samplerate != x->sr) {
        x->sr = samplerate;
        rebuild(x);
    } else if (!aload(&x->active) && !aload(&x->pending)) {
        rebuild(x);
    }
    object_method(dsp64, gensym("dsp_add64"), x, fidddle_perform64, 0, NULL);
}

void fidddle_perform64(t_fidddle* x, t_object* dsp64, double** ins, long numins, double** outs, long numouts, long sampleframes, long flags, void* userparam) {
    // adopt a freshly built detector, handing the old one to the clock thread for deletion
    Detector* fresh = axchg(&x->pending, nullptr);
    if (fresh) {
        Detector* old = axchg(&x->active, fresh);
        if (old) {
            bool parked = false;
            for (auto& g : x->grave) {
                Detector* expected = nullptr;
                if (__atomic_compare_exchange_n(&g, &expected, old, false, __ATOMIC_ACQ_REL, __ATOMIC_ACQUIRE)) { parked = true; break; }
            }
            (void)parked;   // all slots full: leak rather than free on the audio thread
        }
    }
    Detector* d = aload(&x->active);
    if (!d || x->ob.z_disabled) {
        for (long o = 0; o < numouts; ++o) std::memset(outs[o], 0, sizeof(double) * sampleframes);
        return;
    }
    d->process(ins[0], (size_t)sampleframes);
    const PitchFrame& f = d->latest();
    for (int i = 0; i < kSlots && i < numouts / 2; ++i) {
        const VoiceSnapshot& v = f.voices[i];
        bool on = v.state == ACTIVE || v.state == RELEASING;
        double hz = on ? v.frequency_hz : 0.0;
        double amp = on ? std::pow(10.0, v.level_db / 20.0) : 0.0;
        double* fo = outs[i];
        double* ao = outs[kSlots + i];
        for (long n = 0; n < sampleframes; ++n) { fo[n] = hz; ao[n] = amp; }
    }
}

void fidddle_tick(t_fidddle* x) {
    Detector* d = aload(&x->active);
    NoteEvent e;
    t_atom a[3];
    while (d && d->poll_event(e)) {
        // one list outlet: <midinote> <velocity> <slot>; velocity 0 = note off (MIDI convention)
        if (e.on) {
            double lat_ms = 1000.0 * (double)(e.deliver_samples - e.onset_est_samples) / d->config().sample_rate;
            if (!(e.flags & FLAG_RETRIGGER)) {
                x->lat_sum += lat_ms;
                x->lat_max = std::max(x->lat_max, lat_ms);
                x->lat_count += 1;
            }
            atom_setlong(a + 0, e.midi_note);
            atom_setlong(a + 1, std::max(1, e.velocity));
            atom_setlong(a + 2, e.slot);
        } else {
            atom_setlong(a + 0, e.midi_note);
            atom_setlong(a + 1, 0);
            atom_setlong(a + 2, e.slot);
        }
        outlet_list(x->out_events, NULL, 3, a);
    }
    CalibEvent ce;
    while (d && d->poll_calib_event(ce)) {
        t_atom c[5];
        switch (ce.kind) {
            case CalibEvent::Started:
                atom_setlong(c, ce.total);
                post_cal(x, "started", 1, c);                  // number of open strings to play
                break;
            case CalibEvent::Progress:
                atom_setlong(c + 0, ce.string); atom_setlong(c + 1, ce.frames); atom_setlong(c + 2, ce.needed);
                post_cal(x, "progress", 3, c);                 // string index (0 = lowest), frames collected, frames needed
                break;
            case CalibEvent::StringDone:
                atom_setlong(c + 0, ce.string); atom_setfloat(c + 1, ce.f0_hz); atom_setfloat(c + 2, ce.cents); atom_setfloat(c + 3, ce.B);
                post_cal(x, "string", 4, c);                   // string index, measured pitch (Hz), tuning offset (cents), inharmonicity B
                break;
            case CalibEvent::Complete:
                atom_setlong(c + 0, ce.captured); atom_setlong(c + 1, ce.total);
                post_cal(x, "complete", 2, c);
                break;
            case CalibEvent::Finished: {
                atom_setlong(c + 0, ce.captured); atom_setlong(c + 1, ce.total);
                Calibration got;
                if (d->take_calibration(got)) {
                    x->pending_cal = got;
                    __atomic_store_n(&x->pending_cal_ready, 1, __ATOMIC_RELEASE);
                    defer_low(x, (method)fidddle_apply_calibration, nullptr, 0, nullptr);   // rebuild on the main thread
                } else {
                    post_cal(x, "nothing_captured", 2, c);
                }
                break;
            }
            case CalibEvent::Cancelled:
                post_cal(x, "cancelled", 0, nullptr);
                break;
        }
    }
    for (auto& g : x->grave) {
        Detector* old = axchg(&g, nullptr);
        delete old;
    }
    clock_fdelay(x->clock, (double)x->a_poll_ms);
}
