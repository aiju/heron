/* Copying rectangles between surfaces of the same depth, at any
   alignment, overlapping or not.

   A row is copied a destination word at a time. Destination bit t of the
   row comes from source bit t + (sbit - dbit), where sbit and dbit are
   where the rectangle starts in the first source and destination words.
   When they differ, each destination word is put together from two
   neighbouring source words, a funnel shift:

       out = (lo >> rs) | (hi << ls),  ls = 32 - rs

   With pre set (sbit > dbit), destination word j takes source words j
   and j + 1; otherwise words j - 1 and j, and word -1 is never read.
   Only the source words that hold bits of the rectangle are read: last
   says whether the final destination word needs one more. */

#include "gfx.h"

static unsigned merge(unsigned d, unsigned v, unsigned m, int rop)
{
    switch (rop) {
    case GFX_COPY: return (d & ~m) | (v & m);
    case GFX_XOR: return d ^ (v & m);
    case GFX_OR: return d | (v & m);
    default: return d & (v | ~m);
    }
}

void blit_rows_c(const BlitJob *j)
{
    unsigned *d = j->d, *s = j->s, lo, hi, out, m;
    int h, k, n = j->n, rs = j->rs, ls = j->ls;
    for (h = j->h; h > 0; h--) {
        if (!j->back) {
            unsigned *sp = s;
            lo = j->pre ? *sp++ : 0;
            for (k = 0; k <= n; k++) {
                hi = k < n || j->last ? *sp++ : 0;
                out = ls ? (lo >> rs) | (hi << ls) : hi;
                lo = hi;
                m = k == 0 ? j->lmask : k == n ? j->rmask : ~0u;
                if (m == ~0u && j->rop == GFX_COPY)
                    d[k] = out;
                else
                    d[k] = merge(d[k], out, m, j->rop);
            }
        } else {
            /* d and s are at the last destination word, and the source
               word that is its hi */
            unsigned *sp = s;
            hi = j->last ? *sp : 0;
            for (k = n; k >= 0; k--) {
                lo = k + j->pre - 1 >= 0 ? *--sp : 0;
                out = ls ? (lo >> rs) | (hi << ls) : hi;
                hi = lo;
                m = k == 0 ? j->lmask : k == n ? j->rmask : ~0u;
                if (m == ~0u && j->rop == GFX_COPY)
                    d[k - n] = out;
                else
                    d[k - n] = merge(d[k - n], out, m, j->rop);
            }
        }
        d = (unsigned *)((unsigned char *)d + j->dpitch);
        s = (unsigned *)((unsigned char *)s + j->spitch);
    }
}

void gfx_blit(Surface *dst, int dx, int dy, const Surface *src, int sx, int sy,
              int w, int h, int rop)
{
    BlitJob j;
    int d = dst->depth, t, dbit, sbit, nb, slast;
    if (dx < dst->cx0) { t = dst->cx0 - dx; dx += t; sx += t; w -= t; }
    if (dy < dst->cy0) { t = dst->cy0 - dy; dy += t; sy += t; h -= t; }
    if (dx + w > dst->cx1) w = dst->cx1 - dx;
    if (dy + h > dst->cy1) h = dst->cy1 - dy;
    if (sx < 0) { t = -sx; sx = 0; dx += t; w -= t; }
    if (sy < 0) { t = -sy; sy = 0; dy += t; h -= t; }
    if (sx + w > src->w) w = src->w - sx;
    if (sy + h > src->h) h = src->h - sy;
    if (w <= 0 || h <= 0)
        return;
    dbit = (dx << d) & 31;
    sbit = (sx << d) & 31;
    nb = w << d;
    j.n = (dbit + nb - 1) >> 5;
    slast = (sbit + nb - 1) >> 5;
    j.lmask = ~0u << dbit;
    j.rmask = ~0u >> (31 - ((dbit + nb - 1) & 31));
    if (j.n == 0)
        j.lmask &= j.rmask;
    if (sbit == dbit) {
        j.rs = j.ls = 0;
        j.pre = 0;
        j.last = 1;
    } else if (sbit > dbit) {
        j.rs = sbit - dbit;
        j.ls = 32 - j.rs;
        j.pre = 1;
        j.last = j.n + 1 <= slast;
    } else {
        j.ls = dbit - sbit;
        j.rs = 32 - j.ls;
        j.pre = 0;
        j.last = j.n <= slast;
    }
    j.rop = rop;
    j.h = h;
    j.dpitch = dst->pitch;
    j.spitch = src->pitch;
    j.back = 0;
    if (dst->bits == src->bits && dy > sy) {    /* overlapping, moving down: bottom up */
        dy += h - 1;
        sy += h - 1;
        j.dpitch = -j.dpitch;
        j.spitch = -j.spitch;
    } else if (dst->bits == src->bits && dy == sy && dx > sx) {
        j.back = 1;                             /* moving right within the rows */
    }
    j.d = (unsigned *)(dst->bits + dy * dst->pitch) + ((dx << d) >> 5);
    j.s = (unsigned *)(src->bits + sy * src->pitch) + ((sx << d) >> 5);
    if (j.back) {
        j.d += j.n;
        j.s += j.n + j.pre;
    }
    blit_rows(&j);
}
