/* Heron Bricks: a brick breaker in M1 used as 320 x 240 x 8 (every line
   shown twice by the descriptors), drawn the way demos/bobs found
   fastest, and only what moves:

   - The bricks and the backdrop are a background buffer, drawn once. A
     brick that breaks is taken out of the background (copied from a
     backdrop without bricks) and its rectangle restored in each screen
     buffer the next time that buffer is drawn.
   - The ball, the paddle and the capsules are compiled sprites (the bobs'
     sprite compiler: byte and half stores at the edges, L0's pixels being
     bytes), erased by their compiled restores, two buffers flipped with
     TSEL.
   - Particles are 2 x 2 pixels: two half-word stores each, erased with
     two half-word copies from the background (in L0, where a pixel is a
     byte; in L1, whose 8-bit pixels are spread over their word, two
     read-modify-writes and two word copies).
   - The score is a status line from its own buffer through its own
     descriptors: redrawn only when it changes, never erased.
   - The stars twinkle and the title's colours run by palette cycling, at
     no cost in pixels; a caught capsule or a cleared level makes the
     picture wobble by moving each line's start in the descriptors.

   Keys: left and right (or the mouse) move the paddle, space or a click
   serves, A turns the autopilot on and off, Esc gives up. Poke autoplay
   1 to start with it on, burst for the particles a brick makes. */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "gfx.h"
#include "video.h"
#include "input.h"
#include "perf.h"
#include "sprite.h"

int autoplay;
int burst = 12;                 /* particles a brick */

#define W 320
#define H 240
#define GUARD 32
#define PITCH (W / 4 + 2 * GUARD / 4)   /* words a buffer's row: 96 */
#define ROWS (H + 2 * GUARD)
#define SROWS 16                /* the status line's rows */

#define WALL 4                  /* the side walls' width */
#define TOPY 20                 /* the top wall's inside */
#define BW 24                   /* a brick, with its gap */
#define BH 10
#define BCOLS 13
#define BROWS 8
#define BX WALL
#define BY 36
#define PADY 222                /* the paddle's top */
#define PADW 40
#define FIX 8                   /* positions in 1/256 pixels */
#define MAXBALL 8
#define MAXCAP 4
#define MAXPART 1200
#define MAXOBJ (1 + MAXBALL + MAXCAP)

/* the palette */
enum {
    P_BACK = 16,                /* 16-31 the backdrop, dark to light */
    P_WALL = 40,                /* 40-42 the walls: body, light, dark */
    P_BRICK = 48,               /* brick kind k: 48 + 4k light, + 1 body, + 2 dark */
    P_STAR = 100,               /* 100-107 the stars, cycled */
    P_AUTO = 109,               /* AUTO on the status line: shown or not by its colour */
    P_BLINK = 110,              /* blinking text */
    P_TEXT = 111,
    P_TITLE = 112,              /* 112-127 the title's rows, cycled */
    P_SPR = 160,                /* the sprites' own */
};

/* the brick kinds: the letters of the levels */
static const char kinds[] = "ROYGCBPS*";
static const unsigned char brick_rgb[9][3] = {
    {230, 50, 50}, {250, 140, 30}, {240, 220, 40}, {60, 200, 70}, {40, 200, 220},
    {50, 100, 240}, {170, 70, 230}, {150, 160, 170}, {255, 215, 120},
};
#define K_STEEL 7               /* two hits */
#define K_CAPS 8                /* drops a capsule */
#define K_CRACKED 9             /* steel, hit once */

/* the levels: a letter a brick, '.' none */
static const char *levels[2][BROWS] = {
    {".............", "RRRRRRRRRRRRR", "OOOOO*OOOOOOO", "YYYYYYYYYYYYY", "GGGGGGGGG*GGG",
     "CCCCCCCCCCCCC", "BB*BBBBBBBBBB", "PPP*PPPPP*PPP"},
    {"......S......", ".....SRS.....", "....SOOOS....", "...SYY*YYS...", "..SGGGGGGGS..",
     ".SCCC*CCCCCS.", "SBBBBBBBBBBBS", "............."},
};

/* ---- the screen ---- */
static unsigned *buf[4];        /* the two screens, the background, the backdrop */
static unsigned *rowbuf[3][ROWS];
static unsigned **rowp[3];      /* each screen's and the background's row y (from -GUARD), x = 0 */
static Surface pic[4];
static unsigned *status_fb;
static Surface status_s;
static int back;                /* the buffer drawn into */
static int fmt;
static int bytes_px;            /* a pixel is a byte (L0) */
static unsigned pair_mask[2];   /* else: pixels 0 and 1, 2 and 3 of a word */

/* ---- the game ---- */
typedef struct {
    int x, y, dx, dy;           /* the centre, 1/256 pixels */
} Ball;
typedef struct {
    int x, y, dx, dy, life;
    unsigned c;                 /* its colour: a half-word of two pixels (L0), or a word */
} Part;

