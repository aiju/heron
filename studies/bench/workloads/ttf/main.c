/* TrueType text as Heron's desktop draws it: the graphics library's
   rasteriser (ttf.c, raster.c), with a glyph cache and kerning (text.c),
   into a window of 8-bit grey pixels.

   1. Glyphs rasterised and thrown away, at 12, 16, 24 and 48 pixels,
      anti-aliased and plain: what a miss in the glyph cache costs.
   2. A window with a document in it: a title bar in plain text, and
      paragraphs anti-aliased, broken into lines by their kerned widths.
      Laying it out rasterises every glyph it uses; later they come from
      the cache.
   3. The document scrolled, a few lines at a time, and the window drawn
      whole each time, as a text view without a backing store does.

   The parameters: RASTER glyphs in part 1; PARAS paragraphs of the document; SCROLLS redraws in part 3,
   by STEP lines each; the window is WIN_W x WIN_H. */

#include <string.h>
#include "bench.h"
#include "gfx.h"

extern const unsigned char font[];
extern unsigned font_len;

#define PITCH WIN_W                     /* 8-bit pixels; WIN_W a multiple of 4 */

static unsigned window_bits[WIN_H * PITCH / 4];
static Surface win;
static TTF tt;

/* the pixels are greys, 0 black to 255 white */
#define C_INK 16
#define C_PAPER 255
#define C_FRAME 0
#define C_TITLE 96
#define C_TITLE_TEXT 240

/* ---- 1. rasterising ---- */

static const char alnum[] =
    "aAbBcCdDeEfFgGhHiIjJkKlLmMnNoOpPqQrRsStTuUvVwWxXyYzZ0123456789&@?%";

/* RASTER glyphs, going round the sizes, anti-aliased and then plain */
static unsigned raster_all(void)
{
    static const int sizes[4] = { 12, 16, 24, 48 };
    static unsigned gbuf[16384 / 4];
    unsigned h = BENCH_HASH0;
    int i, n, c;
    Glyph g;
    for (i = 0; i < RASTER; i++) {
        c = alnum[(5 * i) % (sizeof alnum - 1)];
        n = ttf_render(&tt, ttf_glyph_index(&tt, c), sizes[i & 3], !(i & 4),
                       (unsigned char *)gbuf, sizeof gbuf, &g);
        if (n > 0)
            h = bench_hash(h, gbuf, n);
        h = bench_hash(h, &g, 8);               /* its box and advances */
    }
    return h;
}

/* ---- 2 and 3. a document in a window ---- */

static const char title[] = "Log";

/* paragraphs, each one string; the window breaks them into lines */
static const char *const doc[] = {
    "The grey heron is a long-legged wading bird of the heron family, native "
    "throughout temperate Europe and Asia and also parts of Africa. A bird of "
    "wetland areas, it can be seen round lakes, rivers, ponds, marshes and on "
    "the sea coast, standing still in the shallows: \"Two!\" said the warden at "
    "Avonmouth. \"Today, Tuesday, we counted 47 nests; yesterday, 45.\"",
    "WAVE, YAWL, TOYS, AVOWAL: the pairs a font kerns are mostly capitals "
    "against capitals and punctuation, and a few like \"Te\", \"Yo\" and \"Wa\" "
    "in running text. Without kerning, \"AV\" leaves a gap that a reader sees "
    "at once; with it, the pen moves back a little before the next glyph.",
    "Every glyph here was decoded from the font's outlines, its curves flattened "
    "into lines, the lines scan-converted at four samples a pixel down and "
    "sixteen across, and the coverage drawn through a ramp of greys. The second "
    "time a glyph is needed it comes from the cache, and only the drawing is "
    "left to do.",
};
#define NDOC (sizeof doc / sizeof doc[0])

/* the window's lines: a run of a paragraph, or a blank between them */
typedef struct {
    short para, start, len;
} Line;

#define MAXLINES 100
static Line lines[MAXLINES];
static int nlines;

static Font f_title, f_body;
static unsigned char ramp[65];

/* the title bar and the text area inside the frame */
#define TITLE_H 18
#define TEXT_X0 8
#define TEXT_X1 (WIN_W - 8)
#define TEXT_Y0 (TITLE_H + 4)
#define TEXT_Y1 (WIN_H - 4)

/* Break the paragraphs into lines no wider than the text area, at spaces,
   measuring each word as it will be drawn: kerned, and with the space
   before it. */
