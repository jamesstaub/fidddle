/**
    @file
    didddle~ : real-time source separator for string instruments (bass, cello, viola, violin, guitar).

    Splits a mono signal into one signal per sounding note (voice slot) plus a residual, using the fidddle~ pitch
    detector internally. Inlet 0 (signal): mono audio.
    Outlets (left to right):
        0-5   signal  voice slot 0..5: the audio of the note holding that slot (silent when the slot is free).
                      Slots are persistent per note, not sorted by pitch.
        6     signal  residual: everything not attributed to a voice (bow noise, unpitched sound, undetected notes)
        7     list    <midinote> <velocity> <slot>  (velocity 0 = note off), as from fidddle~
        8     messages  replies to "info" (profile, latency, timing) and calibration progress

    All outputs are delayed by the same fixed amount (see @latency and the "latency" message), and
        voices 0..5 + residual  ==  the input delayed by that amount        (exactly)
    so inverting a delayed copy of the input and summing it with every output cancels to nothing.

    @latency 0 gives the shortest delay one analysis window allows (about 85 ms for a cello at 48 kHz); a larger value
    waits longer for the detector to confirm each note so its attack can be assigned to the right voice.

    Calibration, @profile, @voices, @minfreq, @maxfreq and the detection attributes behave exactly as in fidddle~ (see its
    reference), since the same detector runs inside.
*/
#include "ext.h"
#include "ext_obex.h"
#include "z_dsp.h"

#include <algorithm>
#include <cmath>
#include <cstring>

#include "didddle/splitter.hpp"
#include "fidddle/settings.hpp"

using namespace fidddle;

constexpr int kSlots = 6;      // guitar: one voice per string
constexpr int kGrave = 4;
static const char* kProfileNames[InstrumentProfile::Count] = {"bass", "cello", "viola", "violin", "guitar", "contrabass"};

struct t_didddle {
    t_pxobject ob;
    void* out_events;
    void* out_info;
    t_clock* clock;

    double sr;
    Settings set;                          // detector attributes (shared with other hosts)
    double a_latency_ms;                   // 0 = shortest
    double a_transient_ms;
    long a_poll_ms;
    bool loading;                          // true while attributes from the object box are being applied
    long a_profile, a_voices, a_confirm;   // attribute-visible copies of set.* (Max reads attributes from the struct)
    double a_minfreq, a_maxfreq, a_min_level, a_release_ms, a_retrigger_db;

    double a_cal[Calibration::LIST_CAP];   // flat list backing the saved @calibration attribute
    long a_cal_n;
    Calibration pending_cal;               // handed from the clock thread to the main thread
    long pending_cal_ready;

    didddle::Splitter* active;             // owned by the audio thread's view; deleted by the clock thread after a swap
    didddle::Splitter* pending;            // built on the main thread, adopted by perform
    didddle::Splitter* grave[kGrave];
};

#define CLASS_ATTR_DIGEST(c, attrname, flags, str) \
    CLASS_ATTR_ATTR_FORMAT(c, attrname, "digest", USESYM(symbol), flags, "s", gensym_tr(str))
#define CLASS_ATTR_DESCRIPTION(c, attrname, flags, str) \
    CLASS_ATTR_ATTR_FORMAT(c, attrname, "description", USESYM(symbol), flags, "s", gensym_tr(str))

static t_class* s_class = nullptr;

