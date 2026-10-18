/* Shards: a vector game in the 1970s arcade manner, drawn with nothing
   but lines. A dart-shaped ship turns, thrusts and fires at jagged
   shards that drift, spin and split in two when hit; a hexagonal
   warden crosses now and then and fires back. Everything is redrawn
   every frame into the back buffer of two (TSEL flips between their
   descriptor tables at the frame's end), and the buffer coming round
   is erased first, in one of four ways (vec.h).

   The point is the cost of lines in RFC 0042's 1- and 2-bit modes and
   layouts: M6 (1024 x 768 x 1) and M5 (x 2), against M3, M4 and M0 at
   640 x 480. The run's variables (prog.toml's pokes, or --poke):

     mode    the video mode: 6, 5, 4, 3 or 0
     f1      1: F1's linear pixels (L0 only)
     erase   0 FILL, 1 redraw the lines cleared, 2 XOR, 3 the objects' boxes,
             4 the boxes widened to words and cleared by stores
     kernel  0 the library's gfx_line, 1 the C kernel, 2 the assembly one
             (-1: the best the variant has)
     rocks   shards at the start (the first wave)
     frames  how long the game runs
     bench   1: the line and fill benchmarks instead of the game; 3: the
             kernels' cost by direction
     hwship  1: the ship is the hardware cursor (C1), drawn once for each
             of 64 headings, so it costs nothing a frame
     autopilot  1: the ship flies itself and frames counts the game's
             frames, not the video's: the same game whatever the speed,
             for measuring

   No floating point: angles are 0-255, sines a table in 2.14 fixed
   point, positions 24.8 in a 1024 x 768 world that the 640 x 480 modes
   show at 5/8. */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "gfx.h"
#include "video.h"
#include "input.h"
#include "perf.h"
#include "vec.h"

int mode = 6;
int f1 = 0;
int erase = 4;
int kernel = -1;
int rocks = 6;
int frames = 1200;
int bench = 0;
int hwship = 0;
int seed = 12345;
int autopilot = 0;

/* ---- fixed point ---- */

static const short sintab[256] = {
    0, 402, 804, 1205, 1606, 2006, 2404, 2801, 3196, 3590, 3981, 4370, 4756, 5139, 5520, 5897,
    6270, 6639, 7005, 7366, 7723, 8076, 8423, 8765, 9102, 9434, 9760, 10080, 10394, 10702, 11003, 11297,
    11585, 11866, 12140, 12406, 12665, 12916, 13160, 13395, 13623, 13842, 14053, 14256, 14449, 14635, 14811, 14978,
    15137, 15286, 15426, 15557, 15679, 15791, 15893, 15986, 16069, 16143, 16207, 16261, 16305, 16340, 16364, 16379,
    16384, 16379, 16364, 16340, 16305, 16261, 16207, 16143, 16069, 15986, 15893, 15791, 15679, 15557, 15426, 15286,
    15137, 14978, 14811, 14635, 14449, 14256, 14053, 13842, 13623, 13395, 13160, 12916, 12665, 12406, 12140, 11866,
    11585, 11297, 11003, 10702, 10394, 10080, 9760, 9434, 9102, 8765, 8423, 8076, 7723, 7366, 7005, 6639,
    6270, 5897, 5520, 5139, 4756, 4370, 3981, 3590, 3196, 2801, 2404, 2006, 1606, 1205, 804, 402,
    0, -402, -804, -1205, -1606, -2006, -2404, -2801, -3196, -3590, -3981, -4370, -4756, -5139, -5520, -5897,
    -6270, -6639, -7005, -7366, -7723, -8076, -8423, -8765, -9102, -9434, -9760, -10080, -10394, -10702, -11003, -11297,
    -11585, -11866, -12140, -12406, -12665, -12916, -13160, -13395, -13623, -13842, -14053, -14256, -14449, -14635, -14811, -14978,
    -15137, -15286, -15426, -15557, -15679, -15791, -15893, -15986, -16069, -16143, -16207, -16261, -16305, -16340, -16364, -16379,
    -16384, -16379, -16364, -16340, -16305, -16261, -16207, -16143, -16069, -15986, -15893, -15791, -15679, -15557, -15426, -15286,
    -15137, -14978, -14811, -14635, -14449, -14256, -14053, -13842, -13623, -13395, -13160, -12916, -12665, -12406, -12140, -11866,
    -11585, -11297, -11003, -10702, -10394, -10080, -9760, -9434, -9102, -8765, -8423, -8076, -7723, -7366, -7005, -6639,
    -6270, -5897, -5520, -5139, -4756, -4370, -3981, -3590, -3196, -2801, -2404, -2006, -1606, -1205, -804, -402,
};

#define ISIN(a) sintab[(a) & 255]
#define ICOS(a) sintab[((a) + 64) & 255]

/* r * sin(a), rounded (a multiply: about 160 ticks) */
static int rsin(int r, int a)
{
    return (r * ISIN(a) + 8192) >> 14;
}

static int rcos(int r, int a)
{
    return (r * ICOS(a) + 8192) >> 14;
}

static unsigned rng;

static unsigned rnd(void)
{
    rng ^= rng << 13;
    rng ^= rng >> 17;
    rng ^= rng << 5;
    return rng;
}

/* 0 .. n-1 */
static int rndn(int n)
{
    return (rnd() >> 8) % n;
}

/* ---- the world and the screen ---- */

#define WW (1024 << 8)          /* the world, 24.8 */
#define WH (768 << 8)

static int xga;                 /* the screen is the world's size; else 5/8 of it */
static int sw, sh;              /* the screen */

/* world lengths (pixels of the 1024 x 768 world) to the screen's */
static int scale(int v)
{
    return xga ? v : (v * 5) >> 3;
}

static int scr_x(int wx)
{
    return xga ? wx >> 8 : (wx * 5) >> 11;
}

static int scr_y(int wy)
{
    return xga ? wy >> 8 : (wy * 5) >> 11;
}

static int wrap(int v, int m)
{
    if (v < 0)
        v += m;
    else if (v >= m)
        v -= m;
    return v;
}

