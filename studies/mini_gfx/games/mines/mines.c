/* Minesweeper on Heron Mini: a board of 16 x 16 tiles, the mouse with
   the hardware cursor (C1), left click to reveal (a flood fill opens the
   empty areas), right click to flag, a click on a number whose flags are
   all there to open its other neighbours, numbers in colours, a status
   bar with a mine counter, a timer and a button, won and lost.

   Every tile comes from a sheet drawn once with the library (gfx/) in the
   screen's format and copied with gfx_blit: the board is word-aligned, so
   each tile is a plain copy of its words. The same program runs in:

     mode 0   M0, 640 x 480 x 4: 16 colours (the default)
     mode 3   M3, 640 x 480 x 2: four greys, the bar in palette bank 1
     mode 5   M5, 1024 x 768 x 2: the same, a 60 x 40 board

   In the two-bit modes the numbers can only differ by shape, and the bar's
   lines take another palette bank from their descriptors (red counters).

   The cursor (swcursor):

     0   the hardware cursor (C1): two register writes a frame, a third
         to change its shape (an arrow, a probe over the board)
     1   software, saved under: the rectangle under it saved, the cursor
         drawn with a mask, the rectangle restored before anything is drawn
         or the mouse moves (the classic way)
     2   software, in a band of lines: the 32 lines it covers copied into a
         buffer, the cursor drawn there, and those lines' descriptors
         pointed at the buffer (two, in turn): nothing to save or restore,
         and the board is drawn without caring where the cursor is

   A software cursor is drawn with the library's gfx_masked, or with
   fastcur pre-shifted: its mask and image made once for each pixel phase
   in a word, so drawing it is d = (d & ~mask) | image a word. level picks
   the first board (0-3), f1 the linear two-bit layout (F1).

   It measures (rt/perf.h) the frames' work, the board's drawing, a click's
   reveal and its flood fill, the timer and each cursor's cost, and counts
   the cursor's updates that overlapped the beam on its lines (a flicker,
   or a cursor split between two places, for that frame). At the end, Esc,
   it measures every cursor technique and the tiles the same way in every
   run. */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "gfx.h"
#include "video.h"
#include "input.h"
#include "perf.h"

/* the run's choices (pokes); fastcur: a software cursor pre-shifted
   rather than drawn with gfx_masked */
int mode = 0, swcursor = 0, f1 = 0, level = -1, fastcur = 0;

#define T 16                    /* a tile's pixels */
#define MAXC 2400               /* 60 x 40 */

enum { HIDDEN, FLAGGED, OPEN };
enum { READY, PLAYING, WON, LOST };
/* the tiles, in the sheet */
enum { T_HIDDEN, T_OPEN, T_N1, T_FLAG = T_N1 + 8, T_MINE, T_BOOM, T_WRONG, NT };

static const struct {
    int cols, rows, mines;
} levels[4] = {{9, 9, 10}, {16, 16, 40}, {30, 16, 99}, {60, 40, 400}};

static Surface scr, sheet;
static unsigned *fb;
static int bar_h;                       /* the bar's height */
static int cols, rows, ncells, nmines, bx, by;     /* the board, its top left */
static int barx, bary, barw;            /* the bar */
static int game, flags, opened, seconds, cur_level;
static unsigned t_start, seed;
static unsigned char mine[MAXC], adj[MAXC], state[MAXC];
static short queue[MAXC];

/* ---- colours: by role, for 4 and 2 bits a pixel ---- */
typedef struct {
    int bg, face, shadow, hi, black, num[8], flag, mine, boom, boom_mine, led_on, led_off, text;
} Colours;

static const Colours col4 = {15, 2, 1, 3, 0, {4, 5, 6, 7, 8, 9, 10, 11}, 12, 0, 12, 0, 13, 14, 3};
static const Colours col2 = {0, 1, 0, 2, 3, {3, 3, 3, 3, 3, 3, 3, 3}, 3, 3, 3, 2, 3, 0, 2};
static const Colours *C;

static const unsigned char pal4[16][3] = {
    {0, 0, 0}, {120, 120, 128}, {192, 192, 196}, {255, 255, 255},
    {30, 60, 230}, {0, 140, 40}, {220, 30, 30}, {20, 20, 140},
    {140, 20, 20}, {0, 140, 140}, {90, 30, 130}, {90, 90, 90},
    {235, 40, 40}, {255, 50, 40}, {48, 6, 6}, {38, 58, 92},
};
/* at two bits: bank 0 for the board's lines, bank 1 for the bar's; a bank
   holds a whole line, so its 0 is the background's grey, and only its 3
   changes, to the counters' red */
static const unsigned char pal2[2][4][3] = {
    {{64, 64, 72}, {168, 168, 172}, {245, 245, 245}, {0, 0, 0}},
    {{64, 64, 72}, {168, 168, 172}, {245, 245, 245}, {255, 50, 40}},
};

