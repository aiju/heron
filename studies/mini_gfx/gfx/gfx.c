/* Surfaces, pixels, fills, patterns (gfx.h). */

#include "gfx.h"
#include "video.h"

void gfx_init(Surface *s, void *bits, int w, int h, int pitch, int fmt)
{
    const Format *f = gfx_format(fmt);
    s->bits = bits;
    s->w = w;
    s->h = h;
    s->pitch = pitch;
    s->fmt = fmt;
    s->bpp = f->bpp;
    s->pshift = f->pshift;
    s->f = f;
    gfx_noclip(s);
}

void gfx_screen(Surface *s, void *bits, int pitch)
{
    gfx_init(s, bits, vid.w, vid.h, pitch, gfx_screen_format());
}

/* a view of a rectangle of the parent, whose x0 must be on a word */
void gfx_sub(Surface *s, const Surface *parent, int x0, int y0, int x1, int y1)
{
    *s = *parent;
    s->bits = parent->bits + y0 * parent->pitch + (x0 >> parent->pshift);
    s->w = x1 - x0;
    s->h = y1 - y0;
    gfx_noclip(s);
}

void gfx_noclip(Surface *s)
{
    s->clip.x0 = 0;
    s->clip.y0 = 0;
    s->clip.x1 = s->w;
    s->clip.y1 = s->h;
}

void gfx_clip(Surface *s, int x0, int y0, int x1, int y1)
{
    s->clip.x0 = x0 < 0 ? 0 : x0;
    s->clip.y0 = y0 < 0 ? 0 : y0;
    s->clip.x1 = x1 > s->w ? s->w : x1;
    s->clip.y1 = y1 > s->h ? s->h : y1;
}

void gfx_clip_rect(Surface *s, const Rect *r)
{
    gfx_clip(s, r->x0, r->y0, r->x1, r->y1);
}

void gfx_pixel(Surface *s, int x, int y, unsigned c, int rop)
{
    const Format *f;
    unsigned *p, m, pat;
    if (x < s->clip.x0 || x >= s->clip.x1 || y < s->clip.y0 || y >= s->clip.y1)
        return;
    f = s->f;
    p = s->bits + y * s->pitch + (x >> s->pshift);
    m = f->pmask[x & ((1 << s->pshift) - 1)];
    pat = gfx_solidf(f, c) & m;
    switch (rop) {
    case ROP_COPY: *p = (*p & ~m) | pat; break;
    case ROP_XOR: *p ^= pat; break;
    case ROP_OR: *p |= pat; break;
    default: *p &= pat | ~m; break;
    }
}

unsigned gfx_get(const Surface *s, int x, int y)
{
    const Format *f;
    unsigned w, c = 0;
    int p, i;
    if (x < 0 || x >= s->w || y < 0 || y >= s->h)
        return 0;
    f = s->f;
    w = s->bits[y * s->pitch + (x >> s->pshift)];
    p = x & ((1 << s->pshift) - 1);
    if (f->lin)
        return (w >> (p * f->bpp)) & ((1u << f->bpp) - 1);
    for (i = 0; i < f->bpp; i++)
        c |= (w >> gfx_bitpos(s->fmt, p, i) & 1) << i;
    return c;
}

/* clip a rectangle to the surface's clip: 0 if nothing's left */
static int clip(const Surface *s, int *x0, int *y0, int *x1, int *y1)
{
    if (*x0 < s->clip.x0) *x0 = s->clip.x0;
    if (*y0 < s->clip.y0) *y0 = s->clip.y0;
    if (*x1 > s->clip.x1) *x1 = s->clip.x1;
    if (*y1 > s->clip.y1) *y1 = s->clip.y1;
    return *x0 < *x1 && *y0 < *y1;
}

/* the job for the words of rows x0..x1 */
static void fill_job(FillJob *j, Surface *s, int x0, int y0, int x1, int y1)
{
    const Format *f = s->f;
    int ps = s->pshift, last = (1 << ps) - 1;
    int w0 = x0 >> ps, w1 = (x1 - 1) >> ps;
    j->p = s->bits + y0 * s->pitch + w0;
    j->pitch = s->pitch;
    j->h = y1 - y0;
    j->lmask = gfx_from(f, x0 & last);
    j->rmask = gfx_before(f, ((x1 - 1) & last) + 1);
    if (w0 == w1) {
        j->lmask &= j->rmask;
        j->rmask = 0;
        j->n = 0;
    } else {
        j->n = w1 - w0 - 1;
    }
    j->pats = 0;
    j->row0 = y0;
}

