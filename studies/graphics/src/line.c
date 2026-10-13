/* Lines: Bresenham's algorithm, clipped exactly.

   The line is drawn along its major axis u, stepping the minor axis v
   when the decision variable e is positive. Going from (u0, v0) with
   du >= dv >= 0, step i has v = v0 + k(i) with

       k(i) = floor((2 dv i + du - 1) / (2 du))
       e(i) = 2 dv (i + 1) - du - 2 du k(i)

   so a clipped line can start at any step with the same pixels as the
   whole line, and the steps where v enters and leaves the clip rectangle
   come out of the same formula solved for i. A line with v decreasing is
   drawn mirrored (v -> -v). */

#include "gfx.h"

/* For the rops as v = (v & ~(m & ka)) ^ (m & kx), m the pixel's mask: */
static void rop_masks(int rop, unsigned c, unsigned *ka, unsigned *kx)
{
    switch (rop) {
    case GFX_COPY: *ka = ~0u; *kx = c; break;
    case GFX_XOR: *ka = 0; *kx = c; break;
    case GFX_OR: *ka = c; *kx = c; break;
    default: *ka = ~c; *kx = 0; break;
    }
}

void line_run_c(const LineJob *j)
{
    unsigned char *p = j->p;
    unsigned m = j->m, ka = j->ka, kx = j->kx;
    unsigned bpp = 1u << j->depth, pm = (1u << bpp) - 1;
    int n = j->n, e = j->e, inc = j->inc, dec = j->dec, ys = j->ystep;
    if (j->depth == 3 && ka == ~0u) {
        /* whole bytes: plain stores */
        if (j->dir == 0) {
            for (; n > 0; n--) {
                *p++ = kx;
                if (e > 0) {
                    p += ys;
                    e -= dec;
                }
                e += inc;
            }
        } else {
            for (; n > 0; n--) {
                *p = kx;
                p += ys;
                if (e > 0) {
                    p += j->dir;
                    e -= dec;
                }
                e += inc;
            }
        }
        return;
    }
    if (j->dir == 0) {                          /* x-major, going right */
        for (; n > 0; n--) {
            *p = (*p & ~(m & ka)) ^ (m & kx);
            m <<= bpp;
            if (m > 255) {
                m = pm;
                p++;
            }
            if (e > 0) {
                p += ys;
                e -= dec;
            }
            e += inc;
        }
    } else if (j->dir > 0) {                    /* y-major, x going right */
        for (; n > 0; n--) {
            *p = (*p & ~(m & ka)) ^ (m & kx);
            p += ys;
            if (e > 0) {
                m <<= bpp;
                if (m > 255) {
                    m = pm;
                    p++;
                }
                e -= dec;
            }
            e += inc;
        }
    } else {                                    /* y-major, x going left */
        for (; n > 0; n--) {
            *p = (*p & ~(m & ka)) ^ (m & kx);
            p += ys;
            if (e > 0) {
                m >>= bpp;
                if (m == 0) {
                    m = pm << (8 - bpp);
                    p--;
                }
                e -= dec;
            }
            e += inc;
        }
    }
}

/* u is the major axis, stepping by one; v the minor one. With xmajor, u
   is x; otherwise u is y and v is x. */
static void line_major(Surface *s, int u0, int v0, int du, int dv,
                       int cu0, int cu1, int cv0, int cv1, int xmajor,
                       unsigned color, int rop)
{
    LineJob j;
    int i0, i1, k, t, vs = 1, x, y, bit, d = s->depth;
    if (dv < 0) {                               /* mirror v */
        vs = -1;
        dv = -dv;
        v0 = -v0;
        t = cv0;
        cv0 = 1 - cv1;
        cv1 = 1 - t;
    }
    i0 = cu0 - u0;
    if (i0 < 0)
        i0 = 0;
    i1 = cu1 - 1 - u0;
    if (i1 > du)
        i1 = du;
    if (v0 >= cv1)
        return;
    if (v0 < cv0) {                             /* the first step with v >= cv0 */
        if (dv == 0)
            return;
        t = (2 * du * (cv0 - v0) - du + 2 * dv) / (2 * dv);
        if (t > i0)
            i0 = t;
    }
    if (v0 + dv >= cv1) {                       /* the last step with v < cv1 */
        t = (2 * du * (cv1 - v0) - du + 2 * dv) / (2 * dv) - 1;
        if (t < i1)
            i1 = t;
    }
    if (i0 > i1)
        return;
    if (du == 0) {
        k = 0;
        j.e = 0;
    } else {
        k = (2 * dv * i0 + du - 1) / (2 * du);
        j.e = 2 * dv * (i0 + 1) - du - 2 * du * k;
    }
    j.n = i1 - i0 + 1;
    j.inc = 2 * dv;
    j.dec = 2 * du;
    if (xmajor) {
        x = u0 + i0;
        y = vs * (v0 + k);
        j.ystep = vs * s->pitch;
        j.dir = 0;
    } else {
        y = u0 + i0;
        x = vs * (v0 + k);
        j.ystep = s->pitch;
        j.dir = vs;
    }
    bit = x << d;
    j.p = s->bits + y * s->pitch + (bit >> 3);
    j.m = gfx_maxcolor(d) << (bit & 7);
    j.depth = d;
    rop_masks(rop, gfx_pat(d, color) & 255, &j.ka, &j.kx);
    line_run(&j);
}

void gfx_line(Surface *s, int x0, int y0, int x1, int y1, unsigned color, int rop)
{
    int t;
    if (s->cx0 >= s->cx1 || s->cy0 >= s->cy1)
        return;
    if ((x0 < s->cx0 && x1 < s->cx0) || (x0 >= s->cx1 && x1 >= s->cx1) ||
        (y0 < s->cy0 && y1 < s->cy0) || (y0 >= s->cy1 && y1 >= s->cy1))
        return;
    if ((x1 > x0 ? x1 - x0 : x0 - x1) >= (y1 > y0 ? y1 - y0 : y0 - y1)) {
        if (x1 < x0) {
            t = x0; x0 = x1; x1 = t;
            t = y0; y0 = y1; y1 = t;
        }
        line_major(s, x0, y0, x1 - x0, y1 - y0, s->cx0, s->cx1, s->cy0, s->cy1, 1, color, rop);
    } else {
        if (y1 < y0) {
            t = x0; x0 = x1; x1 = t;
            t = y0; y0 = y1; y1 = t;
        }
        line_major(s, y0, x0, y1 - y0, x1 - x0, s->cy0, s->cy1, s->cx0, s->cx1, 0, color, rop);
    }
}
