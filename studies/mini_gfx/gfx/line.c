/* Lines and circles (gfx.h). A line is Bresenham's, drawn left to right
   if it's mostly across and top to bottom if it's mostly down, clipped
   exactly: the pixels inside the clip are those of the whole line. Step
   t of a line mostly across from (x0, y0), dx >= dy >= 0, is pixel
   (x0 + t, y0 + floor((2 t dy + dx) / 2 dx)). */

#include "gfx.h"

static void rop_consts(const Surface *s, unsigned c, int rop, unsigned *ka, unsigned *kx)
{
    unsigned pat = gfx_solidf(s->f, c);
    switch (rop) {
    case ROP_COPY: *ka = ~0u; *kx = pat; break;
    case ROP_XOR: *ka = 0; *kx = pat; break;
    case ROP_OR: *ka = pat; *kx = pat; break;
    default: *ka = ~pat; *kx = 0; break;
    }
}

/* the steps t0..t1 of a line of major length d, minor slope m/d, start
   minor coordinate a, for which the minor coordinate lies in [lo, hi):
   returns 0 if none */
static int minor_range(int d, int m, int a, int lo, int hi, int *t0, int *t1)
{
    int k, kk;
    if (m == 0)
        return a >= lo && a < hi;
    /* minor(t) = a + floor((2 t m + d) / 2d) >= lo */
    k = lo - a;
    if (k > 0) {
        int t = (2 * d * k - d + 2 * m - 1) / (2 * m);
        if (t > *t0)
            *t0 = t;
    }
    kk = hi - 1 - a;
    if (kk < 0)
        return 0;
    {
        /* minor(t) <= kk: 2 t m + d < 2 d (kk + 1) */
        int t = (2 * d * (kk + 1) - d - 1) / (2 * m);
        if (t < *t1)
            *t1 = t;
    }
    return *t0 <= *t1;
}

void gfx_line(Surface *s, int x0, int y0, int x1, int y1, unsigned c, int rop)
{
    const Format *f = s->f;
    LineJob j;
    int dx, dy, t0, t1, sy, ppw = 1 << s->pshift, x, y, mn;
    rop_consts(s, c, rop, &j.ka, &j.kx);
    j.masks = f->pmask;
    j.ppw = ppw;
    dx = x1 - x0;
    dy = y1 - y0;
    if ((dx < 0 ? -dx : dx) >= (dy < 0 ? -dy : dy)) {
        /* mostly across: left to right */
        if (dx < 0) {
            int t = x0; x0 = x1; x1 = t;
            t = y0; y0 = y1; y1 = t;
            dx = -dx;
            dy = -dy;
        }
        sy = dy < 0 ? -1 : 1;
        if (dy < 0)
            dy = -dy;
        t0 = s->clip.x0 - x0;
        if (t0 < 0)
            t0 = 0;
        t1 = s->clip.x1 - 1 - x0;
        if (t1 > dx)
            t1 = dx;
        if (t0 > t1)
            return;
        if (sy > 0) {
            if (!minor_range(dx, dy, y0, s->clip.y0, s->clip.y1, &t0, &t1))
                return;
        } else {
            /* mirrored: y0 - minor(t) */
            if (!minor_range(dx, dy, -y0, 1 - s->clip.y1, 1 - s->clip.y0, &t0, &t1))
                return;
        }
        if (dx == 0) {
            mn = 0;
            j.e = -1;
        } else {
            mn = (2 * t0 * dy + dx) / (2 * dx);
            j.e = 2 * (t0 + 1) * dy + dx - 2 * dx * (mn + 1);
        }
        x = x0 + t0;
        y = y0 + sy * mn;
        j.inc = 2 * dy;
        j.dec = 2 * dx;
        j.dir = 0;
        j.ystep = sy * s->pitch;
    } else {
        /* mostly down: top to bottom */
        int sx;
        if (dy < 0) {
            int t = x0; x0 = x1; x1 = t;
            t = y0; y0 = y1; y1 = t;
            dx = -dx;
            dy = -dy;
        }
        sx = dx < 0 ? -1 : 1;
        if (dx < 0)
            dx = -dx;
        t0 = s->clip.y0 - y0;
        if (t0 < 0)
            t0 = 0;
        t1 = s->clip.y1 - 1 - y0;
        if (t1 > dy)
            t1 = dy;
        if (t0 > t1)
            return;
        if (sx > 0) {
            if (!minor_range(dy, dx, x0, s->clip.x0, s->clip.x1, &t0, &t1))
                return;
        } else {
            if (!minor_range(dy, dx, -x0, 1 - s->clip.x1, 1 - s->clip.x0, &t0, &t1))
                return;
        }
        mn = (2 * t0 * dx + dy) / (2 * dy);
        j.e = 2 * (t0 + 1) * dx + dy - 2 * dy * (mn + 1);
        y = y0 + t0;
        x = x0 + sx * mn;
        j.inc = 2 * dx;
        j.dec = 2 * dy;
        j.dir = sx;
        j.ystep = s->pitch;
    }
    j.n = t1 - t0 + 1;
    j.p = s->bits + y * s->pitch + (x >> s->pshift);
    j.i = x & (ppw - 1);
    line_run(&j);
}

