/* Plasma and fire in M1 (320 x 480 x 8, RFC 0042): how many pixels the
   CPU can touch in a frame, and what the palette and the descriptors do
   for nothing instead. Each part measured:

     1  a plasma computed pixel by pixel each frame, four pixels a word:
        p(x, y) = A[x + a(y)] + B[x + b(y)] + c(y), A and B rows of
        bytes kept in four copies shifted a byte apart (so any offset is
        a word's load), each term under 85 so that a plain 32-bit add adds
        four pixels without carries; at 320 x 240, 120 and 60, the lines
        repeated by the descriptors, two buffers flipped with TSEL; the
        inner loop in C, or in assembly (the asm and blk variants)
     2  the same in L1 (--layout L1), where M1's pixels are scattered bit
        by bit (bit i of pixel p at 8i + 2p, or 8(i - 4) + 2p + 1): each
        word made from its four bytes through a table
     3  palette cycling: the plasma drawn once, the 256 entries rotated
        each frame
     4  a descriptor plasma at the full 320 x 480: with one table term,
        p(x, y) = A[x + a(y)] + c(y), every line is a row of A + c from
        some byte on; the 85 rows A + c (for c = 0..84), each in four
        copies a byte apart, are drawn once in bank 1, and each frame
        the descriptors point each line into the right one: no pixel
        touched, and the palette cycles
     5  fire: each pixel the average of four below it, cooled, a burning
        logo, four pixels a word in assembly; at 320 x 120 and 320 x 60

   The palette writes and descriptors cost what the raster bars measured;
   here what matters is the CPU's work a pixel. */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "gfx.h"
#include "video.h"
#include "perf.h"
#include "fx.h"

/* plasma.s */
void plasma_row_asm(unsigned *d, const unsigned *a, const unsigned *b, unsigned c, int n);
void fire_rows_asm(unsigned *d, const unsigned *s, int rows, int words);
void plasma_row_l1_asm(unsigned *d, const unsigned *a, const unsigned *b, unsigned c, int n,
                       const unsigned *t);

#define PAL ((volatile unsigned *)0xF0000400)
#define W 80                        /* a line's words */

static unsigned *buf[2];            /* two pictures of up to 240 rows (plus 2 for the fire) */
static unsigned *rows_ac;           /* 4: the rows A + c */
static int t;

/* ---------------------------------------------------------------- the palettes */

static unsigned pal_base[512];      /* a cyclic palette, twice, rotated by palette_cycle */

static void palette_plasma(void)
{
    int i;
    for (i = 0; i < 256; i++) {
        /* three cosines a third apart, and a second, faster one on blue */
        int r = 128 + fx_sin[(i + 64) & 255] / 2;
        int g = 128 + fx_sin[(i + 64 + 85) & 255] / 2;
        int b = 128 + fx_sin[(2 * i + 64 + 170) & 255] / 2;
        pal_base[i] = pal_base[i + 256] =
            rgb565(r > 255 ? 255 : r, g > 255 ? 255 : g, b > 255 ? 255 : b);
    }
}

/* entry i gets colour i + k */
static void palette_cycle(int k)
{
    volatile unsigned *p = PAL;
    const unsigned *c = pal_base + (k & 255);
    int i;
    for (i = 0; i < 256; i += 4) {
        p[0] = c[0];
        p[1] = c[1];
        p[2] = c[2];
        p[3] = c[3];
        p += 4;
        c += 4;
    }
}

static void palette_fire(void)
{
    int i, r, g, b;
    for (i = 0; i < 256; i++) {
        r = i * 3;
        g = (i - 70) * 2;
        b = (i - 160) * 3;
        r = r > 255 ? 255 : r;
        g = g < 0 ? 0 : g > 255 ? 255 : g;
        b = b < 0 ? 0 : b > 255 ? 255 : b;
        video_pal(i, rgb565(r, g, b));
    }
}

/* ---------------------------------------------------------------- the descriptors */

/* table k: the screen's 480 lines from `rows` rows of the picture at p,
   each shown 480 / rows times */
