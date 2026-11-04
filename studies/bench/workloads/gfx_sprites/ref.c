/* gfx_sprites' reference: the same game played (the sprites' moves, the
 * hits, the scrolls), then its last frame drawn a pixel at a time: the
 * playfield from the map at the final scroll, the sprites in order with
 * colour 0 transparent, the status line. None of the machine's shifted
 * art, save-under or copies: its incremental frames must end up exactly
 * this picture.
 *
 * workload.py has the data's formats; the rules are the machine's
 * (game.s). */

#include "bench.h"
#ifdef DUMP_FB
#include <stdio.h>
#endif

extern const unsigned char font_mono[], tiles[], tilemap[], sprite_art[], actors[];

#define PITCH 320               /* bytes a row: 640 pixels */
#define MAPW 64
#define STATUS_H 16
#define PH (SH - STATUS_H)      /* the playfield's rows */
#define CELL_W 7
#define CELL_H 15

static unsigned char fb[PITCH * 480];

static void pset(int x, int y, int c)
{
    unsigned char *p = &fb[y * PITCH + (x >> 1)];
    if (x & 1)
        *p = (*p & 0x0F) | (c << 4);
    else
        *p = (*p & 0xF0) | c;
}

static int h16(const unsigned char *p)
{
    int v = p[0] | p[1] << 8;
    return v >= 0x8000 ? v - 0x10000 : v;
}

/* pixel x of a row of 16 packed in 8 bytes, the first in the low nibble */
static int nib(const unsigned char *row, int x)
{
    return (row[x >> 1] >> ((x & 1) * 4)) & 15;
}

/* an opaque mono12 cell, 7 x 15 from (x, top): fg on the glyph's pixels,
   bg elsewhere; the glyph's pixels outside the cell aren't drawn */
static void cell(int x, int top, int ch, int fg, int bg)
{
    int first = font_mono[0], count = font_mono[1], asc = font_mono[2];
    int sw = font_mono[4] | font_mono[5] << 8;
    const unsigned char *e = font_mono + 8 + 8 * (ch - first);
    int w = e[0], h = e[1], xo = (signed char)e[3], yo = (signed char)e[4];
    const unsigned char *strike = font_mono + 8 + 8 * count + 4 * (e[6] | e[7] << 8);
    for (int j = 0; j < CELL_H; j++)
        for (int i = 0; i < CELL_W; i++) {
            int gx = i - xo, gy = j - asc - yo, on = 0;
            if (gx >= 0 && gx < w && gy >= 0 && gy < h)
                on = (strike[gy * 4 * sw + (gx >> 3)] >> (gx & 7)) & 1;
            pset(x + i, top + j, on ? fg : bg);
        }
}

/* the number's last n digits into s */
static void digits(char *s, unsigned v, int n)
{
    while (n-- > 0) {
        s[n] = '0' + v % 10;
        v /= 10;
    }
}

int main(void)
{
    int x[NSPR], y[NSPR], vx[NSPR], vy[NSPR], kind[NSPR];
    unsigned score = 0, hits = 0;
    int ox = 0;

    for (int i = 0; i < NSPR; i++) {
        const unsigned char *a = actors + 10 * i;
        x[i] = h16(a);
        y[i] = h16(a + 2);
        vx[i] = h16(a + 4);
        vy[i] = h16(a + 6);
        kind[i] = h16(a + 8);
    }

    /* the game */
    for (int f = 0; f < FRAMES; f++) {
        if (f % SCROLL == SCROLL - 1)
            ox += 8;
        for (int i = 0; i < NSPR; i++) {
            x[i] += vx[i];
            if (x[i] < -8) {
                x[i] = -16 - x[i];
                vx[i] = -vx[i];
            } else if (x[i] > SW - 8) {
                x[i] = 2 * (SW - 8) - x[i];
                vx[i] = -vx[i];
            }
            y[i] += vy[i];
            if (y[i] < -8) {
                y[i] = -16 - y[i];
                vy[i] = -vy[i];
            } else if (y[i] > PH - 8) {
                y[i] = 2 * (PH - 8) - y[i];
                vy[i] = -vy[i];
            }
        }
        int frame = (f >> 2) & 1;
        for (int i = 1; i < NSPR; i++) {
            int dx = x[i] - x[0], dy = y[i] - y[0];
            if (dx > -32 && dx < 32 && dy > -32 && dy < 32) {
                hits++;
                score += 25 + (kind[i] | frame);
            }
        }
    }

    /* the last frame: the playfield */
    for (int py = 0; py < PH; py++)
        for (int px = 0; px < SW; px++) {
            int wx = ox + px;
            int t = tilemap[(py >> 4) * MAPW + ((wx >> 4) & (MAPW - 1))];
            pset(px, py, nib(tiles + 128 * t + 8 * (py & 15), wx & 15));
        }
    /* the sprites, in order, clipped to the playfield */
    int frame = ((FRAMES - 1) >> 2) & 1;
    for (int i = 0; i < NSPR; i++) {
        const unsigned char *art = sprite_art + 256 * (kind[i] | frame);
        for (int j = 0; j < 16; j++)
            for (int k = 0; k < 16; k++) {
                int px = x[i] + k, py = y[i] + j;
                int c = nib(art + 16 * j, k);
                if (nib(art + 16 * j + 8, k) && px >= 0 && px < SW && py >= 0 && py < PH)
                    pset(px, py, c);
            }
    }
    /* the status line */
    for (int py = PH; py < SH; py++)
        for (int px = 0; px < SW; px++)
            pset(px, py, 1);
    char s[] = "SCORE 000000  HITS 0000  FRAME 0000";
    digits(s + 6, score, 6);
    digits(s + 19, hits, 4);
    digits(s + 31, FRAMES, 4);
    for (int i = 0; s[i]; i++)
        cell(2 + CELL_W * i, PH + 1, s[i], 14, 1);

    unsigned s1 = 0, s2 = 0;
    for (int py = 0; py < SH; py++)
        for (int px = 0; px < SW / 2; px += 4) {
            const unsigned char *p = &fb[py * PITCH + px];
            s1 += p[0] | p[1] << 8 | p[2] << 16 | (unsigned)p[3] << 24;
            s2 += s1;
        }
    bench_report("score", score);
    bench_report("hits", hits);
    bench_report("screen_sum", s1);
    bench_report("screen_fletcher", s2);
#ifdef DUMP_FB
    FILE *fd = fopen(DUMP_FB, "wb");
    fwrite(fb, 1, sizeof fb, fd);
    fclose(fd);
#endif
    return 0;
}
