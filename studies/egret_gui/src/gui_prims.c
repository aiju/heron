/* Egret's primitives for the GUI: the screen, events, windows, drawing,
   fonts, the Transcript's output and compiling the Workspace's code.

   They're methods of Object named gui_*, so the desktop (lib/*.eg) calls
   them as functions. Windows are numbers (gwm.c), 0 being the screen;
   drawing takes content coordinates; colours are pixel values. */

#include "egret.h"
#include "gui.h"
#include "theme.h"
#include <heron.h>

#define A0 args[0]
#define A1 args[1]
#define A2 args[2]
#define A3 args[3]
#define I(k) INT(args[k])
#define ITEMS(l) (&F(F(l, L_ITEMS), 0))
#define IS_STR(v) (!IS_INT(v) && (CLASSW(v) == cls_String || CLASSW(v) == cls_Symbol))

extern const unsigned char font_sans12[], font_mono12[], ttf_sans[];

Font fonts[MAXFONTS];
int nfonts;
static TTF ttf;
static int depth = -1;

/* ---- helpers ---- */

/* are args[from..to] all SmallInts? */
static int ints(Value *args, int from, int to)
{
    int k;
    for (k = from; k <= to; k++)
        if (!IS_INT(args[k]))
            return 0;
    return 1;
}

static Value int_list(int n, const int *v)
{
    Value l = make_list(n);
    int i;
    for (i = 0; i < n; i++)
        ITEMS(l)[i] = MKINT(v[i]);
    F(l, L_SIZE) = MKINT(n);
    return l;
}

/* a String's bytes as a C string, in buf (cut to its size) */
static const char *cstr(Value s, char *buf, unsigned size)
{
    unsigned n = SIZE(s);
    if (n > size - 1)
        n = size - 1;
    memcpy(buf, BYTES(s), n);
    buf[n] = 0;
    return buf;
}

static int window_ok(Value v) { return IS_INT(v) && (INT(v) == 0 || gwm_exists(INT(v))); }

#define NEED_INTS(from, to) if (!ints(args, from, to)) return prim_fail("expected integers")
#define NEED_WIN(k) if (!window_ok(args[k])) return prim_fail("no such window")
#define NEED_INIT() if (depth < 0) return prim_fail("gui_init first")

/* ---- the font cache's memory, in VRAM past the screen ---- */

static unsigned char *arena = FONT_ARENA;

void *gui_alloc(unsigned n)
{
    void *p = arena;
    n = (n + 3) & ~3u;
    if (arena + n > FONT_ARENA_END)
        fatal("the font cache is full");
    arena += n;
    return p;
}

void *gui_calloc(unsigned n, unsigned size)
{
    void *p = gui_alloc(n * size);
    memset(p, 0, n * size);
    return p;
}

/* ---- the Transcript's copy of the output ---- */

#define OUTN 8192
static char obuf[OUTN];
static unsigned ohead, otail;           /* in at ohead, out at otail */

void gui_out_char(int c)
{
    unsigned next = (ohead + 1) % OUTN;
    if (next == otail)
        otail = (otail + 1) % OUTN;     /* full: lose the oldest */
    obuf[ohead] = c;
    ohead = next;
}

static Value p_output(Value *args, int argc)
{
    unsigned n = (ohead + OUTN - otail) % OUTN, i;
    Value s;
    if (n == 0)
        return NIL;
    s = alloc_bytes(cls_String, n);
    for (i = 0; i < n; i++)
        BYTES(s)[i] = obuf[(otail + i) % OUTN];
    otail = ohead;
    return s;
}

/* ---- the screen and the clock ---- */

static Value p_init(Value *args, int argc)
{
    int r, g, b, c;
    NEED_INTS(1, 1);
    depth = I(1) & 3;
    GUI_MODE = depth;
    GUI_PAL_INDEX = 0;
    for (c = 0; c < 1 << (1 << depth); c++) {
        theme_rgb(depth, c, &r, &g, &b);
        GUI_PAL_RGB = r << 16 | g << 8 | b;
    }
    theme_init(depth);
    if (nfonts == 0) {
        gfx_tables();
        font_bitmap(&fonts[0], font_sans12);
        font_bitmap(&fonts[1], font_mono12);
        ttf_open(&ttf, ttf_sans);
        nfonts = 2;
    }
    gwm_init(depth);
    HERON_TIMER = CLOCK_HZ / TICK_HZ;
    return NIL;
}

