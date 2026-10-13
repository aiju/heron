/* The benchmark scenes. Each draws on a 640 x 480 screen at the depth
   it's given, and calls mark() at the end of every phase. Random shapes
   are made before the phase that draws them, so the phases measure only
   the drawing; mark_n's count is the work done (pixels, glyphs, ...). */

#include "scenes.h"
#include "theme.h"

unsigned fb_mem[SCREEN_W * SCREEN_H / 4];

Surface screen;

static unsigned seed = 1;

static unsigned rnd(void)              /* xorshift32 */
{
    seed ^= seed << 13;
    seed ^= seed >> 17;
    seed ^= seed << 5;
    return seed;
}

static int rndn(int n)                  /* 0..n-1, n up to 65536 */
{
    return (int)((rnd() >> 16) * (unsigned)n >> 16);
}

void mark(const char *name)
{
    mark_n(name, 0);
}

/* ---- primitives ---- */

#define NR 400
static int sh[NR * 5];                  /* shapes: up to 5 numbers each */

static int random_rects(int n, int minw, int maxw, int minh, int maxh)
{
    int i, *p = sh, w, h, px = 0;
    for (i = 0; i < n; i++, p += 5) {
        w = minw + rndn(maxw - minw + 1);
        h = minh + rndn(maxh - minh + 1);
        p[0] = rndn(SCREEN_W - w + 1);
        p[1] = rndn(SCREEN_H - h + 1);
        p[2] = p[0] + w;
        p[3] = p[1] + h;
        p[4] = rnd();
        px += w * h;
    }
    return px;
}

static void draw_rects(Surface *s, int n, int rop)
{
    int i, *p = sh, m = gfx_maxcolor(s->depth);
    for (i = 0; i < n; i++, p += 5)
        gfx_fill(s, p[0], p[1], p[2], p[3], p[4] & m, rop);
}

static int random_lines(int n, int maxlen, int out)
{
    int i, *p = sh, dx, dy, px = 0;
    for (i = 0; i < n; i++, p += 5) {
        p[0] = rndn(SCREEN_W + 2 * out) - out;
        p[1] = rndn(SCREEN_H + 2 * out) - out;
        p[2] = p[0] + rndn(2 * maxlen + 1) - maxlen;
        p[3] = p[1] + rndn(2 * maxlen + 1) - maxlen;
        p[4] = rnd();
        dx = p[2] - p[0];
        dy = p[3] - p[1];
        if (dx < 0) dx = -dx;
        if (dy < 0) dy = -dy;
        px += (dx > dy ? dx : dy) + 1;
    }
    return px;
}

static void draw_lines(Surface *s, int n, int rop)
{
    int i, *p = sh, m = gfx_maxcolor(s->depth);
    for (i = 0; i < n; i++, p += 5)
        gfx_line(s, p[0], p[1], p[2], p[3], (p[4] & m) | 1, rop);
}

static const int star[] = {
    0, -100, 24, -32, 95, -31, 38, 12, 59, 81, 0, 40, -59, 81, -38, 12, -95, -31, -24, -32
};

