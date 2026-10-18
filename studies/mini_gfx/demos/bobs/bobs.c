/* Bobs: a benchmark of software sprites ("blitter objects"). How many
   masked 16 x 16 and 32 x 32 sprites can be erased, moved and drawn each
   frame over a busy background, at 60 Hz and at 30 Hz, in M1 used as
   320 x 240 x 8 (every line shown twice by the descriptors) or in M0
   (640 x 480 x 4), by each way of drawing and of erasing them:

     drawing   generic    the library's gfx_masked: any phase, any format
               shifted    pre-shifted rows of (~mask, image) words
               spans      pre-shifted, transparent words skipped, opaque
                          ones stored without reading the screen
               compiled   machine code made at start-up (jit.c)
               bytes      compiled, with byte and half stores where an
                          edge word's pixels are whole bytes (M1 in L0)
     erasing   full       the whole picture copied from the background
               dirty      each sprite's rectangle from the background
               save       each sprite's rectangle saved before it's
                          drawn, put back the next time (save-under)
               exact      compiled: the words the sprite drew, from the
                          background

   double-buffered with the two descriptor tables (TSEL), against a single
   buffer. Each configuration runs with a few bobs to measure what a bob
   costs and what a frame costs without them, predicts how many fit a
   frame, and checks the prediction by running that many.

   The buffers have guard bands (32 pixels on each side, 32 rows above
   and below) so the sprites can hang off the edges unclipped: the line
   descriptors show the picture's part. A status line at the top comes
   from a buffer of its own, through its own descriptors, so the sprites
   never need to avoid it or redraw it.

   Pokes: mode_sel 1 (M1, the default) or 0 (M0); quick 1 for fewer
   configurations; showcase 1 for only the showcase at the end. */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "gfx.h"
#include "video.h"
#include "perf.h"
#include "sprite.h"
#include "art.h"

int mode_sel = 1;
int quick;
int showcase;

#if defined(GFX_BLK)
#define SHIFTED draw_shifted_asm
#define SPANS   draw_spans_blk
#define RESTORE restore_blk
#define SAVEK   save_blk
#define UNSAVE  unsave_blk
#elif defined(GFX_ASM)
#define SHIFTED draw_shifted_asm
#define SPANS   draw_spans_asm
#define RESTORE restore_asm
#define SAVEK   save_asm
#define UNSAVE  unsave_asm
#else
#define SHIFTED draw_shifted_c
#define SPANS   draw_spans_c
#define RESTORE restore_c
#define SAVEK   save_c
#define UNSAVE  unsave_c
#endif

#define MAXB 512                /* bobs at most */
#define GUARD 32                /* the guard bands, in pixels and rows */
#define NDES 4                  /* sprite designs */
#define FRAME 840000            /* ticks a frame */
#define MARGIN 12000            /* kept free in a frame's prediction */

enum { T_GENERIC, T_SHIFTED, T_SPANS, T_COMPILED, T_BYTES, NT };
enum { E_FULL, E_DIRTY, E_SAVE, E_EXACT, NE };
static const char *tname[NT] = {"generic", "shifted", "spans", "compiled", "bytes"};
static const char *ename[NE] = {"full", "dirty", "save", "exact"};

typedef struct {
    int x, y, dx, dy;
    Sprite *s;
} Bob;

/* the screen */
static int W, H, ps, ppw, fmt, SROWS;   /* picture, log2 pixels a word, status rows */
static int ROWS;                        /* a buffer's rows, guard bands included */
static unsigned *buf[3];                /* the two buffers and the background */
static unsigned **rows[2];              /* each buffer's rows at the picture's x = 0 */
static Surface pic[3], whole[3];        /* the picture's part of each, and all of it */
static unsigned *status_fb;
static Surface status_s;

/* the sprites and bobs */
static Sprite spr[2][NDES];             /* 16 x 16 and 32 x 32 */
static Bob bob[MAXB];
static Blt dl[MAXB];                    /* this frame's draws */
static Blt rect[2][MAXB];               /* each buffer's rectangles: to restore, or saved */
static int nrect[2];
static unsigned *save_area[2];
static int back;                        /* the buffer drawn into */
static int tech, erase, nbobs, single;

/* each mode's colours for the art's logical ones */
static unsigned char colour[C_N];

/* ---- set-up ---- */

static unsigned rnd_state = 12345;

static int rnd(int n)
{
    rnd_state = rnd_state * 1103515245u + 12345u;
    return (rnd_state >> 16) % n;
}