static void palette(void)
{
    int n, k;
    if (vid.bpp == 4) {
        for (n = 0; n < 16; n++)
            video_pal_rgb(n, pal4[n][0], pal4[n][1], pal4[n][2]);
    } else {
        for (k = 0; k < 2; k++)
            for (n = 0; n < 4; n++)
                video_pal_rgb(16 * k + n, pal2[k][n][0], pal2[k][n][1], pal2[k][n][2]);
    }
    /* the hardware cursor's colours, 253-255 (palette bank 15's last three) */
    video_pal_rgb(253, 0, 0, 0);
    video_pal_rgb(254, 255, 255, 255);
    video_pal_rgb(255, 255, 220, 0);
}

/* ---- the tiles ---- */

static const char *digit_art[8][9] = {
    {"..##..", ".###..", "####..", "..##..", "..##..", "..##..", "..##..", "..##..", "######"},
    {".####.", "##..##", "....##", "...##.", "..##..", ".##...", "##....", "##....", "######"},
    {"#####.", "....##", "....##", ".####.", "....##", "....##", "....##", "....##", "#####."},
    {"...##.", "..###.", ".####.", "##.##.", "##.##.", "######", "...##.", "...##.", "...##."},
    {"######", "##....", "##....", "#####.", "....##", "....##", "....##", "##..##", ".####."},
    {".####.", "##....", "##....", "#####.", "##..##", "##..##", "##..##", "##..##", ".####."},
    {"######", "....##", "....##", "...##.", "...##.", "..##..", "..##..", "..##..", "..##.."},
    {".####.", "##..##", "##..##", ".####.", "##..##", "##..##", "##..##", "##..##", ".####."},
};

static const char *flag_art[11] = {
    "......rr.......",
    "......rrrr.....",
    "......rrrrrr...",
    "......rrrr.....",
    "......rr.......",
    "......k........",
    "......k........",
    "......k........",
    "....kkkkk......",
    "...kkkkkkk.....",
    "...............",
};

static void art(Surface *s, int x, int y, const char *const *rows, int n, int fg, int fg2)
{
    int i, j;
    for (i = 0; i < n; i++)
        for (j = 0; rows[i][j]; j++)
            if (rows[i][j] == '#' || rows[i][j] == 'r')
                gfx_pixel(s, x + j, y + i, fg, ROP_COPY);
            else if (rows[i][j] == 'k')
                gfx_pixel(s, x + j, y + i, fg2, ROP_COPY);
}

static void raised(Surface *s, int x, int y)
{
    gfx_fill(s, x, y, x + T, y + T, C->face, ROP_COPY);
    gfx_fill(s, x, y, x + T - 1, y + 2, C->hi, ROP_COPY);
    gfx_fill(s, x, y + 2, x + 2, y + T - 1, C->hi, ROP_COPY);
    gfx_fill(s, x + 1, y + T - 2, x + T, y + T, C->shadow, ROP_COPY);
    gfx_fill(s, x + T - 2, y + 1, x + T, y + T - 2, C->shadow, ROP_COPY);
}

static void flat(Surface *s, int x, int y, int face)
{
    gfx_fill(s, x, y, x + T, y + T, face, ROP_COPY);
    gfx_fill(s, x, y, x + T, y + 1, C->shadow, ROP_COPY);
    gfx_fill(s, x, y + 1, x + 1, y + T, C->shadow, ROP_COPY);
}

/* a mine: a ball, its spikes, a glint */
static void draw_mine(Surface *s, int x, int y, int c, int glint)
{
    int cx = x + 8, cy = y + 8;
    gfx_fill_circle(s, cx, cy, 4, c, ROP_COPY);
    gfx_fill(s, cx - 6, cy, cx + 7, cy + 1, c, ROP_COPY);
    gfx_fill(s, cx, cy - 6, cx + 1, cy + 7, c, ROP_COPY);
    gfx_line(s, cx - 4, cy - 4, cx + 4, cy + 4, c, ROP_COPY);
    gfx_line(s, cx - 4, cy + 4, cx + 4, cy - 4, c, ROP_COPY);
    gfx_fill(s, cx - 2, cy - 2, cx, cy, glint, ROP_COPY);
}

static void make_tiles(void)
{
    int k, x;
    unsigned *bits;
    int pitch = NT * T * vid.bpp / 32;
    bits = malloc(pitch * 4 * T);
    gfx_init(&sheet, bits, NT * T, T, pitch, scr.fmt);
    raised(&sheet, T_HIDDEN * T, 0);
    flat(&sheet, T_OPEN * T, 0, C->face);
    for (k = 0; k < 8; k++) {
        x = (T_N1 + k) * T;
        flat(&sheet, x, 0, C->face);
        art(&sheet, x + 5, 4, digit_art[k], 9, C->num[k], 0);
    }
    raised(&sheet, T_FLAG * T, 0);
    art(&sheet, T_FLAG * T + 1, 3, flag_art, 11, C->flag, C->black);
    flat(&sheet, T_MINE * T, 0, C->face);
    draw_mine(&sheet, T_MINE * T, 0, C->mine, C->hi);
    flat(&sheet, T_BOOM * T, 0, C->boom);
    draw_mine(&sheet, T_BOOM * T, 0, C->boom_mine, C->hi);
    flat(&sheet, T_WRONG * T, 0, C->face);
    draw_mine(&sheet, T_WRONG * T, 0, C->mine, C->hi);
    gfx_line(&sheet, T_WRONG * T + 2, 2, T_WRONG * T + 13, 13, C->flag, ROP_COPY);
    gfx_line(&sheet, T_WRONG * T + 2, 13, T_WRONG * T + 13, 2, C->flag, ROP_COPY);
    gfx_line(&sheet, T_WRONG * T + 3, 2, T_WRONG * T + 14, 13, C->flag, ROP_COPY);
    gfx_line(&sheet, T_WRONG * T + 3, 13, T_WRONG * T + 14, 2, C->flag, ROP_COPY);
}