/* ---- shapes ---- */

/* shards: four outlines of 11 points, (radius in 16ths, angle) */
#define RP 11
static const unsigned char rock_tpl[4][RP][2] = {
    {{16, 0}, {13, 22}, {15, 45}, {11, 70}, {16, 93}, {14, 116}, {16, 140}, {12, 163}, {15, 186}, {13, 210}, {16, 233}},
    {{15, 0}, {16, 25}, {12, 46}, {15, 70}, {10, 92}, {15, 116}, {16, 140}, {13, 162}, {16, 186}, {11, 208}, {14, 232}},
    {{16, 5}, {11, 28}, {14, 50}, {16, 73}, {13, 95}, {16, 118}, {12, 140}, {15, 163}, {16, 186}, {12, 210}, {15, 232}},
    {{13, 0}, {16, 23}, {14, 47}, {16, 70}, {12, 94}, {16, 117}, {14, 140}, {10, 163}, {16, 186}, {14, 209}, {16, 232}},
};
static const int rock_r[3] = {46, 24, 12};       /* the three sizes' radii, world pixels */
static const int rock_score[3] = {20, 50, 100};
#define SPIN_STEPS 64
/* every outline at every size and 64 turns, in screen pixels: worked out
   once, so a frame has no multiplies for the shards */
static short rock_pts[4][3][SPIN_STEPS][RP * 2];

/* the ship: a dart with a forked tail, (radius, angle) from its centre,
   angle 0 the nose */
static const unsigned char ship_tpl[6][2] = {
    {18, 0}, {14, 102}, {8, 116}, {5, 128}, {8, 140}, {14, 154},
};
static const unsigned char flame_tpl[3][2] = {{7, 118}, {16, 128}, {7, 138}};

/* the warden: a hexagonal lantern, its centre at (0, 0), world pixels */
static const short warden_body[6][2] = {{-16, 0}, {-8, -9}, {8, -9}, {16, 0}, {8, 9}, {-8, 9}};
static const short warden_cap[4][2] = {{-5, -9}, {-3, -14}, {3, -14}, {5, -9}};
static short wbody[12], wcap[8];

/* digits and a few letters as strokes on a 4 x 6 grid, (x0 y0 x1 y1)
   nibbles: a 7-segment font with diagonals for the letters */
static const unsigned short seg7[7] = {
    0x0040, 0x4043, 0x4346, 0x0646, 0x0306, 0x0003, 0x0343,     /* a b c d e f g */
};
static const unsigned char digit_segs[10] = {
    0x3F, 0x06, 0x5B, 0x4F, 0x66, 0x6D, 0x7D, 0x07, 0x7F, 0x6F,
};
typedef struct {
    char ch;
    unsigned char n;
    unsigned short s[6];
} Glyph5;
static const Glyph5 letters[] = {
    {'A', 5, {0x0610, 0x1030, 0x3046, 0x0343, 0x0000}},
    {'E', 4, {0x0040, 0x0006, 0x0646, 0x0333}},
    {'G', 5, {0x4000, 0x0006, 0x0646, 0x4643, 0x4323}},
    {'M', 4, {0x0600, 0x0023, 0x2340, 0x4046}},
    {'O', 4, {0x0040, 0x4046, 0x4606, 0x0600}},
    {'V', 2, {0x0026, 0x2640}},
    {'R', 5, {0x0600, 0x0030, 0x3043, 0x4303, 0x0346}},
    {'W', 4, {0x0016, 0x1623, 0x2336, 0x3640}},
    {'S', 5, {0x4000, 0x0003, 0x0343, 0x4346, 0x4606}},
    {'H', 3, {0x0006, 0x4046, 0x0343}},
    {'D', 4, {0x0006, 0x0030, 0x3046, 0x4606}},
    {0, 0, {0}},
};

/* ---- the game's things ---- */

#define MAXROCKS 96
#define MAXSHOTS 8
#define MAXBITS 160

/* The shards and the debris are kept packed, rk[0..nrocks-1] and
   bits[0..nbits-1] (a dead one is replaced by the last), and walked with
   pointers: indexing an array of structs in a loop costs a multiply
   (MULS, ~160 ticks) per step when the struct isn't a power of two. */
typedef struct {
    int x, y, vx, vy;           /* 24.8 world */
    int size, shape, ang, spin; /* ang: 1024 a turn */
} Rock;

/* shots and explosion debris: short streaks behind them, (dx, dy) in
   screen pixels, worked out as they're made */
typedef struct {
    int x, y, vx, vy, life, dx, dy, pad;
} Shot;

typedef Shot Bit;

static Rock rk[MAXROCKS];
static Shot shots[MAXSHOTS], wshots[4];
static Bit bits[MAXBITS];
static int nrocks, nbits;

static struct {
    int x, y, vx, vy, head;     /* head: 0-255, 0 to the right, 192 up */
    int alive, respawn, safe;   /* frames until it's back; frames it can't be hit */
    int thrust, cool;
} ship;

static struct {
    int x, y, vx, phase, alive, cool, next;
} warden;

static int score, lives, wave, gameover, gametime;
static unsigned frame_work;     /* the last frame's work, ticks: the meter */

static int col_rock, col_ship, col_shot, col_warden, col_hud, col_bits;

/* ---- drawing ---- */

/* an object of radius r (screen pixels) at screen (sx, sy): drawn once,
   and again on the far side where it hangs off an edge (the guard band
   catches what's off the picture). Its centre is on the picture, so a
   copy reaches up to 2r past the edge: the guard band is twice the
   biggest radius (a big shard's 46, 48 with the rounding). */
#define GUARD 96
static int n_off, off_x[4], off_y[4];

static void wrapped(int sx, int sy, int r)
{
    int ox[2], oy[2], nx = 1, ny = 1, i, j;
    ox[0] = sx;
    oy[0] = sy;
    if (sx < r)
        ox[nx++] = sx + sw;
    else if (sx > sw - r)
        ox[nx++] = sx - sw;
    if (sy < r)
        oy[ny++] = sy + sh;
    else if (sy > sh - r)
        oy[ny++] = sy - sh;
    n_off = 0;
    for (i = 0; i < nx; i++)
        for (j = 0; j < ny; j++) {
            off_x[n_off] = ox[i];
            off_y[n_off] = oy[j];
            n_off++;
        }
}

