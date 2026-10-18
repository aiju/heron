/* Snake on Heron Mini, in M1 used as 320 x 240 x 8: every row of the
   framebuffer shown on two lines, two descriptors pointing at the same
   words (RFC 0042, 3). A grid of 8 x 8 cells, the arrow keys, food,
   growing, the score in the cell font, a title screen; all the drawing
   goes through the library (gfx/).

   It draws only what changes: a step draws the new head, turns the old
   head into body and erases the tail, a handful of small fills. Colour
   comes from the palette rather than from drawing: each body segment
   keeps one of 16 palette entries, by its place in the snake, and
   rotating those 16 entries every frame runs a wave of colour down the
   snake (and through the title's letters); the food glints and "press
   space" blinks the same way. The descriptors do the rest: a ripple
   through the title, a banner for pause and game over shown by pointing
   some lines at another buffer (nothing under it is drawn over, so
   nothing has to be saved or restored), and a shake when the snake
   crashes.

   After the game it measures each way of drawing (rt/perf.h): the
   incremental step against redrawing everything, the palette against
   redrawing to recolour, the fonts, the descriptors. */

#include <stdio.h>
#include <string.h>
#include "gfx.h"
#include "video.h"
#include "input.h"
#include "perf.h"

#define W 320
#define H 240
#define PITCH 80                /* words a row: 320 pixels of 8 bits */
#define GW 40                   /* the grid in cells, the walls included */
#define GH 27
#define GY 24                   /* the grid's top on the screen; above it the bar */
#define RING 1024               /* the snake's cells, a ring (38 x 25 fit) */
#define BANNER_Y 96             /* the banner's rows on the screen */
#define BANNER_H 48

/* palette entries; 0-15 are the default palette's 16 (video_default_palette) */
enum {
    C_BLACK = 0, C_YELLOW = 14, C_WHITE = 15,
    C_GRASS0 = 16, C_GRASS1, C_WALL, C_WALL_HI, C_BAR, C_BAR_TEXT, C_BAR_DIM, C_BAR_LINE,
    C_FOOD, C_FOOD_DK, C_LEAF, C_FOOD_HI, C_HEAD, C_EYE, C_PUPIL, C_BLINK,
    C_BODY,                     /* 16 entries: the body's colours, rotated each frame */
    C_BANNER = C_BODY + 16, C_BANNER_HI, C_BANNER_TEXT, C_DEAD, C_TITLE_BG
};

static const int dx[4] = {1, 0, -1, 0}, dy[4] = {0, 1, 0, -1};    /* right, down, left, up */
static const signed char sine[64] = {
    0, 2, 3, 5, 6, 8, 9, 10, 11, 12, 13, 14, 15, 15, 16, 16, 16, 16, 16, 15, 15, 14, 13, 12,
    11, 10, 9, 8, 6, 5, 3, 2, 0, -2, -3, -5, -6, -8, -9, -10, -11, -12, -13, -14, -15, -15,
    -16, -16, -16, -16, -16, -15, -15, -14, -13, -12, -11, -10, -9, -8, -6, -5, -3, -2,
};

/* the screen; the banners for messages and for the pause; the empty
   board (for the measurements) */
static Surface scr, ban, pban, bgs;
static unsigned *fb, *banner, *pbanner, *bg_fb;
static unsigned fb_desc, banner_desc, pause_desc;      /* their row 0's descriptors */
static unsigned t_space;                /* the frame the game was started in */

static unsigned char grid[GH][64];      /* G_FREE, G_WALL, G_SNAKE, G_FOOD */
enum { G_FREE, G_WALL, G_SNAKE, G_FOOD };
static unsigned char sx[RING], sy[RING];
static int head, tail;                  /* ring indices: the newest cell and the oldest */
static int dir, grow, score, best, foods, period, autopilot, alive, paused, steps;
static int fx, fy;                      /* the food */
static int flash;                       /* frames of the grass lit up */
static int turns[4], nturns;            /* turns typed ahead of the steps */
static unsigned frame;
static int cpu_pct, cpu_shown = -1;
static unsigned step_sum, step_max, step_n;    /* the steps' drawing, measured */
static unsigned seed = 2026;

static unsigned rnd(void)
{
    seed = seed * 1103515245u + 12345u;
    return seed >> 16;
}

/* ---- the palette ---- */

/* the body's 16 colours: green to yellow-green and back */
static unsigned body_rgb[16];

