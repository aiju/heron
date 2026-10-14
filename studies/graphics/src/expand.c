/* Drawing 1-bit images in colour (gfx_expand), and anti-aliased coverage
   through a ramp of pixel values (gfx_ramp).

   gfx_expand reads the source bits 32 at a time, lined up with the
   destination words (a funnel shift, as in blit.c), and each 32 bits
   cover 1, 2, 4 or 8 destination words: at 1 bit per pixel the source
   word is the mask, at 2, 4 and 8 a table lookup turns 8 source bits into
   16, 32 or 64 bits of 2-, 4- or 8-bit pixels. The mask picks between the
   colours. Drawing transparently (a glyph, say), the source bits outside
   the rectangle are cleared, so no destination edge masks are needed,
   words with nothing to draw are skipped, and a row stops when its bits
   run out. */

#include "gfx.h"

static void edges(int dx, int w, int d, int *n, unsigned *lmask, unsigned *rmask)
{
    int dbit = (dx << d) & 31, nb = w << d;
    *n = (dbit + nb - 1) >> 5;
    *lmask = ~0u << dbit;
    *rmask = ~0u >> (31 - ((dbit + nb - 1) & 31));
    if (*n == 0)
        *lmask &= *rmask;
}

/* a destination word under a mask: fg where the mask is set */
#define PUT(p, m) (*(p) = (*(p) & ~(m)) | (fg & (m)))

void expand_rows_c(const ExpandJob *j)
{
    unsigned *d = j->d, *p, c, m, e, lo, hi, fg = j->fg, bg = j->bg;
    const unsigned *s = j->s;
    int h, k, rd, dep = j->depth, n = j->n, rs = j->soff & 31, pre = j->soff >= 0, b;
    for (h = j->h; h > 0; h--) {
        rd = 0;
        lo = pre ? s[rd++] : 0;
        if (j->opaque) {
            /* every word, between the destination masks */
            for (k = 0; k <= n; k++) {
                if ((k & ((1 << dep) - 1)) == 0) {
                    hi = rd <= j->slast ? s[rd] : 0;
                    rd++;
                    c = rs ? (lo >> rs) | (hi << (32 - rs)) : lo;
                    lo = hi;
                }
                switch (dep) {
                case 0: m = c; break;
                case 1: m = gfx_x2[c & 255] | (gfx_x2[(c >> 8) & 255] << 16); c >>= 16; break;
                case 2: m = gfx_x4[c & 255]; c >>= 8; break;
                default: m = gfx_x8[2 * (c & 255) + (k & 1)]; if (k & 1) c >>= 8; break;
                }
                e = k == 0 ? j->lmask : k == n ? j->rmask : ~0u;
                d[k] = (d[k] & ~e) | ((bg ^ ((fg ^ bg) & m)) & e);
            }
        } else {
            /* the chunks, masked to the rectangle; a chunk's words until
               its bits run out, and only the words with something in */
            p = d;
            for (k = 0; k < j->nch; k++, p += 1 << dep) {
                hi = rd <= j->slast ? s[rd] : 0;
                rd++;
                c = lo >> rs;           /* glyph rows have many zero words: skip their shifts */
                if (rs && hi)
                    c |= hi << (32 - rs);
                lo = hi;
                if (k == 0)
                    c &= j->cfirst;
                if (k == j->nch - 1)
                    c &= j->clast;
                switch (dep) {
                case 0:
                    if (c)
                        PUT(p, c);
                    break;
                case 1:
                    for (e = 0; c; e++, c >>= 16)
                        if ((m = gfx_x2[c & 255] | (gfx_x2[(c >> 8) & 255] << 16)) != 0)
                            PUT(p + e, m);
                    break;
                case 2:
                    for (e = 0; c; e++, c >>= 8)
                        if ((m = gfx_x4[c & 255]) != 0)
                            PUT(p + e, m);
                    break;
                default:
                    for (e = 0; c; e += 2, c >>= 8) {
                        b = 2 * (c & 255);
                        if ((m = gfx_x8[b]) != 0)
                            PUT(p + e, m);
                        if ((m = gfx_x8[b + 1]) != 0)
                            PUT(p + e + 1, m);
                    }
                    break;
                }
            }
        }
        d = (unsigned *)((unsigned char *)d + j->dpitch);
        s = (const unsigned *)((const unsigned char *)s + j->spitch);
    }
}