static unsigned char grid[BROWS][BCOLS];        /* the kind + 1, 0 none */
static int bricks_left, level, lives, serving, wobble;
static Ball ball[MAXBALL];
static int nball;
static int capx[MAXCAP], capy[MAXCAP], ncap;
static int padx;                /* the paddle's centre */
static Part part[MAXPART];
static int npart;
static unsigned frame_no;
static unsigned shot_at, caught;        /* the multiball's screenshot */
static unsigned char colof[W], rowof[H];        /* the brick under a pixel: 255 none */

/* what was drawn into each buffer, to erase it the next time */
static Blt drawn[2][MAXOBJ];
static int ndrawn[2];
static unsigned char *pdrawn[2][MAXPART];
static int npdrawn[2];
static Rect pending[2][64];     /* rectangles changed in the background */
static int npending[2];

static Sprite spr_ball, spr_paddle, spr_cap;

/* random numbers from 0 to mask (2^k - 1, at most 511): from a table made
   at start-up, as the game's own arithmetic is costly here: a multiply or
   divide is a microcoded loop of tens of cycles, a shift by a constant up
   to 10 */
static unsigned short rnd_table[1024];
static unsigned rnd_at;

static void rnd_init(unsigned seed)
{
    int i;
    for (i = 0; i < 1024; i++) {
        seed ^= seed << 13;
        seed ^= seed >> 17;
        seed ^= seed << 5;
        rnd_table[i] = seed & 511;
    }
}

static int rnd(int mask)
{
    return rnd_table[rnd_at++ & 1023] & mask;
}

/* ---- set-up ---- */

static void palette(void)
{
    int i, k;
    video_default_palette();
    for (i = 0; i < 16; i++)
        video_pal_rgb(P_BACK + i, 4 + i * 2, 6 + i * 3, 24 + i * 5);
    video_pal_rgb(P_WALL, 110, 120, 150);
    video_pal_rgb(P_WALL + 1, 200, 210, 240);
    video_pal_rgb(P_WALL + 2, 50, 55, 80);
    for (k = 0; k < 9; k++) {
        const unsigned char *c = brick_rgb[k];
        video_pal_rgb(P_BRICK + 4 * k, (c[0] + 255) / 2, (c[1] + 255) / 2, (c[2] + 255) / 2);
        video_pal_rgb(P_BRICK + 4 * k + 1, c[0], c[1], c[2]);
        video_pal_rgb(P_BRICK + 4 * k + 2, c[0] / 2, c[1] / 2, c[2] / 2);
    }
    /* steel, hit once: darker, with cracks */
    video_pal_rgb(P_BRICK + 36, 120, 125, 130);
    video_pal_rgb(P_BRICK + 37, 90, 95, 100);
    video_pal_rgb(P_BRICK + 38, 40, 40, 45);
    video_pal_rgb(P_TEXT, 230, 235, 255);
    /* the sprites: the ball's grey shades, the paddle's reds and silvers,
       the capsule's greens */
    video_pal_rgb(P_SPR + 0, 30, 30, 40);
    video_pal_rgb(P_SPR + 1, 255, 255, 255);
    video_pal_rgb(P_SPR + 2, 200, 205, 215);
    video_pal_rgb(P_SPR + 3, 130, 135, 150);
    video_pal_rgb(P_SPR + 4, 120, 10, 20);
    video_pal_rgb(P_SPR + 5, 220, 40, 50);
    video_pal_rgb(P_SPR + 6, 235, 240, 250);
    video_pal_rgb(P_SPR + 7, 170, 180, 195);
    video_pal_rgb(P_SPR + 8, 90, 95, 110);
    video_pal_rgb(P_SPR + 9, 20, 110, 40);
    video_pal_rgb(P_SPR + 10, 70, 220, 100);
}

/* the palette's animation: the stars twinkle, the title's colours run.
   The colours come from tables made at start-up (a hue wheel, a twinkle),
   so a frame's cycling is 25 palette writes */
static unsigned short hue[64], twinkle[64];

static void cycle_init(void)
{
    int h;
    for (h = 0; h < 64; h++) {
        int s = h / 11, f = (h % 11) * 23, v = h < 32 ? h : 63 - h, r, g, b;
        r = s == 0 || s == 5 ? 255 : s == 1 ? 255 - f : s == 4 ? f : 0;
        g = s == 1 || s == 2 ? 255 : s == 0 ? f : s == 3 ? 255 - f : 0;
        b = s == 3 || s == 4 ? 255 : s == 2 ? f : s == 5 ? 255 - f : 0;
        hue[h] = rgb565(r, g, b);
        twinkle[h] = rgb565(60 + v * 6, 60 + v * 6, 80 + v * 5);
    }
}

static void cycle(void)
{
    int i;
    for (i = 0; i < 8; i++)
        VID_PAL(P_STAR + i) = twinkle[(frame_no * 3 + i * 37) & 63];
    for (i = 0; i < 16; i++)
        VID_PAL(P_TITLE + i) = hue[((frame_no >> 1) + i * 4) & 63];
    video_pal_rgb(P_BLINK, 0, (frame_no & 32) ? 255 : 120, (frame_no & 32) ? 200 : 90);
}

static unsigned char sp_pix[PADW * 8], sp_msk[PADW * 8];

