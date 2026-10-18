/* The playfield's scrolling, four ways, and the parallax bands.

   A descriptor starts a line at a whole word, so a view at level pixel x
   starts at word x / 4 and is off by x mod 4 pixels, its phase:

   COARSE    one ring buffer, the descriptors at x / 4: free, but the
             picture moves in steps of 4 pixels (8 on the screen).
   PRESHIFT  four ring buffers, ring p holding the level shifted left by p
             pixels; the descriptors pick ring x mod 4 at word x / 4. Fine
             scrolling for the cost of drawing each new column four times.
   BLIT      one ring at phase 0, copied shifted into a back buffer every
             frame (k_shift: C, MERGE, or BLIT k).
   REDRAW    no ring: every frame the visible tiles are drawn into a back
             buffer from their pre-shifted images.

   A ring buffer is RING_R words of the level (24 tile columns) and 84
   more: a column in the ring's first 84 words is drawn twice, there and
   RING_R words on, so the 80 (or 81) words from any start in the ring are
   contiguous, as a line must be. New columns are drawn at the seam as the
   view moves: the ones on screen at once, the next two ahead one column
   of one ring a frame. The bands (sky, mountains, hills) are periodic and
   pre-shifted (art.c): they cost only their descriptors. */

#include <string.h>
#include "gfx.h"
#include "video.h"
#include "game.h"

const char *const sc_names[SC_N] = {"COARSE", "PRESHIFT", "BLIT", "REDRAW"};
int strategy = SC_PRESHIFT;

unsigned *line_src[SH];
unsigned char line_own[SH];

#define RING_R 96
#define RING_COLS (RING_R / 4)
#define RING_PITCH (RING_R + 84)
#define BACK_PITCH 88           /* 4 words either side of the line's 80 */
#define MARGIN 2                /* columns drawn ahead of the view */

static unsigned *ring[4];
static int ring_lo[4], ring_hi[4];      /* ring p holds columns [lo, hi) */
static int nrings, pre_next;
static unsigned *back[2];
int sky_drift;                  /* the clouds' own motion, in pixels */

/* rows r0..r1-1 of tile column c into ring p: words 1-3 of each line's
   image, and word 4 with column c + 1's word 0 */
static void ring_col(int p, int c, int r0, int r1)
{
    int slot = (4 * c) % RING_R, dup = slot < 84, r, l;
    for (r = r0; r < r1; r++) {
        const unsigned *a = timg(level[r][c], r, p), *b = timg(level[r][c + 1], r, p);
        unsigned *d = ring[p] + slot + 16 * r * RING_PITCH;
        for (l = 0; l < 16; l++) {
            unsigned w3 = a[4] | b[0];
            d[0] = a[1];
            d[1] = a[2];
            d[2] = a[3];
            d[3] = w3;
            if (dup) {
                d[RING_R] = a[1];
                d[RING_R + 1] = a[2];
                d[RING_R + 2] = a[3];
                d[RING_R + 3] = w3;
            }
            a += 5;
            b += 5;
            d += RING_PITCH;
        }
    }
}

/* ring p to hold columns c0..c1 */
static void ring_ensure(int p, int c0, int c1)
{
    if (c0 < 0)
        c0 = 0;
    if (c1 > LEVEL_W - 1)
        c1 = LEVEL_W - 1;
    if (c0 >= ring_hi[p] || c1 < ring_lo[p])
        ring_lo[p] = ring_hi[p] = c0;       /* nothing of it there: start over */
    while (ring_hi[p] <= c1) {
        ring_col(p, ring_hi[p]++, 0, ROWS);
        if (ring_hi[p] - ring_lo[p] > RING_COLS)
            ring_lo[p]++;
    }
    while (ring_lo[p] > c0) {
        ring_col(p, --ring_lo[p], 0, ROWS);
        if (ring_hi[p] - ring_lo[p] > RING_COLS)
            ring_hi[p]--;
    }
}

/* one column of one ring towards MARGIN columns past c1, if any needs it */
static void ring_prefetch(int c1)
{
    int k;
    for (k = 0; k < nrings; k++) {
        int p = (pre_next + k) % nrings;
        if (ring_hi[p] <= c1 + MARGIN && ring_hi[p] < LEVEL_W) {
            ring_col(p, ring_hi[p]++, 0, ROWS);
            if (ring_hi[p] - ring_lo[p] > RING_COLS)
                ring_lo[p]++;
            pre_next = p + 1;
            return;
        }
    }
}