static Value p_depth(Value *args, int argc) { return MKINT(depth); }

static Value p_wait(Value *args, int argc)
{
    gui_wait();
    return NIL;
}

/* ticks since start-up, from the cycle counter (which wraps at 32 bits) */
static unsigned last_cycles, tick_cycles, ticks;

static Value p_ticks(Value *args, int argc)
{
    unsigned now = HERON_CYCLES, per = CLOCK_HZ / TICK_HZ;
    tick_cycles += now - last_cycles;
    last_cycles = now;
    ticks += tick_cycles / per;
    tick_cycles %= per;
    return MKINT(ticks & 0x3FFFFFFF);
}

static Value p_time(Value *args, int argc) { return MKINT(GUI_TIME); }

static Value p_pointer(Value *args, int argc)
{
    NEED_INTS(1, 1);
    GUI_POINTER = I(1);
    return NIL;
}

static Value p_mouse(Value *args, int argc)
{
    unsigned m = GUI_MOUSE, b = GUI_BUTTONS;
    int v[4];
    v[0] = m & 0xFFFF;
    v[1] = m >> 16;
    v[2] = b & 0xFF;
    v[3] = b >> 8;
    return int_list(4, v);
}

/* The next event: a window's update first, then input.
     [8, window, x0, y0, x1, y1]   paint this part of the window
     [1 or 2, code, modifiers]     a key down or up
     [3 or 4, button, x, y]        a button down or up
     [5, delta]                    the wheel */
static Value p_event(Value *args, int argc)
{
    Rect r;
    int v[6], id;
    unsigned e;
    NEED_INIT();
    if ((id = gwm_next_update(&r)) != 0) {
        v[0] = 8; v[1] = id;
        v[2] = r.x0; v[3] = r.y0; v[4] = r.x1; v[5] = r.y1;
        return int_list(6, v);
    }
    e = GUI_EVENT;
    if (e == 0xFFFFFFFF)
        return NIL;
    v[0] = e >> 28;
    switch (v[0]) {
    case 1: case 2:
        v[1] = e & 0xFFFF;
        v[2] = (e >> 16) & 0xFFF;
        return int_list(3, v);
    case 3: case 4:
        v[1] = (e >> 24) & 0xF;
        v[2] = e & 0xFFF;
        v[3] = (e >> 12) & 0xFFF;
        return int_list(4, v);
    case 5:
        v[1] = (short)(e & 0xFFFF);
        return int_list(2, v);
    }
    return NIL;
}

/* ---- colours ---- */

static Value p_rgb(Value *args, int argc)
{
    NEED_INTS(1, 3);
    NEED_INIT();
    if (depth == 0)
        return MKINT(I(1) + I(2) + I(3) >= 3 * 128);
    return MKINT(theme_nearest(depth, I(1), I(2), I(3)));
}

/* the theme's colours: black white desk desk2 frame title title_text
   title_off window text accent shadow light */
static Value p_theme(Value *args, int argc)
{
    int v[13];
    NEED_INIT();
    v[0] = c_black; v[1] = c_white; v[2] = c_desk; v[3] = c_desk2; v[4] = c_frame;
    v[5] = c_title; v[6] = c_title_text; v[7] = c_title_off; v[8] = c_window;
    v[9] = c_text; v[10] = c_accent; v[11] = c_shadow; v[12] = c_light;
    return int_list(13, v);
}

/* ---- windows ---- */

static Value p_open(Value *args, int argc)
{
    char title[64];
    int id, x0, y0;
    NEED_INTS(1, 4);
    NEED_INTS(6, 6);
    NEED_INIT();
    if (!IS_STR(args[5]))
        return prim_fail("the title isn't a String");
    x0 = I(1);
    y0 = I(2);
    id = gwm_open(x0, y0, x0 + I(3) + 2, y0 + I(4) + TITLE_H + 3, cstr(args[5], title, sizeof title), I(6));
    return id ? MKINT(id) : NIL;
}

static Value p_close(Value *args, int argc)
{
    NEED_WIN(1);
    if (I(1))
        gwm_close(I(1));
    return NIL;
}

