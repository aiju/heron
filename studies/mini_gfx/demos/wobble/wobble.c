/* Wobble: a picture bent by the line descriptors alone (RFC 0042, M0
   640 x 480 x 4, D0), at no cost a pixel, and what that can and can't do:

     1  a horizontal wave by each line's start address: whole words only,
        so steps of 8 pixels
     2  the same wave smooth: eight copies of the picture shifted a pixel
        apart, each line taken from the copy its offset needs (8 times the
        memory: what a pixel offset in the descriptor would give for free)
     3  vertical stretch, squash, flip and zoom: lines repeated or skipped,
        rows in reverse; the wave on top
     4  a vertical scroller: credits drawn once, the descriptors moving
        down them, the lines near the top and bottom fading through the
        palette banks
     5  a split screen: the wobbling logo over a sky (banks 0-6), a
        horizontal text scroller made smooth by eight shifted copies of
        its strip, its lines in rainbow colours (banks 8-15), and a 3D
        starfield the CPU draws (bank 7)

   and how many stars the CPU can move in a frame, in C or assembly. */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "gfx.h"
#include "video.h"
#include "perf.h"
#include "fx.h"

#define W 80                        /* a screen line's words */
static int t;
static unsigned blank;              /* a line of colour 0 */

/* ---------------------------------------------------------------- the picture */

/* the logo: LW words by LH rows, in eight copies shifted 0..7 pixels right */
#define LW 96                       /* 768 pixels: the screen's 640 and 64 each side */
#define LH 136
static unsigned *logo[8];
static unsigned lrow[8][LH];        /* copy k's row r: its first word in bank 1 */
static unsigned band7[480];         /* line y's bank in the sky: 7 bands, as descriptor bits */

static void draw_logo(Surface *s)
{
    int w = fx_logo_width("HERON", 8), x0 = (LW * 8 - w) / 2, i;
    gfx_fill(s, 0, 0, LW * 8, LH, 0, ROP_COPY);
    fx_logo(s, x0, 4, "HERON", 8, 1, 7, 15, 8);
    /* a bar of the 13 colours 1-6 and 9-15 under it, in steps */
    for (i = 0; i < 13; i++)
        gfx_fill(s, x0 + i * w / 13, 116, x0 + (i + 1) * w / 13, 128, i < 6 ? 1 + i : 3 + i,
                 ROP_COPY);
    gfx_frame(s, x0 - 4, 112, x0 + w + 4, 132, 2, 15, ROP_COPY);
}

static void make_logo(void)
{
    Surface s0, s;
    int k, r;
    for (k = 0; k < 8; k++) {
        logo[k] = vram_alloc(LW * LH * 4);
        for (r = 0; r < LH; r++)
            lrow[k][r] = video_word(logo[k] + r * LW);
    }
    gfx_init(&s0, logo[0], LW * 8, LH, LW, gfx_screen_format());
    draw_logo(&s0);
    for (k = 1; k < 8; k++) {
        gfx_init(&s, logo[k], LW * 8, LH, LW, gfx_screen_format());
        gfx_fill(&s, 0, 0, LW * 8, LH, 0, ROP_COPY);
        gfx_blit(&s, k, 0, &s0, 0, 0, LW * 8 - 8, LH, ROP_COPY);
    }
    for (r = 0; r < 480; r++)
        band7[r] = (unsigned)(r * 7 / 480) << 19;
}

/* the logo's row r from its pixel x + 64 (x = 0: centred), as a
   descriptor without its bank. Coarse: the nearest whole word. Fine: copy
   k's word w starts at the row's pixel 8w - k, so k = -X & 7 and w =
   (X + k) / 8 for X = x + 64 */
static unsigned line_coarse(int r, int x)
{
    return lrow[0][r] + ((x + 68) >> 3);
}

static unsigned line_fine(int r, int x)
{
    int k = -(x + 64) & 7;
    return lrow[k][r] + ((x + 64 + k) >> 3);
}

/* the logo's colours (1-15) in banks 0-6, and a sky in colour 0 */
static const unsigned char logo_pal[16][3] = {
    {0, 0, 0}, {255, 60, 60}, {255, 150, 40}, {255, 230, 60}, {120, 230, 60}, {40, 200, 160},
    {40, 160, 255}, {225, 225, 235}, {90, 90, 110}, {120, 90, 255}, {200, 80, 255},
    {255, 80, 200}, {255, 255, 255}, {180, 180, 180}, {100, 100, 100}, {255, 255, 255},
};