static void palette(void)
{
    int k;
    video_default_palette();
    video_pal_rgb(C_GRASS0, 22, 70, 30);
    video_pal_rgb(C_GRASS1, 28, 82, 36);
    video_pal_rgb(C_WALL, 120, 60, 40);
    video_pal_rgb(C_WALL_HI, 170, 150, 120);
    video_pal_rgb(C_BAR, 24, 28, 48);
    video_pal_rgb(C_BAR_TEXT, 230, 230, 200);
    video_pal_rgb(C_BAR_DIM, 120, 130, 160);
    video_pal_rgb(C_BAR_LINE, 90, 100, 150);
    video_pal_rgb(C_FOOD, 220, 30, 50);
    video_pal_rgb(C_FOOD_DK, 130, 10, 30);
    video_pal_rgb(C_LEAF, 60, 200, 60);
    video_pal_rgb(C_FOOD_HI, 255, 200, 200);
    video_pal_rgb(C_HEAD, 250, 220, 60);
    video_pal_rgb(C_EYE, 255, 255, 255);
    video_pal_rgb(C_PUPIL, 0, 0, 0);
    video_pal_rgb(C_BLINK, 255, 255, 255);
    video_pal_rgb(C_BANNER, 40, 20, 70);
    video_pal_rgb(C_BANNER_HI, 200, 150, 255);
    video_pal_rgb(C_BANNER_TEXT, 255, 255, 255);
    video_pal_rgb(C_DEAD, 255, 40, 40);
    video_pal_rgb(C_TITLE_BG, 12, 20, 16);
    for (k = 0; k < 16; k++) {
        int t = k < 8 ? k : 16 - k;     /* 0..8..1 */
        body_rgb[k] = rgb565(40 + 20 * t, 150 + 10 * t, 40 + 5 * t);
        video_pal(C_BODY + k, body_rgb[k]);
    }
}

/* each frame: the body's colours one step along (16 writes, nothing
   redrawn), the food's glint and the blinking text */
static void palette_frame(void)
{
    int k, ph = frame >> 1, t = frame & 31;
    for (k = 0; k < 16; k++)
        VID_PAL(C_BODY + k) = body_rgb[(k - ph) & 15];
    t = t < 16 ? t : 31 - t;
    VID_PAL(C_FOOD_HI) = rgb565(140 + 7 * t, 40 + 13 * t, 60 + 12 * t);
    VID_PAL(C_BLINK) = frame & 32 ? rgb565(255, 255, 255) : rgb565(60, 70, 60);
    /* the grass lights up for a few frames when the snake eats */
    if (flash) {
        flash--;
        VID_PAL(C_GRASS0) = flash ? rgb565(50, 110, 50) : vid_palette[C_GRASS0];
        VID_PAL(C_GRASS1) = flash ? rgb565(60, 125, 60) : vid_palette[C_GRASS1];
    }
}

/* ---- the descriptors ---- */

/* rows y0..y0+n of buffer d0 (its row 0's descriptor) on the screen's
   rows from r0: two lines each */
static void map_rows(int r0, unsigned d0, int n)
{
    unsigned *t = video_table(0) + 2 * r0;
    while (n-- > 0) {
        *t++ = d0;
        *t++ = d0;
        d0 += PITCH;
    }
}

static void show_screen(void)
{
    map_rows(0, fb_desc, H);
}

/* a banner's rows (its row 0's descriptor) over the screen's middle, or
   the screen again (0) */
static void show_banner(unsigned desc)
{
    map_rows(BANNER_Y, desc ? desc : fb_desc + BANNER_Y * PITCH, BANNER_H);
}

/* the whole picture moved down k rows (up if k < 0), the edges repeated */
static void shake(int k)
{
    unsigned *t = video_table(0);
    int y, r;
    for (y = 0; y < H; y++) {
        r = y - k;
        r = r < 0 ? 0 : r >= H ? H - 1 : r;
        t[2 * y] = t[2 * y + 1] = fb_desc + r * PITCH;
    }
}

/* ---- a block font: 5 x 7 letters drawn as snake segments ---- */

static const char *letters = "SNAKEGMOVRPUDY";
static const char *letter_art[14][7] = {
    {".####", "#....", "#....", ".###.", "....#", "....#", "####."},  /* S */
    {"#...#", "##..#", "#.#.#", "#..##", "#...#", "#...#", "#...#"},  /* N */
    {".###.", "#...#", "#...#", "#####", "#...#", "#...#", "#...#"},  /* A */
    {"#...#", "#..#.", "#.#..", "##...", "#.#..", "#..#.", "#...#"},  /* K */
    {"#####", "#....", "#....", "####.", "#....", "#....", "#####"},  /* E */
    {".###.", "#...#", "#....", "#.###", "#...#", "#...#", ".###."},  /* G */
    {"#...#", "##.##", "#.#.#", "#.#.#", "#...#", "#...#", "#...#"},  /* M */
    {".###.", "#...#", "#...#", "#...#", "#...#", "#...#", ".###."},  /* O */
    {"#...#", "#...#", "#...#", "#...#", "#...#", ".#.#.", "..#.."},  /* V */
    {"####.", "#...#", "#...#", "####.", "#.#..", "#..#.", "#...#"},  /* R */
    {"####.", "#...#", "#...#", "####.", "#....", "#....", "#...."},  /* P */
    {"#...#", "#...#", "#...#", "#...#", "#...#", "#...#", ".###."},  /* U */
    {"####.", "#...#", "#...#", "#...#", "#...#", "#...#", "####."},  /* D */
    {"#...#", "#...#", ".#.#.", "..#..", "..#..", "..#..", "..#.."},  /* Y */
};

