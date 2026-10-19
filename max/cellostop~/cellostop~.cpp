/**
    @file
    cellostop~ : real-time polyphonic pitch detector for string instruments (MVP: cello, up to 4 voices).

    Inlet 0 (signal): mono audio.
    Outlets (left to right):
        0-3  signal  frequency in Hz of voice slot 0..3 (0 when the slot is silent). Slots are persistent per note.
        4-7  signal  linear level of voice slot 0..3 (0 when silent)
        8    list  <midinote> <velocity> <slot>  (velocity 0 = note off; a retrigger sends the off then the on)
        9    messages  replies to "info" (analysis, timing, latency)

    The detector runs in the audio thread (no allocation, no locks). Attribute changes build a fresh
    detector on the main thread and swap it in at the next signal vector.
*/
#include "ext.h"
#include "ext_obex.h"
#include "z_dsp.h"

#include <cmath>
#include <cstring>

#include "cellostop/detector.hpp"

using namespace cellostop;

constexpr int kSlots = 4;      // MVP cello: one voice per string
constexpr int kGrave = 4;

struct t_cellostop {
    t_pxobject ob;
    void* out_events;
    void* out_info;
    t_clock* clock;

    // main-thread configuration (attributes)
    Config* cfg;
    double sr;
    long a_max_voices;
    double a_min_level;
    long a_confirm;
    double a_release_ms;
    double a_retrigger_db;
    long a_poll_ms;

    // note-on latency statistics (clock thread writes, info reads; display only)
    double lat_sum, lat_max;
    long lat_count;

    // handed between threads with atomic pointer exchanges
    Detector* active;      // owned by the audio thread's view; deleted by the clock thread after a swap
    Detector* pending;     // built on the main thread, adopted by perform
    Detector* grave[kGrave];
};

// Same mechanism the SDK uses for CLASS_ATTR_LABEL: a sub-attribute on the attribute. Max uses these
// for tooltips and attribute documentation; keep the text in sync with docs/cellostop~.maxref.xml.
#define CLASS_ATTR_DIGEST(c, attrname, flags, str) \
    CLASS_ATTR_ATTR_FORMAT(c, attrname, "digest", USESYM(symbol), flags, "s", gensym_tr(str))
#define CLASS_ATTR_DESCRIPTION(c, attrname, flags, str) \
    CLASS_ATTR_ATTR_FORMAT(c, attrname, "description", USESYM(symbol), flags, "s", gensym_tr(str))

static t_class* s_class = nullptr;

void* cellostop_new(t_symbol* s, long argc, t_atom* argv);
void cellostop_free(t_cellostop* x);
void cellostop_assist(t_cellostop* x, void* b, long m, long a, char* s);
void cellostop_dsp64(t_cellostop* x, t_object* dsp64, short* count, double samplerate, long maxvectorsize, long flags);
void cellostop_perform64(t_cellostop* x, t_object* dsp64, double** ins, long numins, double** outs, long numouts, long sampleframes, long flags, void* userparam);
void cellostop_tick(t_cellostop* x);
void cellostop_reset(t_cellostop* x);
void cellostop_info(t_cellostop* x);
t_max_err cellostop_attr_set(t_cellostop* x, t_object* attr, long argc, t_atom* argv);
static void rebuild(t_cellostop* x);

static inline Detector* aload(Detector** p) { return __atomic_load_n(p, __ATOMIC_ACQUIRE); }
static inline Detector* axchg(Detector** p, Detector* v) { return __atomic_exchange_n(p, v, __ATOMIC_ACQ_REL); }

