/* The splash: while the machine compiles Egret's prelude and the desktop
   (20 s at 3 MHz), a heron and an egret standing in the water, and a
   progress bar. The birds are vector drawings, 450 bytes of paths
   (below), filled anti-aliased by the graphics study's scan converter.
   main.c calls gui_boot before the prelude, and the lexer calls
   gui_compiling as it goes; the desktop's gui_init paints over it all. */

#include <string.h>
#include "egret.h"
#include "gui.h"
#include "theme.h"

/* Paths: 'F' r g b sets the colour; 'M' x y starts a shape, which 'L' x
   y and 'C' x1 y1 x2 y2 x y (a cubic Bezier) go on with, and 'Z' fills;
   0 ends. In pixels, from the bird's top left. */
static const unsigned char heron_art[] = {
    'F', 186, 150, 84,              /* legs */
    'M', 60, 128, 'L', 64, 128, 'L', 58, 196, 'L', 55, 196, 'Z',
    'M', 72, 128, 'L', 76, 128, 'L', 74, 160, 'L', 78, 196, 'L', 75, 196, 'L', 71, 160, 'Z',
    'F', 128, 140, 152,             /* body */
    'M', 40, 100, 'C', 66, 86, 96, 92, 102, 108, 'C', 106, 122, 92, 132, 72, 132,
    'C', 52, 132, 32, 130, 10, 142, 'C', 18, 124, 24, 108, 40, 100, 'Z',
    'F', 88, 98, 110,               /* wing */
    'M', 44, 103, 'C', 66, 95, 86, 100, 92, 112, 'C', 78, 120, 48, 124, 14, 140,
    'C', 24, 122, 30, 110, 44, 103, 'Z',
    'F', 226, 230, 234,             /* neck and head */
    'M', 82, 102, 'C', 72, 84, 74, 64, 86, 52, 'C', 94, 44, 94, 34, 89, 26, 'L', 99, 24,
    'C', 102, 34, 101, 46, 94, 56, 'C', 86, 68, 87, 84, 100, 106, 'Z',
    'M', 87, 25, 'C', 86, 17, 99, 15, 102, 22, 'C', 102, 28, 90, 31, 87, 25, 'Z',
    'F', 30, 30, 34,                /* crest */
    'M', 99, 19, 'C', 93, 16, 86, 17, 82, 21, 'C', 76, 25, 70, 29, 61, 35,
    'C', 72, 30, 80, 27, 87, 25, 'C', 92, 24, 96, 23, 99, 22, 'Z',
    'F', 232, 186, 52,              /* bill */
    'M', 100, 20, 'L', 136, 26, 'L', 100, 26, 'Z',
    'F', 30, 30, 34,                /* eye, and the streaks down the neck */
    'M', 96, 21, 'L', 98, 21, 'L', 98, 23, 'L', 96, 23, 'Z',
    'M', 96, 58, 'L', 98, 60, 'L', 94, 66, 'L', 92, 64, 'Z',
    'M', 92, 70, 'L', 94, 72, 'L', 91, 78, 'L', 89, 76, 'Z',
    0
};

static const unsigned char egret_art[] = {
    'F', 30, 30, 34,                /* legs */
    'M', 70, 124, 'L', 73, 124, 'L', 74, 196, 'L', 71, 196, 'Z',
    'M', 80, 124, 'L', 83, 124, 'L', 86, 156, 'L', 82, 196, 'L', 79, 196, 'L', 83, 156, 'Z',
    'F', 252, 252, 250,             /* body, neck, head, plumes */
    'M', 94, 106, 'C', 78, 96, 60, 98, 55, 110, 'C', 52, 122, 64, 128, 80, 128,
    'C', 94, 128, 104, 128, 118, 134, 'C', 112, 120, 106, 110, 94, 106, 'Z',
    'M', 66, 104, 'C', 76, 86, 72, 66, 60, 56, 'C', 52, 48, 52, 40, 58, 34, 'L', 48, 34,
    'C', 44, 44, 46, 52, 52, 60, 'C', 62, 70, 62, 88, 56, 106, 'Z',
    'M', 46, 32, 'C', 46, 26, 58, 25, 60, 31, 'C', 60, 36, 48, 38, 46, 32, 'Z',
    'M', 57, 30, 'C', 64, 32, 70, 38, 76, 50, 'C', 69, 42, 63, 36, 56, 34, 'Z',
    'M', 57, 32, 'C', 62, 36, 66, 42, 68, 52, 'C', 64, 44, 60, 38, 56, 35, 'Z',
    'F', 36, 36, 40,                /* bill */
    'M', 48, 30, 'L', 20, 34, 'L', 48, 34, 'Z',
    'F', 30, 30, 34,                /* eye */
    'M', 51, 30, 'L', 53, 30, 'L', 53, 32, 'L', 51, 32, 'Z',
    0
};

