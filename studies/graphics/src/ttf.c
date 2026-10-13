/* TrueType outlines on the machine: the file is read as it is, big-endian
   tables and all. A glyph's contours are decoded from the glyf table,
   scaled to 24.8 pixels, its quadratic curves flattened into lines, and
   the lines filled by the scan converter (raster.c), plainly or
   anti-aliased. Hinting, kerning and composite glyphs are left out. */

#include <stdlib.h>
#include <string.h>
#include "gfx.h"

static int u16(const unsigned char *p)
{
    return p[0] << 8 | p[1];
}

static int s16(const unsigned char *p)
{
    int v = p[0] << 8 | p[1];
    return v >= 0x8000 ? v - 0x10000 : v;
}

static unsigned u32(const unsigned char *p)
{
    return (unsigned)p[0] << 24 | p[1] << 16 | p[2] << 8 | p[3];
}

#define TAG(a, b, c, d) ((unsigned)(a) << 24 | (b) << 16 | (c) << 8 | (d))

int ttf_open(TTF *t, const unsigned char *data)
{
    int n = u16(data + 4), i, k;
    const unsigned char *head = 0, *hhea = 0, *maxp = 0, *cmap = 0, *r, *sub;
    memset(t, 0, sizeof *t);
    t->data = data;
    for (i = 0; i < n; i++) {
        r = data + 12 + 16 * i;
        switch (u32(r)) {
        case TAG('h', 'e', 'a', 'd'): head = data + u32(r + 8); break;
        case TAG('h', 'h', 'e', 'a'): hhea = data + u32(r + 8); break;
        case TAG('m', 'a', 'x', 'p'): maxp = data + u32(r + 8); break;
        case TAG('c', 'm', 'a', 'p'): cmap = data + u32(r + 8); break;
        case TAG('l', 'o', 'c', 'a'): t->loca = data + u32(r + 8); break;
        case TAG('g', 'l', 'y', 'f'): t->glyf = data + u32(r + 8); break;
        case TAG('h', 'm', 't', 'x'): t->hmtx = data + u32(r + 8); break;
        }
    }
    if (!head || !hhea || !maxp || !cmap || !t->loca || !t->glyf || !t->hmtx)
        return -1;
    t->upem = u16(head + 18);
    t->loca_long = s16(head + 50);
    t->ascent = s16(hhea + 4);
    t->descent = s16(hhea + 6);
    t->linegap = s16(hhea + 8);
    t->nhmetrics = u16(hhea + 34);
    t->nglyphs = u16(maxp + 4);
    /* the Unicode (Windows) subtable, format 4 */
    k = u16(cmap + 2);
    for (i = 0; i < k; i++) {
        r = cmap + 4 + 8 * i;
        sub = cmap + u32(r + 4);
        if (u16(r) == 3 && u16(r + 2) == 1 && u16(sub) == 4)
            t->cmap = sub;
    }
    return t->cmap ? 0 : -1;
}

int ttf_glyph_index(TTF *t, int c)
{
    const unsigned char *s = t->cmap, *ro;
    int segs2 = u16(s + 6), i, start, g;
    for (i = 0; i < segs2; i += 2) {
        if (u16(s + 14 + i) < c)
            continue;
        start = u16(s + 16 + segs2 + i);
        if (c < start)
            return 0;
        ro = s + 16 + 3 * segs2 + i;
        if (u16(ro) == 0)
            return (c + u16(s + 16 + 2 * segs2 + i)) & 0xFFFF;
        g = u16(ro + u16(ro) + 2 * (c - start));
        return g ? (g + u16(s + 16 + 2 * segs2 + i)) & 0xFFFF : 0;
    }
    return 0;
}

static const unsigned char *glyph(TTF *t, int gi, int *len)
{
    unsigned a, b;
    if (gi < 0 || gi >= t->nglyphs)
        return 0;
    if (t->loca_long) {
        a = u32(t->loca + 4 * gi);
        b = u32(t->loca + 4 * gi + 4);
    } else {
        a = 2 * u16(t->loca + 2 * gi);
        b = 2 * u16(t->loca + 2 * gi + 2);
    }
    *len = b - a;
    return t->glyf + a;
}