void ext_main(void* r) {
    t_class* c = class_new("cellostop~", (method)cellostop_new, (method)cellostop_free, (long)sizeof(t_cellostop), 0L, A_GIMME, 0);

    class_addmethod(c, (method)cellostop_dsp64, "dsp64", A_CANT, 0);
    class_addmethod(c, (method)cellostop_assist, "assist", A_CANT, 0);
    class_addmethod(c, (method)cellostop_reset, "reset", 0);
    class_addmethod(c, (method)cellostop_info, "info", 0);

    CLASS_ATTR_LONG(c, "voices", 0, t_cellostop, a_max_voices);
    CLASS_ATTR_FILTER_CLIP(c, "voices", 1, kSlots);
    CLASS_ATTR_LABEL(c, "voices", 0, "Maximum simultaneous voices");
    CLASS_ATTR_ACCESSORS(c, "voices", NULL, cellostop_attr_set);

    CLASS_ATTR_DOUBLE(c, "minlevel", 0, t_cellostop, a_min_level);
    CLASS_ATTR_FILTER_CLIP(c, "minlevel", -90., -20.);
    CLASS_ATTR_LABEL(c, "minlevel", 0, "Level gate (dBFS)");
    CLASS_ATTR_ACCESSORS(c, "minlevel", NULL, cellostop_attr_set);

    CLASS_ATTR_LONG(c, "confirm", 0, t_cellostop, a_confirm);
    CLASS_ATTR_FILTER_CLIP(c, "confirm", 2, 24);
    CLASS_ATTR_LABEL(c, "confirm", 0, "Frames a new pitch must persist before noteon (5.8 ms each at 44.1k)");
    CLASS_ATTR_ACCESSORS(c, "confirm", NULL, cellostop_attr_set);

    CLASS_ATTR_DOUBLE(c, "release", 0, t_cellostop, a_release_ms);
    CLASS_ATTR_FILTER_CLIP(c, "release", 50., 1000.);
    CLASS_ATTR_LABEL(c, "release", 0, "Unsupported time before noteoff (ms)");
    CLASS_ATTR_ACCESSORS(c, "release", NULL, cellostop_attr_set);

    CLASS_ATTR_DOUBLE(c, "retrigger", 0, t_cellostop, a_retrigger_db);
    CLASS_ATTR_FILTER_CLIP(c, "retrigger", 3., 30.);
    CLASS_ATTR_LABEL(c, "retrigger", 0, "Re-attack rise (dB) that retriggers a sounding note");
    CLASS_ATTR_ACCESSORS(c, "retrigger", NULL, cellostop_attr_set);

    // inspector grouping, saving with the patcher, and a stable order
    for (const char* n : {"voices", "minlevel", "confirm", "release", "retrigger"}) {
        CLASS_ATTR_CATEGORY(c, n, 0, "Detection");
        CLASS_ATTR_SAVE(c, n, 0);
    }
    CLASS_ATTR_DIGEST(c, "voices", 0, "Maximum simultaneous voices");
    CLASS_ATTR_DESCRIPTION(c, "voices", 0,
        "The most notes tracked at once, 1 to 4. A lower value uses less CPU and gives fewer false extra notes. Default 4.");
    CLASS_ATTR_DIGEST(c, "minlevel", 0, "Level gate (dBFS)");
    CLASS_ATTR_DESCRIPTION(c, "minlevel", 0,
        "Notes quieter than this level are ignored, -90 to -20 dBFS. Raise it to reject room noise and ringing. Default -58.");
    CLASS_ATTR_DIGEST(c, "confirm", 0, "Frames before a note-on");
    CLASS_ATTR_DESCRIPTION(c, "confirm", 0,
        "How many analysis frames (about 5.8 ms each at 44.1 kHz) a new pitch must persist before a note-on is sent, 2 to 24. Higher values reject short false notes but add latency. Default 6.");
    CLASS_ATTR_DIGEST(c, "release", 0, "Time before a note-off (ms)");
    CLASS_ATTR_DESCRIPTION(c, "release", 0,
        "How long a note may go unsupported by the analysis before its note-off is sent, 50 to 1000 ms. Higher values bridge dropouts but delay note-offs. Default 100.");
    CLASS_ATTR_DIGEST(c, "retrigger", 0, "Re-attack threshold (dB)");
    CLASS_ATTR_DESCRIPTION(c, "retrigger", 0,
        "How much louder (in dB) the partials of a ringing note must become for a repeated pluck to retrigger it, 3 to 30. Lower values retrigger more easily but may split sustained notes. Default 10.");

    CLASS_ATTR_ORDER(c, "voices", 0, "1");
    CLASS_ATTR_ORDER(c, "minlevel", 0, "2");
    CLASS_ATTR_ORDER(c, "confirm", 0, "3");
    CLASS_ATTR_ORDER(c, "release", 0, "4");
    CLASS_ATTR_ORDER(c, "retrigger", 0, "5");

    class_dspinit(c);
    class_register(CLASS_BOX, c);
    s_class = c;
}

void* cellostop_new(t_symbol* s, long argc, t_atom* argv) {
    t_cellostop* x = (t_cellostop*)object_alloc(s_class);
    if (!x) return nullptr;
    dsp_setup((t_pxobject*)x, 1);
    // outlets are created right to left
    x->out_info = outlet_new(x, NULL);
    x->out_events = outlet_new(x, NULL);
    for (int i = kSlots - 1; i >= 0; --i) outlet_new(x, "signal");   // level 3..0
    for (int i = kSlots - 1; i >= 0; --i) outlet_new(x, "signal");   // frequency 3..0

    x->cfg = new Config();
    x->sr = sys_getsr() > 0 ? sys_getsr() : 44100.0;
    x->a_max_voices = kSlots;
    x->a_min_level = x->cfg->min_level_dbfs;
    x->a_confirm = x->cfg->confirm_frames;
    x->a_release_ms = x->cfg->unsupported_timeout_ms;
    x->a_retrigger_db = x->cfg->retrigger_rise_db;
    x->a_poll_ms = 2;
    x->lat_sum = 0.0; x->lat_max = 0.0; x->lat_count = 0;
    x->active = nullptr;
    x->pending = nullptr;
    for (auto& g : x->grave) g = nullptr;

    x->clock = nullptr;   // attribute setters run during creation, before the clock exists
    attr_args_process(x, (short)argc, argv);
    x->clock = (t_clock*)clock_new((t_object*)x, (method)cellostop_tick);
    rebuild(x);
    clock_fdelay(x->clock, (double)x->a_poll_ms);
    return x;
}

