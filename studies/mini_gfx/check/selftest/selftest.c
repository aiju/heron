/* The library against pixel-at-a-time references, in every format:
   random fills (every raster operation), copies within a surface and
   between two (overlapping, shifted), 1-bit expansion, masked sprites and
   lines, each done by the library on one surface and pixel by pixel on
   another, then compared. Prints "selftest ok" or the first differences. */

#include <stdio.h>
#include <string.h>
#include "gfx.h"
#include "video.h"

#define W 100
#define H 24
#define PITCH 26                /* words: enough for 100 pixels at 8 bits */

static unsigned a_bits[PITCH * H], b_bits[PITCH * H], src_bits[PITCH * H];
static unsigned bm_bits[8 * H];
static unsigned seed = 12345;
static int errors;

static unsigned rnd(void)
{
    seed = seed * 1103515245u + 12345u;
    return seed >> 8;
}

static int rr(int n)
{
    return (int)(rnd() % (unsigned)n);
}

static unsigned bmbit(const Bitmap *b, int x, int y)
{
    return b->bits[y * b->pitch + (x >> 5)] >> (x & 31) & 1;
}

static void ref_rop(Surface *s, int x, int y, unsigned c, int rop)
{
    gfx_pixel(s, x, y, c, rop);
}

static int compare(Surface *a, Surface *b, const char *what, int fmt, int op)
{
    int x, y;
    if (!memcmp(a->bits, b->bits, sizeof a_bits))
        return 1;
    for (y = 0; y < H; y++)
        for (x = 0; x < W; x++)
            if (gfx_get(a, x, y) != gfx_get(b, x, y)) {
                if (errors++ < 8)
                    printf("fmt %d %s op %d: (%d,%d) %u want %u\n", fmt, what, op, x, y,
                           gfx_get(a, x, y), gfx_get(b, x, y));
                return 0;
            }
    if (errors++ < 8)
        printf("fmt %d %s op %d: the same pixels, other bits\n", fmt, what, op);
    return 0;
}

static void sync(Surface *a, Surface *b)
{
    memcpy(b->bits, a->bits, sizeof a_bits);
}