static void draw_rock(const Rock *r)
{
    const short *pts = rock_pts[r->shape][r->size][(r->ang >> 4) & (SPIN_STEPS - 1)];
    int k;
    int rr = scale(rock_r[r->size]) + 1;
    wrapped(scr_x(r->x), scr_y(r->y), rr + 1);
    for (k = 0; k < n_off; k++) {
        vec_spoly(pts, RP, off_x[k], off_y[k], 1);
        vec_box(off_x[k] - rr, off_y[k] - rr, off_x[k] + rr, off_y[k] + rr);
    }
}

static short ship_pts[12], flame_pts[6];

static void ship_shape(void)
{
    int i, r;
    for (i = 0; i < 6; i++) {
        r = scale(ship_tpl[i][0]);
        ship_pts[2 * i] = rcos(r, ship.head + ship_tpl[i][1]);
        ship_pts[2 * i + 1] = rsin(r, ship.head + ship_tpl[i][1]);
    }
    for (i = 0; i < 3; i++) {
        r = scale(flame_tpl[i][0] + (i == 1 ? (gametime & 3) * 2 : 0));
        flame_pts[2 * i] = rcos(r, ship.head + flame_tpl[i][1]);
        flame_pts[2 * i + 1] = rsin(r, ship.head + flame_tpl[i][1]);
    }
}

static void draw_ship(void)
{
    int k;
    if (!ship.alive || (ship.safe && (gametime & 8)) || hwship)
        return;
    ship_shape();
    vec_colour(col_ship);
    wrapped(scr_x(ship.x), scr_y(ship.y), scale(20));
    for (k = 0; k < n_off; k++) {
        int r = scale(20);
        vec_poly(ship_pts, 6, off_x[k], off_y[k], 1);
        if (ship.thrust)
            vec_poly(flame_pts, 3, off_x[k], off_y[k], 0);
        vec_box(off_x[k] - r, off_y[k] - r, off_x[k] + r, off_y[k] + r);
    }
}

static void draw_warden(void)
{
    int k;
    if (!warden.alive)
        return;
    vec_colour(col_warden);
    wrapped(scr_x(warden.x), scr_y(warden.y), scale(18));
    for (k = 0; k < n_off; k++) {
        int x = off_x[k], y = off_y[k];
        vec_spoly(wbody, 6, x, y, 1);
        vec_spoly(wcap, 4, x, y, 0);
        vec_line(x + wbody[0], y, x + wbody[6], y);
        vec_box(x - scale(17), y - scale(15), x + scale(17), y + scale(10));
    }
}

/* a short streak behind a shot or a bit of debris */
static void streak(const Shot *s)
{
    int x = scr_x(s->x), y = scr_y(s->y);
    vec_obj_begin();
    vec_line(x, y, x - s->dx, y - s->dy);
    vec_obj_end();
}

static void draw_shots(void)
{
    int i;
    vec_colour(col_shot);
    for (i = 0; i < MAXSHOTS; i++)
        if (shots[i].life)
            streak(&shots[i]);
    vec_colour(col_warden);
    for (i = 0; i < 4; i++)
        if (wshots[i].life)
            streak(&wshots[i]);
}

static void draw_bits(void)
{
    const Bit *b, *e = bits + nbits;
    vec_colour(col_bits);
    for (b = bits; b < e; b++)
        streak(b);
}

/* text: digits and the letters above, cells of 4 x 6 grid units of u
   pixels, at (x, y) its top left; the grid's multiples of u from a table
   (a multiply is ~160 ticks) */
static short gu[16];

static void stroke(int x, int y, unsigned s)
{
    vec_line(x + gu[s >> 12], y + gu[s >> 8 & 15], x + gu[s >> 4 & 15], y + gu[s & 15]);
}

static int draw_text(int x, int y, int u, const char *str)
{
    int k;
    if (gu[1] != u)
        for (k = 0; k < 16; k++)
            gu[k] = k * u;
    vec_obj_begin();
    for (; *str; str++, x += 6 * u) {
        int c = *str, i;
        if (c >= '0' && c <= '9') {
            for (i = 0; i < 7; i++)
                if (digit_segs[c - '0'] >> i & 1)
                    stroke(x, y, seg7[i]);
        } else {
            const Glyph5 *g;
            for (g = letters; g->ch; g++)
                if (g->ch == c)
                    for (i = 0; i < g->n; i++)
                        stroke(x, y, g->s[i]);
        }
    }
    vec_obj_end();
    return x;
}

static void draw_hud(void)
{
    char buf[16];
    int i, u = xga ? 3 : 2, x;
    vec_colour(col_hud);
    sprintf(buf, "%d", score);
    x = draw_text(scale(24), scale(16), u, buf);
    sprintf(buf, "W%d", wave);
    draw_text(sw - scale(24) - 6 * u * (int)strlen(buf), scale(16), u, buf);
    /* the ships left, small */
    for (i = 0; i < lives; i++) {
        static const short mini[8] = {0, -7, 5, 6, 0, 3, -5, 6};
        static short m[8];
        int k, x = scale(30) + i * scale(16), y = scale(56);
        for (k = 0; k < 8; k++)
            m[k] = scale(mini[k]);
        vec_spoly(m, 4, x, y, 1);
        vec_box(x - 5, y - 7, x + 5, y + 6);
    }
    (void)x;
    if (gameover)
        draw_text(sw / 2 - 27 * u, sh / 2 - 3 * u, u, "GAME OVER");
    /* the meter: the last frame's work, a frame the long tick */
    {
        int y = sh - scale(12), full = scale(240), len = (int)(frame_work / (vid.frame_ticks / full));
        vec_obj_begin();
        vec_line(scale(24), y, scale(24) + full, y + 0);
        vec_line(scale(24) + full, y - 4, scale(24) + full, y + 4);
        vec_line(scale(24), y - 3, scale(24) + (len > 2 * full ? 2 * full : len), y - 3);
        vec_obj_end();
    }
}