/* ---- the cursor: hardware (C1) or software ---- */

/* 1 black, 2 white, 3 yellow; '.' clear */
static const char *arrow_art[] = {
    "1", "11", "121", "1221", "12221", "122221", "1222221", "12222221", "122222221",
    "1222222221", "12222211111", "1221221", "121.1221", "11..1221", "1....1221", ".....1221",
    "......11", 0,
};
static const char *probe_art[] = {
    "......111......", "......121......", "......121......", "......121......",
    "......121......", "......111......", "111111.3.111111", "122221333122221",
    "111111.3.111111", "......111......", "......121......", "......121......",
    "......121......", "......121......", "......111......", 0,
};

typedef struct {
    unsigned *hw;               /* the C1 image: 32 rows of two words, in bank 1 */
    int hx, hy;                 /* the hotspot */
    Surface img;                /* the software cursor's image, in the screen's format */
    unsigned mask_bits[32];
    Bitmap mask;
    /* pre-shifted (fastcur): for each pixel phase in a word, 32 rows of nw
       words of the mask (every bit of a drawn pixel) and of the image */
    unsigned *pm, *pi;
    int nw;
} Cursor;

static Cursor arrow, probe, *cursor;

/* both forms of a cursor from its art: the C1 image, and an image in the
   screen's format with a mask for the software ones, whose colours are
   the screen's own (black, white, and red for the hardware's yellow; at
   two bits, white again) */
static void make_cursor(Cursor *c, const char *const *a, int hx, int hy)
{
    int y, x, v, sc[4];
    unsigned *bits;
    sc[0] = 0;
    sc[1] = C->black;
    sc[2] = C->hi;
    sc[3] = vid.bpp == 4 ? C->led_on : C->hi;
    c->hw = vram_alloc(32 * 8);
    memset(c->hw, 0, 32 * 8);
    bits = malloc(32 * vid.bpp / 8 * 32);
    gfx_init(&c->img, bits, 32, 32, vid.bpp, scr.fmt);
    gfx_fill(&c->img, 0, 0, 32, 32, 0, ROP_COPY);
    memset(c->mask_bits, 0, sizeof c->mask_bits);
    for (y = 0; a[y]; y++)
        for (x = 0; a[y][x]; x++) {
            v = a[y][x] == '1' ? 1 : a[y][x] == '2' ? 2 : a[y][x] == '3' ? 3 : 0;
            if (!v)
                continue;
            c->hw[2 * y + x / 16] |= (unsigned)v << (2 * (x % 16));
            gfx_pixel(&c->img, x, y, sc[v], ROP_COPY);
            c->mask_bits[y] |= 1u << x;
        }
    c->mask.bits = c->mask_bits;
    c->mask.pitch = 1;
    c->hx = hx;
    c->hy = hy;
}

/* the cursor drawn at every phase, once: its mask expanded to all of a
   pixel's bits, its image copied under the mask */
static void preshift(Cursor *c)
{
    int ppw = 1 << scr.pshift, nw = 32 / ppw + 1, p, n = nw * 32;
    Surface ti, tm;
    c->nw = nw;
    c->pm = malloc(ppw * n * 4);
    c->pi = malloc(ppw * n * 4);
    for (p = 0; p < ppw; p++) {
        gfx_init(&ti, c->pi + p * n, nw * ppw, 32, nw, scr.fmt);
        gfx_init(&tm, c->pm + p * n, nw * ppw, 32, nw, scr.fmt);
        gfx_fill(&ti, 0, 0, nw * ppw, 32, 0, ROP_COPY);
        gfx_fill(&tm, 0, 0, nw * ppw, 32, 0, ROP_COPY);
        gfx_masked(&ti, p, 0, &c->img, &c->mask, 0, 0, 32, 32);
        gfx_expand(&tm, p, 0, &c->mask, 0, 0, 32, 32, (1 << vid.bpp) - 1, 0, 0);
    }
}

/* a pre-shifted cursor at (x, y) on s, its rows clipped to s's clip:
   each word d = (d & ~mask) | image */
