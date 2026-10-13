/* Scan conversion: polygons and glyph outlines, as edges in 24.8 fixed
   point, filled by the even-odd or the non-zero winding rule.

   The edges are sampled at the centre of each sample row: one per pixel
   row for a plain fill, four for anti-aliasing. Each edge's crossing
   moves by exactly dx/dy per sample row, kept as a whole step q plus a
   remainder r/dy carried in err, so there's no rounding and no division
   once the edge has started. The crossings stay sorted by x (an insertion
   sort, since they hardly move between rows), and a sweep across them
   gives the spans. */

#include "gfx.h"

#define MAXE 1024

static Edge *order[MAXE], *act[MAXE];

static int floordiv(int a, int b)       /* b > 0 */
{
    int q = a / b;
    if (a % b < 0)
        q--;
    return q;
}

void rs_init(Raster *r, Edge *edges, int max)
{
    r->edges = edges;
    r->max = max < MAXE ? max : MAXE;
    r->n = 0;
    r->ymin = r->xmin = 0x7FFFFFFF;
    r->ymax = r->xmax = -0x7FFFFFFF;
}

void rs_edge(Raster *r, int x0, int y0, int x1, int y1)
{
    Edge *e;
    int t, dir = 1;
    if (y0 == y1 || r->n >= r->max)
        return;
    if (y0 > y1) {
        t = x0; x0 = x1; x1 = t;
        t = y0; y0 = y1; y1 = t;
        dir = -1;
    }
    e = &r->edges[r->n++];
    e->x0 = x0;
    e->y0 = y0;
    e->x1 = x1;
    e->y1 = y1;
    e->dir = dir;
    if (y0 < r->ymin) r->ymin = y0;
    if (y1 > r->ymax) r->ymax = y1;
    if (x0 > x1) {
        t = x0; x0 = x1; x1 = t;
    }
    if (x0 < r->xmin) r->xmin = x0;
    if (x1 > r->xmax) r->xmax = x1;
}

/* Sample row k is at y = k*S + S/2. Work out each edge's first and last
   sample rows, and sort the edges that have any by the first. */
static int prepare(Raster *r, int S)
{
    int i, j, n = 0, h = S / 2;
    Edge *e;
    for (i = 0; i < r->n; i++) {
        e = &r->edges[i];
        e->k0 = floordiv(e->y0 - h + S - 1, S);
        e->k1 = floordiv(e->y1 - h + S - 1, S) - 1;
        if (e->k0 > e->k1)
            continue;
        for (j = n; j > 0 && order[j - 1]->k0 > e->k0; j--)
            order[j] = order[j - 1];
        order[j] = e;
        n++;
    }
    return n;
}

/* An edge's crossing at its first sample row, and its step. */
static void start(Edge *e, int S)
{
    int dx = e->x1 - e->x0, num, q;
    e->dy = e->y1 - e->y0;
    num = (e->k0 * S + S / 2 - e->y0) * dx;
    q = floordiv(num, e->dy);
    e->x = e->x0 + q;
    e->err = num - q * e->dy;
    num = dx * S;
    e->q = floordiv(num, e->dy);
    e->r = num - e->q * e->dy;
}

typedef void (*SpanFn)(void *ctx, int k, int xa, int xb);

/* Find the spans of sample rows klo..khi-1 (rows before klo are stepped
   through but give no spans). */