/* the palette: M1's 256 entries (the background's ramps, the sprites'
   ramps from 160), or M0's 16 */
static void palette(void)
{
    static const unsigned char ramp[4][3] = {
        {255, 70, 50}, {255, 200, 40}, {60, 220, 255}, {90, 230, 70},
    };
    int k, i;
    video_default_palette();
    if (vid.bpp == 8) {
        /* the background: 16 to 47 blues, 48 to 79 purples, 80 the grid, 81 the text */
        for (i = 0; i < 32; i++) {
            video_pal_rgb(16 + i, 10 + i * 2, 20 + i * 3, 60 + i * 4);
            video_pal_rgb(48 + i, 40 + i * 3, 12 + i, 50 + i * 3);
        }
        video_pal_rgb(80, 120, 200, 210);
        video_pal_rgb(81, 255, 250, 200);
        for (k = 0; k < 4; k++)
            for (i = 0; i < 8; i++) {
                int a = 40 + i * 30;
                video_pal_rgb(160 + 8 * k + i, ramp[k][0] * a / 255, ramp[k][1] * a / 255,
                              ramp[k][2] * a / 255);
            }
        video_pal_rgb(160 + C_WHITE, 255, 255, 255);
        video_pal_rgb(160 + C_BLACK, 0, 0, 0);
        video_pal_rgb(160 + C_OUTLINE, 20, 70, 20);
        video_pal_rgb(160 + C_MOUTH, 140, 0, 30);
        video_pal_rgb(160 + C_FEET, 255, 140, 0);
        for (i = 0; i < C_N; i++)
            colour[i] = 160 + i;
    } else {
        /* 0 black, 1-3 the background, then three shades of each ramp */
        static const unsigned char m0[16][3] = {
            {0, 0, 0}, {20, 30, 90}, {60, 25, 85}, {110, 180, 200},
            {120, 20, 10}, {230, 60, 40}, {255, 200, 180}, {150, 110, 0},
            {255, 210, 50}, {20, 100, 140}, {80, 220, 255}, {20, 70, 20},
            {90, 220, 70}, {255, 255, 255}, {140, 0, 30}, {255, 140, 0},
        };
        static const unsigned char map[C_N] = {
            4, 4, 4, 5, 5, 5, 6, 6, 7, 7, 7, 8, 8, 8, 13, 13, 9, 9, 9, 10, 10, 10, 13, 13,
            11, 11, 12, 12, 12, 12, 12, 12, 13, 0, 11, 14, 15,
        };
        for (i = 0; i < 16; i++)
            video_pal_all(i, rgb565(m0[i][0], m0[i][1], m0[i][2]));
        for (i = 0; i < C_N; i++)
            colour[i] = map[i];
    }
}

/* the background: tiles of shaded rows in two ramps, a grid, rings and
   lines across, some text: something no fill could erase */
static void background(Surface *s)
{
    int t = vid.bpp == 8 ? 16 : 32, x, y, r;
    unsigned grid, text;
    static const unsigned char dots[8] = {0x88, 0x00, 0x22, 0x00, 0x88, 0x00, 0x22, 0x00};
    if (vid.bpp == 8) {
        for (y = 0; y < H; y++)
            for (x = 0; x < W; x += t) {
                int base = ((x / t + y / t) & 1) ? 48 : 16;
                gfx_fill(s, x, y, x + t, y + 1, base + (y % t) * 2 + (x / t) % 2, ROP_COPY);
            }
        grid = 80;
        text = 81;
    } else {
        for (y = 0; y < H; y += t)
            for (x = 0; x < W; x += t)
                gfx_fill_pat(s, x, y, x + t, y + t, dots, 3, ((x / t + y / t) & 1) ? 1 : 2);
        grid = 3;
        text = 13;
    }
    for (x = 0; x < W; x += t)
        gfx_vline(s, x, 0, H, grid, ROP_COPY);
    for (y = 0; y < H; y += t)
        gfx_hline(s, 0, W, y, grid, ROP_COPY);
    for (r = H / 8; r < H; r += H / 8)
        gfx_circle(s, W / 2, H / 2, r, text, ROP_COPY);
    gfx_line(s, 0, 0, W - 1, H - 1, text, ROP_COPY);
    gfx_line(s, 0, H - 1, W - 1, 0, text, ROP_COPY);
    for (y = 3 * t; y < H; y += 4 * t)
        font_draw(s, font_sans, t / 2 + (y / t) * 3, y, "Heron Mini bobs  Heron Mini bobs  Heron Mini",
                  text, -1);
}