static void fast_draw(Surface *s, int x, int y)
{
    int ps = s->pshift, nw = cursor->nw, p = x & ((1 << ps) - 1), w0 = x >> ps;
    int r0 = y < s->clip.y0 ? s->clip.y0 - y : 0;
    int r1 = y + 32 > s->clip.y1 ? s->clip.y1 - y : 32;
    int k0 = w0 < 0 ? -w0 : 0, k1 = w0 + nw > s->pitch ? s->pitch - w0 : nw, r, k;
    const unsigned *m = cursor->pm + p * nw * 32, *im = cursor->pi + p * nw * 32;
    for (r = r0; r < r1; r++) {
        unsigned *d = s->bits + (y + r) * s->pitch + w0;
        const unsigned *mr = m + r * nw, *ir = im + r * nw;
        for (k = k0; k < k1; k++)
            d[k] = (d[k] & ~mr[k]) | ir[k];
    }
}

/* software cursor 1: saved under */
static Surface save;
static unsigned *save_bits;
static int sw_x, sw_y, sw_shown, sw_sx, sw_sw;      /* where it is; the saved rectangle's x, width */

/* software cursor 2: a band of lines */
static unsigned *band[2], *line_desc;
static Surface band_s[2];
static int band_y = -1, band_n, band_k, switch_b0, switch_b1;

/* measurements: the average, the worst and how many */
typedef struct {
    const char *name;
    unsigned sum, max, n;
} Acc;

static Acc a_frame = {"frame"}, a_cursor = {"cursor"}, a_board = {"board_draw"},
           a_reveal = {"reveal"}, a_flood = {"flood"}, a_timer = {"timer"},
           a_hide = {"cursor_hide"}, a_new = {"new_board"};
static int tears, cursor_updates, flood_cells_max;

static void acc(Acc *a, unsigned t)
{
    a->sum += t;
    a->n++;
    if (t > a->max)
        a->max = t;
}

static void acc_print(Acc *a)
{
    printf("@perf %s %u %u %u\n", a->name, a->n ? a->sum / a->n : 0, a->max, a->n);
}

/* the beam's picture line now (negative in the blanking before the picture) */
static int beam_line(void)
{
    return (int)(VID_BEAM & 0x3FF) - vid.table - 1;
}

static void sw_hide(void)
{
    unsigned t;
    if (!sw_shown)
        return;
    t = video_ticks();
    gfx_blit(&scr, sw_sx, sw_y, &save, 0, 0, sw_sw, 32, ROP_COPY);
    sw_shown = 0;
    acc(&a_hide, video_ticks() - t);
}

static void sw_show(int x, int y)
{
    int ppw = 1 << scr.pshift;
    sw_x = x;
    sw_y = y;
    sw_sx = x & ~(ppw - 1);
    sw_sw = 32 + ppw;
    gfx_blit(&save, 0, 0, &scr, sw_sx, y, sw_sw, 32, ROP_COPY);
    if (fastcur)
        fast_draw(&scr, x, y);
    else
        gfx_masked(&scr, x, y, &cursor->img, &cursor->mask, 0, 0, 32, 32);
    sw_shown = 1;
}

/* the band: lines y0..y0+n of the framebuffer copied into the band not
   shown, the cursor drawn into it, and the descriptors switched: the old
   band's lines back to the framebuffer, the new ones to the band */
static void band_show(int x, int y)
{
    int y0 = y < 0 ? 0 : y, y1 = y + 32 > vid.h ? vid.h : y + 32, k = band_k ^ 1, l;
    unsigned *t = video_table(0), base = video_word(band[k]);
    Surface *b = &band_s[k];
    if (y1 <= y0)
        return;
    gfx_blit(b, 0, 0, &scr, 0, y0, vid.w, y1 - y0, ROP_COPY);
    gfx_clip(b, 0, 0, vid.w, y1 - y0);
    if (fastcur)
        fast_draw(b, x, y - y0);
    else
        gfx_masked(b, x, y - y0, &cursor->img, &cursor->mask, 0, 0, 32, 32);
    /* only this part can be seen half done: the beam before and after */
    switch_b0 = beam_line();
    for (l = band_y; l >= 0 && l < band_y + band_n; l++)
        if (l < y0 || l >= y1)
            t[l] = line_desc[l];
    for (l = y0; l < y1; l++)
        t[l] = (line_desc[l] & ~0x7FFFFu) + base + (l - y0) * vid.words;
    switch_b1 = beam_line();
    band_k = k;
    band_y = y0;
    band_n = y1 - y0;
}

static int drawn;               /* something was drawn on the screen this frame */

/* before drawing on the screen: the saved-under cursor off it */
static void begin_draw(void)
{
    if (swcursor == 1)
        sw_hide();
    drawn = 1;
}

static int last_mx = -1, last_my = -1, hw_y;