static void sky_palette(int banks)
{
    int b, n;
    for (b = 0; b < banks; b++) {
        video_pal(16 * b, rgb565(10 + 8 * b, 20 + 12 * b, 60 + 24 * b));
        for (n = 1; n < 16; n++)
            video_pal(16 * b + n, rgb565(logo_pal[n][0], logo_pal[n][1], logo_pal[n][2]));
    }
}

/* sines scaled to an amplitude, once, so that the lines' loops have no
   multiplies (tens of cycles each) or divides */
static signed char s40[256], s13[256], s16[256], s24[256], s32[256];

static void scaled(signed char *tab, int amp)
{
    int i;
    for (i = 0; i < 256; i++)
        tab[i] = amp * fx_sin[i] / 256;
}

/* ---------------------------------------------------------------- measuring */

static int units[8], nunits;

static void meter_or_wait(int f)
{
    if (f >= 30 && f < 38)
        units[nunits++] = fx_idle();
    else
        fx_idle();
}

static void report(const char *key, const char *what, unsigned ticks)
{
    int k, s = 0, u;
    for (k = 0; k < nunits; k++)
        s += units[k];
    u = fx_used(nunits ? s / nunits : fx_idle_base);
    nunits = 0;
    printf("%-46s %6u ticks a frame; %d.%d%% of the frame used\n", what, ticks, u / 10, u % 10);
    perf_value(key, ticks);
}

/* ---------------------------------------------------------------- 1, 2: waves */

/* the logo centred, each line's offset a sum of two sines */
static void wave_frame(unsigned *d, int fine)
{
    int y, r, x, y0 = 240 - LH / 2, a = 3 * t, b = -2 * t;
    for (y = 0; y < 480; y++) {
        r = y - y0;
        if (r < 0 || r >= LH) {
            d[y] = blank | band7[y];
            continue;
        }
        x = s40[(2 * y + a) & 255] + s13[(5 * y + b) & 255];
        d[y] = (fine ? line_fine(r, x) : line_coarse(r, x)) | band7[y];
    }
}

static void part_wave(int fine, int frames, const char *shot)
{
    int f, k = 0;
    unsigned tk = 0;
    for (f = 0; f < frames; f++) {
        k ^= 1;
        if (f == 20)
            tk = video_ticks();
        wave_frame(video_table(k), fine);
        if (f == 20)
            tk = video_ticks() - tk;
        t++;
        meter_or_wait(f);
        video_ctrl(k ? VC_TSEL : 0, VC_TSEL);
        if (f == frames - 10 && shot)
            rt_shot(shot);
    }
    report(fine ? "wave_fine" : "wave_coarse",
           fine ? "2 smooth wave (8 copies), C" : "1 wave by whole words, C", tk);
}

/* ---------------------------------------------------------------- 3: stretch, flip, zoom */

/* the logo h lines tall (rows repeated or skipped: a step of LH / h rows
   a line in 16.16), its top at y0, upside down if flip, a wave on it */
static void stretch_frame(unsigned *d, int y0, int h, int flip, const signed char *wave)
{
    int y, r, x, step = (LH << 16) / h, acc = 0, a = 3 * t;
    for (y = 0; y < 480; y++) {
        if (y < y0 || y >= y0 + h) {
            d[y] = blank | band7[y];
            continue;
        }
        r = acc >> 16;
        acc += step;
        if (flip)
            r = LH - 1 - r;
        x = wave ? wave[(2 * y + a) & 255] : 0;
        d[y] = line_fine(r, x) | band7[y];
    }
}

