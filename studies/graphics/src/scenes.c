/* The benchmark scenes. Each draws on a 640 x 480 screen at the depth
   it's given, and calls mark() at the end of every phase. Random shapes
   are made before the phase that draws them, so the phases measure only
   the drawing; mark_n's count is the work done (pixels, glyphs, ...). */

#include <string.h>
#include "scenes.h"
#include "theme.h"
#include "wm.h"

unsigned fb_mem[SCREEN_W * SCREEN_H / 4];

Surface screen;

static unsigned seed = 1;

static unsigned rnd(void)              /* xorshift32 */
{
    seed ^= seed << 13;
    seed ^= seed >> 17;
    seed ^= seed << 5;
    return seed;
}

static int rndn(int n)                  /* 0..n-1, n up to 65536 */
{
    return (int)((rnd() >> 16) * (unsigned)n >> 16);
}

void mark(const char *name)
{
    mark_n(name, 0);
}

/* ---- primitives ---- */

#define NR 400
static int sh[NR * 5];                  /* shapes: up to 5 numbers each */

static int random_rects(int n, int minw, int maxw, int minh, int maxh)
{
    int i, *p = sh, w, h, px = 0;
    for (i = 0; i < n; i++, p += 5) {
        w = minw + rndn(maxw - minw + 1);
        h = minh + rndn(maxh - minh + 1);
        p[0] = rndn(SCREEN_W - w + 1);
        p[1] = rndn(SCREEN_H - h + 1);
        p[2] = p[0] + w;
        p[3] = p[1] + h;
        p[4] = rnd();
        px += w * h;
    }
    return px;
}

static void draw_rects(Surface *s, int n, int rop)
{
    int i, *p = sh, m = gfx_maxcolor(s->depth);
    for (i = 0; i < n; i++, p += 5)
        gfx_fill(s, p[0], p[1], p[2], p[3], p[4] & m, rop);
}

static int random_lines(int n, int maxlen, int out)
{
    int i, *p = sh, dx, dy, px = 0;
    for (i = 0; i < n; i++, p += 5) {
        p[0] = rndn(SCREEN_W + 2 * out) - out;
        p[1] = rndn(SCREEN_H + 2 * out) - out;
        p[2] = p[0] + rndn(2 * maxlen + 1) - maxlen;
        p[3] = p[1] + rndn(2 * maxlen + 1) - maxlen;
        p[4] = rnd();
        dx = p[2] - p[0];
        dy = p[3] - p[1];
        if (dx < 0) dx = -dx;
        if (dy < 0) dy = -dy;
        px += (dx > dy ? dx : dy) + 1;
    }
    return px;
}

static void draw_lines(Surface *s, int n, int rop)
{
    int i, *p = sh, m = gfx_maxcolor(s->depth);
    for (i = 0; i < n; i++, p += 5)
        gfx_line(s, p[0], p[1], p[2], p[3], (p[4] & m) | 1, rop);
}

static const int star[] = {
    0, -100, 24, -32, 95, -31, 38, 12, 59, 81, 0, 40, -59, 81, -38, 12, -95, -31, -24, -32
};