static void sweep(Raster *r, int S, int klo, int khi, int rule, SpanFn span, void *ctx)
{
    int n = prepare(r, S), next = 0, na = 0, k, i, j, w, xa = 0, was;
    Edge *e;
    if (n == 0)
        return;
    k = order[0]->k0;
    while (next < n || na > 0) {
        if (na == 0 && order[next]->k0 > k)
            k = order[next]->k0;
        if (k >= khi)
            break;
        while (next < n && order[next]->k0 == k) {
            e = order[next++];
            start(e, S);
            for (j = na; j > 0 && act[j - 1]->x > e->x; j--)
                act[j] = act[j - 1];
            act[j] = e;
            na++;
        }
        if (k >= klo) {
            w = 0;
            for (i = 0; i < na; i++) {
                was = w;
                w += act[i]->dir;
                if (rule == GFX_EVENODD) {
                    if (w & 1)
                        xa = act[i]->x;
                    else
                        span(ctx, k, xa, act[i]->x);
                } else if (was == 0) {
                    xa = act[i]->x;
                } else if (w == 0) {
                    span(ctx, k, xa, act[i]->x);
                }
            }
        }
        for (i = j = 0; i < na; i++) {
            e = act[i];
            if (e->k1 == k)
                continue;
            e->x += e->q;
            e->err += e->r;
            if (e->err >= e->dy) {
                e->x++;
                e->err -= e->dy;
            }
            act[j++] = e;
        }
        na = j;
        for (i = 1; i < na; i++) {
            e = act[i];
            for (j = i; j > 0 && act[j - 1]->x > e->x; j--)
                act[j] = act[j - 1];
            act[j] = e;
        }
        k++;
    }
}

/* ---- plain fills ---- */

typedef struct {
    Surface *s;
    unsigned color;
    int rop;
} Solid;

static void solid_span(void *ctx, int y, int xa, int xb)
{
    Solid *c = ctx;
    gfx_fill(c->s, (xa + 127) >> 8, y, (xb + 127) >> 8, y + 1, c->color, c->rop);
}

void rs_fill(Raster *r, Surface *s, unsigned color, int rop, int rule)
{
    Solid c;
    c.s = s;
    c.color = color;
    c.rop = rop;
    sweep(r, 256, s->cy0, s->cy1, rule, solid_span, &c);
}

/* ---- anti-aliased fills ----

   Each sample row's spans are in sixteenths of a pixel. A span adds 16
   to every pixel it covers whole and the covered part to the ones at its
   ends; as differences between neighbouring pixels that's four additions
   whatever its length, and a running sum turns them into coverage once
   the four sample rows of a pixel row are in. */

#define MAXW 512

static int acc[MAXW + 2];

typedef struct {
    unsigned char *cov;
    int cpitch, w, row;
} Cover;

static void flush(Cover *c)
{
    unsigned char *p = c->cov + c->row * c->cpitch;
    int x, sum = 0;
    for (x = 0; x < c->w; x++) {
        sum += acc[x];
        acc[x] = 0;
        p[x] = sum;
    }
    acc[c->w] = 0;
    acc[c->w + 1] = 0;
}

static void aa_span(void *ctx, int k, int xa, int xb)
{
    Cover *c = ctx;
    int a = xa >> 4, b = xb >> 4, lim = c->w << 4, pa, pb, fa, fb;
    if (c->row != k >> 2) {
        if (c->row >= 0)
            flush(c);
        c->row = k >> 2;
    }
    if (a < 0)
        a = 0;
    if (b > lim)
        b = lim;
    if (a >= b)
        return;
    pa = a >> 4;
    fa = a & 15;
    pb = b >> 4;
    fb = b & 15;
    acc[pa] += 16 - fa;
    acc[pa + 1] += fa;
    acc[pb] += fb - 16;
    acc[pb + 1] -= fb;
}

void rs_fill_aa(Raster *r, unsigned char *cov, int cpitch, int w, int h, int rule)
{
    Cover c;
    if (w > MAXW)
        w = MAXW;
    c.cov = cov;
    c.cpitch = cpitch;
    c.w = w;
    c.row = -1;
    sweep(r, 64, 0, h * 4, rule, aa_span, &c);
    if (c.row >= 0)
        flush(&c);
}

/* ---- polygons ---- */

static Edge poly_edges[MAXE];

void gfx_poly(Surface *s, const int *xy, int n, unsigned color, int rop, int rule)
{
    Raster r;
    int i, j;
    rs_init(&r, poly_edges, MAXE);
    for (i = 0; i < n; i++) {
        j = i + 1 < n ? i + 1 : 0;
        rs_edge(&r, xy[2 * i] << 8, xy[2 * i + 1] << 8, xy[2 * j] << 8, xy[2 * j + 1] << 8);
    }
    rs_fill(&r, s, color, rop, rule);
}
