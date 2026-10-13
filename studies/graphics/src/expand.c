/* Drawing 1-bit images in colour (gfx_expand), and anti-aliased coverage
   through a ramp of pixel values (gfx_ramp).

   gfx_expand works a destination word at a time. The source bits are
   read 32 at a time, lined up with the destination words (a funnel
   shift, as in blit.c), and each destination word takes 32/bpp of them:
   at 1 bit per pixel the source word is the mask, at 2, 4 and 8 a table
   lookup turns 8, 8 or 4 source bits into a word of 2-, 4- or 8-bit
   pixels. The mask then picks between the colours. */

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

void expand_rows_c(const ExpandJob *j)
{
    unsigned *d = j->d, c = 0, m, e, lo, hi, fg = j->fg, bg = j->bg;
    const unsigned *s = j->s;
    int h, k, rd, dep = j->depth, per = (1 << dep) - 1, n = j->n;
    int soff = j->soff, rs, ls;
    if (soff >= 0) {
        rs = soff;
        ls = 32 - soff;
    } else {
        ls = -soff;
        rs = 32 + soff;
    }
    for (h = j->h; h > 0; h--) {
        rd = 0;
        lo = 0;
        if (soff > 0)
            lo = s[rd++];
        for (k = 0; k <= n; k++) {
            if ((k & per) == 0) {
                hi = rd <= j->slast ? s[rd] : 0;
                rd++;
                c = soff == 0 ? hi : (lo >> rs) | (hi << ls);
                lo = hi;
            }
            switch (dep) {
            case 0: m = c; break;
            case 1: m = gfx_x2[c & 255] | (gfx_x2[(c >> 8) & 255] << 16); c >>= 16; break;
            case 2: m = gfx_x4[c & 255]; c >>= 8; break;
            default: m = gfx_x8[c & 15]; c >>= 4; break;
            }
            e = k == 0 ? j->lmask : k == n ? j->rmask : ~0u;
            if (j->opaque)
                d[k] = (d[k] & ~e) | ((bg ^ ((fg ^ bg) & m)) & e);
            else
                d[k] = (d[k] & ~(m & e)) | (fg & m & e);
        }
        d = (unsigned *)((unsigned char *)d + j->dpitch);
        s = (const unsigned *)((const unsigned char *)s + j->spitch);
    }
}

void gfx_expand(Surface *dst, int dx, int dy, const Surface *src, int sx, int sy,
                int w, int h, unsigned fg, unsigned bg, int opaque)
{
    ExpandJob j;
    int d = dst->depth, t, sbit;
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
    j.soff = sbit - (((dx << d) & 31) >> d);
    j.slast = (sbit + w - 1) >> 5;
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