static void show_rows(int k, const unsigned *p, int rows)
{
    unsigned *d = video_table(k), w = video_word(p);
    int y, rep = 480 / rows;
    for (y = 0; y < 480; y++)
        d[y] = w + W * (y / rep);
}

/* ---------------------------------------------------------------- the plasma */

#define TL (320 + 256 + 8)          /* a row table's bytes: x + an offset of 0..255 */
static unsigned char ta[TL], tb[TL];
static unsigned *a4[4], *b4[4];     /* the tables as words, from byte 0, 1, 2, 3 */
static unsigned l1t[256];           /* L1: a byte's bits where pixel 0's go */

static void plasma_init(void)
{
    int i, p;
    for (i = 0; i < TL; i++) {
        ta[i] = 42 + 42 * fx_sin[(2 * i) & 255] / 256;
        tb[i] = 42 + 42 * fx_sin[(3 * i + 40) & 255] / 256;
    }
    for (p = 0; p < 4; p++) {
        a4[p] = malloc(TL);
        b4[p] = malloc(TL);
        for (i = 0; i + p + 3 < TL; i += 4) {
            a4[p][i / 4] = ta[i + p] | ta[i + p + 1] << 8 | ta[i + p + 2] << 16
                           | (unsigned)ta[i + p + 3] << 24;
            b4[p][i / 4] = tb[i + p] | tb[i + p + 1] << 8 | tb[i + p + 2] << 16
                           | (unsigned)tb[i + p + 3] << 24;
        }
    }
    for (i = 0; i < 256; i++) {
        unsigned v = 0;
        for (p = 0; p < 8; p++)
            if (i >> p & 1)
                v |= 1u << (p < 4 ? 8 * p : 8 * (p - 4) + 1);
        l1t[i] = v;
    }
}

/* a word of four L0 pixels (bytes) as L1's */
static unsigned l1_word(unsigned v)
{
    return l1t[v & 255] | l1t[v >> 8 & 255] << 2 | l1t[v >> 16 & 255] << 4 | l1t[v >> 24] << 6;
}

static void plasma_row_c(unsigned *d, const unsigned *a, const unsigned *b, unsigned c, int n)
{
    while (n-- > 0)
        *d++ = *a++ + *b++ + c;
}

/* L1: the same bytes, each word's pixels put in their planes */
static void plasma_row_l1(unsigned *d, const unsigned *a, const unsigned *b, unsigned c, int n)
{
    while (n-- > 0)
        *d++ = l1_word(*a++ + *b++ + c);
}

/* L1: n words of L0 pixels converted, through the same kernels */
static unsigned zero_row[W];

static void to_l1(unsigned *d, const unsigned *s, int n)
{
#ifdef GFX_ASM
    plasma_row_l1_asm(d, s, zero_row, 0, n, l1t);
#else
    plasma_row_l1(d, s, zero_row, 0, n);
#endif
}

/* a row's offsets and constant: y in the screen's lines, so that every
   resolution shows the same plasma */
static void plasma_frame(unsigned *p, int rows, int time, int words)
{
    int r, y, oa, ob, c, step = 480 / rows;
    for (r = 0; r < rows; r++, p += words) {
        y = r * step + step / 2;
        oa = (time * 2 + 128 + 120 * fx_sin[(y / 2 + time * 3) & 255] / 256) & 255;
        ob = (-time * 3 + 128 + 100 * fx_sin[(y / 3 - time * 2 + 50) & 255] / 256) & 255;
        c = 42 + 42 * fx_sin[(y / 2 + time * 5) & 255] / 256;
        if (board_layout)
#ifdef GFX_ASM
            plasma_row_l1_asm(p, a4[oa & 3] + (oa >> 2), b4[ob & 3] + (ob >> 2),
                              c * 0x01010101, words, l1t);
#else
            plasma_row_l1(p, a4[oa & 3] + (oa >> 2), b4[ob & 3] + (ob >> 2), c * 0x01010101,
                          words);
#endif
        else
#ifdef GFX_ASM
            plasma_row_asm(p, a4[oa & 3] + (oa >> 2), b4[ob & 3] + (ob >> 2), c * 0x01010101,
                           words);
#else
            plasma_row_c(p, a4[oa & 3] + (oa >> 2), b4[ob & 3] + (ob >> 2), c * 0x01010101,
                         words);
#endif
    }
}