/* a sprite from string art: '.' transparent, else the character's colour */
static void art(Sprite *s, int w, int h, const char *rows, const char *keys,
                const unsigned char *cols)
{
    int i;
    for (i = 0; i < w * h; i++) {
        const char *k = strchr(keys, rows[i]);
        sp_msk[i] = rows[i] != '.';
        sp_pix[i] = k ? cols[k - keys] : 0;
    }
    sprite_make(s, w, h, sp_pix, sp_msk, fmt);
}

static void sprites(void)
{
    static const char ball_art[] =
        "..####.."
        ".#++==#."
        "#++====#"
        "#+=====#"
        "#=====-#"
        "#====--#"
        ".#=---#."
        "..####..";
    static const unsigned char ball_cols[] = {P_SPR + 0, P_SPR + 1, P_SPR + 2, P_SPR + 3};
    static const char cap_art[] =
        "..############.."
        ".#ggggg++gggggg#"
        "#ggggggWWgggggg#"
        "#ggggWWWWWWgggg#"
        "#ggggWWWWWWgggg#"
        "#ggggggWWgggggg#"
        ".#dddddddddddd#."
        "..############..";
    static const unsigned char cap_cols[] = {P_SPR + 9, P_SPR + 10, P_SPR + 1, P_SPR + 1,
                                             P_SPR + 9};
    int x, y;
    art(&spr_ball, 8, 8, ball_art, "#+=-", ball_cols);
    art(&spr_cap, 16, 8, cap_art, "#g+Wd", cap_cols);
    /* the paddle: a capsule of 40 x 8, red ends, a silver middle shaded
       from the top */
    for (y = 0; y < 8; y++)
        for (x = 0; x < PADW; x++) {
            /* in doubled units: round ends of radius 8 about X = 8 and 2 PADW - 8 */
            int X = 2 * x + 1, dx = X < 8 ? X - 8 : X > 2 * PADW - 8 ? X - (2 * PADW - 8) : 0;
            int dy = 2 * y - 7, in = dx * dx + dy * dy <= 64, end = x < 7 || x >= PADW - 7;
            int shade = y == 0 ? 0 : y < 3 ? 1 : y < 6 ? 2 : 3;
            sp_msk[y * PADW + x] = in;
            if (end)
                sp_pix[y * PADW + x] = shade < 2 ? P_SPR + 5 : P_SPR + 4;
            else
                sp_pix[y * PADW + x] = shade == 0 ? P_SPR + 1 : P_SPR + 5 + shade;
            if (!in || ((dx * dx + dy * dy > 40) && (y == 0 || y == 7)))
                sp_pix[y * PADW + x] = P_SPR + 0;
        }
    sprite_make(&spr_paddle, PADW, 8, sp_pix, sp_msk, fmt);
}

/* text k times its size, each row of it a colour from c0 (+ row / k) */
static void big_text(Surface *s, int x, int y, const char *str, int k, int c0)
{
    static unsigned tmp[64 * 20];
    Surface t;
    int w = font_width(font_sans, str), h = font_sans->height, i, j;
    gfx_init(&t, tmp, w, h, (w + 3) / 4, fmt);
    gfx_fill(&t, 0, 0, w, h, 0, ROP_COPY);
    font_draw(&t, font_sans, 0, font_sans->ascent, str, 1, -1);
    x -= w * k / 2;             /* centred on x */
    for (j = 0; j < h; j++)
        for (i = 0; i < w; i++)
            if (gfx_get(&t, i, j)) {
                gfx_fill(s, x + i * k + 1, y + j * k + 1, x + i * k + k + 1, y + j * k + k + 1,
                         0, ROP_COPY);
                gfx_fill(s, x + i * k, y + j * k, x + i * k + k, y + j * k + k,
                         c0 < P_TITLE ? c0 : c0 + (j * 15 / h), ROP_COPY);
            }
}

static void text_centred(Surface *s, int y, const char *str, unsigned c)
{
    font_draw(s, font_sans, (W - font_width(font_sans, str)) / 2, y, str, c, -1);
}

/* the backdrop: a dark gradient, stars, the walls */
static void backdrop(Surface *s)
{
    int y, i;
    for (y = 0; y < H; y++)
        gfx_fill(s, 0, y, W, y + 1, P_BACK + y * 16 / H, ROP_COPY);
    rnd_at = 0;
    for (i = 0; i < 90; i++)
        gfx_pixel(s, WALL + rnd(255) + rnd(63), TOPY + rnd(127) + rnd(63) + rnd(15),
                  P_STAR + rnd(7), ROP_COPY);
    gfx_fill(s, 0, SROWS, WALL, H, P_WALL, ROP_COPY);
    gfx_fill(s, W - WALL, SROWS, W, H, P_WALL, ROP_COPY);
    gfx_fill(s, 0, SROWS, W, TOPY, P_WALL, ROP_COPY);
    gfx_fill(s, 1, TOPY, 2, H, P_WALL + 1, ROP_COPY);
    gfx_fill(s, W - 3, TOPY, W - 2, H, P_WALL + 2, ROP_COPY);
    gfx_fill(s, 1, SROWS + 1, W - 1, SROWS + 2, P_WALL + 1, ROP_COPY);
}