static void scene_prims(Surface *s)
{
    int n, i, k, m = gfx_maxcolor(s->depth), xy[40];
    unsigned pat[8];

    gfx_fill(s, 0, 0, SCREEN_W, SCREEN_H, m, GFX_COPY);
    mark_n("clear", SCREEN_W * SCREEN_H);

    n = random_rects(100, 8, 200, 8, 200);
    mark("_");
    draw_rects(s, 100, GFX_COPY);
    mark_n("rect", n);
    draw_rects(s, 100, GFX_XOR);
    mark_n("rect.xor", n);
    n = random_rects(NR, 8, 8, 8, 8);
    mark("_");
    draw_rects(s, NR, GFX_COPY);
    mark_n("rect.8x8", n);
    n = random_rects(NR, 1, 3, 1, 3);
    mark("_");
    draw_rects(s, NR, GFX_COPY);
    mark_n("rect.tiny", n);

    for (k = 0; k < 8; k++)
        pat[k] = theme_pattern(s->depth, k);
    gfx_fill_pat(s, 40, 40, 600, 440, pat, GFX_COPY);
    mark_n("pattern", 560 * 400);

    gfx_fill(s, 0, 0, SCREEN_W, SCREEN_H, 0, GFX_COPY);
    n = random_lines(NR, 150, 0);
    mark("_");
    draw_lines(s, NR, GFX_COPY);
    mark_n("line", n);
    draw_lines(s, NR, GFX_XOR);
    mark_n("line.xor", n);
    n = random_lines(NR, 20, 0);
    mark("_");
    draw_lines(s, NR, GFX_COPY);
    mark_n("line.short", n);
    random_lines(100, 600, 300);
    mark("_");
    draw_lines(s, 100, GFX_COPY);
    mark_n("line.clipped", 100);
    for (i = 0; i < 100; i++)
        gfx_line(s, 20, 20 + i * 4, 619, 20 + i * 4, i & m, GFX_COPY);
    mark_n("line.horizontal", 100 * 600);
    for (i = 0; i < 100; i++)
        gfx_line(s, 20 + i * 6, 20, 20 + i * 6, 459, i & m, GFX_COPY);
    mark_n("line.vertical", 100 * 440);

    gfx_fill(s, 0, 0, SCREEN_W, SCREEN_H, 0, GFX_COPY);
    for (i = 0; i < 40; i++)
        gfx_ellipse(s, 320 + (i % 8) * 20 - 70, 240 + (i / 8) * 20 - 40, 10 + i * 5, 8 + i * 4,
                    (i & m) | 1, GFX_COPY);
    mark_n("ellipse", 40);
    for (i = 0; i < 40; i++)
        gfx_fill_ellipse(s, 40 + (i % 8) * 80, 40 + (i / 8) * 100, 10 + i, 10 + (i * 7) % 40,
                         (i & m) | 1, GFX_COPY);
    mark_n("ellipse.fill", 40);

    gfx_fill(s, 0, 0, SCREEN_W, SCREEN_H, 0, GFX_COPY);
    for (k = 0; k < 20; k++) {
        /* even k: a pentagram, even-odd (a hollow middle); odd k: the
           star's outline, non-zero */
        n = k & 1 ? 10 : 5;
        for (i = 0; i < n; i++) {
            int v = k & 1 ? i : (4 * i) % 10;
            xy[2 * i] = 80 + (k % 5) * 120 + star[2 * v] * (k + 10) / 30;
            xy[2 * i + 1] = 110 + (k / 5) * 90 + star[2 * v + 1] * (k + 10) / 30;
        }
        gfx_poly(s, xy, n, (k & m) | 1, GFX_COPY, k & 1 ? GFX_NONZERO : GFX_EVENODD);
    }
    mark_n("polygon", 20);

    /* copying: a busy picture first */
    for (i = 0; i < 64; i++)
        gfx_fill(s, (i * 37) % 600, (i * 53) % 440, (i * 37) % 600 + 40, (i * 53) % 440 + 40,
                 i & m, GFX_XOR);
    mark("_");
    gfx_blit(s, 352, 64, s, 32, 64, 256, 256, GFX_COPY);
    mark_n("blit.aligned", 256 * 256);
    gfx_blit(s, 355, 70, s, 32, 64, 256, 256, GFX_COPY);
    mark_n("blit.unaligned", 256 * 256);
    gfx_blit(s, 0, 0, s, 0, 16, SCREEN_W, SCREEN_H - 16, GFX_COPY);
    mark_n("scroll.up", SCREEN_W * (SCREEN_H - 16));
    gfx_blit(s, 1, 0, s, 0, 0, SCREEN_W - 1, SCREEN_H, GFX_COPY);
    mark_n("scroll.right", (SCREEN_W - 1) * SCREEN_H);
    for (i = 0; i < 100; i++)
        gfx_expand(s, (i * 61) % 620, (i * 47) % 460, &icon, 0, 0, 16, 16, (i & m) | 1, 0, 0);
    mark_n("icon", 100);
    for (i = 0; i < 100; i++)
        gfx_expand(s, (i * 61) % 620, (i * 47) % 460, &icon, 0, 0, 16, 16, (i & m) | 1, 0, 1);
    mark_n("icon.opaque", 100);
}

int run_scene(const char *name, int depth)
{
    gfx_tables();
    gfx_init(&screen, fb_mem, SCREEN_W, SCREEN_H, (SCREEN_W << depth) >> 3, depth);
    theme_init(depth);
    if (name[0] == 'p') {
        scene_prims(&screen);
        return 0;
    }
    return -1;
}