static void part_stretch(int frames, const char *shot1, const char *shot2, const char *shot3)
{
    int f, k = 0, h, y0, s;
    unsigned tk = 0;
    for (f = 0; f < frames; f++) {
        k ^= 1;
        if (f == 20)
            tk = video_ticks();
        if (f < frames / 3) {
            /* bouncing on a floor at 400: squashed as it lands */
            s = fx_sin[(f * 4) & 127];          /* 0..256..0, a bounce */
            h = s < 40 ? LH * (60 + s) / 100 : LH;
            y0 = 400 - h - 220 * s / 256;
            stretch_frame(video_table(k), y0, h, 0, s16);
        } else if (f < 2 * frames / 3) {
            /* turning over: the height through 0, upside down for half */
            s = fx_cos((f - frames / 3) * 3);
            h = LH * (s < 0 ? -s : s) / 256 + 1;
            stretch_frame(video_table(k), 240 - h / 2, h, s < 0, 0);
        } else {
            /* zooming: 1 to 3.5 times as tall */
            h = LH + (LH * 5 / 2) * fx_sin[((f - 2 * frames / 3) * 3) & 127] / 256;
            stretch_frame(video_table(k), 240 - h / 2, h, 0, s24);
        }
        if (f == 20)
            tk = video_ticks() - tk;
        t++;
        meter_or_wait(f);
        video_ctrl(k ? VC_TSEL : 0, VC_TSEL);
        if (f == frames / 3 - 26 && shot1)
            rt_shot(shot1);
        if (f == frames / 3 + frames / 6 + 12 && shot2)
            rt_shot(shot2);
        if (f == frames - 18 && shot3)
            rt_shot(shot3);
    }
    report("stretch", "3 stretch, flip, zoom (+ wave), C", tk);
}

/* ---------------------------------------------------------------- 4: a vertical scroller */

static const char *credits[] = {
    "HERON MINI", "", "a demo of the line descriptors", "", "every line of this text",
    "was drawn once;", "what moves it is", "one word a line", "the video reads", "as each line starts",
    "", "* * *", "", "the fade at the edges:", "sixteen palette banks,", "sixteen brightnesses,",
    "a bank a line", "", "* * *", "", "the CPU's share:", "480 descriptors a frame", "", "",
    "thanks for watching", "", "", 0,
};
#define CR 30                       /* lines of text, 32 rows each */
static unsigned *cred;
static unsigned cred_w;

static void make_credits(void)
{
    Surface s;
    int i, n;
    cred = vram_alloc(CR * 32 * W * 4);
    cred_w = video_word(cred);
    gfx_init(&s, cred, 640, CR * 32, W, gfx_screen_format());
    gfx_fill(&s, 0, 0, 640, CR * 32, 0, ROP_COPY);
    for (i = 0; credits[i]; i++) {
        n = strlen(credits[i]);
        if (i == 0)
            fx_logo(&s, (640 - fx_logo_width(credits[i], 2)) / 2, 0, credits[i], 2, 0, 15, 15, 15);
        else
            font_draw(&s, font_sans, (640 - font_width(font_sans, credits[i])) / 2, 32 * i + 20,
                      credits[i], i % 2 ? 15 : 13, -1);
        (void)n;
    }
}

/* the scroll's lines: text row y + pos, faded within 64 lines of the edges */
static void vscroll_frame(unsigned *d, int pos)
{
    int y, r, b;
    for (y = 0; y < 480; y++) {
        r = y + pos;
        b = y < 64 ? y / 4 : y >= 416 ? (479 - y) / 4 : 15;
        if (r < 0 || r >= CR * 32)
            d[y] = blank | b << 19;
        else
            d[y] = (cred_w + r * W) | b << 19;
    }
}

static void part_vscroll(int frames, const char *shot)
{
    int f, k = 0, b, n;
    unsigned tk = 0;
    /* bank b: the text's colours at brightness b/15 */
    for (b = 0; b < 16; b++) {
        video_pal(16 * b, 0);
        for (n = 1; n < 16; n++)
            video_pal(16 * b + n, fx_dim(n == 13 ? 120 : 255, n == 13 ? 200 : 255, 255, b));
    }
    for (f = 0; f < frames; f++) {
        k ^= 1;
        if (f == 20)
            tk = video_ticks();
        vscroll_frame(video_table(k), 2 * f - 480);
        if (f == 20)
            tk = video_ticks() - tk;
        meter_or_wait(f);
        video_ctrl(k ? VC_TSEL : 0, VC_TSEL);
        if (f == frames - 30 && shot)
            rt_shot(shot);
    }
    report("vscroll", "4 vertical scroller, faded edges, C", tk);
}

/* ---------------------------------------------------------------- 5: the split screen */

/* the horizontal scroller: the message in the cell font, 16 rows, in a
   strip SW words wide with 640 blank pixels before and after, in eight
   copies shifted a pixel apart */
static const char msg[] = "     HERON MINI ... a line descriptor a line, eight copies a pixel "
                          "apart, and the strip slides smoothly by ... the stars below are "
                          "the CPU's work ...     ";
#define SW (80 + (int)(sizeof msg - 1) + 80)
static unsigned *strip[8], strip_w[8];