static void draw_brick(Surface *s, int r, int c)
{
    int x = BX + c * BW, y = BY + r * BH, k = grid[r][c] - 1, p = P_BRICK + 4 * k;
    gfx_fill(s, x, y, x + BW - 1, y + BH - 1, p + 1, ROP_COPY);
    gfx_bevel(s, x, y, x + BW - 1, y + BH - 1, p, p + 2);
    if (k == K_STEEL || k == K_CRACKED) {
        gfx_pixel(s, x + 3, y + 3, p + 2, ROP_COPY);
        gfx_pixel(s, x + BW - 5, y + 3, p + 2, ROP_COPY);
    }
    if (k == K_CRACKED)
        gfx_line(s, x + 6, y + 1, x + 14, y + BH - 3, p + 2, ROP_COPY);
    if (k == K_CAPS) {
        gfx_fill(s, x + 10, y + 4, x + 13, y + 5, p + 2, ROP_COPY);
        gfx_fill(s, x + 11, y + 3, x + 12, y + 6, p + 2, ROP_COPY);
    }
}

/* a screen as the background: every buffer the background, nothing to erase */
static void present(void)
{
    gfx_blit(&pic[0], 0, 0, &pic[2], 0, 0, W, H, ROP_COPY);
    gfx_blit(&pic[1], 0, 0, &pic[2], 0, 0, W, H, ROP_COPY);
    ndrawn[0] = ndrawn[1] = npdrawn[0] = npdrawn[1] = npending[0] = npending[1] = 0;
}

/* The status line. Drawing text through the library at 8 bits a pixel
   costs about 15,000 ticks a glyph, the whole line two thirds of a
   frame, so the labels are drawn once, the digits copied from cells
   rendered at start-up (8 x 16 pixels, two words a row), and AUTO is
   shown and hidden by its palette entry. */
static unsigned digit[10][32];
static int score_x, level_x, lives_x;

static void status_init(void)
{
    static unsigned strip[20 * 16];
    Surface t;
    int d, r, x;
    char str[2];
    gfx_init(&t, strip, 80, 16, 20, fmt);
    gfx_fill(&t, 0, 0, 80, 16, 0, ROP_COPY);
    str[1] = 0;
    for (d = 0; d < 10; d++) {
        str[0] = '0' + d;
        font_draw(&t, font_sans, d * 8 + (8 - font_width(font_sans, str)) / 2, 12, str, P_TEXT,
                  -1);
        for (r = 0; r < 16; r++) {
            digit[d][2 * r] = strip[r * 20 + 2 * d];
            digit[d][2 * r + 1] = strip[r * 20 + 2 * d + 1];
        }
    }
    gfx_fill(&status_s, 0, 0, W, SROWS, 0, ROP_COPY);
    x = font_draw(&status_s, font_sans, 4, 12, "SCORE ", P_TEXT, -1);
    score_x = (x + 3) & ~3;
    font_draw(&status_s, font_sans, score_x + 60, 12, "AUTO", P_AUTO, -1);
    x = font_draw(&status_s, font_sans, 196, 12, "LEVEL ", P_TEXT, -1);
    level_x = (x + 3) & ~3;
    x = font_draw(&status_s, font_sans, level_x + 20, 12, "LIVES ", P_TEXT, -1);
    lives_x = (x + 3) & ~3;
}

/* digit d at x (a multiple of 4) */
static void put_digit(int x, int d)
{
    unsigned *p = status_fb + x / 4;
    const unsigned *c = digit[d];
    int r;
    for (r = 0; r < 16; r++) {
        p[r * (W / 4)] = c[2 * r];
        p[r * (W / 4) + 1] = c[2 * r + 1];
    }
}

/* the score as six decimal digits, the last first: points are added
   digit by digit, and only the digits that change are drawn */
static unsigned char sdig[6], shown[6];

static void add_score(int points)
{
    int i = 0;
    while (points) {
        int d = sdig[i] + points % 10;      /* points < 100: a small divide */
        points /= 10;
        if (d > 9) {
            d -= 10;
            points++;
        }
        sdig[i++] = d;
        if (i == 6)
            break;
    }
}

static void status(void)
{
    int i;
    for (i = 0; i < 6; i++)
        if (sdig[i] != shown[i]) {
            put_digit(score_x + 8 * (5 - i), sdig[i]);
            shown[i] = sdig[i];
        }
    put_digit(level_x, level + 1);
    put_digit(lives_x, lives);
    video_pal(P_AUTO, autoplay ? rgb565(255, 220, 60) : 0);
}

static void reset_score(void)
{
    int i;
    for (i = 0; i < 6; i++) {
        sdig[i] = 0;
        shown[i] = 1;
    }
}

/* the descriptors of table t: the status line, then the picture, each
   line shifted by off(y) words (the wobble); off 0 is the picture */
static const signed char wave[32] = {0, 1, 1, 2, 2, 2, 3, 3, 3, 3, 3, 2, 2, 2, 1, 1,
                                     0, -1, -1, -2, -2, -2, -3, -3, -3, -3, -3, -2, -2, -2, -1, -1};