static int lit(int l, int r, int c)
{
    return l >= 0 && r >= 0 && r < 7 && c >= 0 && c < 5 && letter_art[l][r][c] == '#';
}

/* text in the block font, each dot a cell of `size` pixels: a square
   inset by size/8 and joined to the dots right and below it, so letters
   look like the snake; colour c, or the body's rotating colours by
   position if c < 0 */
static void block_text(Surface *s, int x, int y, const char *str, int size, int c)
{
    int in = size / 8 > 0 ? size / 8 : 1, i, r, col, l;
    for (i = 0; str[i]; i++, x += 6 * size) {
        const char *p = strchr(letters, str[i]);
        if (!p || str[i] == ' ')
            continue;
        l = p - letters;
        for (r = 0; r < 7; r++)
            for (col = 0; col < 5; col++) {
                int px = x + col * size, py = y + r * size;
                unsigned k = c >= 0 ? c : C_BODY + ((15 - col - r - 6 * i) & 15);
                if (!lit(l, r, col))
                    continue;
                gfx_fill(s, px + in, py + in, px + size - in, py + size - in, k, ROP_COPY);
                if (lit(l, r, col + 1))
                    gfx_fill(s, px + size - in, py + in, px + size + in, py + size - in, k,
                             ROP_COPY);
                if (lit(l, r + 1, col))
                    gfx_fill(s, px + in, py + size - in, px + size - in, py + size + in, k,
                             ROP_COPY);
            }
    }
}

static int block_width(const char *str, int size)
{
    return (6 * strlen(str) - 1) * size;
}

/* ---- the board ---- */

static Surface food_img;
static unsigned food_bits[8 * 2];
static unsigned food_mask_bits[8];
static Bitmap food_mask = {food_mask_bits, 1};

/* the food: a berry, its glint the palette's pulsing entry */
static const char *food_art[8] = {
    "....l...",
    "...ll...",
    "..rrrr..",
    ".rhrrrd.",
    ".rhrrrd.",
    ".rrrrdd.",
    "..rddd..",
    "........",
};

static void make_food(void)
{
    int x, y;
    gfx_init(&food_img, food_bits, 8, 8, 2, scr.fmt);
    for (y = 0; y < 8; y++)
        for (x = 0; x < 8; x++) {
            char ch = food_art[y][x];
            unsigned c = ch == 'r' ? C_FOOD : ch == 'd' ? C_FOOD_DK : ch == 'l' ? C_LEAF : C_FOOD_HI;
            if (ch == '.')
                continue;
            gfx_pixel(&food_img, x, y, c, ROP_COPY);
            food_mask_bits[y] |= 1u << x;
        }
}

static unsigned grass_of(int x, int y)
{
    return (x ^ y) & 1 ? C_GRASS1 : C_GRASS0;
}

static void grass(int x, int y)
{
    int px = x * 8, py = GY + y * 8;
    gfx_fill(&scr, px, py, px + 8, py + 8, grass_of(x, y), ROP_COPY);
}

/* a segment: 6 x 6 in its cell */
static void block(int x, int y, unsigned c)
{
    int px = x * 8, py = GY + y * 8;
    gfx_fill(&scr, px + 1, py + 1, px + 7, py + 7, c, ROP_COPY);
}

/* the two pixels' width joining cell (x, y) to the next in direction d */
static void bridge(int x, int y, int d, unsigned c)
{
    int px = x * 8, py = GY + y * 8;
    switch (d) {
    case 0: gfx_fill(&scr, px + 7, py + 1, px + 9, py + 7, c, ROP_COPY); break;
    case 1: gfx_fill(&scr, px + 1, py + 7, px + 7, py + 9, c, ROP_COPY); break;
    case 2: gfx_fill(&scr, px - 1, py + 1, px + 1, py + 7, c, ROP_COPY); break;
    default: gfx_fill(&scr, px + 1, py - 1, px + 7, py + 1, c, ROP_COPY); break;
    }
}

/* the half of a bridge left in the next cell (direction d from (x, y)) once
   (x, y) is gone: back to that cell's grass */
static void unstub(int x, int y, int d)
{
    int nx = x + dx[d], ny = y + dy[d], px = nx * 8, py = GY + ny * 8;
    unsigned c = grass_of(nx, ny);
    switch (d) {
    case 0: gfx_fill(&scr, px, py + 1, px + 1, py + 7, c, ROP_COPY); break;
    case 1: gfx_fill(&scr, px + 1, py, px + 7, py + 1, c, ROP_COPY); break;
    case 2: gfx_fill(&scr, px + 7, py + 1, px + 8, py + 7, c, ROP_COPY); break;
    default: gfx_fill(&scr, px + 1, py + 7, px + 7, py + 8, c, ROP_COPY); break;
    }
}