#define CARD_W 340
#define CARD_H 290
#define CARD_X ((SCREEN_W - CARD_W) / 2)
#define CARD_Y ((SCREEN_H - CARD_H) / 2)
#define SCENE_X (CARD_X + 20)           /* the birds' scene: 300 x 210 */
#define SCENE_Y (CARD_Y + 12)
#define WATER_Y (SCENE_Y + 186)
#define BAR_W 280
#define BAR_X ((SCREEN_W - BAR_W) / 2)
#define BAR_Y (CARD_Y + CARD_H - 22)

/* scratch for the scan converter, in VRAM: Gadgets' layers aren't up yet */
#define MAXEDGE 256
#define EDGES ((Edge *)BACKING)
#define COVER (BACKING + MAXEDGE * sizeof(Edge))

extern const char prelude_src[];
extern const unsigned prelude_len;

static int depth, on;
static unsigned lines0, lines1, bar;    /* the sources' lines; the bar's pixels filled */

/* The palette entry nearest a colour, worked out rather than searched
   for, at 8 bits a pixel: the nearest of the 6 x 6 x 6 cube's colours
   (theme.c: levels 0, 95, 135, 175, 215, 255, from entry 16), or of its
   24 greys (8, 18, ... 238, from 232). Elsewhere, gui_nearest. */
static int level(int v)
{
    return v < 48 ? 0 : v < 115 ? 1 : v < 155 ? 2 : v < 195 ? 3 : v < 235 ? 4 : 5;
}

static unsigned nearest(int r, int g, int b)
{
    static const unsigned char cube[6] = { 0, 95, 135, 175, 215, 255 };
    int ri, gi, bi, k, v, d1, d2;
    if (depth != 3)
        return gui_nearest(r, g, b);
    ri = level(r);
    gi = level(g);
    bi = level(b);
    d1 = (r - cube[ri]) * (r - cube[ri]) + (g - cube[gi]) * (g - cube[gi]) + (b - cube[bi]) * (b - cube[bi]);
    k = ((r + g + b) / 3 - 3) / 10;
    k = k < 0 ? 0 : k > 23 ? 23 : k;
    v = 8 + 10 * k;
    d2 = (r - v) * (r - v) + (g - v) * (g - v) + (b - v) * (b - v);
    return d2 < d1 ? 232 + k : 16 + 36 * ri + 6 * gi + bi;
}

static unsigned lines(const unsigned char *s, unsigned n)
{
    unsigned i, k = 1;
    for (i = 0; i < n; i++)
        if (s[i] == '\n')
            k++;
    return k;
}

/* how many coordinates follow an op */
static int args_of(int op)
{
    return op == 'C' ? 6 : op == 'M' || op == 'L' ? 2 : 0;
}

/* One shape, from its 'M' to its 'Z', at (ox, oy) in colour (r, g, b):
   its outline into the scan converter, coverage out (0 to 64 a pixel),
   and that onto the screen: whole pixels in runs, the edges blended
   with what's there. At 1 bit a pixel, the edges are black: an outline.
   Returns what follows the 'Z'. */