/* ---- the game ---- */

static void add_rock(int x, int y, int size)
{
    int a, sp;
    Rock *r;
    if (nrocks == MAXROCKS)
        return;
    r = &rk[nrocks++];
    a = rndn(256);
    sp = (128 + rndn(192)) * (size + 2) / 2;    /* 24.8 per frame: the small ones faster */
    r->x = x;
    r->y = y;
    r->vx = rcos(sp, a);
    r->vy = rsin(sp, a);
    r->size = size;
    r->shape = rndn(4);
    r->ang = rndn(1024);
    r->spin = rndn(13) - 6;
}

static void new_wave(void)
{
    int i, n = rocks + wave;
    wave++;
    for (i = 0; i < n; i++) {
        /* from the edges, away from the ship */
        int x = rndn(WW), y = rndn(WH);
        if (i & 1)
            x = rndn(WW / 8);
        else
            y = rndn(WH / 8);
        add_rock(x, y, 0);
    }
}

static void boom(int x, int y, int n, int speed)
{
    for (; n > 0 && nbits < MAXBITS; n--) {
        Bit *b = &bits[nbits++];
        int a = rndn(256), sp = speed / 2 + rndn(speed), len = scale(2 + rndn(5));
        b->x = x;
        b->y = y;
        b->vx = rcos(sp, a);
        b->vy = rsin(sp, a);
        b->dx = rcos(len, a);
        b->dy = rsin(len, a);
        b->life = 20 + rndn(25);
    }
}

static void hit_rock(Rock *r)
{
    int x = r->x, y = r->y, size = r->size;
    score += rock_score[size];
    boom(x, y, 6 + 3 * (2 - size), 400);
    *r = rk[--nrocks];
    if (size < 2) {
        add_rock(x, y, size + 1);
        add_rock(x, y, size + 1);
    }
}

static void new_ship(void)
{
    ship.x = WW / 2;
    ship.y = WH / 2;
    ship.vx = ship.vy = 0;
    ship.head = 192;
    ship.alive = 1;
    ship.safe = 120;
}

static void new_game(void)
{
    memset(rk, 0, sizeof rk);
    memset(shots, 0, sizeof shots);
    memset(wshots, 0, sizeof wshots);
    nbits = 0;
    nrocks = 0;
    score = 0;
    lives = 3;
    wave = 0;
    gameover = 0;
    new_ship();
    warden.alive = 0;
    warden.next = 400;
    new_wave();
}

/* |a - b| in the world, the short way round */
static int wdist(int a, int b, int m)
{
    int d = a - b;
    if (d < 0)
        d = -d;
    if (d > m / 2)
        d = m - d;
    return d;
}

/* within r world pixels (r 24.8): the box first, the multiplies only
   inside it */
static int near(int x0, int y0, int x1, int y1, int r)
{
    int dx = wdist(x0, x1, WW), dy = wdist(y0, y1, WH);
    if (dx >= r || dy >= r)
        return 0;
    dx >>= 4;
    dy >>= 4;
    r >>= 4;
    return dx * dx + dy * dy < r * r;
}

/* the first shard within its radius (plus pad) of (x, y), or 0; the box
   test inline, as most are far */
static Rock *rock_at(int x, int y, int pad)
{
    Rock *r, *e = rk + nrocks;
    for (r = rk; r < e; r++) {
        int rr = (rock_r[r->size] + pad) << 8, d = r->x - x;
        if (d >= rr || d <= -rr) {
            /* far, unless it's near across the world's edge */
            if (d < WW - rr && d > rr - WW)
                continue;
        }
        if (near(x, y, r->x, r->y, rr))
            return r;
    }
    return 0;
}

static void move(int *x, int *y, int vx, int vy)
{
    *x = wrap(*x + vx, WW);
    *y = wrap(*y + vy, WH);
}