static void descriptors(int t, int amp)
{
    unsigned *d = video_table(t), w = video_desc(pic[t].bits, 0);
    int y;
    for (y = 0; y < SROWS * 2; y++)
        d[y] = video_desc(status_fb + (y >> 1) * (W / 4), 0);
    for (y = SROWS; y < H; y++) {
        int off = amp ? wave[(y + frame_no) & 31] * amp / 4 : 0;
        d[2 * y] = d[2 * y + 1] = w + y * PITCH + off;
    }
}

static void screen(void)
{
    int b, y;
    video_init(1, 0);
    fmt = gfx_screen_format();
    bytes_px = fmt == PF_LIN8;
    pair_mask[0] = gfx_format(fmt)->pmask[0] | gfx_format(fmt)->pmask[1];
    pair_mask[1] = gfx_format(fmt)->pmask[2] | gfx_format(fmt)->pmask[3];
    for (b = 0; b < 4; b++) {
        buf[b] = vram_alloc(PITCH * ROWS * 4);
        memset(buf[b], 0, PITCH * ROWS * 4);
        gfx_init(&pic[b], buf[b] + GUARD * PITCH + GUARD / 4, W, H, PITCH, fmt);
    }
    for (b = 0; b < 3; b++) {
        for (y = 0; y < ROWS; y++)
            rowbuf[b][y] = pic[b].bits + (y - GUARD) * PITCH;
        rowp[b] = rowbuf[b] + GUARD;
    }
    status_fb = vram_alloc(W * SROWS);
    gfx_init(&status_s, status_fb, W, SROWS, W / 4, fmt);
    status_init();
    bob_pitch = PITCH;
    palette();
    cycle_init();
    descriptors(0, 0);
    descriptors(1, 0);
    for (y = 0; y < W; y++)
        colof[y] = y >= BX && y < BX + BCOLS * BW ? (y - BX) / BW : 255;
    for (y = 0; y < H; y++)
        rowof[y] = y >= BY && y < BY + BROWS * BH ? (y - BY) / BH : 255;
}

/* ---- the frame: erase, then draw ---- */

/* what was drawn into the back buffer last time, from the background */
static void erase(void)
{
    int b = back, i, off = (buf[2] - buf[b]) * 4;
    restore_compiled(drawn[b], ndrawn[b], off);
    if (bytes_px)
        for (i = 0; i < npdrawn[b]; i++) {
            unsigned char *p = pdrawn[b][i];
            *(unsigned short *)p = *(unsigned short *)(p + off);
            *(unsigned short *)(p + PITCH * 4) = *(unsigned short *)(p + PITCH * 4 + off);
        }
    else
        for (i = 0; i < npdrawn[b]; i++) {
            unsigned *p = (unsigned *)pdrawn[b][i];
            p[0] = *(unsigned *)((char *)p + off);
            p[PITCH] = *(unsigned *)((char *)(p + PITCH) + off);
        }
    for (i = 0; i < npending[b]; i++) {
        Rect *r = &pending[b][i];
        gfx_blit(&pic[b], r->x0, r->y0, &pic[2], r->x0, r->y0, r->x1 - r->x0, r->y1 - r->y0,
                 ROP_COPY);
    }
    ndrawn[b] = npdrawn[b] = npending[b] = 0;
}

/* a sprite at (x, y): its byte-store code to draw, its restore to erase */
static void put(Blt *d, Blt *r, const Sprite *s, int x, int y)
{
    int ph = x & 3;
    unsigned *p = rowp[back][y] + (x >> 2);
    d->d = r->d = p;
    d->s = s->bcode[ph];
    r->s = s->rcode[ph];
    d->w = r->w = s->ww[ph];
    d->h = r->h = s->h;
}

static void draw(int paddle)
{
    static Blt list[MAXOBJ];
    int b = back, n = 0, i;
    Blt *r = drawn[b];
    if (paddle) {
        put(&list[n], &r[n], &spr_paddle, padx - PADW / 2, PADY);
        n++;
    }
    for (i = 0; i < ncap; i++, n++)
        put(&list[n], &r[n], &spr_cap, capx[i] - 8, capy[i]);
    for (i = 0; i < nball; i++, n++)
        put(&list[n], &r[n], &spr_ball, (ball[i].x >> FIX) - 4, (ball[i].y >> FIX) - 4);
    draw_compiled(list, n);
    ndrawn[b] = n;
    /* the particles: 2 x 2 (x even), two half-word stores in L0 */
    if (bytes_px)
        for (i = 0; i < npart; i++) {
            Part *q = &part[i];
            unsigned char *p = (unsigned char *)rowp[b][q->y >> FIX] + ((q->x >> FIX) & ~1);
            *(unsigned short *)p = q->c;
            *(unsigned short *)(p + PITCH * 4) = q->c;
            pdrawn[b][i] = p;
        }
    else
        for (i = 0; i < npart; i++) {
            Part *q = &part[i];
            int x = q->x >> FIX;
            unsigned *p = rowp[b][q->y >> FIX] + (x >> 2), m = pair_mask[(x >> 1) & 1];
            p[0] = (p[0] & ~m) | (q->c & m);
            p[PITCH] = (p[PITCH] & ~m) | (q->c & m);
            pdrawn[b][i] = (unsigned char *)p;
        }
    npdrawn[b] = npart;
}