/* the frame's cursor, after the frame's drawing */
static void update_cursor(void)
{
    int x = mouse_x - cursor->hx, y = mouse_y - cursor->hy, moved, b0, b1, top, bot;
    unsigned t;
    moved = mouse_x != last_mx || mouse_y != last_my;
    last_mx = mouse_x;
    last_my = mouse_y;
    if (swcursor == 0) {
        if (moved) {
            t = video_ticks();
            b0 = beam_line();
            video_cursor_at(x, y);
            b1 = beam_line();
            acc(&a_cursor, video_ticks() - t);
            cursor_updates++;
            /* moved while the beam was in its lines: split for a frame */
            top = hw_y < y ? hw_y : y;
            bot = (hw_y > y ? hw_y : y) + 32;
            if (b1 >= top && b0 < bot && b1 >= b0)
                tears++;
            hw_y = y;
        }
        return;
    }
    if (!moved && !drawn && (swcursor != 1 || sw_shown))
        return;
    top = swcursor == 1 ? (sw_shown ? sw_y : y) : (band_y >= 0 ? band_y : y);
    bot = swcursor == 1 ? (sw_shown ? sw_y + 32 : y + 32) : (band_y >= 0 ? band_y + band_n : y + 32);
    if (y < top)
        top = y;
    if (y + 32 > bot)
        bot = y + 32;
    t = video_ticks();
    b0 = beam_line();
    if (swcursor == 1) {
        sw_hide();
        sw_show(x, y);
        b1 = beam_line();
    } else {
        band_show(x, y);
        b0 = switch_b0;
        b1 = switch_b1;
    }
    acc(&a_cursor, video_ticks() - t);
    cursor_updates++;
    /* the beam went over the cursor's lines while they changed: a flicker
       (saved under) or a split (the band) in this frame */
    if (b1 >= top && b0 < bot && b1 >= b0)
        tears++;
}

static void set_cursor(Cursor *c)
{
    if (c == cursor)
        return;
    if (swcursor == 1)
        begin_draw();
    cursor = c;
    if (swcursor == 0)
        video_cursor(c->hw);
    last_mx = -1;               /* moved: drawn again */
}

/* ---- the board ---- */

static void tile(int c, int t)
{
    gfx_blit(&scr, bx + (c % cols) * T, by + (c / cols) * T, &sheet, t * T, 0, T, T, ROP_COPY);
}

static int tile_of(int c)
{
    if (state[c] == HIDDEN)
        return T_HIDDEN;
    if (state[c] == FLAGGED)
        return T_FLAG;
    return adj[c] ? T_N1 + adj[c] - 1 : T_OPEN;
}

static void draw_board(void)
{
    int c;
    unsigned t = video_ticks();
    begin_draw();
    for (c = 0; c < ncells; c++)
        tile(c, tile_of(c));
    acc(&a_board, video_ticks() - t);
}

/* a seven-segment digit, 3 + 2 * u wide and 5 + 4 * u tall... at x, y:
   segments a-g, each lit or not; d < 0 is a minus sign, 10 a blank */
static const unsigned char segs[11] = {0x3F, 0x06, 0x5B, 0x4F, 0x66, 0x6D, 0x7D, 0x07, 0x7F, 0x6F, 0};

static void led_digit(int x, int y, int d, int u)
{
    unsigned s = d < 0 ? 0x40 : segs[d];
    int w = 6 * u, h = 11 * u, th = u + 1, k;
    /* the segments' rectangles, relative: a, b, c, d, e, f, g */
    int r[7][4];
    r[0][0] = th; r[0][1] = 0; r[0][2] = w - th; r[0][3] = th;
    r[1][0] = w - th; r[1][1] = th; r[1][2] = w; r[1][3] = h / 2;
    r[2][0] = w - th; r[2][1] = h / 2 + 1; r[2][2] = w; r[2][3] = h - th;
    r[3][0] = th; r[3][1] = h - th; r[3][2] = w - th; r[3][3] = h;
    r[4][0] = 0; r[4][1] = h / 2 + 1; r[4][2] = th; r[4][3] = h - th;
    r[5][0] = 0; r[5][1] = th; r[5][2] = th; r[5][3] = h / 2;
    r[6][0] = th; r[6][1] = h / 2 - th / 2; r[6][2] = w - th; r[6][3] = h / 2 - th / 2 + th;
    gfx_fill(&scr, x - 2, y - 2, x + w + 2, y + h + 2, 0, ROP_COPY);   /* black, or dark red */
    for (k = 0; k < 7; k++)
        gfx_fill(&scr, x + r[k][0], y + r[k][1], x + r[k][2], y + r[k][3],
                 s >> k & 1 ? C->led_on : C->led_off, ROP_COPY);
}

static int led_u(void)
{
    return vid.h > 600 ? 4 : 3;
}

static void led_number(int x, int y, int v)
{
    int u = led_u(), step = 6 * u + 6, neg = v < 0;
    if (neg)
        v = -v;
    if (v > 999)
        v = 999;
    led_digit(x, y, neg ? -1 : v / 100, u);
    led_digit(x + step, y, v / 10 % 10, u);
    led_digit(x + 2 * step, y, v % 10, u);
}

static int led_w(void)
{
    return 3 * (6 * led_u() + 6) - 6;
}

static void draw_counter(void)
{
    begin_draw();
    led_number(barx + 10, bary + (bar_h - 11 * led_u()) / 2, nmines - flags);
}

