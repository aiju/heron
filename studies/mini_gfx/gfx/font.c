/* Fonts (gfx.h): the graphics study's bitmap fonts, glyphs expanded from
   their strike, and a cell font of 8 x 16 whose rows of text are put
   together as 1-bit rows first and expanded a row at a time. */

#include <stdlib.h>
#include <string.h>
#include "gfx.h"

static Font fonts[3];
Font *font_sans, *font_mono, *font_cell;

/* the graphics study's layout (studies/graphics/fonts.py) */
static void font_bitmap(Font *f, const unsigned char *d)
{
    const unsigned char *g;
    int i, words = d[4] | d[5] << 8;
    memset(f, 0, sizeof *f);
    f->first = d[0];
    f->count = d[1];
    f->ascent = d[2];
    f->descent = d[3];
    f->height = f->ascent + f->descent;
    f->glyphs = malloc(f->count * sizeof(Glyph));
    for (i = 0; i < f->count; i++) {
        g = d + 8 + 8 * i;
        f->glyphs[i].w = g[0];
        f->glyphs[i].h = g[1];
        f->glyphs[i].adv = g[2];
        f->glyphs[i].xoff = (signed char)g[3];
        f->glyphs[i].yoff = (signed char)g[4];
        f->glyphs[i].sx = (g[6] | g[7] << 8) * 32;
    }
    f->strike.bits = (const unsigned *)(d + 8 + 8 * f->count);
    f->strike.pitch = words;
}

void font_init(void)
{
    if (font_sans)
        return;
    font_bitmap(&fonts[0], font_sans12);
    font_bitmap(&fonts[1], font_mono12);
    memset(&fonts[2], 0, sizeof fonts[2]);
    fonts[2].first = 32;
    fonts[2].count = 95;
    fonts[2].ascent = 12;
    fonts[2].descent = 4;
    fonts[2].height = 16;
    fonts[2].cell = 1;
    font_sans = &fonts[0];
    font_mono = &fonts[1];
    font_cell = &fonts[2];
}

static const Glyph *glyph(const Font *f, int c)
{
    if (c < f->first || c >= f->first + f->count)
        c = '?';
    return &f->glyphs[c - f->first];
}

int font_widthn(const Font *f, const char *s, int n)
{
    int w = 0;
    if (f->cell)
        return 8 * n;
    while (n-- > 0 && *s)
        w += glyph(f, (unsigned char)*s++)->adv;
    return w;
}

int font_width(const Font *f, const char *s)
{
    return font_widthn(f, s, strlen(s));
}

/* a glyph's rows (each at most 32 pixels, starting on a word of the
   strike) ORed into a 1-bit buffer from bit `bit` of word dst on */
void text_or_c(unsigned *dst, int dpitch, const unsigned *src, int spitch, int bit, int rows)
{
    while (rows-- > 0) {
        unsigned w = *src;
        dst[0] |= w << bit;
        if (bit)
            dst[1] |= w >> (32 - bit);
        dst += dpitch;
        src += spitch;
    }
}

#ifdef GFX_ASM
void text_or_asm(unsigned *dst, int dpitch, const unsigned *src, int spitch, int bit, int rows);
#define text_or text_or_asm
#else
#define text_or text_or_c
#endif

/* A proportional string: its glyphs ORed into a 1-bit buffer as wide as
   the string and as tall as the font, then the buffer expanded onto the
   surface in one go (opaque: the box in bg). One expansion of the whole
   string costs much less than one a glyph: each has a row's set-up. */
int font_drawn(Surface *s, const Font *f, int x, int y, const char *str, int n, unsigned fg,
               int bg)
{
    static unsigned buf[20 * 66];
    const Glyph *g;
    Bitmap bm;
    int pen = 0, k, x0 = 0, x1 = 0, pitch, h = f->ascent + f->descent;
    if (f->cell) {
        font_cells(s, x, y - 12, str, n, fg, bg);
        return x + 8 * n;
    }
    /* the box: where the glyphs reach, left and right of the pens */
    for (k = 0; k < n && str[k]; k++) {
        g = glyph(f, (unsigned char)str[k]);
        if (g->w && pen + g->xoff < x0)
            x0 = pen + g->xoff;
        if (g->w && pen + g->xoff + g->w > x1)
            x1 = pen + g->xoff + g->w;
        pen += g->adv;
    }
    n = k;
    if (pen > x1)
        x1 = pen;
    if (x1 - x0 > 2048 || h > 20) {
        /* too big for the buffer: a glyph at a time */
        pen = x;
        if (bg >= 0)
            gfx_fill(s, x, y - f->ascent, x + font_widthn(f, str, n), y + f->descent, bg,
                     ROP_COPY);
        for (k = 0; k < n; k++) {
            g = glyph(f, (unsigned char)str[k]);
            if (g->w)
                gfx_expand(s, pen + g->xoff, y + g->yoff, &f->strike, g->sx, 0, g->w, g->h, fg,
                           0, 0);
            pen += g->adv;
        }
        return pen;
    }
    pitch = ((x1 - x0) >> 5) + 2;
    memset(buf, 0, 4 * pitch * h);
    pen = -x0;
    for (k = 0; k < n; k++) {
        g = glyph(f, (unsigned char)str[k]);
        if (g->w) {
            int bx = pen + g->xoff, row = f->ascent + g->yoff;
            text_or(buf + row * pitch + (bx >> 5), pitch, f->strike.bits + (g->sx >> 5),
                    f->strike.pitch, bx & 31, g->h);
        }
        pen += g->adv;
    }
    bm.bits = buf;
    bm.pitch = pitch;
    if (bg >= 0)
        gfx_expand(s, x, y - f->ascent, &bm, -x0, 0, pen + x0, h, fg, bg, 1);
    else
        gfx_expand(s, x + x0, y - f->ascent, &bm, 0, 0, x1 - x0, h, fg, 0, 0);
    return x + pen + x0;
}

int font_draw(Surface *s, const Font *f, int x, int y, const char *str, unsigned fg, int bg)
{
    return font_drawn(s, f, x, y, str, strlen(str), fg, bg);
}

/* a cell-font string, its cells' top at y, transparent if bg < 0: the
   string's 16 rows put together as a 1-bit bitmap (a byte a character),
   a glyph's column at a time, and expanded in one call */
void font_cells(Surface *s, int x, int y, const char *str, int n, unsigned fg, int bg)
{
    static unsigned rows[16 * 66];
    unsigned char *b = (unsigned char *)rows;
    Bitmap bm;
    int r, k, pitch, stride, end = 0;
    if (n > 256)
        n = 256;
    pitch = (n + 3) / 4 + 1;
    stride = 4 * pitch;
    for (k = 0; k < n; k++) {
        int c = end ? ' ' : (unsigned char)str[k];
        const unsigned char *g;
        unsigned char *d = b + k;
        if (!c) {
            end = 1;
            c = ' ';
        }
        if (c < 32 || c > 126)
            c = '?';
        g = font_cell8 + 16 * (c - 32);
        for (r = 0; r < 16; r++) {
            *d = *g++;
            d += stride;
        }
    }
    bm.bits = rows;
    bm.pitch = pitch;
    gfx_expand(s, x, y, &bm, 0, 0, 8 * n, 16, fg, bg, bg >= 0);
}