static void scene_prims(Surface *s)
{
    int n, i, k, m = gfx_maxcolor(s->depth), xy[40];
    unsigned pat[8];

    mark("_");
    gfx_fill(s, 0, 0, SCREEN_W, SCREEN_H, m, GFX_COPY);
    mark_n("clear", SCREEN_W * SCREEN_H);

    n = random_rects(100, 8, 200, 8, 200);
    mark("_");
    draw_rects(s, 100, GFX_COPY);
    mark_n("rect", n);
    draw_rects(s, 100, GFX_XOR);
    mark_n("rect.xor", n);
    n = random_rects(NR, 8, 8, 8, 8);
    mark("_");
    draw_rects(s, NR, GFX_COPY);
    mark_n("rect.8x8", n);
    n = random_rects(NR, 1, 3, 1, 3);
    mark("_");
    draw_rects(s, NR, GFX_COPY);
    mark_n("rect.tiny", n);

    for (k = 0; k < 8; k++)
        pat[k] = theme_pattern(s->depth, k);
    gfx_fill_pat(s, 40, 40, 600, 440, pat, GFX_COPY);
    mark_n("pattern", 560 * 400);

    gfx_fill(s, 0, 0, SCREEN_W, SCREEN_H, 0, GFX_COPY);
    n = random_lines(NR, 150, 0);
    mark("_");
    draw_lines(s, NR, GFX_COPY);
    mark_n("line", n);
    draw_lines(s, NR, GFX_XOR);
    mark_n("line.xor", n);
    n = random_lines(NR, 20, 0);
    mark("_");
    draw_lines(s, NR, GFX_COPY);
    mark_n("line.short", n);
    random_lines(100, 600, 300);
    mark("_");
    draw_lines(s, 100, GFX_COPY);
    mark_n("line.clipped", 100);
    for (i = 0; i < 100; i++)
        gfx_line(s, 20, 20 + i * 4, 619, 20 + i * 4, i & m, GFX_COPY);
    mark_n("line.horizontal", 100 * 600);
    for (i = 0; i < 100; i++)
        gfx_line(s, 20 + i * 6, 20, 20 + i * 6, 459, i & m, GFX_COPY);
    mark_n("line.vertical", 100 * 440);

    gfx_fill(s, 0, 0, SCREEN_W, SCREEN_H, 0, GFX_COPY);
    for (i = 0; i < 40; i++)
        gfx_ellipse(s, 320 + (i % 8) * 20 - 70, 240 + (i / 8) * 20 - 40, 10 + i * 5, 8 + i * 4,
                    (i & m) | 1, GFX_COPY);
    mark_n("ellipse", 40);
    for (i = 0; i < 40; i++)
        gfx_fill_ellipse(s, 40 + (i % 8) * 80, 40 + (i / 8) * 100, 10 + i, 10 + (i * 7) % 40,
                         (i & m) | 1, GFX_COPY);
    mark_n("ellipse.fill", 40);

    gfx_fill(s, 0, 0, SCREEN_W, SCREEN_H, 0, GFX_COPY);
    for (k = 0; k < 20; k++) {
        /* even k: a pentagram, even-odd (a hollow middle); odd k: the
           star's outline, non-zero */
        n = k & 1 ? 10 : 5;
        for (i = 0; i < n; i++) {
            int v = k & 1 ? i : (4 * i) % 10;
            xy[2 * i] = 80 + (k % 5) * 120 + star[2 * v] * (k + 10) / 30;
            xy[2 * i + 1] = 110 + (k / 5) * 90 + star[2 * v + 1] * (k + 10) / 30;
        }
        gfx_poly(s, xy, n, (k & m) | 1, GFX_COPY, k & 1 ? GFX_NONZERO : GFX_EVENODD);
    }
    mark_n("polygon", 20);

    /* copying: a busy picture first */
    for (i = 0; i < 64; i++)
        gfx_fill(s, (i * 37) % 600, (i * 53) % 440, (i * 37) % 600 + 40, (i * 53) % 440 + 40,
                 i & m, GFX_XOR);
    mark("_");
    gfx_blit(s, 352, 64, s, 32, 64, 256, 256, GFX_COPY);
    mark_n("blit.aligned", 256 * 256);
    gfx_blit(s, 355, 70, s, 32, 64, 256, 256, GFX_COPY);
    mark_n("blit.unaligned", 256 * 256);
    gfx_blit(s, 0, 0, s, 0, 16, SCREEN_W, SCREEN_H - 16, GFX_COPY);
    mark_n("scroll.up", SCREEN_W * (SCREEN_H - 16));
    gfx_blit(s, 1, 0, s, 0, 0, SCREEN_W - 1, SCREEN_H, GFX_COPY);
    mark_n("scroll.right", (SCREEN_W - 1) * SCREEN_H);
    for (i = 0; i < 100; i++)
        gfx_expand(s, (i * 61) % 620, (i * 47) % 460, &icon, 0, 0, 16, 16, (i & m) | 1, 0, 0);
    mark_n("icon", 100);
    for (i = 0; i < 100; i++)
        gfx_expand(s, (i * 61) % 620, (i * 47) % 460, &icon, 0, 0, 16, 16, (i & m) | 1, 0, 1);
    mark_n("icon.opaque", 100);
}

/* ---- text ---- */

extern const unsigned char font_sans12[], font_mono12[], ttf_sans[];

static const char *const para[] = {
    "Herons are long-legged, long-necked freshwater and coastal birds. They hunt",
    "by standing still in shallow water and striking at fish with their bills,",
    "and fly with their necks drawn back in an S. The grey heron is common across",
    "Europe and Asia; it nests in colonies, high in trees, and returns to the same",
    "heronry year after year. This machine has no fish to catch, only pixels:",
    "every character on this screen was drawn by its CPU, a bit at a time where",
    "the bits don't line up with its words, through tables where they do.",
    "1234567890 !\"#$%&'()*+,-./:;<=>?@[\\]^_`{|}~ ABCDEFGHIJKLMNOPQRSTUVWXYZ",
};