static void draw_timer(void)
{
    unsigned t = video_ticks();
    begin_draw();
    led_number(barx + barw - 10 - led_w(), bary + (bar_h - 11 * led_u()) / 2, seconds);
    acc(&a_timer, video_ticks() - t);
}

static int button_x, button_y, button_s;

static void draw_button(void)
{
    const char *s = game == WON ? "WON" : game == LOST ? "LOST" : "NEW";
    int x = button_x, y = button_y, n = button_s;
    begin_draw();
    gfx_fill(&scr, x, y, x + n, y + n, C->face, ROP_COPY);
    gfx_bevel(&scr, x, y, x + n, y + n, C->hi, C->shadow);
    gfx_bevel(&scr, x + 1, y + 1, x + n - 1, y + n - 1, C->hi, C->shadow);
    font_draw(&scr, font_sans, x + (n - font_width(font_sans, s)) / 2, y + n / 2 + 5, s,
              game == LOST ? C->num[2] : game == WON ? C->num[1] : C->black, -1);
}

static void draw_bar(void)
{
    begin_draw();
    gfx_fill(&scr, barx, bary, barx + barw, bary + bar_h, C->face, ROP_COPY);
    gfx_bevel(&scr, barx, bary, barx + barw, bary + bar_h, C->hi, C->shadow);
    gfx_bevel(&scr, barx + 1, bary + 1, barx + barw - 1, bary + bar_h - 1, C->hi, C->shadow);
    draw_counter();
    draw_timer();
    draw_button();
}

static void new_board(int lv)
{
    unsigned t = video_ticks();
    int bw, l, gap = 12;
    const char *help = "left click reveals    right click flags    keys 1-4: another board";
    cur_level = lv;
    cols = levels[lv].cols;
    rows = levels[lv].rows;
    nmines = levels[lv].mines;
    ncells = cols * rows;
    memset(state, HIDDEN, ncells);
    memset(mine, 0, ncells);
    memset(adj, 0, ncells);
    game = READY;
    flags = opened = seconds = 0;
    bw = cols * T;
    barw = bw < 208 ? 208 : bw;
    /* the bar and the board, centred together; the board on a tile's
       word boundary at two bits (16 pixels a word) */
    bx = ((vid.w - bw) / 2) & ~15;
    barx = bx + bw / 2 - barw / 2;
    bary = (vid.h - (bar_h + gap + rows * T)) / 2;
    if (bary < 4)
        bary = 4;
    by = bary + bar_h + gap;
    button_s = bar_h - 12;
    button_x = barx + (barw - button_s) / 2;
    button_y = bary + 6;
    begin_draw();
    gfx_fill(&scr, 0, 0, vid.w, vid.h, C->bg, ROP_COPY);
    gfx_bevel(&scr, bx - 3, by - 3, bx + bw + 3, by + rows * T + 3, C->shadow, C->hi);
    font_draw(&scr, font_sans, (vid.w - font_width(font_sans, help)) / 2,
              by + rows * T + 24 < vid.h ? by + rows * T + 24 : vid.h - 4, help, C->text, -1);
    /* in the two-bit modes the bar's lines take palette bank 1 */
    if (vid.bpp == 2) {
        unsigned *tb = video_table(0);
        for (l = 0; l < vid.h; l++) {
            int b = l >= bary && l < bary + bar_h;
            line_desc[l] = (line_desc[l] & ~(15u << 19)) | (unsigned)b << 19;
            if (swcursor != 2 || l < band_y || l >= band_y + band_n)
                tb[l] = line_desc[l];
        }
    }
    draw_bar();
    draw_board();
    acc(&a_new, video_ticks() - t);
}

static unsigned rnd(void)
{
    seed = seed * 1103515245u + 12345u;
    return seed >> 16;
}

static int near(int a, int b)
{
    int ax = a % cols, ay = a / cols, bxx = b % cols, byy = b / cols;
    return ax - bxx <= 1 && bxx - ax <= 1 && ay - byy <= 1 && byy - ay <= 1;
}

/* the mines, away from the first click and its neighbours */
static void place(int first)
{
    int n = 0, c, x, y, dx, dy;
    seed = 2026 + 977 * cur_level;
    while (n < nmines) {
        c = rnd() % ncells;
        if (mine[c] || near(c, first))
            continue;
        mine[c] = 1;
        n++;
    }
    for (c = 0; c < ncells; c++) {
        x = c % cols;
        y = c / cols;
        for (dy = -1; dy <= 1; dy++)
            for (dx = -1; dx <= 1; dx++)
                if ((dx || dy) && x + dx >= 0 && x + dx < cols && y + dy >= 0 && y + dy < rows)
                    adj[c] += mine[c + dy * cols + dx];
    }
    game = PLAYING;
    t_start = rt_frames;
}

static void lose(int c)
{
    int k;
    game = LOST;
    for (k = 0; k < ncells; k++)
        if (mine[k] && state[k] != FLAGGED)
            tile(k, k == c ? T_BOOM : T_MINE);
        else if (!mine[k] && state[k] == FLAGGED)
            tile(k, T_WRONG);
    draw_button();
}