void* didddle_new(t_symbol* s, long argc, t_atom* argv);
void didddle_free(t_didddle* x);
void didddle_assist(t_didddle* x, void* b, long m, long a, char* s);
void didddle_dsp64(t_didddle* x, t_object* dsp64, short* count, double samplerate, long maxvectorsize, long flags);
void didddle_perform64(t_didddle* x, t_object* dsp64, double** ins, long numins, double** outs, long numouts, long sampleframes, long flags, void* userparam);
void didddle_tick(t_didddle* x);
void didddle_reset(t_didddle* x);
void didddle_info(t_didddle* x);
t_max_err didddle_set_profile(t_didddle* x, t_object* attr, long argc, t_atom* argv);
t_max_err didddle_set_voices(t_didddle* x, t_object* attr, long argc, t_atom* argv);
t_max_err didddle_set_minfreq(t_didddle* x, t_object* attr, long argc, t_atom* argv);
t_max_err didddle_set_maxfreq(t_didddle* x, t_object* attr, long argc, t_atom* argv);
t_max_err didddle_attr_set(t_didddle* x, t_object* attr, long argc, t_atom* argv);
t_max_err didddle_set_calibration(t_didddle* x, t_object* attr, long argc, t_atom* argv);
void didddle_calibrate(t_didddle* x, t_symbol* s, long argc, t_atom* argv);
void didddle_apply_calibration(t_didddle* x);
static void rebuild(t_didddle* x);

static inline didddle::Splitter* aload(didddle::Splitter** p) { return __atomic_load_n(p, __ATOMIC_ACQUIRE); }
static inline didddle::Splitter* axchg(didddle::Splitter** p, didddle::Splitter* v) { return __atomic_exchange_n(p, v, __ATOMIC_ACQ_REL); }

