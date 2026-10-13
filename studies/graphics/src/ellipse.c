/* Ellipses and circles: John Kennedy's integer algorithm ("A fast
   Bresenham type algorithm for drawing ellipses") gives, for each row dy
   from the centre, how far the ellipse reaches across. The filled ellipse
   is one span per row; the outline is the part of each row's span that
   the next row out doesn't cover, so every pixel is drawn once (XOR
   works) and with whole spans rather than pixel by pixel. */

#include "gfx.h"

#define MAXR 600

static int ext[MAXR + 2];

/* ext[dy] = the reach at row dy, for dy = 0..b */
static void reach(int a, int b)
{
    int x, y, xchg, ychg, err, ta = 2 * a * a, tb = 2 * b * b, sx, sy;
    for (y = 0; y <= b; y++)
        ext[y] = 0;
    if (a == 0 || b == 0) {
        ext[0] = a;
        return;
    }
    /* from (a, 0) up to where the slope is -1 */
    x = a;
    y = 0;
    xchg = b * b * (1 - 2 * a);
    ychg = a * a;
    err = 0;
    sx = tb * a;
    sy = 0;
    while (sx >= sy) {
        if (ext[y] < x)
            ext[y] = x;
        y++;
        sy += ta;
        err += ychg;
        ychg += ta;
        if (2 * err + xchg > 0) {
            x--;
            sx -= tb;
            err += xchg;
            xchg += tb;
        }
    }
    /* from (0, b) down to the same place */
    x = 0;
    y = b;
    xchg = b * b;
    ychg = a * a * (1 - 2 * b);
    err = 0;
    sx = 0;
    sy = ta * b;
    while (sx <= sy) {
        if (ext[y] < x)
            ext[y] = x;
        x++;
        sx += tb;
        err += xchg;
        xchg += tb;
        if (2 * err + ychg > 0) {
            y--;
            sy -= ta;
            err += ychg;
            ychg += ta;
        }
    }
}

static int clamp(int r)
{
    return r < 0 ? 0 : r > MAXR ? MAXR : r;
}

void gfx_fill_ellipse(Surface *s, int xc, int yc, int a, int b, unsigned color, int rop)
{
    unsigned pat = gfx_pat(s->depth, color);
    int dy;
    a = clamp(a);
    b = clamp(b);
    reach(a, b);
    gfx_span(s, yc, xc - ext[0], xc + ext[0] + 1, pat, rop);
    for (dy = 1; dy <= b; dy++) {
        gfx_span(s, yc - dy, xc - ext[dy], xc + ext[dy] + 1, pat, rop);
        gfx_span(s, yc + dy, xc - ext[dy], xc + ext[dy] + 1, pat, rop);
    }
}

/* One row of the outline, at y: from in to out on both sides. */
static void outline_row(Surface *s, int xc, int y, int in, int out, unsigned pat, int rop)
{
    if (in == 0) {
        gfx_span(s, y, xc - out, xc + out + 1, pat, rop);
    } else {
        gfx_span(s, y, xc - out, xc - in + 1, pat, rop);
        gfx_span(s, y, xc + in, xc + out + 1, pat, rop);
    }
}

void gfx_ellipse(Surface *s, int xc, int yc, int a, int b, unsigned color, int rop)
{
    unsigned pat = gfx_pat(s->depth, color);
    int dy, in;
    a = clamp(a);
    b = clamp(b);
    reach(a, b);
    for (dy = 0; dy <= b; dy++) {
        in = dy < b ? ext[dy + 1] + 1 : 0;
        if (in > ext[dy])
            in = ext[dy];
        outline_row(s, xc, yc - dy, in, ext[dy], pat, rop);
        if (dy > 0)
            outline_row(s, xc, yc + dy, in, ext[dy], pat, rop);
    }
}