static const char *const term[] = {
    "$ ls -l /usr/src/gfx",
    "-rw-r--r--  1 emily  staff   6130 Oct 13 22:41 blit.c",
    "-rw-r--r--  1 emily  staff   3952 Oct 13 22:41 ellipse.c",
    "-rw-r--r--  1 emily  staff   7804 Oct 13 22:41 expand.c",
    "-rw-r--r--  1 emily  staff   7261 Oct 13 22:41 gfx.c",
    "$ cc -O -o wm wm.c gfx.c font.c ttf.c raster.c",
    "$ ./wm &",
    "[1] 4711",
    "$ for i in 1 2 3; do echo \"line $i of the terminal, 80 columns wide\"; done",
    "line 1 of the terminal, 80 columns wide",
    "line 2 of the terminal, 80 columns wide",
    "line 3 of the terminal, 80 columns wide",
};

static const char sample[] = "The quick brown fox jumps over the lazy dog";
static const char sample2[] = "Sphinx of black quartz, judge my vow.";
static const char alnum[] = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789";

static Font sans, mono;
static TTF tt;

/* a phase name with a number on the end */
static const char *numbered(const char *prefix, int n)
{
    static char buf[32];
    char *p = buf;
    while (*prefix)
        *p++ = *prefix++;
    if (n >= 10)
        *p++ = '0' + n / 10;
    *p++ = '0' + n % 10;
    *p = 0;
    return buf;
}

static void scene_text(Surface *s)
{
    static unsigned gbuf[16384 / 4];
    static Font big[3];
    static const int sizes[3] = { 12, 24, 48 };
    unsigned char ramp[65];
    Glyph g;
    int i, k, n, y, aa;

    font_bitmap(&sans, font_sans12);
    font_bitmap(&mono, font_mono12);
    ttf_open(&tt, ttf_sans);
    theme_ramp(s->depth, c_text, c_window, ramp);
    gfx_fill(s, 0, 0, SCREEN_W, SCREEN_H, c_window, GFX_COPY);
    mark("_");

    /* a paragraph in the proportional bitmap font */
    for (i = n = 0, y = 4 + sans.ascent; i < 8; i++, y += sans.height) {
        font_draw(s, &sans, 8, y, para[i], c_text, 0);
        n += strlen(para[i]);
    }
    mark_n("text.sans12", n);

    /* a terminal: the text on black, a line cleared before it's drawn */
    for (i = n = 0, y = 130; i < 12; i++, y += mono.height) {
        gfx_fill(s, 4, y, 4 + 80 * 7, y + mono.height, c_black, GFX_COPY);
        font_draw(s, &mono, 4, y + mono.ascent, term[i], c_white, 0);
        n += strlen(term[i]);
    }
    mark_n("text.mono12", n);

    /* outline glyphs, rasterised and thrown away: what the cache saves */
    for (aa = 0; aa < 2; aa++)
        for (k = 0; k < 3; k++) {
            for (i = 0; alnum[i]; i++)
                ttf_render(&tt, ttf_glyph_index(&tt, alnum[i]), sizes[k], aa,
                           (unsigned char *)gbuf, sizeof gbuf, &g);
            mark_n(numbered(aa ? "raster.aa." : "raster.mono.", sizes[k]), 62);
        }

    /* outline text through the cache: anti-aliased where there are greys */
    aa = s->depth > 0;
    for (k = 0, y = 330; k < 3; k++) {
        font_ttf(&big[k], &tt, sizes[k], aa);
        y += big[k].ascent;
        n = strlen(sample);
        font_draw(s, &big[k], 8, y, sample, c_text, ramp);
        mark_n(numbered("ttf.first.", sizes[k]), n);
        font_draw(s, &big[k], 8, y, sample, c_text, ramp);
        mark_n(numbered("ttf.cached.", sizes[k]), n);
        y += big[k].descent;
    }
    font_draw(s, &big[0], 360, 330 + big[0].ascent, sample2, c_text, ramp);
    mark("_");
}

/* ---- the window manager ---- */

#define TL 16                           /* terminal lines */

typedef struct {
    char line[TL][81];
    int top;                            /* the ring's first line */
} Term;

static Term term_buf;
static Font doc;
static unsigned char doc_ramp[65];

static void term_print(Term *t, const char *str)
{
    char *p = t->line[t->top];
    int n = 0;
    while (str[n] && n < 80) {
        p[n] = str[n];
        n++;
    }
    p[n] = 0;
    t->top = (t->top + 1) % TL;
}