/* show the back buffer from the next frame */
static int flip(void)
{
    int n = video_wait();
    if (wobble) {
        descriptors(back, wobble > 16 ? 4 : wobble / 4);
        wobble--;
    }
    video_ctrl(back ? VC_TSEL : 0, VC_TSEL);
    back ^= 1;
    frame_no++;
    cycle();
    return n;
}

/* ---- the game ---- */

/* a brick's particles (burst, 12 unless poked), from where it was,
   flying up and out.
   Written with a moving pointer and the random table read in place:
   &part[npart++] would multiply by the structure's size each time */
static void spawn(int x, int y, int k)
{
    int n = MAXPART - npart, i;
    unsigned c0 = P_BRICK + 4 * k, c1 = c0 + 1;
    const unsigned short *r;
    Part *q = part + npart;
    if (n > burst)
        n = burst;
    if (n > 200)
        n = 200;                /* the random table's limit */
    if (rnd_at > 1024 - 5 * n)
        rnd_at = 0;
    r = rnd_table + rnd_at;
    rnd_at += 5 * n;
    npart += n;
    x = (x + 2) << FIX;
    y = (y + 1) << FIX;
    if (bytes_px) {
        c0 *= 0x101;            /* two pixels, a half-word */
        c1 *= 0x101;
    } else {
        c0 = gfx_solid(fmt, c0);
        c1 = gfx_solid(fmt, c1);
    }
    for (i = 0; i < n; i++, q++, r += 5) {
        q->x = x + (r[0] & 15) * 256;
        q->y = y + (r[1] & 7) * 256;
        q->dx = r[2] - 256;
        q->dy = -(int)r[3] - 64;
        q->life = 30 + (r[4] & 31);
        q->c = (i & 1) ? c1 : c0;       /* the light shade or the body */
    }
}

/* a brick is hit: steel cracks, anything else breaks into particles, out
   of the background and so, through the pending rectangles, off both
   screens */
static void hit(int r, int c)
{
    int k = grid[r][c] - 1, x = BX + c * BW, y = BY + r * BH, b;
    if (k == K_STEEL) {
        grid[r][c] = K_CRACKED + 1;
        draw_brick(&pic[2], r, c);
        add_score(5);
    } else {
        grid[r][c] = 0;
        bricks_left--;
        gfx_blit(&pic[2], x, y, &pic[3], x, y, BW, BH, ROP_COPY);
        spawn(x, y, k == K_CRACKED ? K_STEEL : k);
        add_score((BROWS - r) * 10);
        if (k == K_CAPS && ncap < MAXCAP) {
            capx[ncap] = x + BW / 2;
            capy[ncap++] = y;
        }
    }
    for (b = 0; b < 2; b++)
        if (npending[b] < 64) {
            Rect *q = &pending[b][npending[b]++];
            q->x0 = x;
            q->y0 = y;
            q->x1 = x + BW;
            q->y1 = y + BH;
        }
    status();
}

/* the brick under pixel (x, y), as row * BCOLS + column, or -1 */
static int brick_at(int x, int y)
{
    int c, r;
    if (x < 0 || x >= W || y < 0 || y >= H)
        return -1;
    c = colof[x];
    r = rowof[y];
    if (c == 255 || r == 255 || !grid[r][c])
        return -1;
    return r * BCOLS + c;
}

/* a ball's box at (x, y) against the bricks: the first under a corner */
static int bricks_under(int x, int y)
{
    int x0 = (x >> FIX) - 4, y0 = (y >> FIX) - 4, k;
    if ((k = brick_at(x0, y0)) >= 0 || (k = brick_at(x0 + 7, y0)) >= 0 ||
        (k = brick_at(x0, y0 + 7)) >= 0 || (k = brick_at(x0 + 7, y0 + 7)) >= 0)
        return k;
    return -1;
}

static void level_start(void)
{
    int r, c;
    const char *const *lv = levels[level & 1];
    gfx_blit(&pic[2], 0, 0, &pic[3], 0, 0, W, H, ROP_COPY);
    bricks_left = 0;
    for (r = 0; r < BROWS; r++)
        for (c = 0; c < BCOLS; c++) {
            const char *k = strchr(kinds, lv[r][c]);
            grid[r][c] = k && lv[r][c] != '.' ? (k - kinds) + 1 : 0;
            if (grid[r][c]) {
                draw_brick(&pic[2], r, c);
                bricks_left++;
            }
        }
    present();
    nball = 0;
    ncap = 0;
    npart = 0;
    serving = 1;
    status();
}

/* the ball on the paddle, until served */
static void serve(void)
{
    nball = 1;
    ball[0].x = padx << FIX;
    ball[0].y = (PADY - 5) << FIX;
    ball[0].dx = (rnd(1) ? 1 : -1) * (200 + rnd(255));
    ball[0].dy = -768;
}