static void descriptors(int b);

/* the status line: grey on black */
static void status(const char *str)
{
    gfx_fill(&status_s, 0, 0, status_s.w, status_s.h, vid.bpp == 8 ? 232 : 0, ROP_COPY);
    font_draw(&status_s, font_sans, 4, 12, str, vid.bpp == 8 ? 250 : 13, -1);
}

static void screen(void)
{
    int b, y, words;
    if (mode_sel == 1) {
        video_init(1, 0);
        W = 320;
        H = 240;
        SROWS = 16;
    } else {
        video_init(0, 0);
        W = 640;
        H = 480;
        SROWS = 32;
    }
    fmt = gfx_screen_format();
    ps = gfx_format(fmt)->pshift;
    ppw = 1 << ps;
    words = W / ppw;
    bob_pitch = words + 2 * GUARD / ppw;
    ROWS = H + 2 * GUARD;
    palette();
    for (b = 0; b < 3; b++) {
        buf[b] = vram_alloc(bob_pitch * ROWS * 4);
        memset(buf[b], 0, bob_pitch * ROWS * 4);
        gfx_init(&whole[b], buf[b], bob_pitch * ppw, ROWS, bob_pitch, fmt);
        gfx_init(&pic[b], buf[b] + GUARD * bob_pitch + GUARD / ppw, W, H, bob_pitch, fmt);
    }
    for (b = 0; b < 2; b++) {
        rows[b] = malloc(ROWS * sizeof(unsigned *));
        for (y = 0; y < ROWS; y++)
            rows[b][y] = pic[b].bits + (y - GUARD) * bob_pitch;
        rows[b] += GUARD;       /* rows[b][y] for y from -GUARD */
    }
    status_fb = vram_alloc(words * 4 * SROWS);
    gfx_init(&status_s, status_fb, W, SROWS, words, fmt);
    /* the descriptors: the status line, then the picture, in both tables */
    for (b = 0; b < 2; b++) {
        for (y = 0; y < SROWS << (mode_sel == 1); y++)
            video_lines(b, y, 1, status_fb + (y >> (mode_sel == 1)) * words, 0, 0);
        descriptors(b);
    }
}

/* table b's picture lines from buffer b (the status line's stay): as a
   page flip would without TSEL, a word a line */
static void descriptors(int b)
{
    int y, dbl = mode_sel == 1;
    unsigned *t = video_table(b), w = video_desc(pic[b].bits, 0) + SROWS * bob_pitch;
    for (y = SROWS << dbl; y < vid.h; y += 1 + dbl) {
        t[y] = w;
        if (dbl)
            t[y + 1] = w;
        w += bob_pitch;
    }
}

/* the most words a sprite's rectangle takes, for the save areas */
static int most_words(void)
{
    int z, d, p, most = 0;
    for (z = 0; z < 2; z++)
        for (d = 0; d < NDES; d++)
            for (p = 0; p < spr[z][d].nph; p++)
                if (spr[z][d].words[p] > most)
                    most = spr[z][d].words[p];
    return most;
}

static void sprites(void)
{
    static unsigned char pix[32 * 32], msk[32 * 32];
    int z, d, i;
    unsigned t0 = video_ticks();
    unsigned bytes = 0, words = 0;
    for (z = 0; z < 2; z++)
        for (d = 0; d < NDES; d++) {
            int s = 16 << z;
            if (d == 0)
                art_ball(s, pix, msk);
            else if (d == 1)
                art_ring(s, pix, msk);
            else if (d == 2)
                art_gem(s, pix, msk);
            else
                art_critter(s, pix, msk);
            for (i = 0; i < s * s; i++)
                pix[i] = colour[pix[i]];
            sprite_make(&spr[z][d], s, s, pix, msk, fmt);
            bytes += spr[z][d].codesize;
            for (i = 0; i < spr[z][d].nph; i++)
                words += spr[z][d].ww[i] * s;
        }
    perf_value("setup_sprites", video_ticks() - t0);
    perf_value("code_bytes", bytes);
    perf_value("shifted_bytes", words * 8);
}

/* ---- a frame ---- */

static void do_erase(void)
{
    int b = back;
    if (erase == E_FULL)
        gfx_blit(&pic[b], 0, 0, &pic[2], 0, 0, W, H, ROP_COPY);
    else if (erase == E_DIRTY)
        RESTORE(rect[b], nrect[b]);
    else if (erase == E_EXACT)
        restore_compiled(rect[b], nrect[b], (buf[2] - buf[b]) * 4);
    else
        UNSAVE(rect[b], nrect[b]);
    nrect[b] = 0;
}