static void test_format(int fmt)
{
    Surface a, b, src;
    Bitmap bm;
    const Format *f = gfx_format(fmt);
    unsigned maxc = (1u << f->bpp) - 1;
    int op, x, y, k;
    gfx_init(&a, a_bits, W, H, PITCH, fmt);
    gfx_init(&b, b_bits, W, H, PITCH, fmt);
    gfx_init(&src, src_bits, W, H, PITCH, fmt);
    bm.bits = bm_bits;
    bm.pitch = 8;
    for (k = 0; k < PITCH * H; k++) {
        a_bits[k] = rnd() ^ rnd() << 16;
        src_bits[k] = rnd() ^ rnd() << 16;
    }
    for (k = 0; k < 8 * H; k++)
        bm_bits[k] = rnd() ^ rnd() << 16;
    sync(&a, &b);
    for (op = 0; op < 90; op++) {
        int kind = op % 6, rop = rr(4);
        int x0 = rr(W + 20) - 10, y0 = rr(H + 10) - 5, w = rr(W / 2) + 1, h = rr(H / 2) + 1;
        unsigned c = rnd() & maxc, c2 = rnd() & maxc;
        Rect cl;
        cl.x0 = rr(20);
        cl.y0 = rr(6);
        cl.x1 = W - rr(20);
        cl.y1 = H - rr(6);
        gfx_clip_rect(&a, &cl);
        gfx_clip_rect(&b, &cl);
        if (kind == 0) {
            gfx_fill(&a, x0, y0, x0 + w, y0 + h, c, rop);
            for (y = y0; y < y0 + h; y++)
                for (x = x0; x < x0 + w; x++)
                    ref_rop(&b, x, y, c, rop);
        } else if (kind == 1 || kind == 2) {
            /* within the surface (kind 1, overlapping), or from src */
            Surface *sa = kind == 1 ? &a : &src, *sb = kind == 1 ? &b : &src;
            int sx = x0 + rr(17) - 8, sy = y0 + rr(9) - 4;
            static unsigned vals[W * H];
            int n = 0;
            if (kind == 2) {
                sx = rr(W);
                sy = rr(H);
            }
            gfx_blit(&a, x0, y0, sa, sx, sy, w, h, rop);
            for (y = 0; y < h; y++)
                for (x = 0; x < w; x++)
                    vals[n++] = (sx + x >= 0 && sx + x < W && sy + y >= 0 && sy + y < H)
                        ? gfx_get(sb, sx + x, sy + y) : 0xFFFF;
            n = 0;
            for (y = 0; y < h; y++)
                for (x = 0; x < w; x++, n++)
                    if (vals[n] != 0xFFFF)
                        ref_rop(&b, x0 + x, y0 + y, vals[n], rop);
        } else if (kind == 3) {
            int sx = rr(200), sy = rr(H - h + 1), opaque = rr(2);
            gfx_expand(&a, x0, y0, &bm, sx, sy, w, h, c, c2, opaque);
            for (y = 0; y < h; y++)
                for (x = 0; x < w; x++) {
                    if (bmbit(&bm, sx + x, sy + y))
                        ref_rop(&b, x0 + x, y0 + y, c, ROP_COPY);
                    else if (opaque)
                        ref_rop(&b, x0 + x, y0 + y, c2, ROP_COPY);
                }
        } else if (kind == 4) {
            int sx = rr(W - 10), sy = rr(H - 10);
            gfx_masked(&a, x0, y0, &src, &bm, sx, sy, w, h);
            for (y = 0; y < h; y++)
                for (x = 0; x < w; x++)
                    if (sx + x < W && sy + y < H && bmbit(&bm, sx + x, sy + y))
                        ref_rop(&b, x0 + x, y0 + y, gfx_get(&src, sx + x, sy + y), ROP_COPY);
        } else {
            int x1 = rr(W + 40) - 20, y1 = rr(H + 20) - 10;
            int dx = x1 - x0, dy = y1 - y0, adx = dx < 0 ? -dx : dx, ady = dy < 0 ? -dy : dy;
            int t;
            gfx_line(&a, x0, y0, x1, y1, c, rop);
            if (adx >= ady) {
                int xs = x0, ys = y0, xe = x1, ye = y1;
                if (dx < 0) { xs = x1; ys = y1; xe = x0; ye = y0; }
                for (t = 0; t <= adx; t++) {
                    int m = adx ? (2 * t * ady + adx) / (2 * adx) : 0;
                    ref_rop(&b, xs + t, ys + (ye >= ys ? m : -m), c, rop);
                }
            } else {
                int xs = x0, ys = y0, xe = x1, ye = y1;
                if (dy < 0) { xs = x1; ys = y1; xe = x0; ye = y0; }
                for (t = 0; t <= ady; t++) {
                    int m = (2 * t * adx + ady) / (2 * ady);
                    ref_rop(&b, xs + (xe >= xs ? m : -m), ys + t, c, rop);
                }
            }
        }
        if (!compare(&a, &b, kind == 0 ? "fill" : kind == 1 ? "blit within" : kind == 2 ?
                     "blit from" : kind == 3 ? "expand" : kind == 4 ? "masked" : "line", fmt, op)) {
            printf("  x0 %d y0 %d w %d h %d rop %d clip %d %d %d %d\n", x0, y0, w, h, rop,
                   cl.x0, cl.y0, cl.x1, cl.y1);
            sync(&a, &b);
        }
    }
}

/* text: font_draw's string at once against its glyphs one at a time */
static void test_text(int fmt)
{
    static const char str[] = "Wavy jig, ho! 0123 {x} Mjq";
    Surface a, b;
    const Font *f = font_sans;
    int k, pen, x = 7 + fmt, y = 15, opaque;
    gfx_init(&a, a_bits, W, H, PITCH, fmt);
    gfx_init(&b, b_bits, W, H, PITCH, fmt);
    for (opaque = 0; opaque < 2; opaque++) {
        for (k = 0; k < PITCH * H; k++)
            a_bits[k] = b_bits[k] = rnd();
        gfx_clip(&a, 0, 0, W - 9, H);
        gfx_clip(&b, 0, 0, W - 9, H);
        font_draw(&a, f, x, y, str, 1, opaque ? 2 : -1);
        if (opaque)
            gfx_fill(&b, x, y - f->ascent, x + font_width(f, str), y + f->descent, 2, ROP_COPY);
        pen = x;
        for (k = 0; str[k]; k++) {
            const Glyph *g = &f->glyphs[(unsigned char)str[k] - f->first];
            if (g->w)
                gfx_expand(&b, pen + g->xoff, y + g->yoff, &f->strike, g->sx, 0, g->w, g->h, 1, 0,
                           0);
            pen += g->adv;
        }
        compare(&a, &b, opaque ? "text opaque" : "text", fmt, 0);
    }
}

int main(void)
{
    int fmt;
    font_init();
    for (fmt = 0; fmt < PF_N; fmt++)
        test_text(fmt);
    for (fmt = 0; fmt < PF_N; fmt++) {
        test_format(fmt);
        printf("format %d done\n", fmt);
    }
    printf(errors ? "selftest: %d errors\n" : "selftest ok\n", errors);
    printf("@done\n");
    return 0;
}