void gfx_fill(Surface *s, int x0, int y0, int x1, int y1, unsigned c, int rop)
{
    FillJob j;
    if (!clip(s, &x0, &y0, &x1, &y1))
        return;
    fill_job(&j, s, x0, y0, x1, y1);
    j.pat = gfx_solidf(s->f, c);
    j.rop = rop;
    fill_rows(&j);
}

void gfx_fill_rect(Surface *s, const Rect *r, unsigned c, int rop)
{
    gfx_fill(s, r->x0, r->y0, r->x1, r->y1, c, rop);
}

void gfx_fill_pat(Surface *s, int x0, int y0, int x1, int y1, const unsigned char *rows,
                  unsigned fg, unsigned bg)
{
    const Format *f = s->f;
    unsigned pats[8], fw = gfx_solidf(f, fg), bw = gfx_solidf(f, bg);
    FillJob j;
    int k, y;
    if (!clip(s, &x0, &y0, &x1, &y1))
        return;
    if (s->pshift >= 3) {
        /* 8 pixels or more a word: a word a row */
        for (k = 0; k < 8; k++) {
            unsigned m = gfx_xmask(f, rows[k] * 0x01010101u);
            pats[k] = (fw & m) | (bw & ~m);
        }
        fill_job(&j, s, x0, y0, x1, y1);
        j.pats = pats;
        j.pat = 0;
        j.rop = ROP_COPY;
        fill_rows(&j);
        return;
    }
    /* 4 pixels a word: the pattern's halves in turn, a word at a time */
    for (y = y0; y < y1; y++) {
        int x = x0;
        unsigned row = rows[y & 7];
        while (x < x1) {
            int xe = (x | 3) + 1;
            unsigned m;
            if (xe > x1)
                xe = x1;
            m = gfx_xmask(f, (x & 4 ? row >> 4 : row) & 15);
            fill_job(&j, s, x, y, xe, y + 1);
            j.pat = (fw & m) | (bw & ~m);
            j.rop = ROP_COPY;
            fill_rows(&j);
            x = xe;
        }
    }
}

void gfx_hline(Surface *s, int x0, int x1, int y, unsigned c, int rop)
{
    gfx_fill(s, x0, y, x1, y + 1, c, rop);
}

void gfx_vline(Surface *s, int x, int y0, int y1, unsigned c, int rop)
{
    gfx_fill(s, x, y0, x + 1, y1, c, rop);
}

void gfx_frame(Surface *s, int x0, int y0, int x1, int y1, int t, unsigned c, int rop)
{
    gfx_fill(s, x0, y0, x1, y0 + t, c, rop);
    gfx_fill(s, x0, y1 - t, x1, y1, c, rop);
    gfx_fill(s, x0, y0 + t, x0 + t, y1 - t, c, rop);
    gfx_fill(s, x1 - t, y0 + t, x1, y1 - t, c, rop);
}

void gfx_bevel(Surface *s, int x0, int y0, int x1, int y1, unsigned light, unsigned dark)
{
    gfx_fill(s, x0, y0, x1, y0 + 1, light, ROP_COPY);
    gfx_fill(s, x0, y0 + 1, x0 + 1, y1, light, ROP_COPY);
    gfx_fill(s, x0 + 1, y1 - 1, x1, y1, dark, ROP_COPY);
    gfx_fill(s, x1 - 1, y0 + 1, x1, y1 - 1, dark, ROP_COPY);
}

/* the C kernel */
void fill_rows_c(const FillJob *j)
{
    unsigned *p = j->p, lm = j->lmask, rm = j->rmask, pat = j->pat, *q, *e;
    int h = j->h, n = j->n, y = j->row0;
    while (h-- > 0) {
        if (j->pats)
            pat = j->pats[y++ & 7];
        q = p;
        e = q + 1 + n;
        switch (j->rop) {
        case ROP_COPY:
            *q = (*q & ~lm) | (pat & lm);
            q++;
            while (q < e)
                *q++ = pat;
            if (rm)
                *q = (*q & ~rm) | (pat & rm);
            break;
        case ROP_XOR:
            *q++ ^= pat & lm;
            while (q < e)
                *q++ ^= pat;
            if (rm)
                *q ^= pat & rm;
            break;
        case ROP_OR:
            *q++ |= pat & lm;
            while (q < e)
                *q++ |= pat;
            if (rm)
                *q |= pat & rm;
            break;
        default:
            *q++ &= pat | ~lm;
            while (q < e)
                *q++ &= pat;
            if (rm)
                *q &= pat | ~rm;
            break;
        }
        p += j->pitch;
    }
}