/* move the bobs, bouncing off the edges (half a sprite off the picture),
   and list where each is drawn and what's to be erased. The globals are
   copied to locals first: the compiler loads a global at every use */
static void move(void)
{
    int i, b = back, off = buf[2] - buf[b], w = W, h = H, sh = ps, pm = ppw - 1, n = nbobs;
    int t = tech, e = erase;
    unsigned **rw = rows[b];
    unsigned *sa = save_area[b];
    Blt *d = dl, *r = rect[b];
    Bob *o = bob;
    for (i = 0; i < n; i++, d++, r++, o++) {
        Sprite *s = o->s;
        int ph, half = s->w >> 1, x = o->x + o->dx, y = o->y + o->dy;
        unsigned *p;
        if (x < -half || x > w - half) {
            o->dx = -o->dx;
            x += 2 * o->dx;
        }
        if (y < -half || y > h - half) {
            o->dy = -o->dy;
            y += 2 * o->dy;
        }
        o->x = x;
        o->y = y;
        ph = x & pm;
        p = rw[y] + (x >> sh);
        d->d = p;
        d->w = s->ww[ph];
        d->h = s->h;
        d->s = t == T_COMPILED ? s->code[ph] : t == T_BYTES ? s->bcode[ph]
             : t == T_SPANS ? (void *)s->spans[ph] : s->shifted[ph];
        r->d = p;
        r->w = d->w;
        r->h = d->h;
        if (e == E_SAVE) {
            r->s = sa;
            sa += s->words[ph];
        } else if (e == E_EXACT)
            r->s = s->rcode[ph];
        else
            r->s = p + off;
    }
    nrect[b] = n;
}

static void do_draw(void)
{
    int i;
    if (tech == T_GENERIC) {
        for (i = 0; i < nbobs; i++) {
            Sprite *s = bob[i].s;
            gfx_masked(&pic[back], bob[i].x, bob[i].y, &s->img, &s->mask, 0, 0, s->w, s->h);
        }
    } else if (tech == T_SHIFTED)
        SHIFTED(dl, nbobs);
    else if (tech == T_SPANS)
        SPANS(dl, nbobs);
    else
        draw_compiled(dl, nbobs);       /* T_COMPILED, T_BYTES */
}

/* the time each part took, summed over the frames measured */
static unsigned t_erase, t_move, t_save, t_draw, t_total, t_max, nframes;
static int late;

static void frame(void)
{
    unsigned t0, t1, t2, t3, t4;
    t0 = video_ticks();
    do_erase();
    t1 = video_ticks();
    move();
    t2 = video_ticks();
    if (erase == E_SAVE)
        SAVEK(rect[back], nbobs);
    t3 = video_ticks();
    do_draw();
    t4 = video_ticks();
    t_erase += t1 - t0;
    t_move += t2 - t1;
    t_save += t3 - t2;
    t_draw += t4 - t3;
    t_total += t4 - t0;
    if (t4 - t0 > t_max)
        t_max = t4 - t0;
    nframes++;
}

/* show the buffer just drawn from the next frame, `hz` frames after the
   last flip (1: 60 Hz, 2: 30 Hz); count the frames it was late */
static void flip(int hz)
{
    int n = video_wait();
    while (n < hz)
        n += video_wait();
    late += n - hz;
    if (!single) {
        video_ctrl(back ? VC_TSEL : 0, VC_TSEL);
        back ^= 1;
    }
}

static void run(int frames, int hz)
{
    while (frames-- > 0) {
        frame();
        flip(hz);
    }
}

static void clear_times(void)
{
    t_erase = t_move = t_save = t_draw = t_total = t_max = nframes = 0;
    late = 0;
}

/* a configuration with n bobs: both buffers the background, the bobs
   anywhere, in every phase */
static void start(int t, int e, int size, int n)
{
    int i;
    tech = t;
    erase = e;
    nbobs = n;
    gfx_blit(&whole[0], 0, 0, &whole[2], 0, 0, whole[2].w, ROWS, ROP_COPY);
    gfx_blit(&whole[1], 0, 0, &whole[2], 0, 0, whole[2].w, ROWS, ROP_COPY);
    nrect[0] = nrect[1] = 0;
    rnd_state = 12345;
    for (i = 0; i < n; i++) {
        Bob *o = &bob[i];
        o->s = &spr[size][i % NDES];
        o->x = rnd(W) - o->s->w / 2;
        o->y = rnd(H) - o->s->h / 2;
        o->dx = rnd(5) - 2;
        o->dy = rnd(5) - 2;
        if (!o->dx)
            o->dx = 3;
        if (!o->dy)
            o->dy = -3;
    }
    video_wait();
}

