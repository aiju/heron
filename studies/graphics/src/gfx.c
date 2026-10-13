/* Surfaces, pixels, rectangles and patterns, and the fill kernel. */

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

void gfx_clip_rect(Surface *s, const Rect *r)
{
    gfx_clip(s, r->x0, r->y0, r->x1, r->y1);
}

int gfx_maxcolor(int depth)
{
    return (1 << (1 << depth)) - 1;
}

/* the colour in every pixel of a word; depth 4 (16-bit pixels) too, for
   patterns of pairs */
unsigned gfx_pat(int depth, unsigned c)
{
    switch (depth) {
    case 0: return -(c & 1);
    case 1: c &= 3; c |= c << 2; c |= c << 4; break;
    case 2: c &= 15; c |= c << 4; break;
    case 3: c &= 255; break;
    default: c &= 0xFFFF; return c | c << 16;
    }
    c |= c << 8;
    return c | c << 16;
}

/* ---- the expansion tables ---- */

unsigned gfx_x2[256], gfx_x4[256], gfx_x8[512];

void gfx_tables(void)
{
    int i, k;
    for (i = 0; i < 256; i++) {
        unsigned a = 0, b = 0;
        for (k = 0; k < 8; k++)
            if (i & (1 << k)) {
                a |= 3u << (2 * k);
                b |= 15u << (4 * k);
            }
        gfx_x2[i] = a;
        gfx_x4[i] = b;
        a = b = 0;
        for (k = 0; k < 4; k++) {
            if (i & (1 << k))
                a |= 255u << (8 * k);
            if (i & (16 << k))
                b |= 255u << (8 * k);
        }
        gfx_x8[2 * i] = a;
        gfx_x8[2 * i + 1] = b;
    }
}

/* ---- pixels ---- */

void gfx_pixel(Surface *s, int x, int y, unsigned color, int rop)
{
    int d = s->depth, bit;
    unsigned char *p, m, c;
    if (x < s->cx0 || x >= s->cx1 || y < s->cy0 || y >= s->cy1)
        return;
    bit = x << d;
    p = s->bits + y * s->pitch + (bit >> 3);
    bit &= 7;
    m = gfx_maxcolor(d) << bit;
    c = color << bit;
    switch (rop) {
    case GFX_COPY: *p = (*p & ~m) | (c & m); break;
    case GFX_XOR: *p ^= c & m; break;
    case GFX_OR: *p |= c & m; break;
    case GFX_AND: *p &= c | ~m; break;
    }
}

unsigned gfx_get(const Surface *s, int x, int y)
{
    int d = s->depth, bit;
    if (x < 0 || x >= s->w || y < 0 || y >= s->h)
        return 0;
    bit = x << d;
    return (s->bits[y * s->pitch + (bit >> 3)] >> (bit & 7)) & gfx_maxcolor(d);
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
   of polygons and ellipses. A kernel: asm/ISA/span.s does it all in one,
   the clipping and the masks too. */
void gfx_span_c(Surface *s, int y, int x0, int x1, unsigned pat, int rop)
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

void gfx_fill_rect(Surface *s, const Rect *r, unsigned color, int rop)
{
    gfx_fill(s, r->x0, r->y0, r->x1, r->y1, color, rop);
}

/* A pattern is 8 rows that repeat down the surface: fill every 8th row
   with the same word, as 8 jobs with 8 times the pitch. */
void gfx_fill_pat(Surface *s, int x0, int y0, int x1, int y1, const unsigned *pat, int rop)
{
    FillJob j;
    int k, h;
    if (x0 < s->cx0) x0 = s->cx0;
    if (y0 < s->cy0) y0 = s->cy0;
    if (x1 > s->cx1) x1 = s->cx1;
    if (y1 > s->cy1) y1 = s->cy1;
    if (x0 >= x1 || y0 >= y1)
        return;
    fill_setup(&j, s, x0, y0, x1);
    j.pitch = s->pitch * 8;
    j.rop = rop;
    h = y1 - y0;
    for (k = 0; k < 8 && k < h; k++) {
        j.h = (h - k + 7) >> 3;
        j.pat = pat[(y0 + k) & 7];
        fill_rows(&j);
        j.p = (unsigned *)((unsigned char *)j.p + s->pitch);
    }
}

/* An outline t pixels thick, inside the rectangle. */
void gfx_frame(Surface *s, int x0, int y0, int x1, int y1, int t, unsigned color, int rop)
{
    if (x1 - x0 <= 2 * t || y1 - y0 <= 2 * t) {
        gfx_fill(s, x0, y0, x1, y1, color, rop);
        return;
    }
    gfx_fill(s, x0, y0, x1, y0 + t, color, rop);
    gfx_fill(s, x0, y1 - t, x1, y1, color, rop);
    gfx_fill(s, x0, y0 + t, x0 + t, y1 - t, color, rop);
    gfx_fill(s, x1 - t, y0 + t, x1, y1 - t, color, rop);
}

/* ---- the fill kernel ---- */

void fill_rows_c(const FillJob *j)
{
    unsigned *row = j->p, *p;
    unsigned pat = j->pat, lm = j->lmask, rm = j->rmask;
    int h = j->h, n;
    switch (j->rop) {
    case GFX_COPY:
        for (; h > 0; h--) {
            p = row;
            *p = (*p & ~lm) | (pat & lm);
            p++;
            for (n = j->n; n > 0; n--)
                *p++ = pat;
            if (rm)
                *p = (*p & ~rm) | (pat & rm);
            row = (unsigned *)((unsigned char *)row + j->pitch);
        }
        break;
    case GFX_XOR:
        for (; h > 0; h--) {
            p = row;
            *p++ ^= pat & lm;
            for (n = j->n; n > 0; n--)
                *p++ ^= pat;
            if (rm)
                *p ^= pat & rm;
            row = (unsigned *)((unsigned char *)row + j->pitch);
        }
        break;
    case GFX_OR:
        for (; h > 0; h--) {
            p = row;
            *p++ |= pat & lm;
            for (n = j->n; n > 0; n--)
                *p++ |= pat;
            if (rm)
                *p |= pat & rm;
            row = (unsigned *)((unsigned char *)row + j->pitch);
        }
        break;
    case GFX_AND:
        for (; h > 0; h--) {
            p = row;
            *p++ &= pat | ~lm;
            for (n = j->n; n > 0; n--)
                *p++ &= pat;
            if (rm)
                *p &= pat | ~rm;
            row = (unsigned *)((unsigned char *)row + j->pitch);
        }
        break;
    }
}
