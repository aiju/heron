/* gfx_desktop's reference: the session's effect on the windows replayed,
 * then the final desktop drawn a pixel at a time in painter's order (the
 * background, the windows from back to front, the cursor), with none of
 * the machine's clipping lists, copies or tables. The machine redraws
 * incrementally; its screen must end up exactly this one.
 *
 * workload.py has the session's format; the drawing rules are the
 * machine's (wm.s). */

#include "bench.h"
#ifdef DUMP_FB
#include <stdio.h>
#endif

extern const unsigned char font_mono[], font_sans[], corpus[], session[], cursor_art[];
extern unsigned corpus_len;

#define PITCH 320               /* bytes a row: 640 pixels */
#define MAXWIN 8
#define MAXLINES 256
#define EDIT_MAX 40
#define TITLE_H 18
#define LINE_H 15
#define CELL_W 7

static unsigned char fb[PITCH * 480];

static void pset(int x, int y, int c)
{
    unsigned char *p = &fb[y * PITCH + (x >> 1)];
    if (x & 1)
        *p = (*p & 0x0F) | (c << 4);
    else
        *p = (*p & 0xF0) | c;
}

static int pget(int x, int y)
{
    return (fb[y * PITCH + (x >> 1)] >> ((x & 1) * 4)) & 15;
}

static int h16(const unsigned char *p)
{
    int v = p[0] | p[1] << 8;
    return v >= 0x8000 ? v - 0x10000 : v;
}

typedef struct { int x0, y0, x1, y1; } Rect;

static int inside(const Rect *r, int x, int y)
{
    return x >= r->x0 && x < r->x1 && y >= r->y0 && y < r->y1;
}

/* ---- fonts (studies/graphics/fonts.py's bitmap format) ---- */

typedef struct { int w, h, adv, xo, yo; const unsigned char *rows; int stride; } Glyph;

static int ascent(const unsigned char *f) { return f[2]; }

static Glyph glyph(const unsigned char *f, int ch)
{
    Glyph g = {0, 0, 0, 0, 0, 0, 0};
    int first = f[0], count = f[1], sw = f[4] | f[5] << 8;
    if (ch < first || ch >= first + count)
        return g;
    const unsigned char *e = f + 8 + 8 * (ch - first);
    g.w = e[0];
    g.h = e[1];
    g.adv = e[2];
    g.xo = (signed char)e[3];
    g.yo = (signed char)e[4];
    g.stride = 4 * sw;
    g.rows = f + 8 + 8 * count + 4 * (e[6] | e[7] << 8);
    return g;
}

static int gbit(const Glyph *g, int gx, int gy)
{
    if (gx < 0 || gx >= g->w || gy < 0 || gy >= g->h)
        return 0;
    const unsigned char *r = g->rows + gy * g->stride;
    unsigned v = r[0] | r[1] << 8 | r[2] << 16 | (unsigned)r[3] << 24;
    return (v >> gx) & 1;
}

/* transparent text: the glyphs' pixels in fg, clipped to c */
static void text(const Rect *c, int x, int base, const unsigned char *s, int n, int fg)
{
    for (int i = 0; i < n; i++) {
        Glyph g = glyph(font_sans, s[i]);
        for (int gy = 0; gy < g.h; gy++)
            for (int gx = 0; gx < g.w; gx++) {
                int px = x + g.xo + gx, py = base + g.yo + gy;
                if (gbit(&g, gx, gy) && inside(c, px, py))
                    pset(px, py, fg);
            }
        x += g.adv;
    }
}

/* an opaque character cell of mono12: 7 x 15 pixels from (x, top), fg
   where the glyph has a pixel and bg elsewhere; the glyph's pixels
   outside the cell aren't drawn */
static void cell(const Rect *c, int x, int top, int ch, int fg, int bg)
{
    Glyph g = glyph(font_mono, ch);
    int base = top + ascent(font_mono);
    for (int j = 0; j < LINE_H; j++)
        for (int i = 0; i < CELL_W; i++) {
            int on = gbit(&g, i - g.xo, top + j - base - g.yo);
            if (inside(c, x + i, top + j))
                pset(x + i, top + j, on ? fg : bg);
        }
}

static void fill(const Rect *c, int x0, int y0, int x1, int y1, int col)
{
    for (int y = y0; y < y1; y++)
        for (int x = x0; x < x1; x++)
            if (inside(c, x, y))
                pset(x, y, col);
}

/* ---- the corpus ---- */

static const unsigned char *line_at[MAXLINES];
static int line_len[MAXLINES], nlines;

static void split_corpus(void)
{
    const unsigned char *p = corpus, *end = corpus + corpus_len;
    while (p < end) {
        const unsigned char *q = p;
        while (q < end && *q != '\n')
            q++;
        line_at[nlines] = p;
        line_len[nlines++] = q - p;
        p = q + 1;
    }
}

/* ---- the windows ---- */

typedef struct {
    int x, y, w, h, kind, tcol, ccol, fg, first, edit, cols, rows;
    const unsigned char *title;
    int scrolled;
    unsigned char text[EDIT_MAX];
    int ntext;
    Rect sel;
} Win;

static Win win[MAXWIN];
static int nwin, order[MAXWIN];

