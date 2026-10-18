/* A rotozoomer: a texture turning and zooming, every pixel looked up each
   frame, a benchmark of what the CPU can draw (RFC 0042's M1, 320 x 480 x
   8, at reduced resolution). Fixed point, no floating point:

   u and v (the texture's coordinates, 8.8) are the two halves of one
   word, uv = u << 16 | v, so one add steps both along a row (the carry
   from v into u's lowest fraction bit is a 1/256 texel's error); the
   texel is tex[(uv >> 24) | (uv & 0xFF00)], u's whole part and v's of a
   256 x 256 texture.

     160 x 120  a texel two pixels wide (the texture holds each doubled:
                a half, two to a word), the rows shown four times each
     80 x 60    a texel four pixels wide (each a word), the rows eight times

   in C (the c variant) and in assembly (asm, blk: the block instructions
   have nothing for this); in L1 (--layout L1) the texture holds each
   texel in L1's bits, so a row costs one shift more a word. The pictures
   are double buffered with the descriptor tables (TSEL). */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "gfx.h"
#include "video.h"
#include "perf.h"
#include "fx.h"

void roto_row2_asm(unsigned *d, unsigned uv, unsigned duv, int n, const unsigned short *tex);
void roto_row4_asm(unsigned *d, unsigned uv, unsigned duv, int n, const unsigned *tex);
void roto_row2_l1_asm(unsigned *d, unsigned uv, unsigned duv, int n, const unsigned *tex);

#define W 80
static unsigned *pic[2];
static unsigned char *tex8;         /* the texture, a byte a texel */
static unsigned short *tex2;        /* each texel twice (160 x 120, L0) */
static unsigned *tex4;              /* four times (80 x 60), or for L1 at 160 x 120 */
static unsigned l1t[256];           /* L1: a byte's bits where pixel 0's go */
static int t;

/* ---------------------------------------------------------------- the texture */

/* 256 x 256 in the default palette's 6 x 6 x 6 cube (16 + 36r + 6g + b):
   a checkerboard of 32-texel squares, rings round the middle, and the
   block logo over them */
static int cube(int r, int g, int b)
{
    return 16 + 36 * r + 6 * g + b;
}

static void make_texture(void)
{
    Surface s;
    int x, y, d, dx, dy;
    tex8 = malloc(256 * 256);
    gfx_init(&s, tex8, 256, 256, 64, PF_LIN8);
    for (y = 0; y < 256; y++)
        for (x = 0; x < 256; x++) {
            dx = x - 128;
            dy = y - 128;
            d = (dx * dx + dy * dy) >> 7;          /* rings, ever closer */
            if ((x ^ y) & 32)
                tex8[y * 256 + x] = cube(0, 1 + (d & 3) / 2, 3 + (y >> 6));
            else
                tex8[y * 256 + x] = cube(1 + (x >> 7), 0, 1 + (d & 3) / 3);
        }
    gfx_fill(&s, 20, 92, 236, 164, cube(0, 0, 1), ROP_COPY);
    fx_logo(&s, 128 - fx_logo_width("HERON", 4) / 2, 98, "HERON", 4, 1, cube(5, 5, 1),
            cube(5, 5, 5), cube(3, 2, 0));
    gfx_frame(&s, 20, 92, 236, 164, 3, cube(5, 3, 0), ROP_COPY);
}

static void make_rows(void)
{
    int i, p, c;
    for (i = 0; i < 256; i++) {
        unsigned v = 0;
        for (p = 0; p < 8; p++)
            if (i >> p & 1)
                v |= 1u << (p < 4 ? 8 * p : 8 * (p - 4) + 1);
        l1t[i] = v;
    }
    tex2 = malloc(2 * 65536);
    tex4 = malloc(4 * 65536);
    for (i = 0; i < 65536; i++) {
        c = tex8[i];
        tex2[i] = c * 0x0101;
        tex4[i] = c * 0x01010101;
    }
}

/* L1: tex4 as pixels 0 and 1 (160 x 120), or all four (80 x 60) */
static void make_l1(int four)
{
    int i;
    for (i = 0; i < 65536; i++)
        tex4[i] = l1t[tex8[i]] * (four ? 0x55 : 0x05);
}

/* ---------------------------------------------------------------- the rows */

static void roto_row2_c(unsigned *d, unsigned uv, unsigned duv, int n, const unsigned short *tex)
{
    unsigned short *h = (unsigned short *)d;
    n *= 2;
    while (n-- > 0) {
        *h++ = tex[(uv >> 24) | (uv & 0xFF00)];
        uv += duv;
    }
}

static void roto_row2_l1_c(unsigned *d, unsigned uv, unsigned duv, int n, const unsigned *tex)
{
    unsigned a;
    while (n-- > 0) {
        a = tex[(uv >> 24) | (uv & 0xFF00)];
        uv += duv;
        *d++ = a | tex[(uv >> 24) | (uv & 0xFF00)] << 4;
        uv += duv;
    }
}