static void make_strip(void)
{
    Surface s0, s;
    int k, n = sizeof msg - 1;
    for (k = 0; k < 8; k++) {
        strip[k] = vram_alloc(SW * 16 * 4);
        strip_w[k] = video_word(strip[k]);
    }
    gfx_init(&s0, strip[0], SW * 8, 16, SW, gfx_screen_format());
    gfx_fill(&s0, 0, 0, SW * 8, 16, 0, ROP_COPY);
    font_cells(&s0, 640, 0, msg, n, 15, -1);
    for (k = 1; k < 8; k++) {
        gfx_init(&s, strip[k], SW * 8, 16, SW, gfx_screen_format());
        gfx_fill(&s, 0, 0, SW * 8, 16, 0, ROP_COPY);
        gfx_blit(&s, k, 0, &s0, 0, 0, SW * 8 - 8, 16, ROP_COPY);
    }
}

/* the stars: 3D points coming at the viewer, projected with a table of
   reciprocals (no divides), each erased from where it was and drawn
   where it is; star_move is in C or in assembly (stars.s) */
typedef struct {
    int x, y, z;                    /* z 16..1023 */
    unsigned *p;                    /* where it was drawn, its mask */
    unsigned m;
} Star;

#define MAXSTARS 2000
static Star stars[MAXSTARS];
static int rz[1024];                /* 2^8 * 200 / z: under 2^15, so that the multiplies
                                       take the microcode's 16-step path */
static unsigned zcol[16];           /* by z / 64: the colour's word */
static Surface sky;                 /* the stars' framebuffer */
static int sky_h;
static unsigned *rows[480];         /* each row's first word in the stars' framebuffer */

static void star_new(Star *s)
{
    s->x = (fx_rand() & 1023) - 512;
    s->y = (fx_rand() & 511) - 256;
    s->z = 1023;
}

static void stars_init(int n)
{
    int i, z;
    for (z = 1; z < 1024; z++)
        rz[z] = (200 << 8) / z;
    for (i = 0; i < 16; i++)
        zcol[i] = gfx_solid(sky.fmt, 15 - i * 14 / 15);
    for (i = 0; i < sky_h; i++)
        rows[i] = sky.bits + i * W;
    for (i = 0; i < n; i++) {
        star_new(&stars[i]);
        stars[i].z = 16 + (fx_rand() & 1007);
        stars[i].p = sky.bits;
        stars[i].m = 0;
    }
}

unsigned stars_seed = 2463534242u;  /* stars.s's xorshift */

#ifdef GFX_ASM
void stars_move_asm(Star *s, int n, const int *rz, const unsigned *zcol, unsigned **rows,
                    const unsigned *pmask, int h, int speed);
#endif

/* move n stars by `speed`: erase, project, draw (stars.s does the same) */
static void stars_move_c(Star *s, int n, int speed)
{
    const unsigned *pmask = sky.f->pmask;
    int sx, sy, r;
    unsigned *p, m;
    for (; n > 0; n--, s++) {
        *s->p &= ~s->m;
        s->z -= speed;
        if (s->z < 16) {
            star_new(s);
            s->m = 0;
            continue;
        }
        r = rz[s->z];
        sx = 320 + (s->x * r >> 8);
        sy = sky_h / 2 + (s->y * r >> 8);
        if ((unsigned)sx >= 640 || (unsigned)sy >= (unsigned)sky_h) {
            star_new(s);
            s->m = 0;
            continue;
        }
        p = rows[sy] + (sx >> 3);
        m = pmask[sx & 7];
        *p = (*p & ~m) | (zcol[s->z >> 6] & m);
        s->p = p;
        s->m = m;
    }
}

static void stars_move(int n, int speed)
{
#ifdef GFX_ASM
    stars_move_asm(stars, n, rz, zcol, rows, sky.f->pmask, sky_h, speed);
#else
    stars_move_c(stars, n, speed);
#endif
}

#define SY0 248                     /* the stars' first line */
#define HS0 208                     /* the scroller's */

static unsigned band_top[HS0];     /* the split screen's sky: 7 bands over HS0 lines */