/* the eyes, by direction: white then pupil, two of each, in the cell */
static const unsigned char eyes[4][8] = {
    {5, 2, 6, 2, 5, 5, 6, 5}, {2, 5, 2, 6, 5, 5, 5, 6},
    {2, 2, 1, 2, 2, 5, 1, 5}, {2, 2, 2, 1, 5, 2, 5, 1},
};

static void draw_head(int x, int y, int d, unsigned c)
{
    int px = x * 8, py = GY + y * 8;
    const unsigned char *e = eyes[d];
    block(x, y, c);
    gfx_pixel(&scr, px + e[0], py + e[1], C_EYE, ROP_COPY);
    gfx_pixel(&scr, px + e[2], py + e[3], C_PUPIL, ROP_COPY);
    gfx_pixel(&scr, px + e[4], py + e[5], C_EYE, ROP_COPY);
    gfx_pixel(&scr, px + e[6], py + e[7], C_PUPIL, ROP_COPY);
}

static void draw_food(void)
{
    gfx_masked(&scr, fx * 8, GY + fy * 8, &food_img, &food_mask, 0, 0, 8, 8);
}

static unsigned body_colour(int i)
{
    return C_BODY + (i & 15);
}

/* the direction from ring cell i to the next one */
static int dir_to_next(int i)
{
    int j = (i + 1) & (RING - 1), ddx = sx[j] - sx[i], ddy = sy[j] - sy[i];
    return ddx > 0 ? 0 : ddy > 0 ? 1 : ddx < 0 ? 2 : 3;
}

/* every segment, the head and the food: what a full redraw draws over
   the empty board */
static void draw_snake(void)
{
    int i;
    for (i = tail; i != head; i = (i + 1) & (RING - 1)) {
        block(sx[i], sy[i], body_colour(i));
        bridge(sx[i], sy[i], dir_to_next(i), body_colour(i));
    }
    draw_head(sx[head], sy[head], dir, C_HEAD);
}

static void draw_walls(Surface *s)
{
    /* bricks: mortar rows 0 and 4, joints staggered */
    static const unsigned char brick[8] = {0xFF, 0x01, 0x01, 0x01, 0xFF, 0x10, 0x10, 0x10};
    gfx_fill_pat(s, 0, GY, W, GY + 8, brick, C_WALL_HI, C_WALL);
    gfx_fill_pat(s, 0, H - 8, W, H, brick, C_WALL_HI, C_WALL);
    gfx_fill_pat(s, 0, GY + 8, 8, H - 8, brick, C_WALL_HI, C_WALL);
    gfx_fill_pat(s, W - 8, GY + 8, W, H - 8, brick, C_WALL_HI, C_WALL);
}

static void draw_grass(Surface *s)
{
    int x, y;
    for (y = 1; y < GH - 1; y++)
        for (x = 1; x < GW - 1; x++)
            gfx_fill(s, x * 8, GY + y * 8, x * 8 + 8, GY + y * 8 + 8, grass_of(x, y), ROP_COPY);
}

/* the bar: the score, the length, the best, and the CPU's share of a
   frame. The labels are drawn once and only the numbers after that: the
   library's expansion at 8 bits is its C kernel in every variant, about
   0.6 ms a character */
static void draw_bar_labels(void)
{
    font_cells(&scr, 8, 4, "SCORE", 5, C_BAR_TEXT, C_BAR);
    font_cells(&scr, 112, 4, "LEN", 3, C_BAR_TEXT, C_BAR);
    font_cells(&scr, W - 8 - 8 * 10, 4, "BEST", 4, C_BAR_DIM, C_BAR);
}

static void draw_numbers(void)
{
    char buf[16];
    sprintf(buf, "%05d", score);
    font_cells(&scr, 56, 4, buf, 5, C_BAR_TEXT, C_BAR);
    sprintf(buf, "%3d", (head - tail) & (RING - 1));
    font_cells(&scr, 144, 4, buf, 3, C_BAR_TEXT, C_BAR);
    sprintf(buf, "%05d", best);
    font_cells(&scr, W - 8 - 8 * 5, 4, buf, 5, C_BAR_DIM, C_BAR);
}

static void draw_cpu(void)
{
    char buf[16];
    if (cpu_pct == cpu_shown)
        return;
    cpu_shown = cpu_pct;
    sprintf(buf, "cpu %d%%", cpu_pct);
    gfx_fill(&scr, 180, 6, 228, 20, C_BAR, ROP_COPY);
    font_draw(&scr, font_sans, 180, 17, buf, C_BAR_LINE, -1);
}