static void paint_term(Window *w, Surface *s, const Rect *c)
{
    Term *t = w->data;
    int i, y;
    gfx_fill(s, s->cx0, s->cy0, s->cx1, s->cy1, c_black, GFX_COPY);
    for (i = 0, y = c->y0 + 3; i < TL; i++, y += mono.height)
        if (y < s->cy1 && y + mono.height > s->cy0)
            font_draw(s, &mono, c->x0 + 4, y + mono.ascent, t->line[(t->top + i) % TL], c_white, 0);
}

static const char *const doc_text[] = {
    "Heron is a minicomputer built from",
    "7400-series logic. Its screen is a",
    "plain bitmap in memory, at 1, 2, 4",
    "or 8 bits per pixel, and everything",
    "on it is drawn by the CPU: the fills",
    "and copies, the lines and curves,",
    "and this text, from a TrueType font",
    "rasterised on the machine itself and",
    "kept in a cache, one bitmap per",
    "character and size.",
    "",
    "Windows are drawn through their",
    "visible regions; nothing is kept",
    "off the screen.",
};

static void paint_doc(Window *w, Surface *s, const Rect *c)
{
    int i, y;
    gfx_fill(s, s->cx0, s->cy0, s->cx1, s->cy1, c_window, GFX_COPY);
    for (i = 0, y = c->y0 + 4; i < 14; i++, y += doc.height + 1)
        if (y < s->cy1 && y + doc.height > s->cy0)
            font_draw(s, &doc, c->x0 + 6, y + doc.ascent, doc_text[i], c_text, doc_ramp);
}

static void paint_drawing(Window *w, Surface *s, const Rect *c)
{
    static const int star5[10] = { 0, -40, 23, 32, -38, -12, 38, -12, -23, 32 };
    unsigned pat[8];
    int i, xy[10], x = c->x0, y = c->y0;
    gfx_fill(s, s->cx0, s->cy0, s->cx1, s->cy1, c_window, GFX_COPY);
    for (i = 0; i < 8; i++)
        pat[i] = gfx_pat(s->depth, i & 1 ? c_accent : c_window) & (i & 2 ? 0x0F0F0F0F : ~0u);
    gfx_fill_pat(s, x + 10, y + 120, x + 110, y + 170, pat, GFX_COPY);
    for (i = 0; i <= 12; i++)
        gfx_line(s, x + 10, y + 10, x + 250, y + 10 + i * 12, s->depth < 2 ? c_text : 1 + i % 14, GFX_COPY);
    for (i = 0; i < 5; i++)
        xy[2 * i] = x + 190 + star5[2 * i], xy[2 * i + 1] = y + 130 + star5[2 * i + 1];
    gfx_poly(s, xy, 5, c_accent, GFX_COPY, GFX_NONZERO);
    gfx_ellipse(s, x + 60, y + 70, 40, 25, c_text, GFX_COPY);
    gfx_fill_ellipse(s, x + 60, y + 70, 20, 12, c_shadow, GFX_COPY);
}

/* sin of 0, 6, ..., 90 degrees, times 1000 */
static const short sin6[16] = { 0, 105, 208, 309, 407, 500, 588, 669, 743, 809, 866, 914, 951,
                                978, 995, 1000 };

static void hand(int k, int len, int *dx, int *dy)     /* k: minutes, 0 at the top */
{
    int q = k / 15 % 4, r = k % 15, sn, cs;
    sn = sin6[r];
    cs = sin6[15 - r];
    switch (q) {
    case 0: *dx = sn; *dy = -cs; break;
    case 1: *dx = cs; *dy = sn; break;
    case 2: *dx = -sn; *dy = cs; break;
    default: *dx = -cs; *dy = -sn; break;
    }
    *dx = *dx * len / 1000;
    *dy = *dy * len / 1000;
}

static void paint_clock(Window *w, Surface *s, const Rect *c)
{
    int cx = (c->x0 + c->x1) / 2, cy = (c->y0 + c->y1) / 2, k, dx, dy, ex, ey;
    gfx_fill(s, s->cx0, s->cy0, s->cx1, s->cy1, c_window, GFX_COPY);
    gfx_ellipse(s, cx, cy, 56, 56, c_frame, GFX_COPY);
    for (k = 0; k < 60; k += 5) {
        hand(k, 54, &dx, &dy);
        hand(k, k % 15 ? 48 : 44, &ex, &ey);
        gfx_line(s, cx + ex, cy + ey, cx + dx, cy + dy, c_frame, GFX_COPY);
    }
    hand(51, 30, &dx, &dy);                 /* ten past ten */
    gfx_line(s, cx, cy, cx + dx, cy + dy, c_text, GFX_COPY);
    gfx_line(s, cx + 1, cy, cx + dx + 1, cy + dy, c_text, GFX_COPY);
    hand(10, 46, &dx, &dy);
    gfx_line(s, cx, cy, cx + dx, cy + dy, c_text, GFX_COPY);
    hand(36, 50, &dx, &dy);
    gfx_line(s, cx, cy, cx + dx, cy + dy, c_accent, GFX_COPY);
    gfx_fill_ellipse(s, cx, cy, 3, 3, c_accent, GFX_COPY);
}