static void layout(void)
{
    int p, width = TEXT_X1 - TEXT_X0, space = font_width(&f_body, " ", 1);
    nlines = 0;
    for (p = 0; p < PARAS && p < NDOC && nlines < MAXLINES - 1; p++) {
        const char *s = doc[p];
        int n = strlen(s), start = 0, at = 0, w = 0;
        while (start < n && nlines < MAXLINES - 1) {
            /* the next word, from at */
            int e = at, ww;
            while (e < n && s[e] != ' ')
                e++;
            ww = font_width(&f_body, s + at, e - at);
            if (at > start && w + space + ww > width) {
                /* it doesn't fit: the line ends before its space */
                lines[nlines].para = p;
                lines[nlines].start = start;
                lines[nlines].len = at - 1 - start;
                nlines++;
                start = at;
                w = 0;
            }
            w += (at > start ? space : 0) + ww;
            at = e + 1;
            if (e >= n) {
                lines[nlines].para = p;
                lines[nlines].start = start;
                lines[nlines].len = n - start;
                nlines++;
                start = n;
            }
        }
        lines[nlines].para = -1;        /* a blank line after each paragraph */
        nlines++;
    }
}

/* The window, with the document scrolled to line `top`: the frame, the
   title bar, and the lines that show, clipped to the text area. Returns
   a checksum of where each string's pen ended. */
static unsigned draw_window(int top)
{
    int y, k, x;
    unsigned sum;
    gfx_noclip(&win);
    gfx_fill(&win, 0, 0, WIN_W, WIN_H, C_FRAME, GFX_COPY);
    gfx_fill(&win, 1, 1, WIN_W - 1, TITLE_H, C_TITLE, GFX_COPY);
    x = (WIN_W - font_width(&f_title, title, sizeof title - 1)) / 2;
    sum = font_draw(&win, &f_title, x, 4 + f_title.ascent, title, sizeof title - 1,
                    C_TITLE_TEXT, 0);
    gfx_fill(&win, 1, TITLE_H, WIN_W - 1, WIN_H - 1, C_PAPER, GFX_COPY);

    gfx_clip(&win, TEXT_X0, TEXT_Y0, TEXT_X1, TEXT_Y1);
    y = TEXT_Y0 + 2 - (top % (nlines + 1)) * f_body.height;
    for (k = 0; k < nlines && y < TEXT_Y1; k++, y += f_body.height) {
        const Line *l = &lines[k];
        if (l->para < 0 || y + f_body.height <= TEXT_Y0)
            continue;
        sum = sum * 31 + font_draw(&win, &f_body, TEXT_X0, y + f_body.ascent,
                                   doc[l->para] + l->start, l->len, C_INK, ramp);
    }
    return sum;
}

/* The window's pixels, a word at a time (bench_hash's bytes would take
   longer than drawing them) */
static unsigned window_hash(void)
{
    const unsigned *p = window_bits;
    unsigned h = BENCH_HASH0;
    int n;
    for (n = WIN_H * PITCH / 4; n > 0; n--)
        h = ((h << 5) + h) ^ *p++;
    return h;
}

int main(void)
{
    unsigned h;
    int k;
    gfx_tables();
    cache_init();
    if (ttf_open(&tt, font) < 0) {
        bench_report("badfont", font_len);
        return 1;
    }
    bench_report("raster", raster_all());

    gfx_init(&win, window_bits, WIN_W, WIN_H, PITCH, 3);
    for (k = 0; k <= 64; k++)
        ramp[k] = (C_PAPER * (64 - k) + C_INK * k + 32) >> 6;
    font_open(&f_title, &tt, 12, 0);
    font_open(&f_body, &tt, 12, 1);
    layout();
    h = BENCH_HASH0;
    for (k = 0; k < nlines; k++)
        h = h * 31 + (lines[k].start << 8) + lines[k].len;
    bench_report("lines", nlines);
    bench_report("layout", h);
    h = draw_window(0);
    bench_report("window", window_hash());
    bench_report("misses", cache_misses);
    for (k = 1; k <= SCROLLS; k++)
        h = h * 31 + draw_window(k * STEP);
    bench_report("scrolled", window_hash());
    bench_report("pens", h);
    bench_report("hits", cache_hits);
    bench_report("cached", cache_bytes);
    return 0;
}