static const unsigned char *shape(const unsigned char *a, int ox, int oy, int r, int g, int b)
{
    const unsigned char *p;
    Raster rs;
    unsigned char *cov = COVER;
    unsigned fill = nearest(r, g, b);
    unsigned key[32], val[32];          /* blends: what was there and how much, to what */
    int x0 = 255, y0 = 255, x1 = 0, y1 = 0, w, h, x, y, k, i;
    int cx = 0, cy = 0, sx = 0, sy = 0;
    for (p = a; *p != 'Z'; p += 1 + args_of(*p))
        for (k = 1; k <= args_of(*p); k += 2) {
            if (p[k] < x0) x0 = p[k];
            if (p[k] > x1) x1 = p[k];
            if (p[k + 1] < y0) y0 = p[k + 1];
            if (p[k + 1] > y1) y1 = p[k + 1];
        }
    w = x1 - x0 + 2;
    h = y1 - y0 + 2;
    rs_init(&rs, EDGES, MAXEDGE);
    /* the points in 24.8, from the shape's top left */
    for (p = a; *p != 'Z'; p += 1 + args_of(*p)) {
        int px = (p[1] - x0) << 8, py = (p[2] - y0) << 8;
        if (*p == 'M') {
            if (p != a)
                rs_edge(&rs, cx, cy, sx, sy);
            sx = cx = px;
            sy = cy = py;
        } else if (*p == 'L') {
            rs_edge(&rs, cx, cy, px, py);
            cx = px;
            cy = py;
        } else {
            /* eight steps along the curve: (u^3 p0 + 3u^2t p1 + 3ut^2 p2 + t^3 p3) / 512 */
            int x1c = px, y1c = py, x2c = (p[3] - x0) << 8, y2c = (p[4] - y0) << 8;
            int x3c = (p[5] - x0) << 8, y3c = (p[6] - y0) << 8, t, u, nx, ny;
            for (t = 1; t <= 8; t++) {
                u = 8 - t;
                nx = (u * u * u * cx + 3 * u * u * t * x1c + 3 * u * t * t * x2c + t * t * t * x3c) >> 9;
                ny = (u * u * u * cy + 3 * u * u * t * y1c + 3 * u * t * t * y2c + t * t * t * y3c) >> 9;
                rs_edge(&rs, cx, cy, nx, ny);
                cx = nx;
                cy = ny;
            }
        }
    }
    rs_edge(&rs, cx, cy, sx, sy);
    memset(key, 0xFF, sizeof key);
    memset(cov, 0, w * h);
    rs_fill_aa(&rs, cov, w, w, h, GFX_NONZERO);
    ox += x0;
    oy += y0;
    for (y = 0; y < h; y++) {
        const unsigned char *c = cov + y * w;
        for (x = 0; x < w; ) {
            if (c[x] >= 64) {
                for (i = x; i < w && c[i] >= 64; i++)
                    ;
                gfx_fill(&screen, ox + x, oy + y, ox + i, oy + y + 1, fill, GFX_COPY);
                x = i;
                continue;
            }
            if (c[x] >= 4) {
                if (depth == 0) {
                    gfx_pixel(&screen, ox + x, oy + y, c_black, GFX_COPY);
                } else {
                    unsigned d = gfx_get(&screen, ox + x, oy + y), f = (c[x] + 4) & ~7;
                    unsigned kk = d << 8 | f, hh = (d ^ f >> 3 ^ d >> 5) & 31;
                    if (key[hh] != kk) {
                        int dr, dg, db;
                        theme_rgb(depth, d, &dr, &dg, &db);
                        key[hh] = kk;
                        val[hh] = nearest(dr + (r - dr) * (int)f / 64, dg + (g - dg) * (int)f / 64,
                                          db + (b - db) * (int)f / 64);
                    }
                    gfx_pixel(&screen, ox + x, oy + y, val[hh], GFX_COPY);
                }
            }
            x++;
        }
    }
    return p + 1;
}

static void draw_art(const unsigned char *a, int ox, int oy)
{
    int r = 0, g = 0, b = 0;
    while (*a) {
        if (*a == 'F') {
            r = a[1];
            g = a[2];
            b = a[3];
            a += 4;
        } else {
            a = shape(a, ox, oy, r, g, b);
        }
    }
}

static void text(int x, int y, const char *s, unsigned fg)
{
    font_draw(&screen, &fonts[0], x, y, s, fg, 0);
}

