/* Surfaces, rectangles and the fill kernel. Copied from
   studies/graphics/src/gfx.c, trimmed to what text on an 8-bit window
   needs: no pixels, patterns or frames, the fill kernel's COPY and OR
   only, and the expansion table for 8-bit pixels only. */

#include "gfx.h"

void gfx_init(Surface *s, void *bits, int w, int h, int pitch, int depth)
{
    s->bits = bits;
    s->w = w;
    s->h = h;
    s->pitch = pitch;
    s->depth = depth;
    gfx_noclip(s);
}

void gfx_noclip(Surface *s)
{
    s->cx0 = 0;
    s->cy0 = 0;
    s->cx1 = s->w;
    s->cy1 = s->h;
}

void gfx_clip(Surface *s, int x0, int y0, int x1, int y1)
{
    s->cx0 = x0 > 0 ? x0 : 0;
    s->cy0 = y0 > 0 ? y0 : 0;
    s->cx1 = x1 < s->w ? x1 : s->w;
    s->cy1 = y1 < s->h ? y1 : s->h;
}

int gfx_maxcolor(int depth)
{
    return (1 << (1 << depth)) - 1;
}

/* the colour in every pixel of a word */
unsigned gfx_pat(int depth, unsigned c)
{
    switch (depth) {
    case 0: return -(c & 1);
    case 1: c &= 3; c |= c << 2; c |= c << 4; break;
    case 2: c &= 15; c |= c << 4; break;
    default: c &= 255; break;
    }
    c |= c << 8;
    return c | c << 16;
}

/* ---- the expansion table ---- */

/* 8 bits to 8 8-bit pixels: two words, at 2i and 2i + 1, made from the
   four pixels of each nibble. The library also has tables for 2- and
   4-bit pixels; the window here is 8-bit. */
unsigned gfx_x8[512];

void gfx_tables(void)
{
    unsigned nib[16];
    int i, k;
    for (i = 0; i < 16; i++) {
        nib[i] = 0;
        for (k = 0; k < 4; k++)
            if (i & (1 << k))
                nib[i] |= 255u << (8 * k);
    }
    for (i = 0; i < 256; i++) {
        gfx_x8[2 * i] = nib[i & 15];
        gfx_x8[2 * i + 1] = nib[i >> 4];
    }
}

/* ---- rectangles ---- */

/* Set up a fill job for the pixels [x0, x1) of rows y0.. of s, which the
   caller has clipped (x0 < x1). */
static void fill_setup(FillJob *j, Surface *s, int x0, int y0, int x1)
{
    int d = s->depth;
    int b0 = x0 << d, b1 = (x1 << d) - 1;       /* first and last bit */
    int w0 = b0 >> 5, w1 = b1 >> 5;
    j->p = (unsigned *)(s->bits + y0 * s->pitch) + w0;
    j->pitch = s->pitch;
    j->lmask = ~0u << (b0 & 31);
    j->rmask = ~0u >> (31 - (b1 & 31));
    if (w0 == w1) {
        j->lmask &= j->rmask;
        j->rmask = 0;
        j->n = 0;
    } else {
        j->n = w1 - w0 - 1;
    }
}

void gfx_fill(Surface *s, int x0, int y0, int x1, int y1, unsigned color, int rop)
{
    FillJob j;
    if (x0 < s->cx0) x0 = s->cx0;
    if (y0 < s->cy0) y0 = s->cy0;
    if (x1 > s->cx1) x1 = s->cx1;
    if (y1 > s->cy1) y1 = s->cy1;
    if (x0 >= x1 || y0 >= y1)
        return;
    fill_setup(&j, s, x0, y0, x1);
    j.h = y1 - y0;
    j.pat = gfx_pat(s->depth, color);
    j.rop = rop;
    fill_rows(&j);
}

/* One row, with the colour already a word of pixels (gfx_pat): the spans
   of outlines filled plainly. */
void gfx_span(Surface *s, int y, int x0, int x1, unsigned pat, int rop)
{
    FillJob j;
    if (y < s->cy0 || y >= s->cy1)
        return;
    if (x0 < s->cx0) x0 = s->cx0;
    if (x1 > s->cx1) x1 = s->cx1;
    if (x0 >= x1)
        return;
    fill_setup(&j, s, x0, y, x1);
    j.h = 1;
    j.pat = pat;
    j.rop = rop;
    fill_rows(&j);
}

/* ---- the fill kernel ---- */

void fill_rows(const FillJob *j)
{
    unsigned *row = j->p, *p;
    unsigned pat = j->pat, lm = j->lmask, rm = j->rmask;
    int h = j->h, n;
    if (j->rop == GFX_OR) {
        for (; h > 0; h--) {
            p = row;
            *p++ |= pat & lm;
            for (n = j->n; n > 0; n--)
                *p++ |= pat;
            if (rm)
                *p |= pat & rm;
            row = (unsigned *)((unsigned char *)row + j->pitch);
        }
        return;
    }
    for (; h > 0; h--) {        /* GFX_COPY */
        p = row;
        *p = (*p & ~lm) | (pat & lm);
        p++;
        for (n = j->n; n > 0; n--)
            *p++ = pat;
        if (rm)
            *p = (*p & ~rm) | (pat & rm);
        row = (unsigned *)((unsigned char *)row + j->pitch);
    }
}
