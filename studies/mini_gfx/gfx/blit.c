/* Copies, 1-bit expansion and masked sprites (gfx.h).

   A copy whose source and destination have the same pixel phase in a
   word copies words (a copy job); any other is a shift job: each
   destination word made of two source words, lo and the next, hi, whose
   pixels from `phase` on line up with it. Which bits of lo and hi go
   where depends only on the format and the phase: shift_terms works it
   out from gfx_bitpos, as a few terms of (lo or hi, shifted, masked).
   The linear formats need two (lo >> b | hi << 32 - b), the planes two
   with masks, L0's interleaved 1 and 2 bits four. */

#include <stdlib.h>
#include <string.h>
#include "gfx.h"

static int clip_copy(const Surface *dst, int *dx, int *dy, const Surface *src, int *sx, int *sy,
                     int *w, int *h)
{
    int d;
    if ((d = dst->clip.x0 - *dx) > 0) { *dx += d; *sx += d; *w -= d; }
    if ((d = dst->clip.y0 - *dy) > 0) { *dy += d; *sy += d; *h -= d; }
    if ((d = *dx + *w - dst->clip.x1) > 0) *w -= d;
    if ((d = *dy + *h - dst->clip.y1) > 0) *h -= d;
    if (src) {
        if ((d = -*sx) > 0) { *dx += d; *sx += d; *w -= d; }
        if ((d = -*sy) > 0) { *dy += d; *sy += d; *h -= d; }
        if ((d = *sx + *w - src->w) > 0) *w -= d;
        if ((d = *sy + *h - src->h) > 0) *h -= d;
    }
    return *w > 0 && *h > 0;
}

/* the terms of a shift by `phase` pixels in format fmt: destination
   pixel t's bits come from pixel t + phase of lo, or of hi if that's past
   the word */
int shift_terms(int fmt, int phase, Term *t)
{
    const Format *f = gfx_format(fmt);
    int ppw = 1 << f->pshift, p, i, k, n = 0;
    for (p = 0; p < ppw; p++) {
        int q = p + phase, src = q >= ppw;
        if (src)
            q -= ppw;
        for (i = 0; i < f->bpp; i++) {
            int to = gfx_bitpos(fmt, p, i), from = gfx_bitpos(fmt, q, i), sh = to - from;
            for (k = 0; k < n; k++)
                if (t[k].src == src && t[k].sh == sh)
                    break;
            if (k == n) {
                t[n].src = src;
                t[n].sh = sh;
                t[n].m = 0;
                n++;
            }
            t[k].m |= 1u << to;
        }
    }
    /* lo's terms first, then hi's */
    for (k = 1; k < n; k++) {
        Term x = t[k];
        int m = k;
        while (m > 0 && t[m - 1].src > x.src) {
            t[m] = t[m - 1];
            m--;
        }
        t[m] = x;
    }
    return n;
}

static unsigned row_buf[1100];

void gfx_blit(Surface *dst, int dx, int dy, const Surface *src, int sx, int sy, int w, int h,
              int rop)
{
    const Format *f = gfx_format(dst->fmt);
    int ps = dst->pshift, last = (1 << ps) - 1;
    int w0, w1, n, base, phase, sw, y, down;
    unsigned lmask, rmask;
    if (!clip_copy(dst, &dx, &dy, src, &sx, &sy, &w, &h))
        return;
    w0 = dx >> ps;
    w1 = (dx + w - 1) >> ps;
    n = w1 - w0;
    lmask = gfx_from(f, dx & last);
    rmask = gfx_before(f, ((dx + w - 1) & last) + 1);
    if (n == 0) {
        lmask &= rmask;
        rmask = 0;
    }
    /* the source's pixel under the first destination word's first pixel */
    base = (w0 << ps) - dx + sx;
    phase = base & last;
    sw = base >> ps;            /* floor: base may be negative */
    down = src->bits == dst->bits && dy > sy;
    if (phase == 0) {
        CopyJob j;
        j.n = n;
        j.lmask = lmask;
        j.rmask = rmask;
        j.rop = rop;
        j.h = h;
        j.back = src->bits == dst->bits && dy == sy && dx > sx && dx < sx + w;
        j.d = dst->bits + dy * dst->pitch + w0;
        j.s = src->bits + sy * src->pitch + sw;
        j.dpitch = dst->pitch;
        j.spitch = src->pitch;
        if (down) {
            j.d += (h - 1) * dst->pitch;
            j.s += (h - 1) * src->pitch;
            j.dpitch = -j.dpitch;
            j.spitch = -j.spitch;
        }
        if (j.back) {
            j.d += n;
            j.s += n;
        }
        copy_rows(&j);
        return;
    }
    {
        ShiftJob j;
        int overlap = src->bits == dst->bits && dy == sy;
        j.n = n;
        j.lmask = lmask;
        j.rmask = rmask;
        j.rop = rop;
        j.nterm = shift_terms(dst->fmt, phase, j.t);
        j.phase = phase;
        j.bpp = f->bpp;
        j.fmt = dst->fmt;
        j.d = dst->bits + dy * dst->pitch + w0;
        j.s = src->bits + sy * src->pitch + sw;
        j.dpitch = dst->pitch;
        j.spitch = src->pitch;
        if (!overlap) {
            j.h = h;
            if (down) {
                j.d += (h - 1) * dst->pitch;
                j.s += (h - 1) * src->pitch;
                j.dpitch = -j.dpitch;
                j.spitch = -j.spitch;
            }
            shift_rows(&j);
            return;
        }
        /* rows that overlap themselves: each through the row buffer */
        j.h = 1;
        for (y = 0; y < h; y++) {
            const unsigned *s = src->bits + (sy + y) * src->pitch + sw;
            memcpy(row_buf, s, (n + 2) * sizeof(unsigned));
            j.s = row_buf;
            j.d = dst->bits + (dy + y) * dst->pitch + w0;
            shift_rows(&j);
        }
    }
}