static void move_balls(void)
{
    int i, k;
    for (i = 0; i < nball; i++) {
        Ball *o = &ball[i];
        int x = o->x + o->dx, y;
        /* across: the walls, then the bricks */
        if (x < (WALL + 4) << FIX || x > (W - WALL - 4) << FIX) {
            o->dx = -o->dx;
            x = o->x;
        } else if ((k = bricks_under(x, o->y)) >= 0) {
            hit(k / BCOLS, k % BCOLS);
            o->dx = -o->dx;
            x = o->x;
        }
        o->x = x;
        /* down or up: the top wall, the bricks, the paddle */
        y = o->y + o->dy;
        if (y < (TOPY + 4) << FIX) {
            o->dy = -o->dy;
            y = o->y;
        } else if ((k = bricks_under(o->x, y)) >= 0) {
            hit(k / BCOLS, k % BCOLS);
            o->dy = -o->dy;
            y = o->y;
        } else if (o->dy > 0 && (y >> FIX) + 4 >= PADY && (o->y >> FIX) + 4 < PADY + 4) {
            int off = (x >> FIX) - padx;
            if (off >= -PADW / 2 - 3 && off <= PADW / 2 + 3) {
                /* the further out, the steeper; a little faster each time */
                o->dx = off * 48;
                o->dy = -(o->dy < 1100 ? o->dy + 16 : o->dy);
                y = o->y;
            }
        }
        o->y = y;
        if ((y >> FIX) > H + 4) {
            *o = ball[--nball];         /* lost */
            i--;
        }
    }
}

static void move_rest(void)
{
    int i;
    for (i = 0; i < ncap; i++) {
        capy[i]++;
        if (capy[i] + 8 >= PADY && capy[i] < PADY + 8 && capx[i] > padx - PADW / 2 - 8 &&
            capx[i] < padx + PADW / 2 + 8) {
            /* caught: two more balls, and the picture wobbles */
            int n = nball ? 0 : -1, j;
            for (j = 0; j < 2 && nball < MAXBALL && n >= 0; j++) {
                ball[nball] = ball[n];
                ball[nball].dx = ball[n].dx + (j ? 300 : -300);
                ball[nball].dy = -(ball[n].dy < 0 ? -ball[n].dy : ball[n].dy);
                nball++;
            }
            add_score(50);
            status();
            wobble = 40;
            if (!caught++)
                shot_at = frame_no + 10;    /* while it wobbles */
            capy[i] = H + 10;
        }
        if (capy[i] > H) {
            capx[i] = capx[--ncap];
            capy[i] = capy[ncap];
            i--;
        }
    }
    for (i = 0; i < npart; i++) {
        Part *q = &part[i];
        q->x += q->dx;
        q->y += q->dy;
        q->dy += 16;            /* gravity */
        if (--q->life <= 0 || q->y >> FIX >= H - 2 || q->y >> FIX < TOPY ||
            q->x >> FIX < WALL || q->x >> FIX >= W - WALL - 2) {
            *q = part[--npart];
            i--;
        }
    }
}

static void paddle(int auto_on)
{
    int target = padx, i, low = -1;
    if (auto_on) {
        /* follow the lowest ball coming down, hitting it off-centre so it
           goes somewhere new */
        for (i = 0; i < nball; i++)
            if (ball[i].dy > 0 && (low < 0 || ball[i].y > ball[low].y))
                low = i;
        if (low >= 0)
            target = (ball[low].x >> FIX) + ((int)(frame_no / 61 % 5) - 2) * 6;
        else if (ncap)
            target = capx[0];
    } else {
        static int last_mx = -1;
        if (last_mx < 0)
            last_mx = mouse_x;
        if (mouse_x != last_mx) {
            last_mx = mouse_x;
            target = mouse_x / 2;
        }
        if (key_down(K_LEFT))
            target = padx - 5;
        if (key_down(K_RIGHT))
            target = padx + 5;
    }
    if (target > padx + 6)
        target = padx + 6;
    if (target < padx - 6)
        target = padx - 6;
    padx = target < WALL + PADW / 2 ? WALL + PADW / 2 : target > W - WALL - PADW / 2
         ? W - WALL - PADW / 2 : target;
}

/* the keys and clicks: A the autopilot, Esc gives up; space or a click
   to go on */
static int give_up;

static int pressed(void)
{
    Event e;
    int go = 0;
    while (input_next(&e)) {
        if (e.type == EV_KEY && (e.ch == 'a' || e.ch == 'A')) {
            autoplay = !autoplay;
            status();
        }
        if (e.type == EV_KEY && e.key == K_ESC)
            give_up = 1;
        if ((e.type == EV_KEY && e.key == ' ') || (e.type == EV_MOUSE && (e.buttons & 1)))
            go = 1;
    }
    return go;
}

/* ---- the screens ---- */

static unsigned t_erase, t_logic, t_draw, nframes, t_max, missed, most_parts, sum_parts;