static void place_food(void)
{
    do {
        fx = 1 + rnd() % (GW - 2);
        fy = 1 + rnd() % (GH - 2);
    } while (grid[fy][fx] != G_FREE);
    grid[fy][fx] = G_FOOD;
    draw_food();
}

static void new_game(void)
{
    int x, y, i;
    memset(grid, G_FREE, sizeof grid);
    for (x = 0; x < GW; x++)
        grid[0][x] = grid[GH - 1][x] = G_WALL;
    for (y = 0; y < GH; y++)
        grid[y][0] = grid[y][GW - 1] = G_WALL;
    gfx_fill(&scr, 0, 0, W, GY, C_BAR, ROP_COPY);
    gfx_fill(&scr, 0, GY - 2, W, GY - 1, C_BAR_LINE, ROP_COPY);
    draw_walls(&scr);
    draw_grass(&scr);
    tail = 0;
    for (i = 0; i < 4; i++) {
        sx[i] = 6 + i;
        sy[i] = GH / 2;
        grid[sy[i]][sx[i]] = G_SNAKE;
    }
    head = 3;
    dir = 0;
    grow = 0;
    score = foods = steps = 0;
    period = 5;
    alive = 1;
    paused = 0;
    nturns = 0;
    draw_snake();
    place_food();
    cpu_shown = -1;
    draw_bar_labels();
    draw_numbers();
}

/* ---- the autopilot: greedy for the food, and wary of small spaces ---- */

static unsigned short seen[GH][64];
static unsigned short stamp;
static unsigned char qx[128], qy[128];

/* cells reachable from (x, y), up to `limit` */
static int room(int x, int y, int limit)
{
    int qh = 0, qt = 0, n = 0, d;
    stamp++;
    seen[y][x] = stamp;
    qx[qt] = x;
    qy[qt++] = y;
    while (qh < qt && n < limit) {
        int cx = qx[qh], cy = qy[qh++];
        n++;
        for (d = 0; d < 4; d++) {
            int nx = cx + dx[d], ny = cy + dy[d];
            if (grid[ny][nx] >= G_WALL && grid[ny][nx] != G_FOOD)
                continue;
            if (seen[ny][nx] == stamp || qt >= 128)
                continue;
            seen[ny][nx] = stamp;
            qx[qt] = nx;
            qy[qt++] = ny;
        }
    }
    return n;
}

static int think(void)
{
    int k, best_d = dir, best_s = 1 << 30, len = (head - tail) & (RING - 1);
    int want = len < 100 ? len : 100;
    for (k = 0; k < 3; k++) {
        int d = (dir + (k == 0 ? 0 : k == 1 ? 1 : 3)) & 3;
        int nx = sx[head] + dx[d], ny = sy[head] + dy[d], s;
        int g = grid[ny][nx];
        if (g == G_WALL || (g == G_SNAKE && !(nx == sx[tail] && ny == sy[tail] && !grow)))
            continue;
        s = (nx > fx ? nx - fx : fx - nx) + (ny > fy ? ny - fy : fy - ny);
        if (room(nx, ny, want) < want)
            s += 1000;
        if (s < best_s) {
            best_s = s;
            best_d = d;
        }
    }
    return best_d;
}

/* ---- a step ---- */

static void step(void)
{
    int nx, ny, old, g, t0;
    if (nturns) {
        int d = turns[0];
        memmove(turns, turns + 1, --nturns * sizeof turns[0]);
        if (d != ((dir + 2) & 3))
            dir = d;
    }
    if (autopilot)
        dir = think();
    t0 = video_ticks();
    nx = sx[head] + dx[dir];
    ny = sy[head] + dy[dir];
    if (grow) {
        grow--;
    } else {
        /* the tail goes: its cell's grass, and its bridge's half in the next cell */
        grass(sx[tail], sy[tail]);
        unstub(sx[tail], sy[tail], dir_to_next(tail));
        grid[sy[tail]][sx[tail]] = G_FREE;
        tail = (tail + 1) & (RING - 1);
    }
    g = grid[ny][nx];
    if (g == G_WALL || g == G_SNAKE) {
        draw_head(sx[head], sy[head], dir, C_DEAD);
        alive = 0;
        return;
    }
    old = head;
    head = (head + 1) & (RING - 1);
    sx[head] = nx;
    sy[head] = ny;
    grid[ny][nx] = G_SNAKE;
    block(sx[old], sy[old], body_colour(old));
    bridge(sx[old], sy[old], dir, body_colour(old));
    draw_head(nx, ny, dir, C_HEAD);
    t0 = video_ticks() - t0;
    step_sum += t0;
    step_n++;
    if (t0 > step_max)
        step_max = t0;
    steps++;
    if (g == G_FOOD) {
        score += 10;
        grow += 3;
        foods++;
        if (score > best)
            best = score;
        if (foods % 3 == 0 && period > 2)
            period--;
        place_food();
        draw_numbers();
        flash = 6;
    }
}

/* ---- the screens ---- */