static void update(void)
{
    int i;
    gametime++;
    /* the ship */
    if (ship.alive) {
        int left, right, fire;
        if (autopilot) {
            /* turning, firing, now and then a burst of thrust */
            left = (gametime & 255) < 96;
            right = !left && (gametime & 255) >= 160;
            ship.thrust = (gametime & 127) < 20;
            fire = 1;
        } else {
            left = key_down(K_LEFT);
            right = key_down(K_RIGHT);
            ship.thrust = key_down(K_UP);
            fire = key_down(' ');
        }
        if (left)
            ship.head = (ship.head - 4) & 255;
        if (right)
            ship.head = (ship.head + 4) & 255;
        if (ship.thrust) {
            ship.vx += ICOS(ship.head) >> 9;
            ship.vy += ISIN(ship.head) >> 9;
        }
        ship.vx -= ship.vx >> 5;
        ship.vy -= ship.vy >> 5;
        move(&ship.x, &ship.y, ship.vx, ship.vy);
        if (ship.cool)
            ship.cool--;
        if (fire && !ship.cool) {
            for (i = 0; i < MAXSHOTS; i++)
                if (!shots[i].life) {
                    shots[i].x = ship.x + (ICOS(ship.head) * 18 >> 6);
                    shots[i].y = ship.y + (ISIN(ship.head) * 18 >> 6);
                    shots[i].vx = ship.vx + (ICOS(ship.head) >> 3);
                    shots[i].vy = ship.vy + (ISIN(ship.head) >> 3);
                    shots[i].dx = rcos(scale(4), ship.head);
                    shots[i].dy = rsin(scale(4), ship.head);
                    shots[i].life = 48;
                    break;
                }
            ship.cool = 7;
        }
        if (ship.safe)
            ship.safe--;
    } else if (!gameover && --ship.respawn <= 0) {
        new_ship();
    }
    if (gameover && --ship.respawn <= 0)
        new_game();
    /* the shards */
    {
        Rock *r, *e = rk + nrocks;
        for (r = rk; r < e; r++) {
            move(&r->x, &r->y, r->vx, r->vy);
            r->ang += r->spin;
        }
    }
    /* shots */
    for (i = 0; i < MAXSHOTS; i++)
        if (shots[i].life) {
            Shot *s = &shots[i];
            Rock *r;
            s->life--;
            move(&s->x, &s->y, s->vx, s->vy);
            if ((r = rock_at(s->x, s->y, 0)) != 0) {
                hit_rock(r);
                s->life = 0;
            }
            if (s->life && warden.alive && near(s->x, s->y, warden.x, warden.y, 16 << 8)) {
                warden.alive = 0;
                score += 500;
                boom(warden.x, warden.y, 16, 500);
                s->life = 0;
            }
        }
    for (i = 0; i < 4; i++)
        if (wshots[i].life) {
            wshots[i].life--;
            move(&wshots[i].x, &wshots[i].y, wshots[i].vx, wshots[i].vy);
            if (ship.alive && !ship.safe && near(wshots[i].x, wshots[i].y, ship.x, ship.y, 10 << 8)) {
                wshots[i].life = 0;
                ship.alive = 0;
            }
        }
    /* the ship against the shards */
    if (ship.alive && !ship.safe) {
        Rock *r = rock_at(ship.x, ship.y, 8);
        if (r) {
            hit_rock(r);
            ship.alive = 0;
        }
    }
    if (!ship.alive && ship.respawn <= 0 && !gameover) {
        boom(ship.x, ship.y, 24, 300);
        ship.respawn = 120;
        if (--lives <= 0) {
            gameover = 1;
            ship.respawn = 240;
        }
    }
    /* the warden: across the screen on a wave, firing at the ship */
    if (warden.alive) {
        warden.phase += 3;
        warden.x += warden.vx;
        warden.y = wrap(warden.y + (ISIN(warden.phase) >> 7), WH);
        if (warden.x < 0 || warden.x >= WW)
            warden.alive = 0;
        if (--warden.cool <= 0 && ship.alive) {
            /* at 3 pixels a frame toward the ship: dx and dy over a divisor
               that makes the longer of them 768 */
            int dx = ship.x - warden.x, dy = ship.y - warden.y, m, q;
            m = abs(dx) > abs(dy) ? abs(dx) : abs(dy);
            q = m / 768;
            if (q < 1)
                q = 1;
            for (i = 0; i < 4; i++)
                if (!wshots[i].life) {
                    wshots[i].x = warden.x;
                    wshots[i].y = warden.y;
                    wshots[i].vx = dx / q;
                    wshots[i].vy = dy / q;
                    wshots[i].dx = scale(wshots[i].vx >> 8);
                    wshots[i].dy = scale(wshots[i].vy >> 8);
                    wshots[i].life = 90;
                    break;
                }
            warden.cool = 50;
        }
    } else if (--warden.next <= 0) {
        warden.alive = 1;
        warden.vx = rnd() & 1 ? 384 : -384;
        warden.x = warden.vx > 0 ? 0 : WW - 1;
        warden.y = WH / 4 + rndn(WH / 2);
        warden.cool = 40;
        warden.next = 900;
    }
    {
        Bit *b;
        for (b = bits; b < bits + nbits;) {
            if (--b->life <= 0) {
                *b = bits[--nbits];
                continue;
            }
            move(&b->x, &b->y, b->vx, b->vy);
            b++;
        }
    }
    if (nrocks == 0)
        new_wave();
}

static void draw(void)
{
    const Rock *r, *e = rk + nrocks;
    vec_colour(col_rock);
    for (r = rk; r < e; r++)
        draw_rock(r);
    draw_ship();
    draw_warden();
    draw_shots();
    draw_bits();
    draw_hud();
}

/* ---- set up ---- */

static void shapes(void)
{
    int t, s, a, i, r;
    for (t = 0; t < 4; t++)
        for (s = 0; s < 3; s++)
            for (a = 0; a < SPIN_STEPS; a++)
                for (i = 0; i < RP; i++) {
                    r = scale(rock_r[s]) * rock_tpl[t][i][0] / 16;
                    rock_pts[t][s][a][2 * i] = rcos(r, rock_tpl[t][i][1] + a * (256 / SPIN_STEPS));
                    rock_pts[t][s][a][2 * i + 1] = rsin(r, rock_tpl[t][i][1] + a * (256 / SPIN_STEPS));
                }
    for (i = 0; i < 6; i++) {
        wbody[2 * i] = scale(warden_body[i][0]);
        wbody[2 * i + 1] = scale(warden_body[i][1]);
    }
    for (i = 0; i < 4; i++) {
        wcap[2 * i] = scale(warden_cap[i][0]);
        wcap[2 * i + 1] = scale(warden_cap[i][1]);
    }
}

/* the palette: in the 1- and 2-bit modes the picture's index is 16 x
   bank + pixel, so each row's descriptor picks its colours: the shards'
   colour shades from cyan at the top to violet at the bottom in 12 bands,
   and the top band (the score) is amber. The 4-bit mode (M0) uses bank 0. */
static void palette(void)
{
    int b, y, nb = 12;
    for (b = 0; b < 16; b++) {
        int k = b < nb ? b : nb - 1;
        video_pal_rgb(16 * b + 0, 0, 0, 0);
        if (vec.bpp == 1) {
            video_pal_rgb(16 * b + 1, 150 + 6 * k, 230 - 10 * k, 255);
        } else {
            video_pal_rgb(16 * b + 1, 90 + 10 * k, 200 - 9 * k, 255 - 3 * k);   /* shards */
            video_pal_rgb(16 * b + 2, 255, 255, 255);                          /* ship, shots */
            video_pal_rgb(16 * b + 3, 255, 150, 40);                           /* warden, debris */
        }
    }
    /* the score's band: amber, bank 13 */
    video_pal_rgb(16 * 13 + 1, 255, 190, 60);
    video_pal_rgb(16 * 13 + 2, 255, 190, 60);
    video_pal_rgb(16 * 13 + 3, 255, 190, 60);
    video_pal_rgb(16 * 13 + 0, 0, 0, 0);
    for (y = 0; y < sh; y++)
        vec_bank(y, y + 1, y < scale(72) ? 13 : (y * nb) / sh);
    if (vec.bpp == 1) {
        col_rock = col_ship = col_shot = col_warden = col_hud = col_bits = 1;
    } else {
        col_rock = 1;
        col_ship = col_shot = 2;
        col_warden = col_bits = 3;
        col_hud = 1;
    }
}