void ext_main(void* r) {
    t_class* c = class_new("didddle~", (method)didddle_new, (method)didddle_free, (long)sizeof(t_didddle), 0L, A_GIMME, 0);

    class_addmethod(c, (method)didddle_dsp64, "dsp64", A_CANT, 0);
    class_addmethod(c, (method)didddle_assist, "assist", A_CANT, 0);
    class_addmethod(c, (method)didddle_reset, "reset", 0);
    class_addmethod(c, (method)didddle_info, "info", 0);
    class_addmethod(c, (method)didddle_calibrate, "calibrate", A_GIMME, 0);

    // --- separation -----------------------------------------------------------------------------
    CLASS_ATTR_DOUBLE(c, "latency", 0, t_didddle, a_latency_ms);
    CLASS_ATTR_FILTER_CLIP(c, "latency", 0., 2000.);
    CLASS_ATTR_LABEL(c, "latency", 0, "Output delay (ms, 0 = shortest)");
    CLASS_ATTR_ACCESSORS(c, "latency", NULL, didddle_attr_set);

    CLASS_ATTR_DOUBLE(c, "transient", 0, t_didddle, a_transient_ms);
    CLASS_ATTR_FILTER_CLIP(c, "transient", 0., 300.);
    CLASS_ATTR_LABEL(c, "transient", 0, "Attack length handed to the new voice (ms)");
    CLASS_ATTR_ACCESSORS(c, "transient", NULL, didddle_attr_set);

    // --- instrument (as fidddle~) ---------------------------------------------------------------
    CLASS_ATTR_LONG(c, "profile", 0, t_didddle, a_profile);
    CLASS_ATTR_ENUMINDEX(c, "profile", 0, "bass cello viola violin guitar contrabass");
    CLASS_ATTR_LABEL(c, "profile", 0, "Instrument profile");
    CLASS_ATTR_ACCESSORS(c, "profile", NULL, didddle_set_profile);

    CLASS_ATTR_LONG(c, "voices", 0, t_didddle, a_voices);
    CLASS_ATTR_FILTER_CLIP(c, "voices", 1, kSlots);
    CLASS_ATTR_LABEL(c, "voices", 0, "Maximum simultaneous voices");
    CLASS_ATTR_ACCESSORS(c, "voices", NULL, didddle_set_voices);

    CLASS_ATTR_DOUBLE(c, "minfreq", 0, t_didddle, a_minfreq);
    CLASS_ATTR_FILTER_CLIP(c, "minfreq", 20., 2000.);
    CLASS_ATTR_LABEL(c, "minfreq", 0, "Lowest pitch (Hz)");
    CLASS_ATTR_ACCESSORS(c, "minfreq", NULL, didddle_set_minfreq);

    CLASS_ATTR_DOUBLE(c, "maxfreq", 0, t_didddle, a_maxfreq);
    CLASS_ATTR_FILTER_CLIP(c, "maxfreq", 100., 6000.);
    CLASS_ATTR_LABEL(c, "maxfreq", 0, "Highest pitch (Hz)");
    CLASS_ATTR_ACCESSORS(c, "maxfreq", NULL, didddle_set_maxfreq);

    // --- detection (as fidddle~) ----------------------------------------------------------------
    CLASS_ATTR_DOUBLE(c, "minlevel", 0, t_didddle, a_min_level);
    CLASS_ATTR_FILTER_CLIP(c, "minlevel", -90., -20.);
    CLASS_ATTR_LABEL(c, "minlevel", 0, "Level gate (dBFS)");
    CLASS_ATTR_ACCESSORS(c, "minlevel", NULL, didddle_attr_set);

    CLASS_ATTR_LONG(c, "confirm", 0, t_didddle, a_confirm);
    CLASS_ATTR_FILTER_CLIP(c, "confirm", 2, 24);
    CLASS_ATTR_LABEL(c, "confirm", 0, "Confirmation frames");
    CLASS_ATTR_ACCESSORS(c, "confirm", NULL, didddle_attr_set);

    CLASS_ATTR_DOUBLE(c, "release", 0, t_didddle, a_release_ms);
    CLASS_ATTR_FILTER_CLIP(c, "release", 0., 1000.);
    CLASS_ATTR_LABEL(c, "release", 0, "Release time (ms)");
    CLASS_ATTR_ACCESSORS(c, "release", NULL, didddle_attr_set);

    CLASS_ATTR_DOUBLE(c, "retrigger", 0, t_didddle, a_retrigger_db);
    CLASS_ATTR_FILTER_CLIP(c, "retrigger", 3., 30.);
    CLASS_ATTR_LABEL(c, "retrigger", 0, "Retrigger threshold (dB)");
    CLASS_ATTR_ACCESSORS(c, "retrigger", NULL, didddle_attr_set);

    CLASS_ATTR_DOUBLE_VARSIZE(c, "calibration", 0, t_didddle, a_cal, a_cal_n, Calibration::LIST_CAP);
    CLASS_ATTR_LABEL(c, "calibration", 0, "Learned calibration");
    CLASS_ATTR_ACCESSORS(c, "calibration", NULL, didddle_set_calibration);

    for (const char* n : {"latency", "transient"}) CLASS_ATTR_CATEGORY(c, n, 0, "Separation");
    for (const char* n : {"profile", "voices", "minfreq", "maxfreq"}) CLASS_ATTR_CATEGORY(c, n, 0, "Instrument");
    for (const char* n : {"minlevel", "confirm", "release", "retrigger"}) CLASS_ATTR_CATEGORY(c, n, 0, "Detection");
    CLASS_ATTR_CATEGORY(c, "calibration", 0, "Calibration");
    CLASS_ATTR_SAVE(c, "calibration", 0);
    int order = 1;
    for (const char* n : {"latency", "transient", "profile", "voices", "minfreq", "maxfreq", "minlevel", "confirm", "release", "retrigger"}) {
        char buf[8];
        snprintf(buf, sizeof buf, "%d", order++);
        CLASS_ATTR_SAVE(c, n, 0);
        CLASS_ATTR_ORDER(c, n, 0, buf);
    }

    CLASS_ATTR_DIGEST(c, "latency", 0, "Output delay (ms, 0 = shortest)");
    CLASS_ATTR_DESCRIPTION(c, "latency", 0,
        "The delay of every output relative to the input, 0 to 2000 ms. 0 uses the shortest delay the analysis window allows (about 85 ms for a cello at 48 kHz). A larger value gives the detector time to confirm each note before its audio is emitted, so attacks land in the right voice. Voices plus residual always equal the input delayed by this amount.");
    CLASS_ATTR_DIGEST(c, "transient", 0, "Attack length handed to the new voice (ms)");
    CLASS_ATTR_DESCRIPTION(c, "transient", 0,
        "How long after a note starts the unpitched attack (pluck click, bow noise) is given to that note's voice instead of the residual, 0 to 300 ms. 0 keeps attacks in the residual. Default 80.");
    CLASS_ATTR_DIGEST(c, "profile", 0, "Instrument profile");
    CLASS_ATTR_DESCRIPTION(c, "profile", 0,
        "Selects the instrument: 0 bass (plucked 5-string electric), 1 cello, 2 viola, 3 violin, 4 guitar, 5 contrabass (bowed and plucked double bass). Sets voices, minfreq and maxfreq to that instrument's defaults and adapts the analysis window and harmonic model. Default 1 (cello).");
    CLASS_ATTR_DIGEST(c, "voices", 0, "Maximum simultaneous voices");
    CLASS_ATTR_DESCRIPTION(c, "voices", 0,
        "The most notes separated at once, 1 to 6. The profile sets this (4 for bass, cello, viola and violin, 6 for guitar). A lower value uses less CPU and gives fewer false extra voices.");
    CLASS_ATTR_DIGEST(c, "minfreq", 0, "Lowest pitch (Hz)");
    CLASS_ATTR_DESCRIPTION(c, "minfreq", 0,
        "The lowest fundamental frequency searched, 20 to 2000 Hz. The profile sets this. A lower value needs a longer analysis window and so adds latency.");
    CLASS_ATTR_DIGEST(c, "maxfreq", 0, "Highest pitch (Hz)");
    CLASS_ATTR_DESCRIPTION(c, "maxfreq", 0,
        "The highest fundamental frequency searched, 100 to 6000 Hz. The profile sets this. Set it just above the highest note you play to reduce false notes.");
    CLASS_ATTR_DIGEST(c, "calibration", 0, "Learned string calibration");
    CLASS_ATTR_DESCRIPTION(c, "calibration", 0,
        "Produced by the calibrate message (see fidddle~): per-open-string inharmonicity and tuning and the harmonic weights. Saved with the patcher. Send calibrate clear to remove it.");
    CLASS_ATTR_DIGEST(c, "minlevel", 0, "Level gate (dBFS)");
    CLASS_ATTR_DESCRIPTION(c, "minlevel", 0, "Notes quieter than this level are ignored, -90 to -20 dBFS. Default -58.");
    CLASS_ATTR_DIGEST(c, "confirm", 0, "Frames before a note-on");
    CLASS_ATTR_DESCRIPTION(c, "confirm", 0,
        "How many analysis frames a new pitch must persist before a voice starts, 2 to 24. Higher values reject short false notes but add delay before a voice appears. Default 6.");
    CLASS_ATTR_DIGEST(c, "release", 0, "Time before a note-off (ms, 0 = profile)");
    CLASS_ATTR_DESCRIPTION(c, "release", 0,
        "How long a note may go unsupported before its voice ends, 50 to 1000 ms. 0 (default) uses the profile's own value.");
    CLASS_ATTR_DIGEST(c, "retrigger", 0, "Re-attack threshold (dB)");
    CLASS_ATTR_DESCRIPTION(c, "retrigger", 0,
        "How much louder the partials of a ringing note must become for a repeated pluck to retrigger it, 3 to 30 dB. Default 10.");

    class_dspinit(c);
    class_register(CLASS_BOX, c);
    s_class = c;
}

