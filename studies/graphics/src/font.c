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

/* Glyphs entirely inside the clip rectangle, which is most of them, go
   straight to the kernel, with the job's constant parts set once per
   string; the others through gfx_expand, which clips. */
int font_draw(Surface *s, Font *f, int x, int y, const char *str, unsigned fg,
              const unsigned char *ramp)
{
    ExpandJob j;
    RampJob rj;
    Glyph *g;
    Surface gs;
    unsigned char *row = s->bits + y * s->pitch;
    int c, d = s->depth, gx, gy, bit, lead, last;
    rj.dpitch = s->pitch;
    rj.ramp = ramp;
    rj.depth = d;
    j.dpitch = s->pitch;
    j.spitch = f->strike.pitch;
    j.fg = gfx_pat(d, fg);
    j.bg = 0;
    j.opaque = 0;
    j.depth = d;
    j.slast = 0;
    while ((c = (unsigned char)*str++) != 0) {
        g = f->get(f, c);
        gx = x + g->xoff;
        gy = y + g->yoff;
        x += g->adv;
        if (!g->w)
            continue;
        if (f->aa) {
            if (gx >= s->cx0 && gy >= s->cy0 && gx + g->w <= s->cx1 && gy + g->h <= s->cy1) {
                bit = gx << d;
                rj.d = (unsigned *)(row + g->yoff * s->pitch) + (bit >> 5);
                rj.lead = (bit & 31) >> d;
                rj.n = (((bit & 31) + (g->w << d) - 1) >> 5);
                rj.c = g->bits;
                rj.cpitch = g->w;
                rj.w = g->w;
                rj.h = g->h;
                ramp_rows(&rj);
            } else {
                gfx_ramp(s, gx, gy, g->bits, g->w, g->w, g->h, ramp);
            }
            continue;
        }
        if (gx >= s->cx0 && gy >= s->cy0 && gx + g->w <= s->cx1 && gy + g->h <= s->cy1 && g->w <= 32) {
            bit = gx << d;
            lead = (bit & 31) >> d;
            last = lead + g->w - 1;
            j.d = (unsigned *)(row + g->yoff * s->pitch) + (bit >> 5);
            if (f->ttf) {
                j.s = (const unsigned *)g->bits;
                j.spitch = 4;
            } else {
                j.s = (const unsigned *)f->strike.bits + (g->sx >> 5);
            }
            j.h = g->h;
            j.soff = -lead;
            j.nch = (last >> 5) + 1;
            j.cfirst = ~0u << lead;
            j.clast = ~0u >> (31 - (last & 31));
            if (j.nch == 1)
                j.cfirst &= j.clast;
            expand_rows(&j);
        } else if (f->ttf) {
            gfx_init(&gs, g->bits, g->w, g->h, ((g->w + 31) >> 5) << 2, 0);
            gfx_expand(s, gx, gy, &gs, 0, 0, g->w, g->h, fg, 0, 0);
        } else {
            gfx_expand(s, gx, gy, &f->strike, g->sx, 0, g->w, g->h, fg, 0, 0);
        }
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