/* ---- the ship as the hardware cursor ----

   The cursor (C1) is 32 x 32 at 2 bits a pixel, its pixel p at bits 2p
   and 2p + 1 of a row's two words: the library's linear 2-bit format, a
   surface of pitch 2. Each of 64 headings is drawn into its own image
   once, with gfx_line; a frame only moves the cursor and points it at
   the heading's image. Its colours are palette entries 253-255. */
static unsigned *ship_imgs;

static void make_ship_images(void)
{
    int h, i;
    Surface s;
    ship_imgs = vram_alloc(64 * 64 * 4);
    memset(ship_imgs, 0, 64 * 64 * 4);
    for (h = 0; h < 64; h++) {
        gfx_init(&s, ship_imgs + 64 * h, 32, 32, 2, PF_LIN2);
        ship.head = h * 4;
        ship_shape();
        for (i = 0; i < 6; i++)
            gfx_line(&s, 16 + ship_pts[2 * i], 16 + ship_pts[2 * i + 1],
                     16 + ship_pts[(2 * i + 2) % 12], 16 + ship_pts[(2 * i + 3) % 12], 3, ROP_COPY);
    }
    video_pal_rgb(253, 255, 255, 255);
    video_pal_rgb(254, 255, 255, 255);
    video_pal_rgb(255, 255, 255, 255);
}

static void place_cursor(void)
{
    int x = scr_x(ship.x), y = scr_y(ship.y);
    if (!ship.alive || (ship.safe && (gametime & 8))) {
        video_cursor_at(-64, -64);
        return;
    }
    /* the cursor's position is in the timing family's pixels, which are
       the mode's here */
    VID_CURIMG = video_word(ship_imgs + 64 * (((ship.head + 2) >> 2) & 63));
    video_cursor_at(x - 16, y - 16);
}

/* ---- the benchmarks ---- */

/* nl lines len pixels long at random angles: each a kernel call, and as
   one polyline (a random walk) */
static void bench_lines(const char *fmtname, int len, int nl)
{
    static short ln[256][4], walk[2 * 257];
    int i, k, op, a, x, y;
    unsigned t;
    const char *kn[3] = {"lib", "c", "asm"};
    rng = 777;
    for (i = 0; i < nl; i++) {
        a = rndn(256);
        x = 80 + rndn(sw - 160);
        y = 80 + rndn(sh - 160);
        ln[i][0] = x;
        ln[i][1] = y;
        ln[i][2] = x + rcos(len, a);
        ln[i][3] = y + rsin(len, a);
    }
    x = sw / 2;
    y = sh / 2;
    walk[0] = x;
    walk[1] = y;
    for (i = 1; i <= nl; i++) {
        int nx, ny;
        do {
            a = rndn(256);
            nx = x + rcos(len, a);
            ny = y + rsin(len, a);
        } while (nx < 40 || nx >= sw - 40 || ny < 40 || ny >= sh - 40);
        walk[2 * i] = x = nx;
        walk[2 * i + 1] = y = ny;
    }
    for (k = 0; k < VK_N; k++) {
#ifndef GFX_ASM
        if (k == VK_ASM)
            continue;
#endif
        vec.kernel = k;
        for (op = 0; op < 3; op++) {
            char name[48];
            if (op == VOP_XOR)
                continue;
            vec_op(op);
            vec_colour((1 << vec.bpp) - 1);
            t = video_ticks();
            for (i = 0; i < nl; i++)
                vec_kernel_line(ln[i][0], ln[i][1], ln[i][2], ln[i][3]);
            t = video_ticks() - t;
            sprintf(name, "b_%s_L%d_%s_%s", fmtname, len, kn[k], op == VOP_OR ? "or" : "clr");
            printf("@perf %s %u\n", name, t / nl);
            printf("  %-28s %6u ticks a line, %4u lines a frame\n", name, t / nl,
                   vid.frame_ticks / (t / nl));
            if (op != VOP_OR)
                continue;
            t = video_ticks();
            vec_kernel_poly(walk, nl + 1, 0, 0, 0);
            t = video_ticks() - t;
            sprintf(name, "b_%s_P%d_%s", fmtname, len, kn[k]);
            printf("@perf %s %u\n", name, t / nl);
            printf("  %-28s %6u ticks a line, %4u lines a frame (a polyline)\n", name, t / nl,
                   vid.frame_ticks / (t / nl));
        }
    }
    vec_op(VOP_OR);
}

/* the kernels against the library: the same pixels, and XOR's half-open
   polylines cancel exactly */