/* frames of the plasma at `rows` rows, recomputed as fast as it goes:
   into the picture not on the screen, then shown from the next frame */
static void part_plasma(int rows, int frames, const char *shot)
{
    int k = 0, n = 0, f0;
    unsigned tk, sum = 0;
    char name[40];
    show_rows(0, buf[0], rows);
    show_rows(1, buf[1], rows);
    f0 = rt_frames;
    while ((int)rt_frames - f0 < frames) {
        k ^= 1;
        tk = video_ticks();
        plasma_frame(buf[k], rows, t, W);
        sum += video_ticks() - tk;
        n++;
        rt_wait_frame_after(rt_frames);         /* the frame's end: */
        video_ctrl(k ? VC_TSEL : 0, VC_TSEL);   /* the new picture from the next */
        palette_cycle(t);
        t++;
        if (shot && (int)rt_frames - f0 >= frames / 2) {
            rt_shot(shot);
            shot = 0;
        }
    }
    sum /= n;
    printf("plasma %3d rows (%s): %6u ticks an update (%d.%d ms, %d.%d%% of a frame), "
           "%d updates in %d frames: %d.%d a second; %u ticks a word\n",
           rows, board_layout ? "L1" : "L0", sum, sum / 50352, sum / 5035 % 10, sum / 8400,
           sum / 840 % 10, n, (int)rt_frames - f0, 60 * n / ((int)rt_frames - f0),
           600 * n / ((int)rt_frames - f0) % 10, sum / (rows * W));
    sprintf(name, "plasma_%d", rows);
    perf_value(name, sum);
}

/* ---------------------------------------------------------------- measuring the cheap ones */

static int units[8], nunits;

static void report(const char *key, const char *what, unsigned ticks)
{
    int k, s = 0, u;
    for (k = 0; k < nunits; k++)
        s += units[k];
    u = fx_used(nunits ? s / nunits : fx_idle_base);
    nunits = 0;
    printf("%-44s %6u ticks a frame; %d.%d%% of the frame used\n", what, ticks, u / 10, u % 10);
    perf_value(key, ticks);
}

/* 3: the plasma at 240 rows drawn once, the palette cycled */
static void part_cycle(int frames, const char *shot)
{
    int f;
    unsigned tk = 0;
    plasma_frame(buf[0], 240, 0, W);
    show_rows(0, buf[0], 240);
    rt_wait_frame_after(rt_frames);
    video_ctrl(0, VC_TSEL);
    for (f = 0; f < frames; f++) {
        if (f == 20)
            tk = video_ticks();
        palette_cycle(t++);
        if (f == 20)
            tk = video_ticks() - tk;
        if (f >= 30 && f < 38)
            units[nunits++] = fx_idle();
        else
            fx_idle();
        if (f == frames / 2 && shot)
            rt_shot(shot);
    }
    report("cycle", "palette cycling (256 writes, C)", tk);
}

/* 4: the rows A + c for c = 0..84, each in four copies a byte apart
   (copy p from byte p of A + c), RW words each: in bank 1, 85 * 4 * RW
   words. Line y shows row c(y), copy a(y) & 3, from word a(y) >> 2. The
   offsets and constants as in plasma_frame, but from tables: no
   multiplies or divides in the loop */
#define RW 144                      /* 80 words and an offset of up to 255 bytes */
static signed char s120[256], s100[256], s42[256];
static unsigned row_desc[85 * 4];   /* row c's copy p: its descriptor */

static void rows_init(void)
{
    int c, p, i;
    unsigned *r = rows_ac;
    for (c = 0; c < 85; c++)
        for (p = 0; p < 4; p++, r += RW) {
            row_desc[c << 2 | p] = video_word(r);
            for (i = 0; i < RW; i++)
                r[i] = board_layout ? l1_word(a4[p][i] + c * 0x01010101)
                                    : a4[p][i] + c * 0x01010101;
        }
    for (i = 0; i < 256; i++) {
        s120[i] = 120 * fx_sin[i] / 256 / 2;    /* halved: a signed char */
        s100[i] = 100 * fx_sin[i] / 256 / 2;
        s42[i] = 42 * fx_sin[i] / 256;
    }
}