static Value p_raise(Value *args, int argc)
{
    NEED_WIN(1);
    if (I(1))
        gwm_raise(I(1));
    return NIL;
}

static Value p_move(Value *args, int argc)
{
    NEED_WIN(1);
    NEED_INTS(2, 3);
    if (I(1))
        gwm_move(I(1), I(2), I(3));
    return NIL;
}

static Value p_resize(Value *args, int argc)
{
    NEED_WIN(1);
    NEED_INTS(2, 3);
    if (I(1))
        gwm_resize(I(1), I(2), I(3));
    return NIL;
}

static Value p_set_title(Value *args, int argc)
{
    char title[64];
    NEED_WIN(1);
    if (!IS_STR(args[2]))
        return prim_fail("the title isn't a String");
    if (I(1))
        gwm_set_title(I(1), cstr(args[2], title, sizeof title));
    return NIL;
}

static Value p_top(Value *args, int argc)
{
    int id = gwm_top();
    return id ? MKINT(id) : NIL;
}

/* [window, part] at a point (part: 1 content, 2 title bar, 3 close box,
   4 the bottom right corner), or nil on the desktop */
static Value p_hit(Value *args, int argc)
{
    int v[2];
    NEED_INTS(1, 2);
    v[0] = gwm_hit(I(1), I(2), &v[1]);
    return v[0] ? int_list(2, v) : NIL;
}

static Value p_frame(Value *args, int argc)
{
    Rect r;
    NEED_WIN(1);
    gwm_frame(I(1), &r);
    return int_list(4, &r.x0);
}

/* [x, y, w, h] of the content, on the screen */
static Value p_content(Value *args, int argc)
{
    Rect r;
    int v[4];
    NEED_WIN(1);
    gwm_content(I(1), &r);
    v[0] = r.x0; v[1] = r.y0; v[2] = r.x1 - r.x0; v[3] = r.y1 - r.y0;
    return int_list(4, v);
}

static Value p_scroll(Value *args, int argc)
{
    NEED_WIN(1);
    NEED_INTS(2, 6);
    if (I(1))
        gwm_scroll(I(1), I(2), I(3), I(2) + I(4), I(3) + I(5), I(6));
    return NIL;
}

static Value p_invalidate(Value *args, int argc)
{
    Rect r;
    NEED_WIN(1);
    if (!I(1))
        return NIL;
    if (argc < 5) {
        gwm_invalidate(I(1), 0);
        return NIL;
    }
    NEED_INTS(2, 5);
    r.x0 = I(2); r.y0 = I(3); r.x1 = I(2) + I(4); r.y1 = I(3) + I(5);
    gwm_invalidate(I(1), &r);
    return NIL;
}

static Value p_clip(Value *args, int argc)
{
    Rect r;
    NEED_WIN(1);
    if (!I(1))
        return NIL;
    if (argc < 5) {
        gwm_paint_clip(I(1), 0);
        return NIL;
    }
    NEED_INTS(2, 5);
    r.x0 = I(2); r.y0 = I(3); r.x1 = I(2) + I(4); r.y1 = I(3) + I(5);
    gwm_paint_clip(I(1), &r);
    return NIL;
}

static Value p_outline(Value *args, int argc)
{
    Rect r;
    NEED_INTS(1, 4);
    r.x0 = I(1); r.y0 = I(2); r.x1 = I(1) + I(3); r.y1 = I(2) + I(4);
    gwm_outline(&r);
    return NIL;
}

/* ---- drawing: through each of the window's clips ---- */