static void split_frame(unsigned *d, int pos)
{
    int y, r, x, y0 = 20 + s32[(t * 3) & 255], w, k, a = 3 * t;
    /* the logo: lines 0..HS0, bobbing; the sky in banks 0-6 */
    for (y = 0; y < HS0; y++) {
        r = y - y0;
        if (r < 0 || r >= LH)
            d[y] = blank | band_top[y];
        else {
            x = s32[(2 * y + a) & 255];
            d[y] = line_fine(r, x) | band_top[y];
        }
    }
    /* the scroller: 16 rows twice each, from pixel pos, banks 8-15 in turn */
    w = (pos + 7) >> 3;
    k = 8 * w - pos;
    for (y = 0; y < 40; y++) {
        r = (y - 4) >> 1;
        if (r < 0 || r >= 16)
            d[HS0 + y] = blank | 7 << 19;
        else
            d[HS0 + y] = (strip_w[k] + r * SW + w) | (8 + ((y + t) & 7)) << 19;
    }
    /* the stars: their framebuffer, bank 7 */
    for (y = SY0; y < 480; y++)
        d[y] = video_word(sky.bits + (y - SY0) * W) | 7 << 19;
}

static void split_palette(void)
{
    int b, n, a;
    sky_palette(7);
    /* bank 7: the stars, greys */
    video_pal(16 * 7, 0);
    for (n = 1; n < 16; n++)
        video_pal(16 * 7 + n, rgb565(17 * n, 17 * n, 17 * n + (n < 12 ? 30 : 0)));
    /* banks 8-15: the scroller's text (15) in eight hues over a dark band */
    for (b = 8; b < 16; b++) {
        a = (b - 8) * 32;
        video_pal(16 * b, rgb565(10, 10, 40));
        video_pal(16 * b + 15, rgb565(128 + fx_sin[a] / 2 - (fx_sin[a] > 254),
                                      128 + fx_sin[(a + 85) & 255] / 2 - (fx_sin[(a + 85) & 255] > 254),
                                      128 + fx_sin[(a + 170) & 255] / 2 - (fx_sin[(a + 170) & 255] > 254)));
    }
}

static void part_split(int frames, int nstars, const char *shot)
{
    int f, k = 0, pos = 0;
    unsigned tk = 0, ts = 0;
    split_palette();
    for (f = 0; f < HS0; f++)
        band_top[f] = (unsigned)(f * 7 / HS0) << 19;
    gfx_fill(&sky, 0, 0, 640, sky_h, 0, ROP_COPY);
    stars_init(nstars);
    for (f = 0; f < frames; f++) {
        k ^= 1;
        if (f == 20)
            tk = video_ticks();
        split_frame(video_table(k), pos);
        if (f == 20) {
            tk = video_ticks() - tk;
            ts = video_ticks();
        }
        stars_move(nstars, 6);
        if (f == 20)
            ts = video_ticks() - ts;
        pos += 2;
        if (pos > 8 * (SW - 80))
            pos = 0;
        t++;
        meter_or_wait(f);
        video_ctrl(k ? VC_TSEL : 0, VC_TSEL);
        if (f == frames - 20 && shot)
            rt_shot(shot);
    }
    report("split", "5 split screen: descriptors, C", tk);
    printf("   and %d stars: %u ticks, %u a star\n", nstars, ts, ts / nstars);
}

/* ---------------------------------------------------------------- 6: stars by the descriptors */

/* every fourth line a row of a star field: a strip two screens wide with
   one star (two pixels) in it, at a random place, in eight copies a pixel
   apart; each line slides its row sideways at its own speed through its
   start address, and its bank makes it as bright as it is fast. All the
   stars for 480 descriptors a frame; the logo bounces over them */
#define SR 120                      /* star rows */
#define SRW 160                     /* a row's words: 1280 pixels */
static unsigned *srow[8];
static int s_x[SR], s_v[SR];        /* each row's offset (pixels, 16.4) and speed */

static void make_star_rows(void)
{
    Surface c[8];
    int k, r, x;
    for (k = 0; k < 8; k++) {
        srow[k] = vram_alloc(SR * SRW * 4);
        gfx_init(&c[k], srow[k], SRW * 8, SR, SRW, gfx_screen_format());
        gfx_fill(&c[k], 0, 0, SRW * 8, SR, 0, ROP_COPY);
    }
    for (r = 0; r < SR; r++) {
        x = fx_rand() % 640;
        s_v[r] = 8 + fx_rand() % 120;           /* 0.5 to 8 pixels a frame: bank 1-15 */
        s_x[r] = (fx_rand() % 640) << 4;
        /* the star at x and x + 640, so that any 640 from 0..639 hold it */
        for (k = 0; k < 8; k++) {
            gfx_fill(&c[k], x + k, r, x + k + 2, r + 1, 15, ROP_COPY);
            gfx_fill(&c[k], x + 640 + k, r, x + 640 + k + 2, r + 1, 15, ROP_COPY);
        }
    }
}