static void draw_window(Win *w)
{
    Rect scr = {0, 0, SW, SH};
    Rect bar = {w->x + 1, w->y + 1, w->x + w->w - 1, w->y + TITLE_H - 1};
    Rect cl = {w->x + 1, w->y + TITLE_H, w->x + w->w - 1, w->y + w->h - 1};
    int x1 = w->x + w->w, y1 = w->y + w->h;

    /* the frame, the title bar and its line, the client area */
    fill(&scr, w->x, w->y, x1, w->y + 1, 0);
    fill(&scr, w->x, y1 - 1, x1, y1, 0);
    fill(&scr, w->x, w->y, w->x + 1, y1, 0);
    fill(&scr, x1 - 1, w->y, x1, y1, 0);
    fill(&scr, bar.x0, bar.y0, bar.x1, bar.y1, w->tcol);
    fill(&scr, bar.x0, bar.y1, bar.x1, bar.y1 + 1, 0);
    int n = 0;
    while (w->title[n])
        n++;
    text(&bar, w->x + 6, w->y + 13, w->title, n, 15);
    fill(&scr, cl.x0, cl.y0, cl.x1, cl.y1, w->ccol);

    if (w->kind == 0) {
        /* a terminal: rows of cells, each its line padded with spaces */
        for (int r = 0; r < w->rows; r++) {
            int k = (w->first + w->scrolled + r) % nlines;
            for (int col = 0; col < w->cols; col++) {
                int ch = col < line_len[k] ? line_at[k][col] : ' ';
                cell(&cl, cl.x0 + 2 + CELL_W * col, cl.y0 + 1 + LINE_H * r, ch, w->fg, w->ccol);
            }
        }
    } else {
        /* a document: lines while they start inside, the edit line its
           own text; then the selection inverted */
        for (int i = 0; cl.y0 + 2 + LINE_H * i < cl.y1; i++) {
            int base = cl.y0 + 2 + ascent(font_sans) + LINE_H * i;
            if (i == w->edit) {
                text(&cl, cl.x0 + 4, base, w->text, w->ntext, w->fg);
            } else {
                int k = (w->first + i) % nlines;
                text(&cl, cl.x0 + 4, base, line_at[k], line_len[k], w->fg);
            }
        }
        for (int y = w->sel.y0; y < w->sel.y1; y++)
            for (int x = w->sel.x0; x < w->sel.x1; x++)
                if (inside(&cl, cl.x0 + x, cl.y0 + y))
                    pset(cl.x0 + x, cl.y0 + y, pget(cl.x0 + x, cl.y0 + y) ^ 15);
    }
}

int main(void)
{
    const unsigned char *s = session;
    nwin = h16(s);
    int nops = h16(s + 2), cx = h16(s + 4), cy = h16(s + 6);
    split_corpus();
    for (int i = 0; i < nwin; i++) {
        const unsigned char *r = s + 16 + 48 * i;
        Win *w = &win[i];
        w->x = h16(r);
        w->y = h16(r + 2);
        w->w = h16(r + 4);
        w->h = h16(r + 6);
        w->kind = h16(r + 8);
        w->tcol = h16(r + 10);
        w->ccol = h16(r + 12);
        w->fg = h16(r + 14);
        w->first = h16(r + 16);
        w->edit = h16(r + 18);
        w->cols = h16(r + 20);
        w->rows = h16(r + 22);
        w->title = r + 24;
        order[i] = i;
    }

    /* the session's effect */
    const unsigned char *op = s + 16 + 48 * nwin;
    for (int k = 0; k < nops; k++, op += 12) {
        int code = h16(op), wi = h16(op + 2);
        int a = h16(op + 4), b = h16(op + 6), c = h16(op + 8), d = h16(op + 10);
        Win *w = &win[wi];
        switch (code) {
        case 1:                 /* the cursor */
            cx = a;
            cy = b;
            break;
        case 2:                 /* move */
            w->x += a;
            w->y += b;
            break;
        case 3:                 /* scroll */
            w->scrolled++;
            break;
        case 4: {               /* raise */
            int j = 0;
            while (order[j] != wi)
                j++;
            for (; j < nwin - 1; j++)
                order[j] = order[j + 1];
            order[nwin - 1] = wi;
            break;
        }
        case 5:                 /* type */
            if (w->ntext < EDIT_MAX)
                w->text[w->ntext++] = a;
            break;
        case 6:                 /* select */
            w->sel.x0 = a;
            w->sel.y0 = b;
            w->sel.x1 = c;
            w->sel.y1 = d;
            break;
        }
    }

    /* the final desktop: the background, two rows of patterns */
    static const unsigned pat[2] = {0x36363636u, 0x63636363u};
    for (int y = 0; y < SH; y++)
        for (int x = 0; x < SW; x++)
            pset(x, y, (pat[y & 1] >> (4 * (x & 7))) & 15);
    for (int i = 0; i < nwin; i++)
        draw_window(&win[order[i]]);

    /* the cursor: 16 rows of image and mask, a nibble a pixel */
    for (int y = 0; y < 16; y++) {
        const unsigned char *r = cursor_art + 16 * y;
        for (int x = 0; x < 16; x++) {
            int byte = x >> 1, sh = (x & 1) * 4;
            if ((r[8 + byte] >> sh) & 15)
                pset(cx + x, cy + y, (r[byte] >> sh) & 15);
        }
    }

    /* the checksums: the screen's words, their sum and sum of sums */
    unsigned s1 = 0, s2 = 0;
    for (int y = 0; y < SH; y++)
        for (int x = 0; x < SW / 2; x += 4) {
            const unsigned char *p = &fb[y * PITCH + x];
            s1 += p[0] | p[1] << 8 | p[2] << 16 | (unsigned)p[3] << 24;
            s2 += s1;
        }
    bench_report("screen_sum", s1);
    bench_report("screen_fletcher", s2);
#ifdef DUMP_FB
    /* for debugging: the framebuffer, to compare with the machine's */
    FILE *f = fopen(DUMP_FB, "wb");
    fwrite(fb, 1, sizeof fb, f);
    fclose(f);
#endif
    return 0;
}