static void bench_check(const char *fmtname)
{
    int i, k, bad = 0, n = vec.pitch * (vec.h + 2 * vec.gy);
    unsigned *a = vec.rows[0][-vec.gy], *b = vec.rows[1][-vec.gy];
    rng = 99;
    for (k = VK_C; k < VK_N; k++) {
#ifndef GFX_ASM
        if (k == VK_ASM)
            continue;
#endif
        memset(a, 0, n * 4);
        memset(b, 0, n * 4);
        /* lines anywhere in the guard band, any direction */
        rng = 99;
        for (i = 0; i < 300; i++) {
            int x0 = rndn(sw + 60) - 30, y0 = rndn(sh + 60) - 30;
            int x1 = x0 + rndn(61) - 30, y1 = y0 + rndn(61) - 30;
            int c = 1 + rndn((1 << vec.bpp) - 1);
            vec_colour(c);
            vec_select(0);
            vec.kernel = VK_LIB;
            vec_kernel_line(x0, y0, x1, y1);
            vec_select(1);
            vec.kernel = k;
            vec_kernel_line(x0, y0, x1, y1);
        }
        for (i = 0; i < n; i++)
            if (a[i] != b[i])
                bad++;
        /* clearing them again leaves nothing */
        rng = 99;
        vec_op(VOP_CLR);
        for (i = 0; i < 300; i++) {
            int x0 = rndn(sw + 60) - 30, y0 = rndn(sh + 60) - 30;
            int x1 = x0 + rndn(61) - 30, y1 = y0 + rndn(61) - 30;
            rndn(3);
            vec_kernel_line(x0, y0, x1, y1);
        }
        vec_op(VOP_OR);
        for (i = 0; i < n; i++)
            if (b[i])
                bad++;
        /* closed polylines (shards, apart), half-open, with XOR: each
           point once, so they match the OR drawing */
        memset(a, 0, n * 4);
        memset(b, 0, n * 4);
        vec_half(1);
        for (i = 0; i < 40; i++) {
            const short *p = rock_pts[i & 3][i % 3][(i * 7) & 63];
            int x = scale(60) + (i % 8) * scale(120), y = scale(60) + (i / 8) * scale(120);
            vec_select(0);
            vec_op(VOP_OR);
            vec_poly(p, RP, x, y, 1);
            vec_select(1);
            vec_op(VOP_XOR);
            vec_poly(p, RP, x, y, 1);
        }
        vec_half(0);
        vec_op(VOP_OR);
        vec.recp = vec.recb = 0;
        for (i = 0; i < n; i++)
            if (a[i] != b[i])
                bad++;
        printf("@perf check_%s_%s %d\n", fmtname, k == VK_C ? "c" : "asm", bad);
        printf("  check %s %s: %d words differ\n", fmtname, k == VK_C ? "c" : "asm", bad);
    }
    vec_select(0);
}

/* shards as the game draws them: 60 big ones' polylines through vec_poly
   and vec_line, against the same lines straight into the kernel */
static void bench_poly(const char *fmtname)
{
    unsigned t, tk;
    int i, k, e;
    char name[48];
    static const char *en[ER_N] = {"fill", "redraw", "xor", "box", "wbox"};
    vec.kernel = VK_C;
#ifdef GFX_ASM
    vec.kernel = VK_ASM;
#endif
    for (e = 0; e < ER_N; e++) {
        if (e == ER_XOR || e == ER_WBOX)
            continue;
        vec.recp = e == ER_REDRAW;
        vec.recb = e == ER_BOX;
        vec.npolys[0] = vec.npool[0] = vec.nboxes[0] = 0;
        t = video_ticks();
        for (i = 0; i < 60; i++) {
            int x = 80 + (i % 10) * scale(96), y = 80 + (i / 10) * scale(96);
            vec_spoly(rock_pts[i & 3][0][i & 63], RP, x, y, 1);
            vec_box(x - 47, y - 47, x + 47, y + 47);
        }
        t = video_ticks() - t;
        sprintf(name, "b_%s_poly_%s", fmtname, en[e]);
        printf("@perf %s %u\n", name, t / 60);
        printf("  %-28s %6u ticks a big shard (11 lines)\n", name, t / 60);
    }
    vec.recp = vec.recb = 0;
    tk = video_ticks();
    for (i = 0; i < 60; i++) {
        const short *p = rock_pts[i & 3][0][i & 63];
        int ox = 80 + (i % 10) * scale(96), oy = 80 + (i / 10) * scale(96);
        for (k = 0; k < RP; k++) {
            int k1 = k + 1 == RP ? 0 : k + 1;
            vec_kernel_line(p[2 * k] + ox, p[2 * k + 1] + oy, p[2 * k1] + ox, p[2 * k1 + 1] + oy);
        }
    }
    tk = video_ticks() - tk;
    sprintf(name, "b_%s_poly_bylines", fmtname);
    printf("@perf %s %u\n", name, tk / 60);
    printf("  %-28s %6u ticks a big shard, a kernel call a line\n", name, tk / 60);
}

static void bench_clear(const char *fmtname)
{
    unsigned t;
    int i, sz;
    char name[48];
    Surface *s = &vec.s[0];
    /* the picture's rows, a fill each */
    t = video_ticks();
    gfx_fill(s, vec.gx, vec.gy, vec.gx + vec.w, vec.gy + vec.h, 0, ROP_COPY);
    t = video_ticks() - t;
    sprintf(name, "b_%s_fillrows", fmtname);
    printf("@perf %s %u\n", name, t);
    printf("  %-28s %7u ticks, %3u%% of a frame\n", name, t, 100 * t / vid.frame_ticks);
    /* the rows and the guard words between them as one fill (ER_FILL) */
    t = video_ticks();
    gfx_fill(&vec.flat[0], 0, 0, vec.flat[0].w, 1, 0, ROP_COPY);
    t = video_ticks() - t;
    sprintf(name, "b_%s_fill", fmtname);
    printf("@perf %s %u\n", name, t);
    printf("  %-28s %7u ticks, %3u%% of a frame (%d words)\n", name, t, 100 * t / vid.frame_ticks,
           vec.flat[0].pitch);
    /* 40 boxes the size of a big shard's, of a small one's: the library's
       fill, and widened to words and cleared by stores */
    for (sz = 0; sz < 2; sz++) {
        int d = scale(sz ? 26 : 94);
        Rect r;
        t = video_ticks();
        for (i = 0; i < 40; i++)
            gfx_fill(s, 100 + i * 7, 100 + i * 3, 100 + i * 7 + d, 100 + i * 3 + d, 0, ROP_COPY);
        t = video_ticks() - t;
        sprintf(name, "b_%s_box%d", fmtname, sz ? 26 : 94);
        printf("@perf %s %u\n", name, t / 40);
        printf("  %-28s %7u ticks a box\n", name, t / 40);
        t = video_ticks();
        for (i = 0; i < 40; i++) {
            r.x0 = 100 + i * 7;
            r.y0 = 100 + i * 3;
            r.x1 = r.x0 + d;
            r.y1 = r.y0 + d;
            vec_clear_wbox(0, &r);
        }
        t = video_ticks() - t;
        sprintf(name, "b_%s_wbox%d", fmtname, sz ? 26 : 94);
        printf("@perf %s %u\n", name, t / 40);
        printf("  %-28s %7u ticks a box\n", name, t / 40);
    }
}