static void roto_row4_c(unsigned *d, unsigned uv, unsigned duv, int n, const unsigned *tex)
{
    while (n-- > 0) {
        *d++ = tex[(uv >> 24) | (uv & 0xFF00)];
        uv += duv;
    }
}

/* the frame at time `time`: w x h texels (w 160 or 80) into p. The step
   along a row is (du, dv) = zoom (cos a, sin a), down the rows (-dv, du);
   the middle of the picture at the texture's middle */
static void roto_frame(unsigned *p, int w, int h, int time)
{
    int a = time & 255, zoom, du, dv, u0, v0, y;
    unsigned duv;
    zoom = 384 + (fx_sin[(time * 3 / 2) & 255] * 5 >> 2);      /* 8.8: 0.25 to 2.75 */
    du = fx_cos(a) * zoom >> 8;
    dv = fx_sin[a] * zoom >> 8;
    if (w == 80) {                          /* a texel twice as wide: steps twice as long */
        du *= 2;
        dv *= 2;
    }
    duv = ((unsigned)du << 16) + dv;
    /* the top left corner: the middle less half a row and half a column */
    u0 = (128 << 8) - du * w / 2 + dv * h / 2;
    v0 = (128 << 8) - dv * w / 2 - du * h / 2;
    for (y = 0; y < h; y++, p += W) {
        unsigned uv = ((unsigned)u0 << 16) + (v0 & 0xFFFF);
        if (w == 80)
#ifdef GFX_ASM
            roto_row4_asm(p, uv, duv, 80, tex4);
#else
            roto_row4_c(p, uv, duv, 80, tex4);
#endif
        else if (board_layout)
#ifdef GFX_ASM
            roto_row2_l1_asm(p, uv, duv, 80, tex4);
#else
            roto_row2_l1_c(p, uv, duv, 80, tex4);
#endif
        else
#ifdef GFX_ASM
            roto_row2_asm(p, uv, duv, 80, tex2);
#else
            roto_row2_c(p, uv, duv, 80, tex2);
#endif
        u0 -= dv;
        v0 += du;
    }
}

/* table k: the 480 lines from h rows of pic[k] */
static void show_rows(int k, int h)
{
    unsigned *d = video_table(k), w = video_word(pic[k]);
    int y, rep = 480 / h;
    for (y = 0; y < 480; y++)
        d[y] = w + W * (y / rep);
}

static void part(int w, int h, int frames, const char *shot1, const char *shot2)
{
    int k = 0, n = 0, f0;
    unsigned tk, sum = 0, mx = 0;
    char name[32];
    show_rows(0, h);
    show_rows(1, h);
    f0 = rt_frames;
    while ((int)rt_frames - f0 < frames) {
        k ^= 1;
        tk = video_ticks();
        roto_frame(pic[k], w, h, t);
        tk = video_ticks() - tk;
        sum += tk;
        mx = tk > mx ? tk : mx;
        n++;
        rt_wait_frame_after(rt_frames);
        video_ctrl(k ? VC_TSEL : 0, VC_TSEL);
        t += 2;
        if (shot1 && (int)rt_frames - f0 >= frames / 3) {
            rt_shot(shot1);
            shot1 = 0;
        }
        if (shot2 && (int)rt_frames - f0 >= 3 * frames / 4) {
            rt_shot(shot2);
            shot2 = 0;
        }
    }
    sum /= n;
    printf("rotozoom %3d x %3d (%s): %7u ticks a frame (%d.%d ms, %d.%d%% of a frame), "
           "%d frames in %d: %d.%d a second; %u ticks a texel\n", w, h,
           board_layout ? "L1" : "L0", sum, sum / 50352, sum / 5035 % 10, sum / 8400,
           sum / 840 % 10, n, (int)rt_frames - f0, 60 * n / ((int)rt_frames - f0),
           600 * n / ((int)rt_frames - f0) % 10, sum / (w * h));
    sprintf(name, "roto_%d", w);
    perf_value(name, sum);
}

int main(void)
{
    unsigned tk;
    fx_init();
    video_init(1, 0);
    video_default_palette();
    pic[0] = vram_alloc(120 * W * 4);
    pic[1] = vram_alloc(120 * W * 4);
    tk = video_ticks();
    make_texture();
    make_rows();
    printf("the texture: %u ticks\n", video_ticks() - tk);
    if (board_layout)
        make_l1(0);
    part(160, 120, 150, "roto_160a", "roto_160b");
    if (board_layout)
        make_l1(1);
    part(80, 60, 150, "roto_80", 0);
    printf("@done\n");
    return 0;
}