void gfx_expand(Surface *dst, int dx, int dy, const Surface *src, int sx, int sy,
                int w, int h, unsigned fg, unsigned bg, int opaque)
{
    ExpandJob j;
    int d = dst->depth, t, sbit, lead;
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
    edges(dx, w, d, &j.n, &j.lmask, &j.rmask);
    j.d = (unsigned *)(dst->bits + dy * dst->pitch) + ((dx << d) >> 5);
    j.s = (const unsigned *)(src->bits + sy * src->pitch) + (sx >> 5);
    sbit = sx & 31;
    lead = ((dx << d) & 31) >> d;
    j.soff = sbit - lead;
    j.slast = (sbit + w - 1) >> 5;
    j.cfirst = ~0u << lead;
    j.clast = ~0u >> (31 - ((lead + w - 1) & 31));
    j.nch = ((lead + w - 1) >> 5) + 1;
    if (j.nch == 1)
        j.cfirst &= j.clast;
    j.dpitch = dst->pitch;
    j.spitch = src->pitch;
    j.h = h;
    j.fg = gfx_pat(d, fg);
    j.bg = gfx_pat(d, bg);
    j.opaque = opaque;
    j.depth = d;
    expand_rows(&j);
}

/* ---- coverage through a ramp ---- */

void ramp_rows_c(const RampJob *j)
{
    unsigned *d = j->d, v, m, cv, pm;
    const unsigned char *c = j->c, *ramp = j->ramp;
    int h, k, i, x, dep = j->depth, bpp = 1 << dep, ppw = 32 >> dep, n = j->n;
    pm = (unsigned)gfx_maxcolor(dep) << (32 - bpp);
    for (h = j->h; h > 0; h--) {
        if (dep == 3) {
            /* whole bytes: store the pixels that have coverage */
            unsigned char *dp = (unsigned char *)d + j->lead;
            for (x = 0; x < j->w; x++)
                if ((cv = c[x]) != 0)
                    dp[x] = ramp[cv];
        } else {
            i = -j->lead;
            for (k = 0; k <= n; k++) {
                v = m = 0;
                for (x = 0; x < ppw; x++, i++) {
                    v >>= bpp;
                    m >>= bpp;
                    cv = i >= 0 && i < j->w ? c[i] : 0;
                    if (cv) {
                        v |= (unsigned)ramp[cv] << (32 - bpp);
                        m |= pm;
                    }
                }
                d[k] = (d[k] & ~m) | (v & m);
            }
        }
        d = (unsigned *)((unsigned char *)d + j->dpitch);
        c += j->cpitch;
    }
}

void gfx_ramp(Surface *dst, int dx, int dy, const unsigned char *cov, int cpitch,
              int w, int h, const unsigned char *ramp)
{
    RampJob j;
    int d = dst->depth, t;
    unsigned lm, rm;
    if (dx < dst->cx0) { t = dst->cx0 - dx; dx += t; cov += t; w -= t; }
    if (dy < dst->cy0) { t = dst->cy0 - dy; dy += t; cov += t * cpitch; h -= t; }
    if (dx + w > dst->cx1) w = dst->cx1 - dx;
    if (dy + h > dst->cy1) h = dst->cy1 - dy;
    if (w <= 0 || h <= 0)
        return;
    edges(dx, w, d, &j.n, &lm, &rm);
    j.d = (unsigned *)(dst->bits + dy * dst->pitch) + ((dx << d) >> 5);
    j.lead = ((dx << d) & 31) >> d;
    j.w = w;
    j.c = cov;
    j.dpitch = dst->pitch;
    j.cpitch = cpitch;
    j.h = h;
    j.ramp = ramp;
    j.depth = d;
    ramp_rows(&j);
}