/* the title's rows rippling: each line of the band shows a row up to 2
   above or below its own, by a sine running down it (keeping the
   descriptors' interrupt bit) */
static void ripple(int y0, int n)
{
    unsigned *t = video_table(0) + 2 * y0;
    int l, r;
    for (l = 0; l < 2 * n; l++) {
        r = y0 + l / 2 + (sine[(l * 2 + frame * 3) & 63] >> 3);
        t[l] = (t[l] & 1u << 23) | (fb_desc + r * PITCH);
    }
}

/* the title's sky: the background's palette entry changed every 16
   lines from a descriptor's interrupt, a gradient of 30 bands drawn in
   one colour */
static unsigned sky[30];
static int sky_lines;

static void sky_line(int y)
{
    VID_PAL(C_TITLE_BG) = sky[(y >> 4) + 1 < 30 ? (y >> 4) + 1 : 29];
}

static void sky_frame(void)
{
    VID_PAL(C_TITLE_BG) = sky[0];
}

static void sky_on(int on)
{
    int y;
    sky_lines = 0;
    for (y = 15; y < 2 * H - 1; y += 16, sky_lines++)
        video_line_irq(0, y, on);
    rt_line_hook = on ? sky_line : 0;
    rt_frame_hook = on ? sky_frame : 0;
}

static void title(void)
{
    Event e;
    int tw = block_width("SNAKE", 8), x0 = (W - tw) / 2, k;
    unsigned f0 = 0;
    char buf[40];
    for (k = 0; k < 30; k++)
        sky[k] = rgb565(8 + 2 * k, 10 + 4 * k, 24 + 5 * k);
    perf_start();
    gfx_fill(&scr, 0, 0, W, H, C_TITLE_BG, ROP_COPY);
    block_text(&scr, x0, 40, "SNAKE", 8, -1);
    font_draw(&scr, font_sans, (W - font_width(font_sans, "PRESS SPACE TO START")) / 2, 140,
              "PRESS SPACE TO START", C_BLINK, -1);
    font_cells(&scr, 24, 176, "ARROWS STEER  P PAUSE  A AUTO", 29, C_BAR_DIM, -1);
    sprintf(buf, "BEST %05d", best);
    font_cells(&scr, (W - 80) / 2, 200, buf, 10, C_BAR_DIM, -1);
    gfx_fill(&scr, x0, 112, x0 + tw, 114, C_BAR_LINE, ROP_COPY);
    perf_end("title_draw");
    show_screen();
    sky_on(1);
    for (;;) {
        video_wait();
        perf_frame_begin();
        frame = rt_frames;      /* the colours by the time, however long drawing took */
        palette_frame();
        ripple(32, 72);
        perf_frame_end();
        if (++f0 == 40)
            rt_shot("title");
        while (input_next(&e))
            if (e.type == EV_KEY && e.key == ' ') {
                perf_frames("title_frame");
                sky_on(0);
                t_space = rt_frames;
                return;
            }
    }
}

static void input(void)
{
    Event e;
    while (input_next(&e)) {
        int d = -1;
        if (e.type != EV_KEY)
            continue;
        switch (e.key) {
        case K_RIGHT: d = 0; break;
        case K_DOWN: d = 1; break;
        case K_LEFT: d = 2; break;
        case K_UP: d = 3; break;
        case 'a': autopilot = !autopilot; break;
        case 'p':
            paused = !paused;
            show_banner(paused ? pause_desc : 0);
            break;
        case K_ESC: alive = 0; break;
        }
        if (d >= 0 && nturns < 4)
            turns[nturns++] = d;
    }
}

static void draw_banner(Surface *b, const char *big, const char *small)
{
    int w = block_width(big, 4);
    gfx_fill(b, 0, 0, W, BANNER_H, C_BANNER, ROP_COPY);
    gfx_fill(b, 0, 1, W, 2, C_BANNER_HI, ROP_COPY);
    gfx_fill(b, 0, BANNER_H - 2, W, BANNER_H - 1, C_BANNER_HI, ROP_COPY);
    block_text(b, (W - w) / 2, 6, big, 4, C_BANNER_TEXT);
    if (small)
        font_draw(b, font_sans, (W - font_width(font_sans, small)) / 2, 44, small,
                  C_BANNER_HI, -1);
}