static void desc_frame(unsigned *d, int time)
{
    int y, oa, c, t2 = time * 2 + 128, t3 = time * 3, t5 = time * 5;
    for (y = 0; y < 480; y++) {
        oa = (t2 + 2 * s120[((y >> 1) + t3) & 255]) & 255;
        c = 42 + s42[((y >> 1) + t5) & 255];
        d[y] = row_desc[c << 2 | (oa & 3)] + (oa >> 2);
    }
}

static void part_desc(int frames, const char *shot)
{
    int f, k = 0;
    unsigned tk = 0, tp = 0;
    rows_init();
    for (f = 0; f < frames; f++) {
        k ^= 1;
        if (f == 20)
            tk = video_ticks();
        desc_frame(video_table(k), t);
        if (f == 20) {
            tk = video_ticks() - tk;
            tp = video_ticks();
        }
        palette_cycle(t);
        if (f == 20)
            tp = video_ticks() - tp;
        t++;
        if (f >= 30 && f < 38)
            units[nunits++] = fx_idle();
        else
            fx_idle();
        video_ctrl(k ? VC_TSEL : 0, VC_TSEL);
        if (f == frames / 2 && shot)
            rt_shot(shot);
    }
    report("desc", "descriptor plasma, 320 x 480 (480 descriptors)", tk);
    printf("   and the palette cycled: %u ticks\n", tp);
}

/* ---------------------------------------------------------------- fire */

/* the fire's rows: fire[k] is rows + 2 rows, the last two its fuel,
   seeded each frame; the logo's pixels kept hot */
static unsigned char *logo_mask;     /* a byte a pixel: 0 or the heat it adds */
static int logo_y0, logo_y1;        /* its rows */

static void fire_logo(int rows)
{
    Surface t1;
    int w = fx_logo_width("HERON", 1), h = font_sans->height, x0, y0, i, j;
    unsigned bits[64];
    memset(bits, 0, sizeof bits);
    gfx_init(&t1, bits, 64, 16, 2, PF_LIN1);
    font_draw(&t1, font_sans, 0, font_sans->ascent, "HERON", 1, -1);
    font_draw(&t1, font_sans, 1, font_sans->ascent, "HERON", 1, -1);
    logo_mask = calloc(320, rows);
    /* the logo at 5 pixels a dot across, a dot a row (the rows are 480 / rows lines tall) */
    x0 = (320 - 5 * w) / 2;
    y0 = rows / 2 - h / 2;
    logo_y0 = y0;
    logo_y1 = y0 + h;
    for (j = 0; j < h; j++)
        for (i = 0; i < 5 * w; i++)
            if (gfx_get(&t1, i / 5, j))
                logo_mask[(y0 + j) * 320 + x0 + i] = 0xFF;
}

/* the fuel: the two rows below, in runs of 4 to 64 pixels hot or not */
static void fire_seed(unsigned *f, int rows)
{
    unsigned *p = f + rows * W;
    int x = 0, n, r;
    unsigned v;
    while (x < 2 * W) {
        r = fx_rand();
        n = 1 + (r & 15);
        v = r & 0x30 ? 0xFFFFFFFF : 0x28282828;
        while (n-- > 0 && x < 2 * W)
            p[x++] = v;
    }
}

/* the logo's pixels kept glowing: ORed with random heat, its rows only */

static void fire_burn(unsigned *f, int rows)
{
    unsigned *m = (unsigned *)logo_mask + logo_y0 * W, r = fx_seed;
    int i, n = (logo_y1 - logo_y0) * W;
    (void)rows;
    f += logo_y0 * W;
    for (i = 0; i < n; i++)
        if (m[i]) {
            r = r * 1103515245 + 12345;
            f[i] |= m[i] & r;
        }
    fx_seed = r;
}

#ifndef GFX_ASM
/* the C kernel: what fire_rows_asm does (plasma.s) */
static unsigned avg4(unsigned x, unsigned y)
{
    return (x & y) + ((x ^ y) >> 1 & 0x7F7F7F7F);
}