void cellostop_free(t_cellostop* x) {
    dsp_free((t_pxobject*)x);
    if (x->clock) { clock_unset(x->clock); object_free(x->clock); }
    delete x->active;
    delete x->pending;
    for (auto g : x->grave) delete g;
    delete x->cfg;
}

void cellostop_assist(t_cellostop* x, void* b, long m, long a, char* s) {
    if (m == ASSIST_INLET) {
        snprintf_zero(s, ASSIST_MAX_STRING_LEN, "(signal) mono audio input; messages: reset, info");
    } else if (a < kSlots) {
        snprintf_zero(s, ASSIST_MAX_STRING_LEN, "(signal) voice %ld frequency in Hz (0 = silent)", a);
    } else if (a < 2 * kSlots) {
        snprintf_zero(s, ASSIST_MAX_STRING_LEN, "(signal) voice %ld level (linear)", a - kSlots);
    } else if (a == 2 * kSlots) {
        snprintf_zero(s, ASSIST_MAX_STRING_LEN, "list: midinote velocity slot (velocity 0 = note off)");
    } else {
        snprintf_zero(s, ASSIST_MAX_STRING_LEN, "replies to info: analysis, timing_us, latency_ms");
    }
}

// Build a detector from the current attributes on the main thread; perform adopts it.
static void rebuild(t_cellostop* x) {
    Config c = *x->cfg;
    c.sample_rate = x->sr;
    c.max_voices = (int)x->a_max_voices;
    c.min_level_dbfs = x->a_min_level;
    c.confirm_frames = (int)x->a_confirm;
    c.strong_confirm_frames = std::max(2, (int)x->a_confirm * 2 / 3);
    c.unsupported_timeout_ms = x->a_release_ms;
    c.retrigger_rise_db = x->a_retrigger_db;
    x->lat_sum = 0.0; x->lat_max = 0.0; x->lat_count = 0;
    Detector* d = new Detector(c);
    Detector* old = axchg(&x->pending, d);
    delete old;   // never adopted; the audio thread never saw it
}

t_max_err cellostop_attr_set(t_cellostop* x, t_object* attr, long argc, t_atom* argv) {
    t_symbol* name = (t_symbol*)object_method(attr, gensym("getname"));
    if (argc < 1) return MAX_ERR_NONE;
    double v = atom_getfloat(argv);
    const char* n = name->s_name;
    if (!strcmp(n, "voices")) x->a_max_voices = std::min<long>(std::max<long>((long)v, 1), kSlots);
    else if (!strcmp(n, "minlevel")) x->a_min_level = std::min(std::max(v, -90.0), -20.0);
    else if (!strcmp(n, "confirm")) x->a_confirm = std::min<long>(std::max<long>((long)v, 2), 24);
    else if (!strcmp(n, "release")) x->a_release_ms = std::min(std::max(v, 50.0), 1000.0);
    else if (!strcmp(n, "retrigger")) x->a_retrigger_db = std::min(std::max(v, 3.0), 30.0);
    if (x->clock) rebuild(x);   // not during object creation (attr_args_process runs before the clock exists)
    return MAX_ERR_NONE;
}

void cellostop_reset(t_cellostop* x) { rebuild(x); }

void cellostop_info(t_cellostop* x) {
    Detector* d = aload(&x->active);
    t_atom a[4];
    if (!d) { atom_setsym(a, gensym("inactive")); outlet_anything(x->out_info, gensym("state"), 1, a); return; }
    const Diagnostics& g = d->diagnostics();
    atom_setfloat(a + 0, d->config().sample_rate);
    atom_setlong(a + 1, d->long_fft_size());
    outlet_anything(x->out_info, gensym("analysis"), 2, a);
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

void cellostop_dsp64(t_cellostop* x, t_object* dsp64, short* count, double samplerate, long maxvectorsize, long flags) {
    if (samplerate != x->sr) {
        x->sr = samplerate;
        rebuild(x);
    } else if (!aload(&x->active) && !aload(&x->pending)) {
        rebuild(x);
    }
    object_method(dsp64, gensym("dsp_add64"), x, cellostop_perform64, 0, NULL);
}

void cellostop_perform64(t_cellostop* x, t_object* dsp64, double** ins, long numins, double** outs, long numouts, long sampleframes, long flags, void* userparam) {
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

void cellostop_tick(t_cellostop* x) {
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
    for (auto& g : x->grave) {
        Detector* old = axchg(&g, nullptr);
        delete old;
    }
    clock_fdelay(x->clock, (double)x->a_poll_ms);
}