// Mirror Settings into the attribute fields (Max reads attributes straight from the struct).
static void sync_attrs(t_didddle* x) {
    x->a_profile = x->set.profile;
    x->a_voices = x->set.voices;
    x->a_minfreq = x->set.minfreq;
    x->a_maxfreq = x->set.maxfreq;
    x->a_min_level = x->set.min_level_dbfs;
    x->a_confirm = x->set.confirm_frames;
    x->a_release_ms = x->set.release_ms;
    x->a_retrigger_db = x->set.retrigger_db;
}

void* didddle_new(t_symbol* s, long argc, t_atom* argv) {
    t_didddle* x = (t_didddle*)object_alloc(s_class);
    if (!x) return nullptr;
    dsp_setup((t_pxobject*)x, 1);
    // outlets are created right to left
    x->out_info = outlet_new(x, NULL);
    x->out_events = outlet_new(x, NULL);
    outlet_new(x, "signal");                                         // residual
    for (int i = kSlots - 1; i >= 0; --i) outlet_new(x, "signal");   // voice slots 5..0

    new (&x->set) Settings();
    x->sr = sys_getsr() > 0 ? sys_getsr() : 44100.0;
    x->set.apply_profile_defaults(false, kSlots);
    sync_attrs(x);
    x->a_latency_ms = 0.0;
    x->a_transient_ms = didddle::Config().transient_ms;
    x->a_poll_ms = 2;
    x->a_cal_n = 0; x->pending_cal_ready = 0;
    x->active = nullptr;
    x->pending = nullptr;
    for (auto& g : x->grave) g = nullptr;

    // Setters only record values while `loading`; afterwards the profile fills in whatever the user did not set
    // explicitly, so the order of the attributes in the object box does not matter.
    x->clock = nullptr;
    x->loading = true;
    attr_args_process(x, (short)argc, argv);
    x->loading = false;
    x->set.apply_profile_defaults(true, kSlots);
    sync_attrs(x);

    x->clock = (t_clock*)clock_new((t_object*)x, (method)didddle_tick);
    rebuild(x);
    clock_fdelay(x->clock, (double)x->a_poll_ms);
    return x;
}