/* ---- the check ---- */

/* every kind of drawing against the library's gfx_masked, every sprite
   at every phase, on the background: the words that differ */
static int check(void)
{
    static unsigned ref[9 * 32];
    int z, d, p, t, k, r, bad = 0;
    for (z = 0; z < 2; z++)
        for (d = 0; d < NDES; d++)
            for (p = 0; p < ppw; p++) {
                Sprite *s = &spr[z][d];
                int x = 40 + p, y = 40;
                Blt b, bg;
                b.d = rows[0][y] + (x >> ps);
                b.w = s->ww[p];
                b.h = s->h;
                bg = b;
                bg.s = b.d + (buf[2] - buf[0]);
                restore_c(&bg, 1);
                gfx_masked(&pic[0], x, y, &s->img, &s->mask, 0, 0, s->w, s->h);
                for (r = 0; r < b.h; r++)
                    for (k = 0; k < b.w; k++)
                        ref[r * b.w + k] = b.d[r * bob_pitch + k];
                for (t = T_SHIFTED; t < NT; t++) {
                    restore_c(&bg, 1);
                    if (t == T_SHIFTED) {
                        b.s = s->shifted[p];
                        SHIFTED(&b, 1);
                    } else if (t == T_SPANS) {
                        b.s = s->spans[p];
                        SPANS(&b, 1);
                    } else {
                        b.s = t == T_COMPILED ? s->code[p] : s->bcode[p];
                        draw_compiled(&b, 1);
                    }
                    for (r = 0; r < b.h; r++)
                        for (k = 0; k < b.w; k++)
                            if (ref[r * b.w + k] != b.d[r * bob_pitch + k]) {
                                if (!bad)
                                    printf("check: %s, %d x %d design %d phase %d: row %d word"
                                           " %d is %08x, not %08x\n", tname[t], s->w, s->h, d, p,
                                           r, k, b.d[r * bob_pitch + k], ref[r * b.w + k]);
                                bad++;
                            }
                }
                /* the exact restore: back to the background where drawn */
                b.s = s->rcode[p];
                restore_compiled(&b, 1, (buf[2] - buf[0]) * 4);
                for (r = 0; r < b.h; r++)
                    for (k = 0; k < b.w; k++)
                        if (b.d[r * bob_pitch + k] != ((unsigned *)bg.s)[r * bob_pitch + k]) {
                            if (!bad)
                                printf("check: exact restore, %d x %d design %d phase %d: row %d"
                                       " word %d\n", s->w, s->h, d, p, r, k);
                            bad++;
                        }
                restore_c(&bg, 1);
            }
    return bad;
}

/* ---- the benchmark ---- */

typedef struct {
    int fixed, per, draw, erase, move, save;    /* ticks: a frame's without bobs, a bob's */
    int n60, n30, ok60;                         /* bobs predicted at 60 and 30 Hz, and run at 60 */
} Result;

static int predict(const Result *r, int budget)
{
    int n = (budget - MARGIN - r->fixed) / r->per;
    return n < 0 ? 0 : n > MAXB ? MAXB : n;
}

static void bench(int t, int e, int size, Result *r)
{
    int n = t == T_GENERIC ? 6 : 24, k;
    char name[48];
    start(t, e, size, n);
    run(2, 1);
    clear_times();
    run(4, 1);
    r->draw = t_draw / (nframes * n);
    r->erase = e == E_FULL ? 0 : t_erase / (nframes * n);
    r->move = t_move / (nframes * n);
    r->save = e == E_SAVE ? t_save / (nframes * n) : 0;
    r->per = r->draw + r->erase + r->move + r->save;
    r->fixed = t_total / nframes - n * r->per;
    r->n60 = predict(r, FRAME);
    r->n30 = predict(r, 2 * FRAME);
    /* check: that many for 10 frames, fewer while frames are missed */
    r->ok60 = r->n60;
    for (k = 0; k < 4 && r->ok60 > 0; k++) {
        start(t, e, size, r->ok60);
        run(2, 1);
        clear_times();
        run(10, 1);
        if (!late)
            break;
        r->ok60 = r->ok60 * 94 / 100;
    }
    sprintf(name, "m%d.%d.%s.%s", vid.mode, 16 << size, tname[t], ename[e]);
    printf("@perf %s %d %d %d %d %d %d %d %d %d\n", name, r->fixed, r->per, r->draw, r->erase,
           r->move, r->save, r->n60, r->n30, r->ok60);
    printf("M%d %2dx%-2d %-8s %-5s  a bob: draw %5d erase %5d move %3d save %5d = %5d;"
           " a frame %6d; 60 Hz %3d bobs (ran %3d), 30 Hz %3d\n",
           vid.mode, 16 << size, 16 << size, tname[t], ename[e], r->draw, r->erase, r->move,
           r->save, r->per, r->fixed, r->n60, r->ok60, r->n30);
}