/* Called with the input's first line, which says "SCREEN_DEPTH = d"
   (build.py's console_input; no splash for anything else), and then with
   all of the input, for the bar's length */
void gui_boot(const unsigned char *in, unsigned n)
{
    static const char want[] = "SCREEN_DEPTH = ";
    unsigned k = sizeof want - 1;
    unsigned sky, water, ripple, grey;
    if (on) {
        lines1 = lines(in, n);
        return;
    }
    if (n <= k || memcmp(in, want, k) != 0 || in[k] < '0' || in[k] > '3')
        return;
    depth = in[k] - '0';
    gui_setup(depth);                   /* (the desktop's gui_init does it again) */
    lines0 = lines((const unsigned char *)prelude_src, prelude_len);
    lines1 = 1;
    sky = depth ? nearest(215, 235, 255) : c_white;
    water = nearest(120, 170, 220);
    ripple = depth ? nearest(190, 220, 245) : c_black;
    grey = depth ? nearest(96, 96, 96) : c_black;
    gfx_noclip(&screen);
    gfx_fill(&screen, CARD_X + 4, CARD_Y + 4, CARD_X + CARD_W + 4, CARD_Y + CARD_H + 4, c_shadow, GFX_COPY);
    gfx_fill(&screen, CARD_X, CARD_Y, CARD_X + CARD_W, CARD_Y + CARD_H, c_white, GFX_COPY);
    gfx_fill(&screen, CARD_X, CARD_Y, CARD_X + CARD_W, WATER_Y, sky, GFX_COPY);
    gfx_frame(&screen, CARD_X, CARD_Y, CARD_X + CARD_W, CARD_Y + CARD_H, 1, c_black, GFX_COPY);
    draw_art(heron_art, SCENE_X + 10, SCENE_Y);
    draw_art(egret_art, SCENE_X + 140, SCENE_Y + 4);
    /* the water over the birds' feet, and its ripples */
    if (depth)
        gfx_fill(&screen, CARD_X + 1, WATER_Y, CARD_X + CARD_W - 1, SCENE_Y + 212, water, GFX_COPY);
    gfx_fill(&screen, SCENE_X + 40, WATER_Y + 4, SCENE_X + 100, WATER_Y + 6, ripple, GFX_COPY);
    gfx_fill(&screen, SCENE_X + 190, WATER_Y + 8, SCENE_X + 260, WATER_Y + 10, ripple, GFX_COPY);
    gfx_fill(&screen, SCENE_X + 10, WATER_Y + 14, SCENE_X + 60, WATER_Y + 16, ripple, GFX_COPY);
    gfx_fill(&screen, SCENE_X + 150, WATER_Y + 18, SCENE_X + 230, WATER_Y + 20, ripple, GFX_COPY);
    if (!depth)
        gfx_fill(&screen, CARD_X + 1, SCENE_Y + 212, CARD_X + CARD_W - 1, SCENE_Y + 213, c_black, GFX_COPY);
    text(BAR_X, BAR_Y - 22, "Egret on the Heron", c_black);
    text(BAR_X + 132, BAR_Y - 22, "compiling the desktop...", grey);
    gfx_frame(&screen, BAR_X, BAR_Y, BAR_X + BAR_W, BAR_Y + 10, 1, c_black, GFX_COPY);
    bar = 0;
    on = 1;
}

/* The compiler is at this line of the prelude or the desktop: the bar
   that far. Returns the line to be told at next, a pixel on. */
int gui_compiling(const char *source, int line)
{
    unsigned done, px;
    if (!on)
        return 0x7FFFFFFF;
    done = strcmp(source, "prelude") == 0 ? line : lines0 + line;
    px = done * (BAR_W - 2) / (lines0 + lines1);
    if (px > BAR_W - 2)
        px = BAR_W - 2;
    if (px > bar) {
        gfx_noclip(&screen);
        gfx_fill(&screen, BAR_X + 1 + bar, BAR_Y + 1, BAR_X + 1 + px, BAR_Y + 9, c_title, GFX_COPY);
        bar = px;
    }
    return line + (lines0 + lines1) / (BAR_W - 2) + 1;
}