void copy_rows_c(const CopyJob *j)
{
    unsigned *d = j->d, lm = j->lmask, rm = j->rmask;
    const unsigned *s = j->s;
    int h = j->h, n = j->n, k;
    while (h-- > 0) {
        unsigned *q = d;
        const unsigned *r = s;
        if (!j->back) {
            if (j->rop == ROP_COPY) {
                *q = (*q & ~lm) | (*r++ & lm);
                q++;
                for (k = 1; k < n; k++)
                    *q++ = *r++;
                if (n > 0)
                    *q = (*q & ~rm) | (*r & rm);
            } else {
                unsigned m = lm;
                for (k = 0; k <= n; k++) {
                    unsigned v = *r++;
                    if (k == n && n > 0)
                        m = rm;
                    else if (k > 0)
                        m = ~0u;
                    if (j->rop == ROP_XOR)
                        *q ^= v & m;
                    else if (j->rop == ROP_OR)
                        *q |= v & m;
                    else
                        *q &= v | ~m;
                    q++;
                }
            }
        } else {
            /* right to left, from the last word */
            unsigned m = n > 0 ? rm : lm;
            for (k = n; k >= 0; k--) {
                unsigned v = *r--;
                if (k == 0)
                    m = lm;
                else if (k < n)
                    m = ~0u;
                if (j->rop == ROP_COPY)
                    *q = (*q & ~m) | (v & m);
                else if (j->rop == ROP_XOR)
                    *q ^= v & m;
                else if (j->rop == ROP_OR)
                    *q |= v & m;
                else
                    *q &= v | ~m;
                q--;
            }
        }
        d += j->dpitch;
        s += j->spitch;
    }
}

static unsigned merge(const ShiftJob *j, unsigned lo, unsigned hi)
{
    unsigned v = 0;
    int k;
    for (k = 0; k < j->nterm; k++) {
        unsigned x = j->t[k].src ? hi : lo;
        int sh = j->t[k].sh;
        v |= (sh >= 0 ? x << sh : x >> -sh) & j->t[k].m;
    }
    return v;
}

void shift_rows_c(const ShiftJob *j)
{
    unsigned *d = j->d, lm = j->lmask, rm = j->rmask;
    const unsigned *s = j->s;
    int h = j->h, n = j->n, k;
    while (h-- > 0) {
        unsigned *q = d, lo = s[0], hi, v, m;
        const unsigned *r = s + 1;
        for (k = 0; k <= n; k++) {
            hi = *r++;
            v = merge(j, lo, hi);
            lo = hi;
            m = k == 0 ? lm : k == n ? rm : ~0u;
            switch (j->rop) {
            case ROP_COPY: *q = (*q & ~m) | (v & m); break;
            case ROP_XOR: *q ^= v & m; break;
            case ROP_OR: *q |= v & m; break;
            default: *q &= v | ~m; break;
            }
            q++;
        }
        d += j->dpitch;
        s += j->spitch;
    }
}