static unsigned srow_w[8];

static void lstars_frame(unsigned *d, int y0, int h)
{
    int y, r, x, k, step = (LH << 16) / h, acc = 0;
    for (y = 0; y < 480; y++) {
        if (y >= y0 && y < y0 + h) {            /* the logo, stretched */
            d[y] = line_fine(acc >> 16, 0) | 7 << 19;
            acc += step;
            continue;
        }
        if (y & 3) {
            d[y] = blank;
            continue;
        }
        r = y >> 2;
        x = 640 - ((s_x[r] >> 4) + 1);          /* the row moves left: its window right */
        k = -x & 7;
        /* the bank masked: a bank of 16 would set bit 23, the line's interrupt */
        d[y] = (srow_w[k] + r * SRW + ((x + k) >> 3)) | (s_v[r] >> 3 & 15) << 19;
        s_x[r] += s_v[r];
        if (s_x[r] >= 640 << 4)
            s_x[r] -= 640 << 4;
    }
}

static void part_lstars(int frames, const char *shot)
{
    int f, k = 0, b, n, s, h, y0;
    unsigned tk = 0;
    for (k = 0; k < 8; k++)
        srow_w[k] = video_word(srow[k]);
    k = 0;
    /* banks 0-15: a star (15) as bright as the bank, a black sky; bank 7
       also the logo's colours */
    for (b = 0; b < 16; b++) {
        video_pal(16 * b, 0);
        video_pal(16 * b + 15, fx_dim(200, 220, 255, b < 15 ? b + 1 : 15));
    }
    for (n = 1; n < 15; n++)
        video_pal(16 * 7 + n, rgb565(logo_pal[n][0], logo_pal[n][1], logo_pal[n][2]));
    video_pal(16 * 7 + 15, rgb565(255, 255, 255));
    for (f = 0; f < frames; f++) {
        k ^= 1;
        s = fx_sin[(f * 3) & 127];
        h = s < 40 ? LH * (60 + s) / 100 : LH;
        y0 = 420 - h - 260 * s / 256;
        if (f == 20)
            tk = video_ticks();
        lstars_frame(video_table(k), y0, h);
        if (f == 20)
            tk = video_ticks() - tk;
        t++;
        meter_or_wait(f);
        video_ctrl(k ? VC_TSEL : 0, VC_TSEL);
        if (f == frames - 20 && shot)
            rt_shot(shot);
    }
    report("lstars", "6 stars by the descriptors (120 rows), C", tk);
}

/* how many stars a frame: the time for n stars */
static void bench_stars(void)
{
    int n, f;
    unsigned tk;
    char name[32];
    for (n = 250; n <= 2000; n *= 2) {
        stars_init(n);
        gfx_fill(&sky, 0, 0, 640, sky_h, 0, ROP_COPY);
        for (f = 0; f < 6; f++) {
            fx_idle();
            tk = video_ticks();
            stars_move(n, 6);
            tk = video_ticks() - tk;
        }
        printf("stars %4d: %7u ticks a frame (%d.%d%%), %u a star\n", n, tk, tk / 8400,
               tk / 840 % 10, tk / n);
        sprintf(name, "stars_%d", n);
        perf_value(name, tk);
    }
}

/* ---------------------------------------------------------------- main */

int main(void)
{
    unsigned *z, tk;
    fx_init();
    video_init(0, 0);
    z = vram_alloc(W * 4);
    memset(z, 0, W * 4);
    blank = video_word(z);
    scaled(s40, 40);
    scaled(s13, 13);
    scaled(s16, 16);
    scaled(s24, 24);
    scaled(s32, 32);
    tk = video_ticks();
    make_logo();
    printf("the logo and its 7 shifted copies: %u ticks, %u bytes\n", video_ticks() - tk,
           8 * LW * LH * 4);
    make_credits();
    make_strip();
    sky_h = 480 - SY0;
    gfx_init(&sky, vram_alloc(W * 4 * sky_h), 640, sky_h, W, gfx_screen_format());
    sky_palette(7);
    fx_calibrate();

    part_wave(0, 70, "wave_coarse");
    part_wave(1, 70, "wave_fine");
    part_stretch(240, "bounce", "flip", "zoom");
    part_vscroll(260, "vscroll");
    part_split(180, 300, "split");
    bench_stars();
    make_star_rows();
    part_lstars(150, "lstars");
    printf("@done\n");
    return 0;
}
