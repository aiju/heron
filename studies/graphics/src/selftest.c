/* Checks of the word-level code against pixel-at-a-time references:
   fills, blits (overlapping too), expansion, ramps and clipped lines, at
   random positions and sizes, at every depth. heron graphics selftest
   runs it on the host with gcc (the C kernels), and on the simulator for
   both ISAs with the assembly kernels, with fewer iterations. */

#include <stdio.h>
#include <string.h>
#include "gfx.h"

#ifndef ITERS
#define ITERS 3000
#endif

#define W 200
#define H 40
#define PITCH 200               /* bytes: enough for 200 pixels at 8 bits */

static unsigned a_mem[PITCH * H / 4], b_mem[PITCH * H / 4], src_mem[PITCH * H / 4];
static unsigned seed = 12345;

static unsigned rnd(void)
{
    seed ^= seed << 13;
    seed ^= seed >> 17;
    seed ^= seed << 5;
    return seed;
}

static int rop_pixel(int d, int v, int c, int rop)
{
    switch (rop) {
    case GFX_COPY: return c;
    case GFX_XOR: return v ^ c;
    case GFX_OR: return v | c;
    default: return v & c;
    }
}

/* Bresenham as line.c does it, a pixel at a time, clipped per pixel */
static void ref_line(Surface *s, int x0, int y0, int x1, int y1, int c, int rop)
{
    int t, du, dv, vs, e, u, v, xmajor;
    int adx = x1 > x0 ? x1 - x0 : x0 - x1, ady = y1 > y0 ? y1 - y0 : y0 - y1;
    xmajor = adx >= ady;
    if (xmajor ? x1 < x0 : y1 < y0) {
        t = x0; x0 = x1; x1 = t;
        t = y0; y0 = y1; y1 = t;
    }
    du = xmajor ? x1 - x0 : y1 - y0;
    dv = xmajor ? y1 - y0 : x1 - x0;
    vs = dv < 0 ? -1 : 1;
    dv *= vs;
    e = 2 * dv - du;
    u = xmajor ? x0 : y0;
    v = xmajor ? y0 : x0;
    for (t = 0; t <= du; t++, u++) {
        int x = xmajor ? u : v, y = xmajor ? v : u;
        if (x >= s->cx0 && x < s->cx1 && y >= s->cy0 && y < s->cy1)
            gfx_pixel(s, x, y, rop_pixel(0, gfx_get(s, x, y), c, rop), GFX_COPY);
        if (e > 0) {
            v += vs;
            e -= 2 * du;
        }
        e += 2 * dv;
    }
}

static int same(Surface *a, Surface *b, const char *what, int depth, int iter)
{
    if (memcmp(a->bits, b->bits, PITCH * H) == 0)
        return 1;
    printf("FAIL %s depth %d iteration %d\n", what, depth, iter);
    return 0;
}

static void randomize(Surface *s)
{
    int i;
    for (i = 0; i < PITCH * H; i++)
        s->bits[i] = rnd();
}

int main(void)
{
    Surface a, b, src;
    int d, it, x, y, x0, y0, w, h, sx, sy, rop, c, fg, bg, opaque, fails = 0;
    gfx_tables();
    for (d = 0; d < 4; d++) {
        gfx_init(&a, a_mem, W, H, PITCH, d);
        gfx_init(&b, b_mem, W, H, PITCH, d);
        gfx_init(&src, src_mem, W, H, PITCH, 0);
        for (it = 0; it < ITERS; it++) {
            randomize(&a);
            memcpy(b.bits, a.bits, PITCH * H);
            x0 = rnd() % W; y0 = rnd() % H;
            w = rnd() % (W - x0) + 1; h = rnd() % (H - y0) + 1;
            rop = rnd() % 4;
            c = rnd() & gfx_maxcolor(d);
            switch (it % 5) {
            case 4:                         /* a line, clipped to a random rectangle */
                gfx_clip(&a, x0, y0, x0 + w, y0 + h);
                gfx_clip(&b, x0, y0, x0 + w, y0 + h);
                {
                    int lx0 = (int)(rnd() % (3 * W)) - W, ly0 = (int)(rnd() % (3 * H)) - H;
                    int lx1 = (int)(rnd() % (3 * W)) - W, ly1 = (int)(rnd() % (3 * H)) - H;
                    gfx_line(&a, lx0, ly0, lx1, ly1, c, rop);
                    ref_line(&b, lx0, ly0, lx1, ly1, c, rop);
                }
                gfx_noclip(&a);
                gfx_noclip(&b);
                fails += !same(&a, &b, "line", d, it);
                break;
            case 0:                         /* fill */
                gfx_fill(&a, x0, y0, x0 + w, y0 + h, c, rop);
                for (y = y0; y < y0 + h; y++)
                    for (x = x0; x < x0 + w; x++)
                        gfx_pixel(&b, x, y, rop_pixel(d, gfx_get(&b, x, y), c, rop), GFX_COPY);
                fails += !same(&a, &b, "fill", d, it);
                break;
            case 1:                         /* blit within the surface, overlapping */
                sx = rnd() % (W - w + 1); sy = rnd() % (H - h + 1);
                gfx_blit(&a, x0, y0, &a, sx, sy, w, h, rop);
                {
                    static unsigned char tmp[W * H];
                    for (y = 0; y < h; y++)
                        for (x = 0; x < w; x++)
                            tmp[y * W + x] = gfx_get(&b, sx + x, sy + y);
                    for (y = 0; y < h; y++)
                        for (x = 0; x < w; x++)
                            gfx_pixel(&b, x0 + x, y0 + y,
                                      rop_pixel(d, gfx_get(&b, x0 + x, y0 + y), tmp[y * W + x], rop),
                                      GFX_COPY);
                }
                fails += !same(&a, &b, "blit", d, it);
                break;
            case 2:                         /* expand from a 1-bit surface */
                randomize(&src);
                sx = rnd() % (W - w + 1); sy = rnd() % (H - h + 1);
                fg = rnd() & gfx_maxcolor(d);
                bg = rnd() & gfx_maxcolor(d);
                opaque = rnd() & 1;
                gfx_expand(&a, x0, y0, &src, sx, sy, w, h, fg, bg, opaque);
                for (y = 0; y < h; y++)
                    for (x = 0; x < w; x++) {
                        if (gfx_get(&src, sx + x, sy + y))
                            gfx_pixel(&b, x0 + x, y0 + y, fg, GFX_COPY);
                        else if (opaque)
                            gfx_pixel(&b, x0 + x, y0 + y, bg, GFX_COPY);
                    }
                fails += !same(&a, &b, "expand", d, it);
                break;
            case 3:                         /* ramp from coverage bytes */
                {
                    static unsigned char cov[W * H], ramp[256];
                    for (x = 0; x < 256; x++)
                        ramp[x] = x * 7 & gfx_maxcolor(d);
                    for (x = 0; x < W * H; x++)
                        cov[x] = rnd() % 3 ? rnd() % 65 : 0;
                    gfx_ramp(&a, x0, y0, cov, W, w, h, ramp);
                    for (y = 0; y < h; y++)
                        for (x = 0; x < w; x++)
                            if (cov[y * W + x])
                                gfx_pixel(&b, x0 + x, y0 + y, ramp[cov[y * W + x]], GFX_COPY);
                }
                fails += !same(&a, &b, "ramp", d, it);
                break;
            }
            if (fails > 10)
                return 1;
        }
    }
    printf(fails ? "%d failures\n" : "all good\n", fails);
    return fails != 0;
}
