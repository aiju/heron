/* Fonts: bitmap fonts drawn from their strike, and outline fonts whose
   glyphs are rasterised by ttf.c the first time they're drawn and then
   kept, as 1-bit bitmaps or as coverage for anti-aliasing. Drawing a
   string is one gfx_expand (or gfx_ramp) per character. */

#include <stdlib.h>
#include <string.h>
#include "gfx.h"

static Glyph *bitmap_get(Font *f, int c)
{
    if (c < f->first || c >= f->first + f->count)
        c = '?';
    return &f->glyphs[c - f->first];
}

/* The layout is in fonts.py. */
void font_bitmap(Font *f, const unsigned char *d)
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
        f->glyphs[i].bits = 0;
    }
    gfx_init(&f->strike, (void *)(d + 8 + 8 * f->count), words * 32, d[6], words * 4, 0);
    f->get = bitmap_get;
}

Glyph *font_glyph(Font *f, int c)
{
    return f->get(f, c);
}

int font_width(Font *f, const char *s)
{
    int w = 0;
    while (*s)
        w += f->get(f, (unsigned char)*s++)->adv;
    return w;
}

int font_draw(Surface *s, Font *f, int x, int y, const char *str, unsigned fg,
              const unsigned char *ramp)
{
    Glyph *g;
    Surface gs;
    int c;
    while ((c = (unsigned char)*str++) != 0) {
        g = f->get(f, c);
        if (g->w) {
            if (!f->ttf)
                gfx_expand(s, x + g->xoff, y + g->yoff, &f->strike, g->sx, 0, g->w, g->h, fg, 0, 0);
            else if (f->aa)
                gfx_ramp(s, x + g->xoff, y + g->yoff, g->bits, g->w, g->w, g->h, ramp);
            else {
                gfx_init(&gs, g->bits, g->w, g->h, ((g->w + 31) >> 5) << 2, 0);
                gfx_expand(s, x + g->xoff, y + g->yoff, &gs, 0, 0, g->w, g->h, fg, 0, 0);
            }
        }
        x += g->adv;
    }
    return x;
}

/* ---- outline fonts, with a glyph cache ---- */

#define BUF 16384
static unsigned buf[BUF / 4];

static Glyph *ttf_get(Font *f, int c)
{
    Glyph *g;
    int n;
    if (c < f->first || c >= f->first + f->count)
        c = '?';
    g = &f->glyphs[c - f->first];
    if (!g->pad) {                                  /* not rasterised yet */
        TTF *t = f->ttf;
        n = ttf_render(t, ttf_glyph_index(t, c), f->size, f->aa, (unsigned char *)buf, BUF, g);
        if (n > 0) {
            g->bits = malloc(n);
            memcpy(g->bits, buf, n);
        }
        g->pad = 1;
    }
    return g;
}

void font_ttf(Font *f, TTF *t, int size, int aa)
{
    memset(f, 0, sizeof *f);
    f->first = 32;
    f->count = 95;
    f->ttf = t;
    f->size = size;
    f->aa = aa;
    f->ascent = (t->ascent * size + t->upem / 2) / t->upem;
    f->descent = (-t->descent * size + t->upem / 2) / t->upem;
    f->height = f->ascent + f->descent;
    f->glyphs = calloc(f->count, sizeof(Glyph));
    f->get = ttf_get;
}