/* pixels per font unit, as 16.16 */
static int scale_of(TTF *t, int size)
{
    return (size << 16) / t->upem;
}

int ttf_advance(TTF *t, int gi, int size)
{
    int k = gi < t->nhmetrics ? gi : t->nhmetrics - 1;
    return (u16(t->hmtx + 4 * k) * scale_of(t, size) + 128) >> 8;
}

/* ---- outlines ---- */

#define MAXPTS 400
#define MAXCONT 40

static int px[MAXPTS], py[MAXPTS];
static unsigned char pf[MAXPTS];
static int ends[MAXCONT];

/* A quadratic curve from (x0, y0) through control (x1, y1) to (x2, y2),
   as 2^k lines: forward differences on the curve scaled by n*n, so it's
   additions only and the end point comes out exact. k is chosen so that
   no line is more than 1/8 pixel from the curve (that's |a| / 4n^2, a
   the second difference). */
static void quad(Raster *r, int x0, int y0, int x1, int y1, int x2, int y2)
{
    int ax = x0 - 2 * x1 + x2, ay = y0 - 2 * y1 + y2, dd, k = 0, n, i;
    int sx, sy, dx, dy, ddx, ddy, half, xp = x0, yp = y0, x, y;
    dd = ax < 0 ? -ax : ax;
    if ((ay < 0 ? -ay : ay) > dd)
        dd = ay < 0 ? -ay : ay;
    while (k < 5 && (128 << (2 * k)) < dd)
        k++;
    n = 1 << k;
    sx = x0 * (n * n);
    sy = y0 * (n * n);
    dx = 2 * n * (x1 - x0) + ax;
    dy = 2 * n * (y1 - y0) + ay;
    ddx = 2 * ax;
    ddy = 2 * ay;
    half = (1 << (2 * k)) >> 1;
    for (i = 1; i < n; i++) {
        sx += dx;
        sy += dy;
        dx += ddx;
        dy += ddy;
        x = (sx + half) >> (2 * k);
        y = (sy + half) >> (2 * k);
        rs_edge(r, xp, yp, x, y);
        xp = x;
        yp = y;
    }
    rs_edge(r, xp, yp, x2, y2);
}

/* Decode a simple glyph's points into px/py/pf/ends (font units);
   returns the number of contours, or -1. */
static int decode(const unsigned char *g, int len)
{
    int nc, np, i, v, f, rep;
    const unsigned char *p;
    if (len < 10)
        return 0;
    nc = s16(g);
    if (nc < 0 || nc > MAXCONT)
        return -1;                                  /* composite, or too big */
    for (i = 0; i < nc; i++)
        ends[i] = u16(g + 10 + 2 * i);
    np = nc ? ends[nc - 1] + 1 : 0;
    if (np > MAXPTS)
        return -1;
    p = g + 12 + 2 * nc + u16(g + 10 + 2 * nc);    /* past the instructions */
    for (i = 0; i < np;) {
        f = *p++;
        pf[i++] = f;
        if (f & 8)
            for (rep = *p++; rep > 0 && i < np; rep--)
                pf[i++] = f;
    }
    for (i = v = 0; i < np; i++) {
        f = pf[i];
        if (f & 2)
            v += f & 16 ? *p++ : -*p++;
        else if (!(f & 16)) {
            v += s16(p);
            p += 2;
        }
        px[i] = v;
    }
    for (i = v = 0; i < np; i++) {
        f = pf[i];
        if (f & 4)
            v += f & 32 ? *p++ : -*p++;
        else if (!(f & 32)) {
            v += s16(p);
            p += 2;
        }
        py[i] = v;
    }
    return nc;
}

