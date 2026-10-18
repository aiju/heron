/* The library's operations in every pixel format, timed with the beam
   (ticks of 19.86 ns): fills, copies at every alignment, 1-bit expansion,
   text, lines and pixels, on surfaces in memory, each over enough pixels
   to time. Prints "@perf FORMAT.OP TICKS PIXELS" for bench.py to turn into
   a time per screen of 640 x 480. */

#include <stdio.h>
#include <string.h>
#include "gfx.h"
#include "video.h"
#include "perf.h"

#define W 640
#define H 96
#define WORDS 160               /* a row of 640 pixels at 8 bits */

static unsigned a_bits[WORDS * H], b_bits[WORDS * H], bm_bits[20 * H];
static unsigned seed = 7;
static const char *fmt_names[PF_N] = {"lin1", "lin2", "lin4", "lin8", "chk1", "chk2", "pl2",
                                      "pl4", "pl8"};

static unsigned rnd(void)
{
    seed = seed * 1103515245u + 12345u;
    return seed >> 8;
}

static void report(int fmt, const char *op, unsigned ticks, unsigned pixels)
{
    printf("@perf %s.%s %u %u\n", fmt_names[fmt], op, ticks, pixels);
}

static void bench(int fmt)
{
    Surface a, b;
    Bitmap bm;
    unsigned t;
    int k, x, ppw;
    static const char text[] = "The quick brown fox jumps over the lazy dog, 0123456789 times.";
    gfx_init(&a, a_bits, W, H, WORDS, fmt);
    gfx_init(&b, b_bits, W, H, WORDS, fmt);
    ppw = 1 << a.pshift;
    bm.bits = bm_bits;
    bm.pitch = 20;

    /* fills: 512 x 64, on words and off them */
    perf_start(); t = video_ticks();
    for (k = 0; k < 4; k++)
        gfx_fill(&a, 64, 16, 576, 80, k + 1, ROP_COPY);
    report(fmt, "fill", video_ticks() - t, 4 * 512 * 64);
    t = video_ticks();
    for (k = 0; k < 4; k++)
        gfx_fill(&a, 61, 16, 573, 80, k + 1, ROP_COPY);
    report(fmt, "fill_odd", video_ticks() - t, 4 * 512 * 64);
    t = video_ticks();
    for (k = 0; k < 4; k++)
        gfx_fill(&a, 61, 16, 573, 80, k + 1, ROP_XOR);
    report(fmt, "fill_xor", video_ticks() - t, 4 * 512 * 64);
    /* small fills: 24 x 12 boxes, a widget's worth */
    t = video_ticks();
    for (k = 0; k < 100; k++)
        gfx_fill(&a, 13 + 5 * k, 20 + k % 40, 37 + 5 * k, 32 + k % 40, k, ROP_COPY);
    report(fmt, "fill_small", video_ticks() - t, 100 * 24 * 12);

    /* copies 512 x 64: the same phase, then shifted by 1 pixel and by half a word */
    t = video_ticks();
    for (k = 0; k < 2; k++)
        gfx_blit(&b, 64, 16, &a, 64 + 8 * ppw * k, 16, 512, 64, ROP_COPY);
    report(fmt, "copy", video_ticks() - t, 2 * 512 * 64);
    t = video_ticks();
    for (k = 0; k < 2; k++)
        gfx_blit(&b, 65, 16, &a, 64, 16, 512, 64, ROP_COPY);
    report(fmt, "copy_shift1", video_ticks() - t, 2 * 512 * 64);
    t = video_ticks();
    for (k = 0; k < 2; k++)
        gfx_blit(&b, 64 + ppw / 2, 16, &a, 64, 16, 512, 64, ROP_COPY);
    report(fmt, "copy_shift_half", video_ticks() - t, 2 * 512 * 64);
    /* within a surface, moving right by 3: overlapping rows */
    t = video_ticks();
    gfx_blit(&a, 67, 16, &a, 64, 16, 512, 64, ROP_COPY);
    report(fmt, "copy_overlap", video_ticks() - t, 512 * 64);

    /* 1-bit expansion, 512 x 64: opaque on a word, opaque off it, transparent
       (the format's tables built first) */
    gfx_expand(&a, 64, 16, &bm, 0, 0, 8, 1, 3, 1, 1);
    t = video_ticks();
    gfx_expand(&a, 64, 16, &bm, 0, 0, 512, 64, 3, 1, 1);
    report(fmt, "expand", video_ticks() - t, 512 * 64);
    t = video_ticks();
    gfx_expand(&a, 67, 16, &bm, 0, 0, 512, 64, 3, 1, 1);
    report(fmt, "expand_odd", video_ticks() - t, 512 * 64);
    t = video_ticks();
    gfx_expand(&a, 67, 16, &bm, 0, 0, 512, 64, 3, 1, 0);
    report(fmt, "expand_trans", video_ticks() - t, 512 * 64);

    /* text: proportional and cells, in characters */
    t = video_ticks();
    for (k = 0; k < 4; k++)
        font_draw(&a, font_sans, 3 + k, 20 + 15 * k, text, 3, -1);
    report(fmt, "text_sans", video_ticks() - t, 4 * (sizeof text - 1));
    t = video_ticks();
    for (k = 0; k < 4; k++)
        font_cells(&a, 8 * k + 8, 16 + 16 * k, text, 64, 3, 1);
    report(fmt, "text_cells", video_ticks() - t, 4 * 64);
    t = video_ticks();
    for (k = 0; k < 4; k++)
        font_cells(&a, 8 * k + 11, 16 + 16 * k, text, 64, 3, 1);
    report(fmt, "text_cells_odd", video_ticks() - t, 4 * 64);

    /* lines: 100 of about 100 pixels in all directions, in pixels drawn */
    t = video_ticks();
    {
        unsigned px = 0;
        for (k = 0; k < 100; k++) {
            int x0 = 100 + rnd() % 400, y0 = rnd() % H, x1 = x0 + (int)(rnd() % 200) - 100,
                y1 = rnd() % H, dx = x1 - x0, dy = y1 - y0;
            gfx_line(&a, x0, y0, x1, y1, k, ROP_COPY);
            dx = dx < 0 ? -dx : dx;
            dy = dy < 0 ? -dy : dy;
            px += (dx > dy ? dx : dy) + 1;
        }
        report(fmt, "line", video_ticks() - t, px);
    }
    /* single pixels */
    t = video_ticks();
    {
        int px = 0, py = 0;
        for (k = 0; k < 2000; k++) {
            gfx_pixel(&a, px, py, k, ROP_COPY);
            px += 7;
            if (px >= W)
                px -= W;
            if (++py == H)
                py = 0;
        }
    }
    report(fmt, "pixel", video_ticks() - t, 2000);
    (void)x;
}

int bench_formats = 0x1FF;      /* a bit a format */

int main(void)
{
    int fmt, k;
    video_init(0, 0);
    font_init();
    for (k = 0; k < 20 * H; k++)
        bm_bits[k] = rnd() ^ rnd() << 16;
    for (fmt = 0; fmt < PF_N; fmt++)
        if (bench_formats >> fmt & 1)
            bench(fmt);
    printf("@done\n");
    return 0;
}