static void play(void)
{
    unsigned work;
    int tick = 0;
    new_game();
    /* ready: the board under a banner until 45 frames after the start,
       however long the board took to draw */
    draw_banner(&ban, "READY", "ARROWS TO STEER");
    show_screen();
    show_banner(banner_desc);
    while (rt_frames < t_space + 45) {
        video_wait();
        frame = rt_frames;
        palette_frame();
    }
    show_banner(0);
    while (alive) {
        tick += video_wait();   /* the frames since the last: steps keep time */
        perf_frame_begin();
        work = video_ticks();
        frame = rt_frames;
        palette_frame();
        input();
        if (paused) {
            tick = 0;
        } else if (alive && tick >= period) {
            tick = 0;
            step();
        }
        if ((frame & 31) == 0)
            draw_cpu();
        perf_frame_end();
        work = video_ticks() - work;
        cpu_pct = (cpu_pct * 7 + (work * 100 + vid.frame_ticks / 2) / vid.frame_ticks) / 8;
        if (steps == 200 && tick == 0)
            rt_shot("game");
    }
    perf_frames("game_frame");
    perf_value("step_draw_avg", step_n ? step_sum / step_n : 0);
    perf_value("step_draw_max", step_max);
    printf("score %d, length %d, %d steps\n", score, (head - tail) & (RING - 1), steps);
}

static void game_over(void)
{
    char buf[32];
    int k;
    sprintf(buf, "SCORE %d", score);
    draw_banner(&ban, "GAME OVER", buf);
    /* the crash: the picture shaken by its descriptors */
    for (k = 0; k < 16; k++) {
        video_wait();
        frame = rt_frames;
        palette_frame();
        shake(k & 1 ? 3 - k / 6 : k / 6 - 3);
    }
    show_screen();
    show_banner(banner_desc);
    for (k = 0; k < 40; k++) {
        video_wait();
        frame = rt_frames;
        palette_frame();
        if (k == 20)
            rt_shot("game_over");
    }
}

/* ---- the measurements ---- */

static void bench_redraw(void)
{
    gfx_blit(&scr, 0, GY, &bgs, 0, GY, W, H - GY, ROP_COPY);
    draw_snake();
    draw_food();
}

static void bench_recolour(void)
{
    int i;
    for (i = tail; i != head; i = (i + 1) & (RING - 1)) {
        block(sx[i], sy[i], body_colour(i + 1));
        bridge(sx[i], sy[i], dir_to_next(i), body_colour(i + 1));
    }
}

static void bench_step_cells(void)
{
    /* what a step draws, at a cell in the middle */
    int x = 20, y = 12;
    grass(x - 1, y);
    unstub(x - 1, y, 0);
    block(x, y, C_BODY);
    bridge(x, y, 0, C_BODY);
    draw_head(x + 1, y, 0, C_HEAD);
}

static unsigned t_start;

static void tic(void)
{
    t_start = video_ticks();
}

static void toc(const char *name, int reps)
{
    perf_value(name, (video_ticks() - t_start) / reps);
}

/* the techniques the library doesn't use, for comparison: a cell's words
   written directly, and text at 8 bits through a table of the 16 masks of
   a nibble's four pixels (the format's own bits, so any layout) */
static void cell_direct(int x, int y, unsigned c)
{
    unsigned w = gfx_solidf(scr.f, c), *p = scr.bits + (GY + y * 8) * PITCH + 2 * x;
    int r;
    for (r = 0; r < 8; r++, p += PITCH) {
        p[0] = w;
        p[1] = w;
    }
}

static unsigned nib[16];

/* the cell font, x a multiple of 4, opaque */
static void text8(int x, int y, const char *s, int n, unsigned fg, unsigned bg)
{
    unsigned fw = gfx_solidf(scr.f, fg), bw = gfx_solidf(scr.f, bg), xw = fw ^ bw;
    unsigned *p = scr.bits + y * PITCH + (x >> 2), *q;
    const unsigned char *g;
    int r, c;
    if (!nib[15])
        for (r = 0; r < 16; r++)
            nib[r] = gfx_xmask(scr.f, r);
    for (; n > 0; n--, p += 2) {
        c = (unsigned char)*s++;
        g = font_cell8 + 16 * ((c < 32 || c > 126 ? '?' : c) - 32);
        q = p;
        for (r = 0; r < 16; r++, q += PITCH) {
            unsigned b = *g++;
            q[0] = bw ^ (xw & nib[b & 15]);
            q[1] = bw ^ (xw & nib[b >> 4]);
        }
    }
}

/* idle loop turns over `frames` frames: what's left of the CPU */
static unsigned idle(int frames)
{
    unsigned n = 0, f;
    video_wait();               /* returns at once if a frame has passed */
    video_wait();
    f = rt_frames + frames;
    while ((int)(rt_frames - f) < 0)
        n++;
    return n;
}

static unsigned save_bits[PITCH * BANNER_H];