void didddle_free(t_didddle* x) {
    dsp_free((t_pxobject*)x);
    if (x->clock) { clock_unset(x->clock); object_free(x->clock); }
    delete x->active;
    delete x->pending;
    for (auto g : x->grave) delete g;
    x->set.~Settings();
}

void didddle_assist(t_didddle* x, void* b, long m, long a, char* s) {
    if (m == ASSIST_INLET) {
        snprintf_zero(s, ASSIST_MAX_STRING_LEN, "(signal) mono audio input; messages: reset, info, calibrate");
    } else if (a < kSlots) {
        snprintf_zero(s, ASSIST_MAX_STRING_LEN, "(signal) voice slot %ld audio (delayed)", a);
    } else if (a == kSlots) {
        snprintf_zero(s, ASSIST_MAX_STRING_LEN, "(signal) residual: input minus all voices (same delay)");
    } else if (a == kSlots + 1) {
        snprintf_zero(s, ASSIST_MAX_STRING_LEN, "list: midinote velocity slot (velocity 0 = note off)");
    } else {
        snprintf_zero(s, ASSIST_MAX_STRING_LEN, "replies to info: profile, latency, analysis, timing_us; calibrate progress");
    }
}

static void post_latency(t_didddle* x, didddle::Splitter* s) {
    t_atom a[2];
    atom_setlong(a + 0, s->latency_samples());
    atom_setfloat(a + 1, 1000.0 * s->latency_samples() / s->config().detector.sample_rate);
    outlet_anything(x->out_info, gensym("latency"), 2, a);   // samples, milliseconds: delay every output has relative to the input
}