static void title(void)
{
    int i;
    Surface *s = &pic[2];
    gfx_blit(s, 0, 0, &pic[3], 0, 0, W, H, ROP_COPY);
    big_text(s, W / 2, 40, "HERON", 5, P_TITLE);
    big_text(s, W / 2, 105, "BRICKS", 4, P_TITLE);
    text_centred(s, 180, "SPACE OR CLICK TO PLAY", P_BLINK);
    text_centred(s, 200, "ARROWS OR MOUSE: PADDLE    A: AUTOPILOT", P_TEXT);
    text_centred(s, 220, "a brick breaker for Heron Mini, M1 320 x 240 x 8", P_WALL);
    present();
    reset_score();
    lives = 3;
    status();
    /* balls bounce about behind nothing */
    nball = 3;
    for (i = 0; i < 3; i++) {
        ball[i].x = (60 + 90 * i) << FIX;
        ball[i].y = (150 - 30 * i) << FIX;
        ball[i].dx = 300 - 250 * i;
        ball[i].dy = 260 + 60 * i;
    }
    for (;;) {
        erase();
        for (i = 0; i < nball; i++) {
            Ball *o = &ball[i];
            o->x += o->dx;
            o->y += o->dy;
            if (o->x < (WALL + 4) << FIX || o->x > (W - WALL - 4) << FIX)
                o->dx = -o->dx;
            if (o->y < (TOPY + 4) << FIX || o->y > (H - 4) << FIX)
                o->dy = -o->dy;
        }
        draw(0);
        flip();
        if (frame_no == 40)
            printf("@shot title\n");
        if (pressed())
            break;
    }
}

static void play(void)
{
    unsigned t0, t1, t2, t3;
    int serve_wait = 0;
    level = 0;
    lives = 3;
    give_up = 0;
    reset_score();
    padx = W / 2;
    level_start();
    t_erase = t_logic = t_draw = nframes = t_max = missed = most_parts = sum_parts = 0;
    video_wait();               /* the set-up's frames aren't the game's */
    for (;;) {
        int go;
        perf_frame_begin();
        t0 = video_ticks();
        erase();
        t1 = video_ticks();
        go = pressed();
        if (give_up)
            break;
        paddle(autoplay);
        if (serving) {
            serve();
            ball[0].x = padx << FIX;
            if (go || (autoplay && ++serve_wait > 30)) {
                serving = 0;
                serve_wait = 0;
            }
        } else {
            move_balls();
            if (!nball) {
                if (--lives <= 0)
                    break;
                serving = 1;
                ncap = 0;
                status();
            }
        }
        move_rest();
        if (!bricks_left) {
            level++;
            wobble = 40;
            level_start();
        }
        t2 = video_ticks();
        draw(1);
        t3 = video_ticks();
        perf_frame_end();
        t_erase += t1 - t0;
        t_logic += t2 - t1;
        t_draw += t3 - t2;
        if (npart > most_parts)
            most_parts = npart;
        sum_parts += npart;
        if (t3 - t0 > t_max)
            t_max = t3 - t0;
#ifdef SLOW_FRAMES
        if (t3 - t0 > SLOW_FRAMES)
            printf("slow frame %u: erase %u logic %u draw %u, %d balls %d particles\n", nframes,
                   t1 - t0, t2 - t1, t3 - t2, nball, npart);
#endif
        nframes++;
        missed += flip() - 1;
        if (nframes == 300)
            printf("@shot play\n");
        if (frame_no == shot_at)
            printf("@shot multiball\n");
    }
    perf_frames("play");
    printf("game over at frame %u\n", frame_no);
    printf("@perf play_erase %u\n@perf play_logic %u\n@perf play_draw %u\n", t_erase / nframes,
           t_logic / nframes, t_draw / nframes);
    printf("played %u frames: erase %u, logic %u, draw %u ticks a frame on average, %u at most;"
           " %u frames missed; particles %u on average, %u at most\n", nframes, t_erase / nframes,
           t_logic / nframes, t_draw / nframes, t_max, missed, sum_parts / nframes, most_parts);
    printf("@perf play_parts %u %u\n", sum_parts / nframes, most_parts);
}

static void game_over(void)
{
    char line[40];
    int i;
    Surface *s = &pic[2];
    lives = 0;
    status();
    gfx_fill(s, 40, 60, W - 40, 170, P_BACK, ROP_COPY);
    gfx_frame(s, 40, 60, W - 40, 170, 2, P_WALL + 1, ROP_COPY);
    big_text(s, W / 2, 70, "GAME OVER", 3, P_TITLE);
    sprintf(line, "SCORE %d%d%d%d%d%d", sdig[5], sdig[4], sdig[3], sdig[2], sdig[1], sdig[0]);
    big_text(s, W / 2, 112, line, 2, P_TEXT);
    text_centred(s, 160, "SPACE OR CLICK TO PLAY AGAIN", P_BLINK);
    present();
    nball = ncap = npart = 0;
    for (i = 0;; i++) {
        erase();
        /* fireworks: a burst of particles now and then */
        if (i % 25 == 0)
            spawn(40 + rnd(127) + rnd(63) + rnd(31), 40 + rnd(63), rnd(3) + rnd(3));
        move_rest();
        draw(0);
        flip();
        if (i == 20)
            printf("@shot gameover\n");
        if (pressed())
            break;
    }
}

int main(void)
{
    font_init();
    input_init();
    rnd_init(12345);
    screen();
    sprites();
    backdrop(&pic[3]);
    for (;;) {
        title();
        play();
        game_over();
    }
    return 0;
}