static void fire_rows_c(unsigned *d, const unsigned *s, int rows, int words)
{
    int r, i;
    unsigned wp, w, wn, dd, l, rt, v;
    for (r = 0; r < rows; r++) {
        const unsigned *s1 = s + (r + 1) * words, *s2 = s1 + words;
        wp = 0;
        w = s1[0];
        for (i = 0; i < words; i++) {
            wn = i + 1 < words ? s1[i + 1] : 0;
            dd = s2[i];
            l = w << 8 | wp >> 24;
            rt = w >> 8 | wn << 24;
            v = avg4(avg4(l, rt), avg4(w, dd));
            *d++ = v - (v >> 3 & 0x1F1F1F1F);
            wp = w;
            w = wn;
        }
    }
}
#define fire_rows fire_rows_c
#else
#define fire_rows fire_rows_asm
#endif

/* the fire's pixels: the screen's two pictures in L0, two buffers in bank
   0 in L1, converted into the pictures each frame */
static unsigned *fire_buf[2];

static void part_fire(int rows, int frames, const char *shot)
{
    int k = 0, n = 0, f0, r;
    unsigned tk, sum = 0, *src, *dst;
    char name[40];
    for (k = 0; k < 2; k++) {
        fire_buf[k] = board_layout ? malloc((rows + 2) * W * 4) : buf[k];
        memset(fire_buf[k], 0, (rows + 2) * W * 4);
        memset(buf[k], 0, (rows + 2) * W * 4);
    }
    k = 0;
    fire_logo(rows);
    show_rows(0, buf[0], rows);
    show_rows(1, buf[1], rows);
    f0 = rt_frames;
    while ((int)rt_frames - f0 < frames) {
        k ^= 1;
        tk = video_ticks();
        src = fire_buf[k ^ 1];
        dst = fire_buf[k];
        fire_seed(src, rows);
        fire_rows(dst, src, rows, W);
        fire_burn(dst, rows);
        if (board_layout)
            for (r = 0; r < rows; r++)
                to_l1(buf[k] + r * W, dst + r * W, W);
        sum += video_ticks() - tk;
        n++;
        rt_wait_frame_after(rt_frames);
        video_ctrl(k ? VC_TSEL : 0, VC_TSEL);
        if (shot && (int)rt_frames - f0 >= frames * 3 / 4) {
            rt_shot(shot);
            shot = 0;
        }
    }
    free(logo_mask);
    sum /= n;
    printf("fire   %3d rows: %6u ticks an update (%d.%d ms, %d.%d%% of a frame), %d updates "
           "in %d frames: %d.%d a second\n", rows, sum, sum / 50352, sum / 5035 % 10,
           sum / 8400, sum / 840 % 10, n, (int)rt_frames - f0, 60 * n / ((int)rt_frames - f0),
           600 * n / ((int)rt_frames - f0) % 10);
    sprintf(name, "fire_%d", rows);
    perf_value(name, sum);
    /* the kernel alone */
    tk = video_ticks();
    fire_rows(fire_buf[k ^ 1], fire_buf[k], rows, W);
    tk = video_ticks() - tk;
    printf("       the kernel alone: %u ticks, %u a word\n", tk, tk / (rows * W));
    if (board_layout)
        for (k = 0; k < 2; k++)
            free(fire_buf[k]);
}

/* ---------------------------------------------------------------- main */

int main(void)
{
    fx_init();
    video_init(1, 0);
    buf[0] = vram_alloc(242 * W * 4);
    buf[1] = vram_alloc(242 * W * 4);
    rows_ac = vram_alloc(85 * 4 * RW * 4);
    plasma_init();
    palette_plasma();
    palette_cycle(0);
    fx_calibrate();

    part_plasma(240, 60, "plasma_240");
    part_plasma(120, 60, "plasma_120");
    part_plasma(60, 60, "plasma_60");
    part_cycle(60, "cycle");
    part_desc(100, "desc");
    palette_fire();
    part_fire(120, 120, "fire_120");
    part_fire(60, 90, "fire_60");
    printf("@done\n");
    return 0;
}