// Build a splitter from the current attributes on the main thread; perform adopts it.
static void rebuild(t_didddle* x) {
    bool clamped = false;
    didddle::SplitterConfig sc;
    sc.detector = x->set.detector_config(x->sr, kSlots, &clamped);
    if (clamped) object_warn((t_object*)x, "maxfreq must be at least 1.5 x minfreq; using %.1f Hz", sc.detector.profile.max_frequency_hz);
    sc.finalize();
    sc.separator.latency_ms = x->a_latency_ms;
    sc.separator.transient_ms = x->a_transient_ms;
    didddle::Splitter* s = new didddle::Splitter(sc);
    post_latency(x, s);
    didddle::Splitter* old = axchg(&x->pending, s);
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

t_max_err didddle_set_profile(t_didddle* x, t_object* attr, long argc, t_atom* argv) {
    x->set.profile = (int)profile_from_atoms(argc, argv, x->set.profile);
    if (!x->loading && x->clock) {
        x->set.apply_profile_defaults(false, kSlots);   // switching instrument restores that instrument's defaults
        x->set.clear_calibration();                     // a calibration belongs to one instrument's strings
        x->a_cal_n = 0;
        sync_attrs(x);
        object_attr_touch((t_object*)x, gensym("voices"));
        object_attr_touch((t_object*)x, gensym("minfreq"));
        object_attr_touch((t_object*)x, gensym("maxfreq"));
        rebuild(x);
    } else {
        sync_attrs(x);
    }
    return MAX_ERR_NONE;
}

t_max_err didddle_set_voices(t_didddle* x, t_object* attr, long argc, t_atom* argv) {
    if (argc < 1) return MAX_ERR_NONE;
    x->set.voices = (int)std::min<long>(std::max<long>(atom_getlong(argv), 1), kSlots);
    x->set.user_voices = true;
    sync_attrs(x);
    if (!x->loading && x->clock) rebuild(x);
    return MAX_ERR_NONE;
}

t_max_err didddle_set_minfreq(t_didddle* x, t_object* attr, long argc, t_atom* argv) {
    if (argc < 1) return MAX_ERR_NONE;
    x->set.minfreq = std::min(std::max(atom_getfloat(argv), 20.0), 2000.0);
    x->set.user_minfreq = true;
    sync_attrs(x);
    if (!x->loading && x->clock) rebuild(x);
    return MAX_ERR_NONE;
}

t_max_err didddle_set_maxfreq(t_didddle* x, t_object* attr, long argc, t_atom* argv) {
    if (argc < 1) return MAX_ERR_NONE;
    x->set.maxfreq = std::min(std::max(atom_getfloat(argv), 100.0), 6000.0);
    x->set.user_maxfreq = true;
    sync_attrs(x);
    if (!x->loading && x->clock) rebuild(x);
    return MAX_ERR_NONE;
}

t_max_err didddle_attr_set(t_didddle* x, t_object* attr, long argc, t_atom* argv) {
    t_symbol* name = (t_symbol*)object_method(attr, gensym("getname"));
    if (argc < 1) return MAX_ERR_NONE;
    double v = atom_getfloat(argv);
    const char* n = name->s_name;
    if (!strcmp(n, "latency")) x->a_latency_ms = std::min(std::max(v, 0.0), 2000.0);
    else if (!strcmp(n, "transient")) x->a_transient_ms = std::min(std::max(v, 0.0), 300.0);
    else if (!strcmp(n, "minlevel")) x->set.min_level_dbfs = std::min(std::max(v, -90.0), -20.0);
    else if (!strcmp(n, "confirm")) x->set.confirm_frames = (int)std::min<long>(std::max<long>((long)v, 2), 24);
    else if (!strcmp(n, "release")) x->set.release_ms = v <= 0.0 ? 0.0 : std::min(std::max(v, 50.0), 1000.0);
    else if (!strcmp(n, "retrigger")) x->set.retrigger_db = std::min(std::max(v, 3.0), 30.0);
    sync_attrs(x);
    if (!x->loading && x->clock) rebuild(x);
    return MAX_ERR_NONE;
}

void didddle_reset(t_didddle* x) { rebuild(x); }

void didddle_info(t_didddle* x) {
    didddle::Splitter* s = aload(&x->active);
    t_atom a[5];
    atom_setsym(a + 0, gensym(kProfileNames[std::min<long>(std::max<long>(x->set.profile, 0), InstrumentProfile::Count - 1)]));
    atom_setlong(a + 1, x->set.voices);
    atom_setfloat(a + 2, x->set.minfreq);
    atom_setfloat(a + 3, x->set.maxfreq);
    outlet_anything(x->out_info, gensym("profile"), 4, a);   // name, voices, minfreq, maxfreq
    if (x->set.cal_on) {
        long got = 0;
        for (int i = 0; i < x->set.cal.n_strings; ++i) got += x->set.cal.captured[i];
        atom_setlong(a + 0, got);
        atom_setlong(a + 1, x->set.cal.n_strings);
        atom_setlong(a + 2, x->set.cal.n_weights > 0 ? 1 : 0);
        outlet_anything(x->out_info, gensym("calibration"), 3, a);   // strings captured, strings, harmonic weights learned (0/1)
    } else {
        atom_setsym(a, gensym("none"));
        outlet_anything(x->out_info, gensym("calibration"), 1, a);
    }
    if (!s) { atom_setsym(a, gensym("inactive")); outlet_anything(x->out_info, gensym("state"), 1, a); return; }
    post_latency(x, s);
    const fidddle::Config& dc = s->config().detector;
    const fidddle::Diagnostics& g = s->detector().diagnostics();
    atom_setfloat(a + 0, dc.sample_rate);
    atom_setlong(a + 1, s->detector().long_fft_size());
    atom_setlong(a + 2, s->config().separator.derived_fft());
    outlet_anything(x->out_info, gensym("analysis"), 3, a);   // sample rate, detector window, separator window
    atom_setfloat(a + 0, g.mean_us);
    atom_setfloat(a + 1, g.max_us);
    atom_setfloat(a + 2, 1e6 * dc.hop_size / dc.sample_rate);
    atom_setlong(a + 3, (long)g.overflow_events);
    outlet_anything(x->out_info, gensym("timing_us"), 4, a);   // detector: mean, max, hop budget, event-queue overflows
    const didddle::Diagnostics& sd = s->separator_diagnostics();
    atom_setfloat(a + 0, sd.mean_us);
    atom_setfloat(a + 1, sd.max_us);
    atom_setfloat(a + 2, 1e6 * s->config().separator.derived_hop() / dc.sample_rate);
    outlet_anything(x->out_info, gensym("separator_us"), 3, a);   // separator: mean, max per frame, frame period (budget)
}

static void post_cal(t_didddle* x, const char* what, long argc, t_atom* argv) {
    t_atom a[8];
    atom_setsym(a, gensym(what));
    for (long i = 0; i < argc && i < 7; ++i) a[1 + i] = argv[i];
    outlet_anything(x->out_info, gensym("calibrate"), 1 + std::min<long>(argc, 7), a);
}

// [calibrate 1] starts, [calibrate 0] finishes with the strings captured so far, [calibrate cancel], [calibrate clear]; a bare [calibrate] starts
void didddle_calibrate(t_didddle* x, t_symbol* s, long argc, t_atom* argv) {
    const char* cmd = "start";
    if (argc > 0 && atom_gettype(argv) == A_SYM) cmd = atom_getsym(argv)->s_name;
    else if (argc > 0 && (atom_gettype(argv) == A_LONG || atom_gettype(argv) == A_FLOAT)) cmd = atom_getfloat(argv) != 0.0 ? "start" : "done";
    didddle::Splitter* sp = aload(&x->active);
    if (!strcmp(cmd, "clear")) {
        x->set.clear_calibration(); x->a_cal_n = 0;
        object_attr_touch((t_object*)x, gensym("calibration"));
        rebuild(x);
        post_cal(x, "cleared", 0, nullptr);
        return;
    }
    if (!sp) { object_warn((t_object*)x, "calibrate: start audio first (the detector runs with the signal)"); return; }
    if (!strcmp(cmd, "start")) sp->detector().calibrate_start();
    else if (!strcmp(cmd, "done")) sp->detector().calibrate_finish();
    else if (!strcmp(cmd, "cancel")) sp->detector().calibrate_cancel();
    else object_warn((t_object*)x, "calibrate: unknown argument %s (use 1, 0, cancel or clear)", cmd);
}

// Main thread: adopt the calibration the audio thread finished (handed over by the clock thread).
void didddle_apply_calibration(t_didddle* x) {
    if (!__atomic_exchange_n(&x->pending_cal_ready, 0, __ATOMIC_ACQ_REL)) return;
    x->set.cal = x->pending_cal;
    x->set.cal_on = true;
    x->a_cal_n = x->set.cal.to_list(x->a_cal);
    object_attr_touch((t_object*)x, gensym("calibration"));
    rebuild(x);
    t_atom a[Calibration::LIST_CAP + 1];
    for (long i = 0; i < x->a_cal_n; ++i) atom_setfloat(a + i, x->a_cal[i]);
    post_cal(x, "applied", 0, nullptr);
    outlet_anything(x->out_info, gensym("calibration_data"), (short)x->a_cal_n, a);
}

t_max_err didddle_set_calibration(t_didddle* x, t_object* attr, long argc, t_atom* argv) {
    Calibration c;
    double v[Calibration::LIST_CAP];
    long n = std::min<long>(argc, Calibration::LIST_CAP);
    for (long i = 0; i < n; ++i) v[i] = atom_getfloat(argv + i);
    if (n > 0 && Calibration::from_list(v, (int)n, c)) {
        x->set.cal = c; x->set.cal_on = true;
        for (long i = 0; i < n; ++i) x->a_cal[i] = v[i];
        x->a_cal_n = n;
    } else {
        x->set.clear_calibration(); x->a_cal_n = 0;
        if (n > 0) object_warn((t_object*)x, "calibration: unrecognised list ignored");
    }
    if (!x->loading && x->clock) rebuild(x);
    return MAX_ERR_NONE;
}

void didddle_dsp64(t_didddle* x, t_object* dsp64, short* count, double samplerate, long maxvectorsize, long flags) {
    if (samplerate != x->sr) {
        x->sr = samplerate;
        rebuild(x);
    } else if (!aload(&x->active) && !aload(&x->pending)) {
        rebuild(x);
    }
    object_method(dsp64, gensym("dsp_add64"), x, didddle_perform64, 0, NULL);
}

void didddle_perform64(t_didddle* x, t_object* dsp64, double** ins, long numins, double** outs, long numouts, long sampleframes, long flags, void* userparam) {
    // adopt a freshly built splitter, handing the old one to the clock thread for deletion
    didddle::Splitter* fresh = axchg(&x->pending, nullptr);
    if (fresh) {
        didddle::Splitter* old = axchg(&x->active, fresh);
        if (old) {
            for (auto& g : x->grave) {
                didddle::Splitter* expected = nullptr;
                if (__atomic_compare_exchange_n(&g, &expected, old, false, __ATOMIC_ACQ_REL, __ATOMIC_ACQUIRE)) break;
            }   // all slots full: leak rather than free on the audio thread
        }
    }
    didddle::Splitter* s = aload(&x->active);
    if (!s || x->ob.z_disabled) {
        for (long o = 0; o < numouts; ++o) std::memset(outs[o], 0, sizeof(double) * sampleframes);
        return;
    }
    const int V = std::min<int>(s->slots(), kSlots);
    double* vp[MAX_VOICES];
    for (int v = 0; v < V; ++v) vp[v] = outs[v];
    for (int v = V; v < kSlots; ++v) std::memset(outs[v], 0, sizeof(double) * sampleframes);
    s->process(ins[0], (size_t)sampleframes, vp, outs[kSlots]);
}

void didddle_tick(t_didddle* x) {
    didddle::Splitter* s = aload(&x->active);
    NoteEvent e;
    t_atom a[3];
    while (s && s->poll_event(e)) {
        // one list outlet: <midinote> <velocity> <slot>; velocity 0 = note off (MIDI convention). These follow the
        // detector, i.e. they are not delayed by the separator's latency.
        atom_setlong(a + 0, e.midi_note);
        atom_setlong(a + 1, e.on ? std::max(1, e.velocity) : 0);
        atom_setlong(a + 2, e.slot);
        outlet_list(x->out_events, NULL, 3, a);
    }
    CalibEvent ce;
    while (s && s->detector().poll_calib_event(ce)) {
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
                if (s->detector().take_calibration(got)) {
                    x->pending_cal = got;
                    __atomic_store_n(&x->pending_cal_ready, 1, __ATOMIC_RELEASE);
                    defer_low(x, (method)didddle_apply_calibration, nullptr, 0, nullptr);   // rebuild on the main thread
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
        didddle::Splitter* old = axchg(&g, nullptr);
        delete old;
    }
    clock_fdelay(x->clock, (double)x->a_poll_ms);
}