#define EACH_CLIP(id) \
    Rect *cl; int ncl, ox, oy, ci; \
    ncl = gwm_clips(id, &cl, &ox, &oy); \
    for (ci = 0; ci < ncl; ci++) { \
        gfx_clip_rect(&screen, &cl[ci]);
#define END_CLIPS } gfx_noclip(&screen);

/* gui_fill(win, x, y, w, h, color, rop) */
static Value p_fill(Value *args, int argc)
{
    int x, y, w, h;
    NEED_WIN(1);
    NEED_INTS(2, 7);
    x = I(2); y = I(3); w = I(4); h = I(5);
    {
        EACH_CLIP(I(1))
            gfx_fill(&screen, ox + x, oy + y, ox + x + w, oy + y + h, I(6), I(7));
        END_CLIPS
    }
    return NIL;
}

/* gui_box(win, x, y, w, h, color): a 1-pixel frame */
static Value p_box(Value *args, int argc)
{
    int x, y, w, h;
    NEED_WIN(1);
    NEED_INTS(2, 6);
    x = I(2); y = I(3); w = I(4); h = I(5);
    {
        EACH_CLIP(I(1))
            gfx_frame(&screen, ox + x, oy + y, ox + x + w, oy + y + h, 1, I(6), GFX_COPY);
        END_CLIPS
    }
    return NIL;
}

/* gui_line(win, x0, y0, x1, y1, color, rop) */
static Value p_line(Value *args, int argc)
{
    NEED_WIN(1);
    NEED_INTS(2, 7);
    {
        EACH_CLIP(I(1))
            gfx_line(&screen, ox + I(2), oy + I(3), ox + I(4), oy + I(5), I(6), I(7));
        END_CLIPS
    }
    return NIL;
}

/* gui_oval(win, cx, cy, a, b, color, filled) */
static Value p_oval(Value *args, int argc)
{
    NEED_WIN(1);
    NEED_INTS(2, 6);
    {
        EACH_CLIP(I(1))
            if (FALSY(args[7]))
                gfx_ellipse(&screen, ox + I(2), oy + I(3), I(4), I(5), I(6), GFX_COPY);
            else
                gfx_fill_ellipse(&screen, ox + I(2), oy + I(3), I(4), I(5), I(6), GFX_COPY);
        END_CLIPS
    }
    return NIL;
}

/* gui_poly(win, [x0, y0, x1, y1, ...], color): filled, non-zero */
#define MAXPOLY 64
static Value p_poly(Value *args, int argc)
{
    int xy[2 * MAXPOLY], n, i;
    Value l = args[2];
    NEED_WIN(1);
    NEED_INTS(3, 3);
    if (IS_INT(l) || CLASSW(l) != cls_List)
        return prim_fail("expected a List of coordinates");
    n = INT(F(l, L_SIZE));
    if (n & 1 || n > 2 * MAXPOLY)
        return prim_fail("expected up to 64 (x, y) pairs");
    for (i = 0; i < n; i++) {
        if (!IS_INT(ITEMS(l)[i]))
            return prim_fail("expected integers");
        xy[i] = INT(ITEMS(l)[i]);
    }
    {
        EACH_CLIP(I(1))
            int k;
            for (k = 0; k < n; k += 2) {
                xy[k] += ox;
                xy[k + 1] += oy;
            }
            gfx_poly(&screen, xy, n / 2, I(3), GFX_COPY, GFX_NONZERO);
            for (k = 0; k < n; k += 2) {
                xy[k] -= ox;
                xy[k + 1] -= oy;
            }
        END_CLIPS
    }
    return NIL;
}

/* gui_pixels(win, x, y, string): a row of pixels, a byte each */
static Value p_pixels(Value *args, int argc)
{
    Surface src;
    int n, x, y, i;
    NEED_WIN(1);
    NEED_INTS(2, 3);
    if (!IS_STR(args[4]))
        return prim_fail("expected a String of pixels");
    n = SIZE(args[4]);
    x = I(2);
    y = I(3);
    if (depth == 3)
        gfx_init(&src, BYTES(args[4]), n, 1, (n + 3) & ~3, 3);
    {
        EACH_CLIP(I(1))
            if (depth == 3)
                gfx_blit(&screen, ox + x, oy + y, &src, 0, 0, n, 1, GFX_COPY);
            else
                for (i = 0; i < n; i++)
                    gfx_pixel(&screen, ox + x + i, oy + y, BYTES(args[4])[i], GFX_COPY);
        END_CLIPS
    }
    return NIL;
}

/* ---- text ---- */

/* the ramps for anti-aliased text, for the last few colour pairs */
#define NRAMP 6
static unsigned char ramps[NRAMP][65];
static unsigned ramp_key[NRAMP];
static int ramp_next;

static const unsigned char *ramp_for(unsigned fg, unsigned bg)
{
    unsigned key = fg << 8 | bg | 0x10000;
    int i;
    for (i = 0; i < NRAMP; i++)
        if (ramp_key[i] == key)
            return ramps[i];
    i = ramp_next;
    ramp_next = (ramp_next + 1) % NRAMP;
    theme_ramp(depth, fg, bg, ramps[i]);
    ramp_key[i] = key;
    return ramps[i];
}

static Font *font_arg(Value v)
{
    if (!IS_INT(v) || INT(v) < 0 || INT(v) >= nfonts)
        return 0;
    return &fonts[INT(v)];
}

/* gui_text(win, x, y, string, fg, bg, font): y is the baseline; returns
   the x after it. bg matters only to anti-aliased fonts. */
static Value p_text(Value *args, int argc)
{
    static char buf[512];
    Font *f = font_arg(args[7]);
    const unsigned char *ramp = 0;
    int end = 0;
    NEED_WIN(1);
    NEED_INTS(2, 3);
    NEED_INTS(5, 6);
    if (!IS_STR(args[4]))
        return prim_fail("expected a String");
    if (!f)
        return prim_fail("no such font");
    cstr(args[4], buf, sizeof buf);
    if (f->aa)
        ramp = ramp_for(I(5), I(6));
    {
        EACH_CLIP(I(1))
            end = font_draw(&screen, f, ox + I(2), oy + I(3), buf, I(5), ramp) - ox;
        END_CLIPS
        if (ncl == 0)
            end = I(2) + font_width(f, buf);
    }
    return MKINT(end);
}

static Value p_text_width(Value *args, int argc)
{
    static char buf[512];
    Font *f = font_arg(args[2]);
    if (!IS_STR(args[1]))
        return prim_fail("expected a String");
    if (!f)
        return prim_fail("no such font");
    return MKINT(font_width(f, cstr(args[1], buf, sizeof buf)));
}

/* [ascent, descent, height] */
static Value p_font_info(Value *args, int argc)
{
    Font *f = font_arg(args[1]);
    int v[3];
    if (!f)
        return prim_fail("no such font");
    v[0] = f->ascent; v[1] = f->descent; v[2] = f->height;
    return int_list(3, v);
}

/* gui_font(size): DejaVu Sans at a size, rasterised on the machine,
   anti-aliased at 8 bits per pixel; returns its number */
static Value p_font(Value *args, int argc)
{
    int i, aa = depth == 3;
    NEED_INTS(1, 1);
    NEED_INIT();
    for (i = 2; i < nfonts; i++)
        if (fonts[i].size == I(1) && fonts[i].aa == aa)
            return MKINT(i);
    if (nfonts >= MAXFONTS || I(1) < 6 || I(1) > 48)
        return prim_fail("can't make that font");
    font_ttf(&fonts[nfonts], &ttf, I(1), aa);
    return MKINT(nfonts++);
}

/* ---- saving what's under a menu ---- */

static Surface saved;
static int saved_x, saved_y, saved_on;

static Value p_save(Value *args, int argc)
{
    int w, h, pitch;
    NEED_INTS(1, 4);
    w = I(3);
    h = I(4);
    pitch = (((w << depth) + 31) >> 5) << 2;
    if (w <= 0 || h <= 0 || pitch * h > SAVE_UNDER_SIZE)
        return prim_fail("too big to save");
    gfx_init(&saved, SAVE_UNDER, w, h, pitch, depth);
    gfx_noclip(&screen);
    gfx_blit(&saved, 0, 0, &screen, I(1), I(2), w, h, GFX_COPY);
    saved_x = I(1);
    saved_y = I(2);
    saved_on = 1;
    return NIL;
}

static Value p_restore(Value *args, int argc)
{
    if (saved_on) {
        gfx_noclip(&screen);
        gfx_blit(&screen, saved_x, saved_y, &saved, 0, 0, saved.w, saved.h, GFX_COPY);
        saved_on = 0;
    }
    return NIL;
}

/* ---- compiling the Workspace's code ----

   gui_compile(source) compiles each top-level statement as a method of
   Object with a selector of its own, and returns the selectors, for the
   desktop to send (so the code runs in the interpreter as the desktop's
   own does, and an error in it is an Egret error the desktop catches).
   Classes and defs take effect as they're compiled, as in a program.
   With a syntax error it returns the compiler's messages, a String. */

#define MAXSRC 16384
#define MAXSTMT 64
static char src[MAXSRC];
static unsigned doits;

static Value p_compile(Value *args, int argc)
{
    Value sels[MAXSTMT], m, l;
    unsigned n, mark = ohead, errs = compile_errors;
    int k = 0, i;
    char name[16];
    if (!IS_STR(args[1]))
        return prim_fail("expected a String");
    n = SIZE(args[1]);
    if (n >= MAXSRC)
        return prim_fail("too much source");
    memcpy(src, BYTES(args[1]), n);
    compile_source(src, n, "workspace");
    while ((m = compile_next()) != 0) {
        if (k >= MAXSTMT)
            return prim_fail("too many statements");
        doits++;
        memcpy(name, "__doit", 6);
        for (i = 0; doits >> (4 * i) && i < 8; i++)
            name[6 + i] = "0123456789abcdef"[(doits >> (4 * i)) & 15];
        sels[k] = intern(name, 6 + i);
        F(m, M_SEL) = sels[k];
        class_add_method(cls_Object, sels[k], m);
        k++;
    }
    if (compile_errors != errs) {
        /* what the compiler said since we started */
        unsigned len = (ohead + OUTN - mark) % OUTN, j;
        Value s = alloc_bytes(cls_String, len);
        for (j = 0; j < len; j++)
            BYTES(s)[j] = obuf[(mark + j) % OUTN];
        return s;
    }
    l = make_list(k);
    for (i = 0; i < k; i++)
        ITEMS(l)[i] = sels[i];
    F(l, L_SIZE) = MKINT(k);
    return l;
}

/* ---- the table ---- */

static const PrimDef defs[] = {
    { "Object", "gui_init", 1, p_init, 0 },
    { "Object", "gui_depth", 0, p_depth, 0 },
    { "Object", "gui_wait", 0, p_wait, 0 },
    { "Object", "gui_ticks", 0, p_ticks, 0 },
    { "Object", "gui_time", 0, p_time, 0 },
    { "Object", "gui_pointer", 1, p_pointer, 0 },
    { "Object", "gui_mouse", 0, p_mouse, 0 },
    { "Object", "gui_event", 0, p_event, 0 },
    { "Object", "gui_output", 0, p_output, 0 },
    { "Object", "gui_rgb", 3, p_rgb, 0 },
    { "Object", "gui_theme", 0, p_theme, 0 },
    { "Object", "gui_open", 6, p_open, 0 },
    { "Object", "gui_close", 1, p_close, 0 },
    { "Object", "gui_raise", 1, p_raise, 0 },
    { "Object", "gui_move", 3, p_move, 0 },
    { "Object", "gui_resize", 3, p_resize, 0 },
    { "Object", "gui_set_title", 2, p_set_title, 0 },
    { "Object", "gui_top", 0, p_top, 0 },
    { "Object", "gui_hit", 2, p_hit, 0 },
    { "Object", "gui_frame", 1, p_frame, 0 },
    { "Object", "gui_content", 1, p_content, 0 },
    { "Object", "gui_scroll", 6, p_scroll, 0 },
    { "Object", "gui_invalidate", -2, p_invalidate, 0 },
    { "Object", "gui_clip", -2, p_clip, 0 },
    { "Object", "gui_outline", 4, p_outline, 0 },
    { "Object", "gui_fill", 7, p_fill, 0 },
    { "Object", "gui_box", 6, p_box, 0 },
    { "Object", "gui_line", 7, p_line, 0 },
    { "Object", "gui_oval", 7, p_oval, 0 },
    { "Object", "gui_poly", 3, p_poly, 0 },
    { "Object", "gui_pixels", 4, p_pixels, 0 },
    { "Object", "gui_text", 7, p_text, 0 },
    { "Object", "gui_text_width", 2, p_text_width, 0 },
    { "Object", "gui_font_info", 1, p_font_info, 0 },
    { "Object", "gui_font", 1, p_font, 0 },
    { "Object", "gui_save", 4, p_save, 0 },
    { "Object", "gui_restore", 0, p_restore, 0 },
    { "Object", "gui_compile", 1, p_compile, 0 },
    { 0, 0, 0, 0, 0 }
};

const PrimDef *gui_prim_defs(void) { return defs; }