static void measure(void)
{
    char buf[40];
    unsigned a, b;
    Surface save;
    int k, len = (head - tail) & (RING - 1);
    printf("measuring, the snake %d long\n", len);
    show_screen();
    /* the empty board, kept for redrawing from */
    tic();
    draw_walls(&bgs);
    toc("walls_fill_pat", 1);
    tic();
    draw_grass(&bgs);
    toc("grass_950_fills", 1);
    tic();
    for (k = 0; k < 100; k++)
        gfx_fill(&scr, 160, 120, 168, 128, C_GRASS0, ROP_COPY);
    toc("fill_cell_8x8", 100);
    tic();
    for (k = 0; k < 100; k++)
        cell_direct(20, 12, C_GRASS0);
    toc("cell_direct_8x8", 100);
    tic();
    for (k = 0; k < 100; k++)
        gfx_pixel(&scr, 161, 121, C_EYE, ROP_COPY);
    toc("pixel", 100);
    tic();
    gfx_fill(&scr, 0, GY, W, H, C_GRASS0, ROP_COPY);
    toc("field_fill", 1);
    tic();
    gfx_blit(&scr, 0, GY, &bgs, 0, GY, W, H - GY, ROP_COPY);
    toc("field_blit", 1);
    tic();
    bench_redraw();
    toc("full_redraw", 1);
    tic();
    draw_snake();
    toc("snake_redraw", 1);
    tic();
    bench_recolour();
    toc("recolour_redraw", 1);
    tic();
    for (k = 0; k < 10; k++)
        palette_frame();
    toc("palette_frame", 10);
    tic();
    for (k = 0; k < 256; k++)
        VID_PAL(k) = vid_palette[k];
    toc("palette_256", 1);
    tic();
    for (k = 0; k < 10; k++)
        bench_step_cells();
    toc("step_cells", 10);
    tic();
    for (k = 0; k < 10; k++)
        draw_food();
    toc("food_sprite", 10);
    /* the bar's 13 digits: the library's cell font, the sans font, and
       the nibble table */
    tic();
    for (k = 0; k < 10; k++)
        draw_numbers();
    toc("digits_font_cells", 10);
    sprintf(buf, "%05d%3d%05d", score, len, best);
    tic();
    for (k = 0; k < 10; k++) {
        gfx_fill(&scr, 56, 4, 56 + 8 * 13, 20, C_BAR, ROP_COPY);
        font_draw(&scr, font_sans, 56, 16, buf, C_BAR_TEXT, -1);
    }
    toc("digits_sans", 10);
    tic();
    for (k = 0; k < 10; k++)
        text8(56, 4, buf, 13, C_BAR_TEXT, C_BAR);
    toc("digits_text8", 10);
    draw_bar_labels();
    draw_numbers();
    /* the line interrupts' cost, from what they leave of an idle loop */
    a = idle(10);
    sky_on(1);
    b = idle(10);
    sky_on(0);
    /* ticks an idle turn (x 16), then the turns lost an interrupt */
    k = 10 * vid.frame_ticks / (a / 16);
    printf("idle loop: %u turns a frame, %u with %d line interrupts\n", a / 10, b / 10,
           sky_lines);
    perf_value("line_irq_cost", (a - b) * k / 16 / (10 * sky_lines));
    tic();
    for (k = 0; k < 10; k++)
        show_screen();
    toc("desc_480", 10);
    tic();
    for (k = 0; k < 10; k++)
        show_banner(banner_desc);
    toc("banner_desc", 10);
    /* the banner the other way: saved under, copied into the framebuffer,
       restored */
    gfx_init(&save, save_bits, W, BANNER_H, PITCH, scr.fmt);
    tic();
    gfx_blit(&save, 0, 0, &scr, 0, BANNER_Y, W, BANNER_H, ROP_COPY);
    gfx_blit(&scr, 0, BANNER_Y, &ban, 0, 0, W, BANNER_H, ROP_COPY);
    gfx_blit(&scr, 0, BANNER_Y, &save, 0, 0, W, BANNER_H, ROP_COPY);
    toc("banner_saveunder", 1);
    tic();
    draw_banner(&ban, "GAME OVER", "SCORE 0");
    toc("banner_draw", 1);
    tic();
    for (k = 0; k < 10; k++)
        ripple(32, 72);
    toc("ripple", 10);
    show_screen();
}

int main(void)
{
    font_init();
    input_init();
    video_init(1, 0);
    palette();
    fb = vram_alloc(PITCH * 4 * H);
    banner = vram_alloc(PITCH * 4 * BANNER_H);
    pbanner = vram_alloc(PITCH * 4 * BANNER_H);
    bg_fb = vram_alloc(PITCH * 4 * H);
    fb_desc = video_desc(fb, 0);
    banner_desc = video_desc(banner, 0);
    pause_desc = video_desc(pbanner, 0);
    gfx_init(&scr, fb, W, H, PITCH, gfx_screen_format());
    gfx_init(&ban, banner, W, BANNER_H, PITCH, scr.fmt);
    gfx_init(&pban, pbanner, W, BANNER_H, PITCH, scr.fmt);
    gfx_init(&bgs, bg_fb, W, H, PITCH, scr.fmt);
    make_food();
    draw_banner(&pban, "PAUSED", "P TO GO ON");
    title();
    play();
    game_over();
    measure();
    printf("@done\n");
    for (;;)
        video_wait();
    return 0;
}