/* a configuration on screen with its line of status, and a screenshot */
static void show(int t, int e, int size, int n, int hz, const char *shot)
{
    char line[96];
    sprintf(line, "%s, %s: %d bobs %dx%d, %d Hz%s", tname[t], ename[e], n, 16 << size,
            16 << size, 60 / hz, single ? ", 1 buffer" : "");
    status(line);
    start(t, e, size, n);
    clear_times();
    run(24, hz);
    printf("%s: %u ticks a frame (%u at most), %d frames late\n", line, t_total / nframes, t_max,
           late);
    if (shot) {
        /* a screenshot of a frame while it runs (rt_shot would stop it) */
        printf("@shot %s\n", shot);
        run(4, hz);
    }
}

/* the fastest erase for a kind of drawing and a size, by the bobs run at 60 Hz */
static int best_erase(Result r[NE][2], int z)
{
    int e, best = E_DIRTY;
    for (e = 0; e < NE; e++)
        if (r[e][z].ok60 > r[best][z].ok60)
            best = e;
    return best;
}

int main(void)
{
    static Result res[NT][NE][2];
    int t, e, z, k, top;
    unsigned t0;
    font_init();
    screen();
    background(&pic[2]);
    status("bobs: making the sprites");
    sprites();
    for (z = 0; z < 2; z++)
        save_area[z] = vram_alloc(MAXB * most_words() * 4);
    /* a page flip with TSEL is a register's write; without it, every
       descriptor of the picture rewritten */
    t0 = video_ticks();
    descriptors(1);
    perf_value("rewrite_descriptors", video_ticks() - t0);
    k = check();
    printf("check: %d words differ\n", k);
    perf_value("check_errors", k);
    /* the byte stores only where a pixel is a byte */
    top = fmt == PF_LIN8 ? T_BYTES : T_COMPILED;
    if (!showcase) {
        for (z = 0; z < 2; z++)
            for (t = 0; t <= top; t++)
                for (e = 0; e < NE; e++) {
                    /* the generic and shifted kinds only with dirty
                       rectangles, save-under only for spans and compiled;
                       quick: the compiled ones */
                    if ((t == T_GENERIC || t == T_SHIFTED) && e != E_DIRTY)
                        continue;
                    if (t == T_BYTES && e == E_SAVE)
                        continue;
                    if (quick && t < T_COMPILED)
                        continue;
                    status("bobs: measuring");
                    bench(t, e, z, &res[t][e][z]);
                }
    } else {
        for (z = 0; z < 2; z++) {
            res[top][E_EXACT][z].ok60 = mode_sel == 1 ? 150 >> 2 * z : 100 >> 2 * z;
            res[top][E_FULL][z].n30 = mode_sel == 1 ? 300 >> 2 * z : 100 >> 2 * z;
            res[T_GENERIC][E_DIRTY][z].ok60 = 6;
        }
    }
    /* the showcase: the fastest, at 60 Hz and 30 Hz */
    e = best_erase(res[top], 0);
    show(top, e, 0, res[top][e][0].ok60, 1, mode_sel ? "m1_16" : "m0_16");
    e = best_erase(res[top], 1);
    show(top, e, 1, res[top][e][1].ok60, 1, mode_sel ? "m1_32" : "m0_32");
    if (mode_sel == 1) {
        show(top, E_FULL, 0, res[top][E_FULL][0].n30, 2, "m1_16_30hz");
        show(T_GENERIC, E_DIRTY, 0, res[T_GENERIC][E_DIRTY][0].ok60, 1, "m1_generic");
        /* one buffer: drawn while the beam shows it */
        single = 1;
        back = (vid.ctrl & VC_TSEL) ? 1 : 0;
        show(top, E_EXACT, 0, res[top][E_EXACT][0].ok60, 1, "m1_single");
        single = 0;
    }
    printf("@done\n");
    return 0;
}