/* the expansion of a 1-bit source */
void gfx_expand(Surface *dst, int dx, int dy, const Bitmap *src, int sx, int sy, int w, int h,
                unsigned fg, unsigned bg, int opaque)
{
    const Format *f = gfx_format(dst->fmt);
    int ps = dst->pshift, last = (1 << ps) - 1, w0, w1, base;
    ExpandJob j;
    if (!clip_copy(dst, &dx, &dy, 0, &sx, &sy, &w, &h))
        return;
    if (sx < 0 || sy < 0)
        return;
    w0 = dx >> ps;
    w1 = (dx + w - 1) >> ps;
    j.n = w1 - w0;
    j.lmask = gfx_from(f, dx & last);
    j.rmask = gfx_before(f, ((dx + w - 1) & last) + 1);
    if (j.n == 0) {
        j.lmask &= j.rmask;
        j.rmask = 0;
    }
    base = (w0 << ps) - dx + sx;    /* the source bit under the first word's first pixel */
    j.s = src->bits + sy * src->pitch + (base >> 5);
    j.soff = base & 31;
    j.spitch = src->pitch;
    j.d = dst->bits + dy * dst->pitch + w0;
    j.dpitch = dst->pitch;
    j.h = h;
    j.fg = gfx_solid(dst->fmt, fg);
    j.bg = gfx_solid(dst->fmt, bg);
    j.opaque = opaque;
    j.f = f;
    j.fmt = dst->fmt;
    gfx_xmask(f, 0);            /* the tables */
    expand_rows(&j);
}

void expand_rows_c(const ExpandJob *j)
{
    unsigned *d = j->d, lm = j->lmask, rm = j->rmask, fg = j->fg, bg = j->bg;
    const unsigned *s = j->s;
    const Format *f = j->f;
    int h = j->h, n = j->n, ppw = 1 << f->pshift, k;
    unsigned keep = ppw == 32 ? ~0u : (1u << ppw) - 1;
    while (h-- > 0) {
        unsigned *q = d;
        int bit = j->soff;
        for (k = 0; k <= n; k++) {
            int i = bit >> 5, o = bit & 31;
            unsigned bits = s[i] >> o, m, e;
            if (o)
                bits |= s[i + 1] << (32 - o);
            m = gfx_xmask(f, bits & keep);
            e = k == 0 ? lm : k == n ? rm : ~0u;
            if (j->opaque)
                *q = (*q & ~e) | ((bg ^ ((fg ^ bg) & m)) & e);
            else
                *q ^= (*q ^ fg) & m & e;
            q++;
            bit += ppw;
        }
        d += j->dpitch;
        s += j->spitch;
    }
}

/* a sprite: the image's pixels where the mask is 1, at any phase */
void gfx_masked(Surface *dst, int dx, int dy, const Surface *img, const Bitmap *mask, int sx,
                int sy, int w, int h)
{
    const Format *f = gfx_format(dst->fmt);
    int ps = dst->pshift, last = (1 << ps) - 1, ppw = 1 << ps;
    int w0, w1, n, base, phase, sw, y, k, nterm;
    unsigned lmask, rmask, keep;
    Term t[6];
    if (!clip_copy(dst, &dx, &dy, img, &sx, &sy, &w, &h))
        return;
    w0 = dx >> ps;
    w1 = (dx + w - 1) >> ps;
    n = w1 - w0;
    lmask = gfx_from(f, dx & last);
    rmask = gfx_before(f, ((dx + w - 1) & last) + 1);
    if (n == 0) {
        lmask &= rmask;
        rmask = 0;
    }
    base = (w0 << ps) - dx + sx;
    phase = base & last;
    sw = base >> ps;
    nterm = phase ? shift_terms(dst->fmt, phase, t) : 0;
    keep = ppw == 32 ? ~0u : (1u << ppw) - 1;
    gfx_xmask(f, 0);
    for (y = 0; y < h; y++) {
        unsigned *q = dst->bits + (dy + y) * dst->pitch + w0;
        const unsigned *s = img->bits + (sy + y) * img->pitch + sw;
        const unsigned *mb = mask->bits + (sy + y) * mask->pitch;
        int bit = base;
        unsigned lo = s[0], hi, v, m, e;
        for (k = 0; k <= n; k++) {
            int i = bit >> 5, o = bit & 31;
            unsigned bits = mb[i] >> o;
            if (o)
                bits |= mb[i + 1] << (32 - o);
            m = gfx_xmask(f, bits & keep);
            if (nterm) {
                int a;
                hi = s[k + 1];
                v = 0;
                for (a = 0; a < nterm; a++) {
                    unsigned x = t[a].src ? hi : lo;
                    v |= (t[a].sh >= 0 ? x << t[a].sh : x >> -t[a].sh) & t[a].m;
                }
                lo = hi;
            } else {
                v = s[k];
            }
            e = (k == 0 ? lmask : k == n ? rmask : ~0u) & m;
            *q = (*q & ~e) | (v & e);
            q++;
            bit += ppw;
        }
    }
}