static void scene_wm(Surface *s)
{
    Window *wt, *wd, *wdr, *wc;
    Rect r;
    int i, cx = 300, cy = 220;
    char line[64];

    font_bitmap(&sans, font_sans12);
    font_bitmap(&mono, font_mono12);
    ttf_open(&tt, ttf_sans);
    font_ttf(&doc, &tt, 13, s->depth > 0);
    theme_ramp(s->depth, c_text, c_window, doc_ramp);
    for (i = 0; i < TL; i++)
        term_print(&term_buf, i < TL - 4 ? term[i % 12] : "");
    wm_init(s, &sans);
    wt = wm_open(100, 24, 100 + 570, 24 + TL * 15 + 6 + TITLE_H + 3, "Terminal", paint_term, &term_buf);
    wd = wm_open(330, 170, 610, 430, "Readme", paint_doc, 0);
    wdr = wm_open(70, 220, 340, 460, "Drawing", paint_drawing, 0);
    wc = wm_open(470, 10, 600, 160, "Clock", paint_clock, 0);
    wt->frame.x1 = 100 + 570 > SCREEN_W ? SCREEN_W - 10 : wt->frame.x1;
    wt->frame.x0 = wt->frame.x1 - 570;
    mark("_");

    for (i = 32; i < 127; i++)
        font_glyph(&doc, i);
    mark_n("wm.glyphs", 95);

    wm_paint_all();
    cursor_show(cx, cy);
    mark("wm.paint");

    cursor_hide();
    wm_raise(wd);
    cursor_show(cx, cy);
    mark("wm.raise");

    for (i = 0; i < 8; i++) {               /* drag the top window */
        cursor_hide();
        wm_move(wd, -12, -9);
        cx -= 12;
        cy -= 9;
        cursor_show(cx, cy);
    }
    mark_n("wm.move", 8);

    r = wd->frame;                          /* dragging an outline instead */
    cursor_hide();
    wm_outline(&r);
    for (i = 0; i < 8; i++) {
        wm_outline(&r);
        r.x0 += 12; r.x1 += 12; r.y0 += 9; r.y1 += 9;
        wm_outline(&r);
    }
    wm_outline(&r);
    cursor_show(cx, cy);
    mark_n("wm.outline", 8);

    for (i = 0; i < 4; i++) {               /* the terminal scrolls, partly covered */
        cursor_hide();
        strcpy(line, "$ echo scrolled under the other windows: 0");
        line[strlen(line) - 1] = '0' + i;
        term_print(&term_buf, line);
        wm_scroll(wt, 15);
        cursor_show(cx, cy);
    }
    mark_n("wm.scroll.covered", 4);

    cursor_hide();
    wm_raise(wt);
    cursor_show(cx, cy);
    mark("wm.raise.term");

    for (i = 0; i < 4; i++) {               /* and on top */
        cursor_hide();
        strcpy(line, "$ echo scrolled on top: 0");
        line[strlen(line) - 1] = '0' + i;
        term_print(&term_buf, line);
        wm_scroll(wt, 15);
        cursor_show(cx, cy);
    }
    mark_n("wm.scroll", 4);

    for (i = 0; i < 20; i++) {
        cx += 13;
        cy += 7;
        cursor_move(cx, cy);
    }
    mark_n("wm.cursor", 20);

    cursor_hide();
    wm_close(wt);
    cursor_show(cx, cy);
    mark("wm.close");

    cursor_hide();
    wm_paint_all();
    cursor_show(cx, cy);
    mark("wm.repaint");
    (void)wdr;
    (void)wc;
}

int run_scene(const char *name, int depth)
{
    gfx_tables();
    gfx_init(&screen, fb_mem, SCREEN_W, SCREEN_H, (SCREEN_W << depth) >> 3, depth);
    theme_init(depth);
    if (strcmp(name, "prims") == 0)
        scene_prims(&screen);
    else if (strcmp(name, "text") == 0)
        scene_text(&screen);
    else if (strcmp(name, "wm") == 0)
        scene_wm(&screen);
    else
        return -1;
    return 0;
}