int ttf_outline(TTF *t, int gi, int size, int penx, int peny, Raster *r)
{
    const unsigned char *g;
    int len, nc, c, i, s, e, n, sc = scale_of(t, size), k;
    int x0, y0, cx, cy, x, y, sx0, sy0, on, have_ctrl;
    g = glyph(t, gi, &len);
    if (!g)
        return -1;
    nc = decode(g, len);
    if (nc < 0)
        return -1;
    /* to 24.8 pixels, y down */
    n = nc ? ends[nc - 1] + 1 : 0;
    for (i = 0; i < n; i++) {
        px[i] = penx + ((px[i] * sc + 128) >> 8);
        py[i] = peny - ((py[i] * sc + 128) >> 8);
    }
    for (c = 0, s = 0; c < nc; c++, s = e + 1) {
        e = ends[c];
        if (e < s)
            continue;
        /* start on an on-curve point; if there's none, at the midpoint
           of the first two */
        for (k = s; k <= e && !(pf[k] & 1); k++)
            ;
        if (k > e) {
            k = s + 1 <= e ? s + 1 : s;
            sx0 = (px[s] + px[k]) >> 1;
            sy0 = (py[s] + py[k]) >> 1;
        } else {
            sx0 = px[k];
            sy0 = py[k];
            k++;
        }
        x0 = sx0;
        y0 = sy0;
        have_ctrl = 0;
        cx = cy = 0;
        for (i = 0; i <= e - s + 1; i++, k++) {
            if (k > e)
                k = s;
            if (i == e - s + 1) {                  /* back to the start */
                x = sx0;
                y = sy0;
                on = 1;
            } else {
                x = px[k];
                y = py[k];
                on = pf[k] & 1;
            }
            if (on) {
                if (have_ctrl)
                    quad(r, x0, y0, cx, cy, x, y);
                else
                    rs_edge(r, x0, y0, x, y);
                x0 = x;
                y0 = y;
                have_ctrl = 0;
            } else {
                if (have_ctrl) {                   /* two controls: the midpoint is on the curve */
                    int mx = (cx + x) >> 1, my = (cy + y) >> 1;
                    quad(r, x0, y0, cx, cy, mx, my);
                    x0 = mx;
                    y0 = my;
                }
                cx = x;
                cy = y;
                have_ctrl = 1;
            }
        }
    }
    return ttf_advance(t, gi, size);
}

/* ---- rendering glyphs ---- */

static Edge glyph_edges[1024];

int ttf_render(TTF *t, int gi, int size, int aa, unsigned char *buf, int bufsize, Glyph *gl)
{
    const unsigned char *g;
    int len, sc = scale_of(t, size), x0, y0, x1, y1, w, h, pitch;
    Raster r;
    Surface s;
    memset(gl, 0, sizeof *gl);
    g = glyph(t, gi, &len);
    if (!g)
        return -1;
    gl->adv = (ttf_advance(t, gi, size) + 128) >> 8;
    if (len < 10)
        return 0;                                   /* no outline: a space */
    /* the box in whole pixels, from the glyph's own bounding box */
    x0 = (s16(g + 2) * sc) >> 16;
    x1 = (s16(g + 6) * sc + 0xFFFF) >> 16;
    y0 = (-s16(g + 8) * sc) >> 16;
    y1 = (-s16(g + 4) * sc + 0xFFFF) >> 16;
    w = x1 - x0 + 1;
    h = y1 - y0 + 1;
    pitch = aa ? w : ((w + 31) >> 5) << 2;
    if (pitch * h > bufsize)
        return -1;
    memset(buf, 0, pitch * h);
    rs_init(&r, glyph_edges, 1024);
    if (ttf_outline(t, gi, size, -x0 * 256, -y0 * 256, &r) < 0)
        return -1;
    if (aa) {
        rs_fill_aa(&r, buf, w, w, h, GFX_NONZERO);
    } else {
        gfx_init(&s, buf, w, h, pitch, 0);
        rs_fill(&r, &s, 1, GFX_OR, GFX_NONZERO);
    }
    gl->w = w;
    gl->h = h;
    gl->xoff = x0;
    gl->yoff = y0;
    gl->bits = buf;
    return pitch * h;
}