static void run_bench(void)
{
    static const signed char modes[] = {6, 5, 4, 3, 0};
    int mi, f, m;
    char fmtname[16];
    static const char *pf[PF_N] = {"lin1", "lin2", "lin4", "lin8", "chk1", "chk2", "pl2", "pl4",
                                   "pl8"};
    for (mi = 0; mi < 5; mi++)
        for (f = 0; f < 2; f++) {
            m = modes[mi];
            if (f && (board_layout || m == 0))
                continue;           /* F1 is L0's, and only for 1 and 2 bits */
            vec_init(m, f ? VC_F1 : 0, ER_FILL, VK_C, GUARD);
            xga = vec.w == 1024;
            sw = vec.w;
            sh = vec.h;
            shapes();
            sprintf(fmtname, "m%d%s", m, pf[vec.fmt]);
            printf("%s: M%d, %s\n", fmtname, m, pf[vec.fmt]);
            bench_check(fmtname);
            bench_poly(fmtname);
            if (m >= 5 || m == 3) {
                bench_lines(fmtname, xga ? 32 : 20, 200);
                if (m >= 5) {
                    bench_lines(fmtname, 8, 200);
                    bench_lines(fmtname, 96, 100);
                }
            }
            bench_clear(fmtname);
        }
}

/* ---- the frame loop ---- */

typedef struct {
    unsigned sum, max;
} Span;

static void span(Span *s, unsigned t)
{
    s->sum += t;
    if (t > s->max)
        s->max = t;
}

static const char *erase_names[ER_N] = {"fill", "redraw", "xor", "boxes", "word boxes"};
static const char *kernel_names[VK_N] = {"lib", "c", "asm"};

int main(void)
{
    Span s_erase = {0, 0}, s_update = {0, 0}, s_draw = {0, 0}, s_work = {0, 0}, s_lines = {0, 0};
    int f, missed = 0, n = 0, k;
    unsigned t0, t1, t2, t3;
    input_init();
    rng = seed;
    if (bench == 3) {
        /* the kernels by direction: 100 lines of 64 and of 1 pixel each way */
        static const signed char dirs[][2] = {{64, 0}, {64, 16}, {64, 32}, {64, 64}, {32, 64}, {16, 64},
                                              {0, 64}, {-16, 64}, {-64, 64}, {0, 0}};
        int d, i, k;
        vec_init(mode, 0, ER_FILL, VK_C, GUARD);
        for (k = VK_C; k < VK_N; k++) {
#ifndef GFX_ASM
            if (k == VK_ASM)
                continue;
#endif
            vec.kernel = k;
            for (d = 0; d < 10; d++) {
                unsigned t = video_ticks();
                for (i = 0; i < 100; i++)
                    vec_kernel_line(100 + i, 100 + i, 100 + i + dirs[d][0], 100 + i + dirs[d][1]);
                t = video_ticks() - t;
                printf("  %s (%d, %d): %u ticks a line\n", kernel_names[k], dirs[d][0], dirs[d][1],
                       t / 100);
            }
        }
        printf("@done\n");
        return 0;
    }
    if (bench) {
        run_bench();
        printf("@done\n");
        return 0;
    }
    k = kernel;
    if (k < 0) {
#ifdef GFX_ASM
        k = VK_ASM;
#else
        k = VK_C;
#endif
    }
#ifndef GFX_ASM
    if (k == VK_ASM)
        k = VK_C;
#endif
    vec_init(mode, f1 && mode != 0 ? VC_F1 : 0, erase, k, GUARD);
    xga = vec.w == 1024;
    sw = vec.w;
    sh = vec.h;
    palette();
    shapes();
    if (hwship) {
        make_ship_images();
        video_cursor(ship_imgs);
    }
    vec_half(erase == ER_XOR);
    printf("Shards: M%d %dx%dx%d, %s, erase %s, kernel %s\n", mode, vec.w, vec.h, vec.bpp,
           vec.fmt == PF_CHK1 || vec.fmt == PF_CHK2 ? "L0 chunky" :
           vec.fmt == PF_PL2 ? "L1 planes" : "linear", erase_names[erase], kernel_names[k]);
    new_game();
    vec_show();
    /* f counts the video's frames, so the script's keys come when they
       would for a player, however slow the game */
    for (f = 0; f < frames; f += autopilot ? 1 : k) {
        t0 = video_ticks();
        vec_frame();
        t1 = video_ticks();
        update();
        t2 = video_ticks();
        draw();
        t3 = video_ticks();
        if (hwship)
            place_cursor();
        /* the first frames fill the records: measured from the second second */
        if (f >= 60) {
            span(&s_erase, t1 - t0);
            span(&s_update, t2 - t1);
            span(&s_draw, t3 - t2);
            span(&s_work, t3 - t0);
            span(&s_lines, vec.drawn);
            n++;
        }
        frame_work = t3 - t0;
        k = vec_show();
        if (f >= 60)
            missed += k - 1;
    }
    printf("%d frames drawn, %d missed: %d.%d frames a second\n", n, missed,
           60 * n / (n + missed), (600 * n / (n + missed)) % 10);
    printf("  a frame: erase %u, update %u, draw %u, all %u ticks (%u%% of a frame), max %u\n",
           s_erase.sum / n, s_update.sum / n, s_draw.sum / n, s_work.sum / n,
           100 * (s_work.sum / n) / vid.frame_ticks, s_work.max);
    printf("  lines drawn a frame: %u on average, %u at most\n", s_lines.sum / n, s_lines.max);
    printf("@perf rk_erase %u %u\n", s_erase.sum / n, s_erase.max);
    printf("@perf rk_update %u %u\n", s_update.sum / n, s_update.max);
    printf("@perf rk_draw %u %u\n", s_draw.sum / n, s_draw.max);
    printf("@perf rk_work %u %u\n", s_work.sum / n, s_work.max);
    printf("@perf rk_lines_avg %u\n", s_lines.sum / n);
    printf("@perf rk_missed %d\n", missed);
    printf("@done\n");
    return 0;
}