static void win(void)
{
    int k;
    game = WON;
    for (k = 0; k < ncells; k++)
        if (mine[k] && state[k] != FLAGGED) {
            state[k] = FLAGGED;
            tile(k, T_FLAG);
        }
    flags = nmines;
    draw_counter();
    draw_button();
}

/* open cell c; a cell with no mines around opens its neighbours, and so
   on (breadth first, through the queue): returns the cells opened */
static int reveal(int c)
{
    int qh = 0, qt = 0, n = 0, x, y, dx, dy, k;
    if (state[c] != HIDDEN)
        return 0;
    if (mine[c]) {
        state[c] = OPEN;
        lose(c);
        return 0;
    }
    state[c] = OPEN;
    queue[qt++] = c;
    while (qh < qt) {
        c = queue[qh++];
        tile(c, tile_of(c));
        n++;
        if (adj[c])
            continue;
        x = c % cols;
        y = c / cols;
        for (dy = -1; dy <= 1; dy++)
            for (dx = -1; dx <= 1; dx++) {
                if (x + dx < 0 || x + dx >= cols || y + dy < 0 || y + dy >= rows)
                    continue;
                k = c + dy * cols + dx;
                if (state[k] == HIDDEN) {
                    state[k] = OPEN;
                    queue[qt++] = k;
                }
            }
    }
    opened += n;
    return n;
}

/* a click on an open number with as many flags around: the rest opened */
static void chord(int c)
{
    int x = c % cols, y = c / cols, dx, dy, f = 0, k;
    for (dy = -1; dy <= 1; dy++)
        for (dx = -1; dx <= 1; dx++)
            if (x + dx >= 0 && x + dx < cols && y + dy >= 0 && y + dy < rows)
                f += state[c + dy * cols + dx] == FLAGGED;
    if (f != adj[c])
        return;
    for (dy = -1; dy <= 1 && game == PLAYING; dy++)
        for (dx = -1; dx <= 1 && game == PLAYING; dx++)
            if (x + dx >= 0 && x + dx < cols && y + dy >= 0 && y + dy < rows) {
                k = c + dy * cols + dx;
                if (state[k] == HIDDEN)
                    reveal(k);
            }
}

static int cell_at(int x, int y)
{
    if (x < bx || y < by || x >= bx + cols * T || y >= by + rows * T)
        return -1;
    return (y - by) / T * cols + (x - bx) / T;
}

static void click(int x, int y, int buttons)
{
    int c = cell_at(x, y), n;
    unsigned t;
    if (x >= button_x && x < button_x + button_s && y >= button_y && y < button_y + button_s &&
        (buttons & 1)) {
        new_board(cur_level);
        return;
    }
    if (c < 0 || game == WON || game == LOST)
        return;
    begin_draw();
    if ((buttons & 1) && game == READY) {
        char name[16];
        t = video_ticks();
        place(c);
        sprintf(name, "place_mines_%d", ncells);
        perf_value(name, video_ticks() - t);
    }
    t = video_ticks();
    if (buttons & 1) {
        if (state[c] == OPEN) {
            chord(c);
        } else if (state[c] == HIDDEN) {
            n = reveal(c);
            t = video_ticks() - t;
            if (n > 1) {
                acc(&a_flood, t);
                if (n > flood_cells_max) {
                    flood_cells_max = n;
                    perf_value("flood_largest", t);
                    printf("the largest flood fill: %d cells\n", n);
                }
            } else if (n == 1) {
                acc(&a_reveal, t);
            }
        }
        if (game == PLAYING && opened == ncells - nmines)
            win();
    } else if (buttons & 2) {
        if (state[c] == HIDDEN) {
            state[c] = FLAGGED;
            flags++;
        } else if (state[c] == FLAGGED) {
            state[c] = HIDDEN;
            flags--;
        } else {
            return;
        }
        tile(c, tile_of(c));
        draw_counter();
    }
}

static void alloc_save(void)
{
    int w = 32 + 32 / vid.bpp;      /* the cursor and a word's pixels */
    if (save_bits)
        return;
    save_bits = malloc(w * vid.bpp / 8 * 32);
    gfx_init(&save, save_bits, w, 32, w * vid.bpp / 32, scr.fmt);
}

static void alloc_bands(void)
{
    int k;
    if (band[0])
        return;
    for (k = 0; k < 2; k++) {
        band[k] = vram_alloc(vid.words * 4 * 32);
        gfx_init(&band_s[k], band[k], vid.w, 32, vid.words, scr.fmt);
    }
}

static unsigned t0;

static void tic(void)
{
    t0 = video_ticks();
}

static void toc(const char *name, int reps)
{
    perf_value(name, (video_ticks() - t0) / reps);
}