void scroll_tile(int row, int col)
{
    int p;
    for (p = 0; p < nrings; p++) {
        if (col >= ring_lo[p] && col < ring_hi[p])
            ring_col(p, col, row, row + 1);
        if (col - 1 >= ring_lo[p] && col - 1 < ring_hi[p])
            ring_col(p, col - 1, row, row + 1);
    }
}

void scroll_init(void)
{
    int k;
    nrings = strategy == SC_PRESHIFT ? 4 : strategy == SC_REDRAW ? 0 : 1;
    for (k = 0; k < nrings; k++) {
        ring[k] = vram_alloc(PF_H * RING_PITCH * 4);
        ring_lo[k] = ring_hi[k] = 0;
    }
    if (strategy == SC_BLIT || strategy == SC_REDRAW)
        for (k = 0; k < 2; k++) {
            back[k] = vram_alloc(PF_H * BACK_PITCH * 4);
            memset(back[k], 0, PF_H * BACK_PITCH * 4);
        }
}

/* a band's lines at scroll s (pixels): phase s mod 4 (0 if coarse) */
static void band_lines(int y0, int h, unsigned *const *band, int s)
{
    unsigned *p;
    int y;
    s %= BAND_P;
    if (s < 0)
        s += BAND_P;
    p = band[strategy == SC_COARSE ? 0 : s & 3] + (s >> 2);
    for (y = 0; y < h; y++) {
        line_src[y0 + y] = p;
        line_own[y0 + y] = 0;
        p += BAND_PITCH;
    }
}

void scroll_frame(int t, int x)
{
    int p = x & 3, w0 = x >> 2, cf = x >> 4, cl = (x + SW - 1) >> 4, y, r, i;
    unsigned *s, *d;

    band_lines(SKY_Y, SKY_H, band_sky, (x >> 3) + sky_drift);
    band_lines(MTN_Y, MTN_H, band_mtn, x >> 2);
    band_lines(HILL_Y, HILL_H, band_hill, x >> 1);
    pmark(P_DESC);

    switch (strategy) {
    case SC_COARSE:
    case SC_PRESHIFT:
        /* the descriptors do it all: the ring of this phase, at word w0 */
        if (strategy == SC_COARSE)
            p = 0;
        ring_ensure(p, cf, cl);
        ring_prefetch(cl);
        pmark(P_SEAM);
        s = ring[p] + w0 % RING_R;
        for (y = 0; y < PF_H; y++) {
            line_src[PF_Y + y] = s;
            line_own[PF_Y + y] = 0;
            s += RING_PITCH;
        }
        break;
    case SC_BLIT:
        /* the ring at phase 0 shifted into this frame's back buffer */
        ring_ensure(0, cf, cl + 1);
        ring_prefetch(cl + 1);
        pmark(P_SEAM);
        s = ring[0] + w0 % RING_R;
        d = back[t] + 4;
        for (y = 0; y < PF_H; y++) {
            k_shift(d, s, LW, p);
            line_src[PF_Y + y] = d;
            line_own[PF_Y + y] = 1;
            s += RING_PITCH;
            d += BACK_PITCH;
        }
        pmark(P_PLAYFIELD);
        break;
    case SC_REDRAW: {
        /* every visible tile from its image at this phase */
        const unsigned *tiles[22];
        RedrawJob j;
        pmark(P_SEAM);
        j.pitch = BACK_PITCH;
        j.h = 16;
        j.tiles = tiles;
        for (r = 0; r < ROWS; r++) {
            for (i = 0; i < 22; i++) {
                int c = cf + i;
                tiles[i] = timg(c <= LEVEL_W ? level[r][c] : T_EMPTY, r, p);
            }
            j.d = back[t] + 16 * r * BACK_PITCH + 4 - (w0 & 3);
            k_redraw(&j);
        }
        pmark(P_PLAYFIELD);
        d = back[t] + 4;
        for (y = 0; y < PF_H; y++) {
            line_src[PF_Y + y] = d;
            line_own[PF_Y + y] = 1;
            d += BACK_PITCH;
        }
        break;
    }
    }
    pmark(P_DESC);
}