void line_run_c(const LineJob *j)
{
    unsigned *p = j->p, ka = j->ka, kx = j->kx, m;
    const unsigned *masks = j->masks;
    int i = j->i, n = j->n, e = j->e, ppw = j->ppw;
    while (n-- > 0) {
        m = masks[i];
        *p = (*p & ~(m & ka)) ^ (m & kx);
        if (j->dir == 0) {
            if (++i == ppw) {
                i = 0;
                p++;
            }
            if (e >= 0) {
                p += j->ystep;
                e -= j->dec;
            }
        } else {
            p += j->ystep;
            if (e >= 0) {
                i += j->dir;
                if (i == ppw) {
                    i = 0;
                    p++;
                } else if (i < 0) {
                    i = ppw - 1;
                    p--;
                }
                e -= j->dec;
            }
        }
        e += j->inc;
    }
}

/* circles: the midpoint algorithm, its octants by symmetry */
void gfx_circle(Surface *s, int xc, int yc, int r, unsigned c, int rop)
{
    int x = r, y = 0, e = 1 - r;
    if (r <= 0) {
        gfx_pixel(s, xc, yc, c, rop);
        return;
    }
    while (x >= y) {
        gfx_pixel(s, xc + x, yc + y, c, rop);
        gfx_pixel(s, xc - x, yc + y, c, rop);
        if (y) {
            gfx_pixel(s, xc + x, yc - y, c, rop);
            gfx_pixel(s, xc - x, yc - y, c, rop);
        }
        if (x != y) {
            gfx_pixel(s, xc + y, yc + x, c, rop);
            gfx_pixel(s, xc + y, yc - x, c, rop);
            if (y) {
                gfx_pixel(s, xc - y, yc + x, c, rop);
                gfx_pixel(s, xc - y, yc - x, c, rop);
            }
        }
        y++;
        if (e < 0) {
            e += 2 * y + 1;
        } else {
            x--;
            e += 2 * (y - x) + 1;
        }
    }
}

void gfx_fill_circle(Surface *s, int xc, int yc, int r, unsigned c, int rop)
{
    int x = r, y = 0, e = 1 - r, lasty = -1;
    while (x >= y) {
        /* the rows yc +- y span +-x; the rows yc +- x span +-y, once each */
        if (y != lasty) {
            gfx_fill(s, xc - x, yc + y, xc + x + 1, yc + y + 1, c, rop);
            if (y)
                gfx_fill(s, xc - x, yc - y, xc + x + 1, yc - y + 1, c, rop);
            lasty = y;
        }
        if (e >= 0 && x != y) {
            gfx_fill(s, xc - y, yc + x, xc + y + 1, yc + x + 1, c, rop);
            gfx_fill(s, xc - y, yc - x, xc + y + 1, yc - x + 1, c, rop);
        }
        y++;
        if (e < 0) {
            e += 2 * y + 1;
        } else {
            x--;
            e += 2 * (y - x) + 1;
        }
    }
}