/* each way of drawing the cursor, and the tiles, the same in every run */
static void bench(void)
{
    int k, x = 203, y = 150;
    tic();
    toc("empty_span", 1);
    tic();
    for (k = 0; k < 100; k++)
        video_cursor_at(x + (k & 7), y);
    toc("hw_cursor_move", 100);
    tic();
    for (k = 0; k < 100; k++)
        video_cursor(k & 1 ? arrow.hw : probe.hw);
    toc("hw_cursor_shape", 100);
    tic();
    for (k = 0; k < 100; k++)
        tile(k % ncells, T_HIDDEN);
    toc("tile", 100);
    tic();
    draw_board();
    toc("board", 1);
    /* saved under: restore, save, draw, at a pixel off a word and on one;
       drawn with gfx_masked, then pre-shifted */
    swcursor = 1;
    cursor = &arrow;
    alloc_save();
    alloc_bands();
    for (fastcur = 0; fastcur < 2; fastcur++) {
        sw_shown = 0;
        sw_show(x, y);
        tic();
        for (k = 0; k < 10; k++) {
            sw_hide();
            sw_show(x + (k & 1), y);
        }
        toc(fastcur ? "sw_move_preshifted" : "sw_move_masked", 10);
        sw_hide();
    }
    sw_show(x, y);
    tic();
    sw_hide();
    toc("sw_restore", 1);
    tic();
    gfx_blit(&save, 0, 0, &scr, sw_sx, y, sw_sw, 32, ROP_COPY);
    toc("sw_save", 1);
    tic();
    for (k = 0; k < 10; k++)
        gfx_masked(&scr, x + (k & 1), y, &cursor->img, &cursor->mask, 0, 0, 32, 32);
    toc("sw_draw_masked", 10);
    tic();
    for (k = 0; k < 10; k++)
        fast_draw(&scr, x + (k & 1), y);
    toc("sw_draw_preshifted", 10);
    /* the band */
    swcursor = 2;
    for (fastcur = 0; fastcur < 2; fastcur++) {
        tic();
        for (k = 0; k < 10; k++)
            band_show(x + (k & 1), y + k);
        toc(fastcur ? "band_move_preshifted" : "band_move_masked", 10);
    }
    tic();
    for (k = 0; k < 10; k++)
        gfx_blit(&band_s[0], 0, 0, &scr, 0, y, vid.w, 32, ROP_COPY);
    toc("band_copy", 10);
}

int main(void)
{
    Event e;
    int k, buttons = 0;
    unsigned t;
    font_init();
    input_init();
    video_init(mode, VC_CURSOR | (f1 && mode >= 3 ? VC_F1 : 0));
    C = vid.bpp == 4 ? &col4 : &col2;
    palette();
    fb = vram_alloc(vid.words * 4 * vid.h);
    gfx_screen(&scr, fb, vid.words);
    line_desc = malloc(vid.h * sizeof(unsigned));
    for (k = 0; k < vid.h; k++)
        line_desc[k] = video_desc(fb + k * vid.words, 0);
    video_lines(0, 0, vid.h, fb, vid.words * 4, 0);
    bar_h = vid.h > 600 ? 64 : 48;
    make_tiles();
    make_cursor(&arrow, arrow_art, 0, 0);
    make_cursor(&probe, probe_art, 7, 7);
    preshift(&arrow);
    preshift(&probe);
    if (swcursor == 1)
        alloc_save();
    if (swcursor == 2)
        alloc_bands();
    if (swcursor)
        video_ctrl(0, VC_CURSOR);
    cursor = &arrow;
    if (!swcursor)
        video_cursor(arrow.hw);
    printf("mode %d, %d x %d x %d, format %d, cursor %s\n", mode, vid.w, vid.h, vid.bpp, scr.fmt,
           swcursor == 0 ? "hardware" : swcursor == 1 ? "software, saved under" : "software, band");
    new_board(level >= 0 ? level : vid.h > 600 ? 3 : 2);
    for (;;) {
        video_wait();
        perf_frame_begin();
        t = video_ticks();
        drawn = 0;
        while (input_next(&e)) {
            if (e.type == EV_KEY && e.key >= '1' && e.key <= '4') {
                if (levels[e.key - '1'].rows * T + bar_h + 20 < vid.h)
                    new_board(e.key - '1');
            } else if (e.type == EV_KEY && e.key == K_ESC) {
                goto out;
            } else if (e.type == EV_MOUSE) {
                int pressed = e.buttons & ~buttons;
                buttons = e.buttons;
                if (pressed)
                    click(e.x, e.y, pressed);
            }
        }
        set_cursor(cell_at(mouse_x, mouse_y) >= 0 && game < WON ? &probe : &arrow);
        if (game == PLAYING) {
            int s = (rt_frames - t_start) * 1001 / 60000;
            if (s != seconds && s <= 999) {
                seconds = s;
                draw_timer();
            }
        }
        update_cursor();
        acc(&a_frame, video_ticks() - t);
        perf_frame_end();
    }
out:
    perf_frames("frames");
    acc_print(&a_frame);
    acc_print(&a_board);
    acc_print(&a_new);
    acc_print(&a_reveal);
    acc_print(&a_flood);
    acc_print(&a_timer);
    acc_print(&a_cursor);
    acc_print(&a_hide);
    printf("cursor updates %d, %d of them under the beam\n", cursor_updates, tears);
    bench();
    printf("@done\n");
    for (;;)
        video_wait();
    return 0;
}
