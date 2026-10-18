/* Fennec Run: a fennec fox runs, jumps, collects coins and stomps beetles
   through a scrolling level, on M1 at 320 x 240 x 8 (game.h has the
   screen's bands, scroll.c the scrolling strategies, NOTES.md what was
   found).

   Each frame: the game's logic for every 60 Hz tick since the last frame
   (so the game runs at the same speed whatever the drawing costs), then
   the next frame is built into the descriptor table that isn't shown:
   the playfield and the bands' lines (scroll.c), the sprites, the HUD,
   the descriptors; the frame's interrupt switches tables (TSEL) when it's
   done. A sprite is drawn into lines the frame owns: a back buffer's, or
   a spare line the shown line is copied into first, since the rings and
   the bands are shared by every frame.

   Run options (--poke NAME=V): strategy (0 coarse, 1 preshift, 2 blit, 3
   redraw), cursor_bird (1: the bird is the hardware cursor, C1), bench
   (1: measure the kernels and stop), trace (N: the fox's position every N
   ticks). */

#include <stdio.h>
#include <string.h>
#include "gfx.h"
#include "video.h"
#include "input.h"
#include "perf.h"
#include "game.h"

int bench = 0;
int cursor_bird = 0;
int race = 0;
int trace = 0;
int start_frame = 100;          /* the game's first tick: init is done by then */
int end_tick = 1460;            /* and its last */

#if defined(GFX_BLK)
#define VARIANT "BLK"
#elif defined(GFX_ASM)
#define VARIANT "ASM"
#else
#define VARIANT "C"
#endif

/* ---- timing: each part's ticks over the frames built ---- */

unsigned ptime[P_N];
static unsigned plast, pframe[P_N], pmax[P_N];
static const char *const pnames[P_N] = {"logic", "seam", "playfield", "desc", "lines",
                                        "sprites", "hud"};

void pmark(int part)
{
    unsigned t = video_ticks();
    ptime[part] += t - plast;
    pframe[part] += t - plast;
    plast = t;
}

/* each part's worst frame */
static void pframe_end(void)
{
    int k;
    for (k = 0; k < P_N; k++) {
        if (pframe[k] > pmax[k])
            pmax[k] = pframe[k];
        pframe[k] = 0;
    }
}

/* ---- the game ---- */

#define FX 8                    /* fixed point: 8 fraction bits */
#define ACC 0x14                /* running: per tick per tick */
#define FRICTION 0x20
#define MAXV 0x1C0              /* 1.75 pixels a tick */
#define JUMP 0x3A0
#define GRAV 0x30               /* half that going up with the key held */
#define MAXFALL 0x500
#define K_L 1
#define K_R 2
#define K_J 4

typedef struct {
    int x, y, vx, vy;           /* the sprite's top left in the playfield, fixed point */
    int ground, face, inv, anim;
} Fox;

typedef struct {
    int x, y, dir, state, timer;    /* state: 0 not yet, 1 walking, 2 flat, 3 gone */
} Bug;

typedef struct {
    int x, y, t;                /* a coin rising from a star block */
} Pop;

static Fox fox;
static Bug bugs[24];
static Pop pops[4];
static int bird_x, bird_y, cam, score, coins, lives, tick, safe_x, nbugs;
static const signed char wave[32] = {0, 2, 3, 5, 6, 7, 7, 8, 8, 8, 7, 7, 6, 5, 3, 2,
                                     0, -2, -3, -5, -6, -7, -7, -8, -8, -8, -7, -7, -6, -5, -3, -2};

/* the tile at level pixel (x, y), y from the playfield's top; walls at the
   level's ends, air above it and in the pits below it */
static int tile_at(int x, int y)
{
    if (x < 0 || x >= LEVEL_W * TS)
        return T_STONE;
    if (y < 0 || y >= ROWS * TS)
        return T_EMPTY;
    return level[y >> 4][x >> 4];
}

static int solid(int x, int y)
{
    return tile_solid(tile_at(x, y));
}

/* with trace on, what happens as it happens */
static void event(const char *what)
{
    if (trace)
        printf("t %d %s at %d %d\n", tick, what, fox.x >> FX, fox.y >> FX);
}

/* a tile changed: its buffers redrawn now, or with race on, when the
   sprites drawn into them are off again (race_stage) */
static unsigned char tq[16][2];
static int ntq, race_on;

static void tile_changed(int r, int c)
{
    if (race_on && ntq < 16) {
        tq[ntq][0] = r;
        tq[ntq][1] = c;
        ntq++;
    } else {
        scroll_tile(r, c);
    }
}

static void take(int c, int r)
{
    level[r][c] = T_EMPTY;
    tile_changed(r, c);
    coins++;
    score += 10;
    event("coin");
}

static void bump(int c, int r)
{
    int k;
    event("bump");
    level[r][c] = T_USED;
    tile_changed(r, c);
    coins++;
    score += 50;
    for (k = 0; k < 4; k++)
        if (!pops[k].t) {
            pops[k].x = c * TS;
            pops[k].y = r * TS - TS;
            pops[k].t = 24;
            break;
        }
}

static void hurt(void)
{
    if (fox.inv)
        return;
    event("hurt");
    fox.inv = 90;
    fox.vy = -0x280;
    if (lives > 0)
        lives--;
}

static void fox_tick(int keys, int prev)
{
    int l, r, t, b, m, ob, tl, tr, k;
    /* running, and slowing down without a key */
    if (keys & K_R) {
        fox.vx += ACC;
        if (fox.vx > MAXV)
            fox.vx = MAXV;
        fox.face = 0;
    } else if (keys & K_L) {
        fox.vx -= ACC;
        if (fox.vx < -MAXV)
            fox.vx = -MAXV;
        fox.face = 1;
    } else if (fox.vx > 0) {
        fox.vx = fox.vx > FRICTION ? fox.vx - FRICTION : 0;
    } else if (fox.vx < 0) {
        fox.vx = fox.vx < -FRICTION ? fox.vx + FRICTION : 0;
    }
    /* a jump as the key goes down on the ground; held, it goes higher */
    if ((keys & K_J) && !(prev & K_J) && fox.ground)
        fox.vy = -JUMP;
    fox.vy += (keys & K_J) && fox.vy < 0 ? GRAV / 2 : GRAV;
    if (fox.vy > MAXFALL)
        fox.vy = MAXFALL;

    /* across: the box's side against the tiles at its top, middle, bottom */
    fox.x += fox.vx;
    l = (fox.x >> FX) + 3;
    r = (fox.x >> FX) + 12;
    t = (fox.y >> FX) + 2;
    b = (fox.y >> FX) + 22;
    m = (t + b) >> 1;
    if (fox.vx > 0 && (solid(r, t) || solid(r, m) || solid(r, b))) {
        fox.x = ((r & ~15) - 13) << FX;
        fox.vx = 0;
    } else if (fox.vx < 0 && (solid(l, t) || solid(l, m) || solid(l, b))) {
        fox.x = ((l | 15) + 1 - 3) << FX;
        fox.vx = 0;
    }
    l = (fox.x >> FX) + 3;
    r = (fox.x >> FX) + 12;

    /* down or up: landing on a tile's top (a plank's only from above), or
       a head against a ceiling, which knocks a star block's coin out */
    ob = (fox.y >> FX) + 22;
    fox.y += fox.vy;
    t = (fox.y >> FX) + 2;
    b = (fox.y >> FX) + 22;
    fox.ground = 0;
    if (fox.vy >= 0) {
        /* the pixel under the feet: standing still is landing every tick */
        b++;
        tl = tile_at(l, b);
        tr = tile_at(r, b);
        if (tile_solid(tl) || tile_solid(tr) ||
            ((tile_top(tl) || tile_top(tr)) && ob < (b & ~15))) {
            fox.y = ((b & ~15) - 23) << FX;
            fox.vy = 0;
            fox.ground = 1;
            if (tl == T_SPIKES || tr == T_SPIKES)
                hurt();
            else if (tile_solid(tl) && tile_solid(tr))
                safe_x = fox.x;
        }
    } else if (fox.vy < 0) {
        tl = tile_at(l, t);
        tr = tile_at(r, t);
        if (tile_solid(tl) || tile_solid(tr)) {
            int c = tile_at((l + r) >> 1, t) == T_BLOCK ? (l + r) >> 1 : tl == T_BLOCK ? l : r;
            fox.y = ((t | 15) + 1 - 2) << FX;
            fox.vy = 0;
            if (tile_at(c, t) == T_BLOCK)
                bump(c >> 4, t >> 4);
        }
    }

    /* coins under the box's corners and middle */
    t = (fox.y >> FX) + 2;
    b = (fox.y >> FX) + 22;
    m = (t + b) >> 1;
    for (k = 0; k < 6; k++) {
        int x = k & 1 ? r : l, y = k < 2 ? t : k < 4 ? m : b;
        if (tile_at(x, y) == T_COIN)
            take(x >> 4, y >> 4);
    }

    /* into a pit: back to the last safe ground */
    if ((fox.y >> FX) > PF_H + 48) {
        event("pit");
        fox.x = safe_x;
        fox.y = -32 << FX;
        fox.vx = fox.vy = 0;
        if (lives > 0)
            lives--;
    }
    if (fox.inv)
        fox.inv--;
    fox.anim += fox.vx < 0 ? -fox.vx : fox.vx;
}

static void bug_tick(Bug *g)
{
    int nx, front, y;
    if (g->state == 2) {
        if (--g->timer == 0)
            g->state = 3;
        return;
    }
    if (g->state != 1)
        return;
    /* walking; turning at a wall or the ground's edge */
    nx = g->x + g->dir * 0x80;
    front = (nx >> FX) + (g->dir > 0 ? 15 : 0);
    y = g->y >> FX;
    if (solid(front, y + 10) || !(solid(front, y + 16) || tile_top(tile_at(front, y + 16))))
        g->dir = -g->dir;
    else
        g->x = nx;
    /* the fox: stomping from above, or hurt from the side */
    {
        int fl = (fox.x >> FX) + 3, fr = (fox.x >> FX) + 12, ft = (fox.y >> FX) + 2,
            fb = (fox.y >> FX) + 22, bl = (g->x >> FX) + 1, br = (g->x >> FX) + 14,
            bt = y + 6, bb = y + 15;
        if (fl <= br && fr >= bl && ft <= bb && fb >= bt) {
            if (fox.vy > 0 && fb < bt + 6) {
                g->state = 2;
                g->timer = 40;
                fox.vy = -0x300;
                score += 100;
                event("stomp");
            } else if (!fox.inv) {
                hurt();
                fox.vx = fl + fr < bl + br ? -0x180 : 0x180;
            }
        }
    }
}

static void game_init(void)
{
    int k;
    fox.x = 40 << FX;
    fox.y = (6 * TS - 23) << FX;
    fox.vx = fox.vy = 0;
    fox.ground = 1;
    safe_x = fox.x;
    lives = 3;
    nbugs = level_nbugs;
    for (k = 0; k < nbugs; k++) {
        bugs[k].x = level_bug[k][0] * TS << FX;
        bugs[k].y = level_bug[k][1] * TS << FX;
        bugs[k].dir = -1;
        bugs[k].state = 0;
    }
    bird_x = (SW + 40) << FX;
    cam = 0;
}

static void game_tick(int keys, int prev)
{
    int k, sx;
    fox_tick(keys, prev);
    for (k = 0; k < nbugs; k++) {
        if (bugs[k].state == 0 && (bugs[k].x >> FX) < cam + SW + 32)
            bugs[k].state = 1;
        if (bugs[k].state == 1 && (bugs[k].x >> FX) < cam - 64)
            bugs[k].state = 3;
        bug_tick(&bugs[k]);
    }
    for (k = 0; k < 4; k++)
        if (pops[k].t) {
            pops[k].t--;
            pops[k].y -= 1;
        }
    /* the bird crosses the sky leftwards, again and again */
    bird_x -= 0x140;
    if ((bird_x >> FX) < cam - 40)
        bird_x = (cam + SW + 80) << FX;
    bird_y = 24 + wave[(tick >> 2) & 31];
    /* the camera keeps the fox between 100 and 150 pixels from the left */
    sx = (fox.x >> FX) - cam;
    if (sx > 150)
        cam = (fox.x >> FX) - 150;
    if (sx < 100)
        cam = (fox.x >> FX) - 100;
    if (cam < 0)
        cam = 0;
    if (cam > LEVEL_W * TS - SW)
        cam = LEVEL_W * TS - SW;
    if (trace && tick % trace == 0) {
        int bx = -1;
        for (k = 0; k < nbugs; k++)
            if (bugs[k].state == 1 && bx < 0)
                bx = bugs[k].x >> FX;
        printf("t %d fox %d %d cam %d score %d coins %d lives %d bug %d\n", tick, fox.x >> FX,
               fox.y >> FX, cam, score, coins, lives, bx);
    }
}

/* ---- drawing ---- */

#define SCRATCH_N 160           /* spare lines a frame */
static unsigned *scratch[2];
static int nscratch;
static unsigned *hud[2];
static char hud_shown[2][48];
static int pct;                 /* the HUD's figure: work as % of a frame */

/* line y as the frame's own: copied into a spare line if it isn't */
static unsigned *own_line(int t, int y)
{
    if (!line_own[y]) {
        unsigned *s;
        if (nscratch >= SCRATCH_N)
            return 0;
        s = scratch[t] + LW * nscratch++;
        k_copy(s, line_src[y], LW);
        line_src[y] = s;
        line_own[y] = 1;
    }
    return line_src[y];
}

typedef struct {
    const Sprite *s;
    int x, y;                   /* on the screen: M1 pixels, logical lines */
} Drawn;

static Drawn drawn[32];
static int ndrawn;

static void want(const Sprite *s, int x, int y)
{
    if (ndrawn < 32 && x > -16 && x < SW && y > HUD_H - s->h && y < SH) {
        drawn[ndrawn].s = s;
        drawn[ndrawn].x = x;
        drawn[ndrawn].y = y;
        ndrawn++;
    }
}

/* race: the sprites of the frame built into table t, drawn into the shared
   buffers when that frame starts and taken off when the next one does */
typedef struct {
    unsigned *rows[24];
    const unsigned *data;
    int y0, h, n;
} Pend;

static Pend pend[2][32];
static int npend[2];
static const Pend *on;          /* the sprites drawn now, and their saved words */
static int non, on_off[32];
static unsigned saved[32 * 24 * 5];
static int late;                /* frames whose race_stage ended after the beam reached a sprite */

static void race_stage(int t)
{
    int k, off = 0, ymin = SH;
    /* the last frame's sprites off, the last drawn first */
    for (k = non - 1; k >= 0; k--) {
        SprJob j;
        j.rows = (unsigned **)on[k].rows;
        j.h = on[k].h;
        j.n = on[k].n;
        j.save = saved + on_off[k];
        k_restore(&j);
        if (on[k].y0 < ymin)
            ymin = on[k].y0;
    }
    /* the tiles that changed meanwhile */
    for (k = 0; k < ntq; k++)
        scroll_tile(tq[k][0], tq[k][1]);
    ntq = 0;
    /* this frame's on, what they cover kept */
    for (k = 0; k < npend[t]; k++) {
        SprJob j;
        j.rows = pend[t][k].rows;
        j.data = pend[t][k].data;
        j.h = pend[t][k].h;
        j.n = pend[t][k].n;
        j.stride = 10;
        j.save = saved + off;
        on_off[k] = off;
        k_sprite_save(&j);
        off += j.h * j.n;
        if (pend[t][k].y0 < ymin)
            ymin = pend[t][k].y0;
    }
    on = pend[t];
    non = npend[t];
    /* in time if the beam (P1) hasn't reached the first line changed: logical
       line y is picture lines 2y and 2y + 1, beam line T + 1 + 2y */
    if (ymin < SH && (int)(VID_BEAM & 0x3FF) >= vid.table + 1 + 2 * ymin)
        late++;
}

/* a sprite's lines made the frame's own (pass 1), or drawn (pass 2) */
static void sprite_pass(int t, const Drawn *d, int draw)
{
    unsigned *rows[32];
    int q = d->x & 3, wx = d->x >> 2, j0 = 0, n = q ? 5 : 4, y0 = d->y, y1 = d->y + d->s->h, y;
    SprJob j;
    if (y0 < HUD_H)
        y0 = HUD_H;
    if (y1 > SH)
        y1 = SH;
    if (wx < 0)
        j0 = -wx;
    if (wx + n > LW)
        n = LW - wx;
    n -= j0;
    if (n <= 0 || y0 >= y1)
        return;
    if (race_on) {
        /* recorded for race_stage, in the shared buffers this frame shows */
        Pend *p;
        if (!draw || npend[t] >= 32)
            return;
        p = &pend[t][npend[t]++];
        for (y = y0; y < y1; y++)
            p->rows[y - y0] = line_src[y] + wx + j0;
        p->data = d->s->ph[q] + 10 * (y0 - d->y) + 2 * j0;
        p->y0 = y0;
        p->h = y1 - y0;
        p->n = n;
        return;
    }
    if (!draw) {
        for (y = y0; y < y1; y++)
            own_line(t, y);
        return;
    }
    for (y = y0; y < y1; y++)
        rows[y - y0] = line_own[y] ? line_src[y] + wx + j0 : 0;
    j.rows = rows;
    j.data = d->s->ph[q] + 10 * (y0 - d->y) + 2 * j0;
    j.h = y1 - y0;
    j.n = n;
    j.stride = 10;
    k_sprite(&j);
}

static void sprites_frame(int t, int view)
{
    const Sprite *set;
    int k, f;
    ndrawn = 0;
    nscratch = 0;
    npend[t] = 0;
    for (k = 0; k < nbugs; k++)
        if (bugs[k].state == 1 || bugs[k].state == 2) {
            f = bugs[k].state == 2 ? S_BUG_FLAT : S_BUG0 + ((tick >> 3) & 1);
            want(&sprites[bugs[k].dir < 0][f], (bugs[k].x >> FX) - view, PF_Y + (bugs[k].y >> FX));
        }
    for (k = 0; k < 4; k++)
        if (pops[k].t)
            want(&sprites[0][S_COIN], pops[k].x - view, PF_Y + pops[k].y);
    if (!cursor_bird)
        want(&sprites[1][S_BIRD0 + ((tick >> 3) & 1)], (bird_x >> FX) - view, bird_y);
    if (!(fox.inv & 4)) {
        set = sprites[fox.face];
        f = !fox.ground ? (fox.vy < 0 ? S_FOX_JUMP : S_FOX_FALL)
            : fox.vx ? S_FOX_RUN0 + ((fox.anim >> 11) & 3) : S_FOX_STAND;
        want(&set[f], (fox.x >> FX) - view, PF_Y + (fox.y >> FX));
    }
    for (k = 0; k < ndrawn; k++)
        sprite_pass(t, &drawn[k], 0);
    pmark(P_LINES);
    for (k = 0; k < ndrawn; k++)
        sprite_pass(t, &drawn[k], 1);
    pmark(P_SPRITES);
}

#define HUD_BG 8
#define HUD_FG 9
#define HUD_DIM 10
#define HUD_GOLD 11

/* text in the HUD's 8 x 16 cells (the library's cell font, a byte a row,
   bit 0 the left): each row's two nibbles through a table of words in the
   two colours. The library's font_cells does the same through its general
   1-bit expansion, which at 8 bits a pixel is C in every variant and
   about 12 times as slow. */
static unsigned nib[2][16];

static void hud_init(void)
{
    static const unsigned char fg[2] = {HUD_GOLD, HUD_DIM};
    int s, v;
    for (s = 0; s < 2; s++)
        for (v = 0; v < 16; v++)
            nib[s][v] = pack4(v & 1 ? fg[s] : HUD_BG, v & 2 ? fg[s] : HUD_BG,
                              v & 4 ? fg[s] : HUD_BG, v & 8 ? fg[s] : HUD_BG);
}

static void hud_char(unsigned *buf, int col, int ch, int scheme)
{
    const unsigned *tab = nib[scheme];
    const unsigned char *g = font_cell8 + 16 * ((ch < 32 || ch > 126 ? ' ' : ch) - 32);
    unsigned *d = buf + 2 * col;
    int r;
    for (r = 0; r < 15; r++, d += LW) {
        d[0] = tab[g[r] & 15];
        d[1] = tab[g[r] >> 4];
    }
}

static void hud_text(unsigned *buf, int col, const char *str, int scheme)
{
    for (; *str; str++, col++)
        hud_char(buf, col, *str, scheme);
}

static void hud_frame(int t)
{
    static char buf[48];
    static int last[4] = {-1};
    int y;
    if (score != last[0] || coins != last[1] || lives != last[2] || pct != last[3]) {
        /* formatted only when it changes: sprintf's digits are divisions */
        last[0] = score;
        last[1] = coins;
        last[2] = lives;
        last[3] = pct;
        memset(buf, 0, sizeof buf);
        sprintf(buf, "%06d $%02d x%d", score, coins, lives);
        sprintf(buf + 16, "%-8s %-3s %3d%%", sc_names[strategy], VARIANT, pct);
    }
    /* each buffer's characters redrawn where they're out of date: the
       score's last digits, mostly */
    for (y = 0; y < 36; y++)
        if (buf[y] != hud_shown[t][y]) {
            hud_char(hud[t], y < 16 ? 1 + y : 3 + y, buf[y], y >= 16);
            hud_shown[t][y] = buf[y];
        }
    for (y = 0; y < HUD_H; y++) {
        line_src[HUD_Y + y] = hud[t] + y * LW;
        line_own[HUD_Y + y] = 0;
    }
}

/* table t: each logical line's word, twice */
static void descriptors_c(int t)
{
    unsigned *d = video_table(t);
    int y;
    for (y = 0; y < SH; y++) {
        unsigned w = ((unsigned)line_src[y] - BANK1) >> 2;
        d[0] = w;
        d[1] = w;
        d += 2;
    }
}

static void descriptors(int t)
{
#ifdef GFX_ASM
    k_desc_asm(video_table(t), line_src, SH);
#else
    descriptors_c(t);
#endif
}

static void render(int t)
{
    /* the coarse strategy's view is on a word: the sprites go with it */
    int view = strategy == SC_COARSE ? cam & ~3 : cam;
    scroll_frame(t, view);
    sprites_frame(t, view);
    hud_frame(t);
    pmark(P_HUD);
    descriptors(t);
    pmark(P_DESC);
}

/* ---- the frame's interrupt: the keys as they are at each frame's end
   (the ticks read them from there, whenever they run), and the table
   (and the cursor) switched in the blanking ---- */

static unsigned char keys_at[256];
static volatile int want_tsel = -1;
static volatile unsigned cur_x, cur_y, cur_img;
static int shown;

static void frame_hook(void)
{
    int k = 0;
    if (key_down(K_LEFT))
        k |= K_L;
    if (key_down(K_RIGHT))
        k |= K_R;
    if (key_down(' ') || key_down(K_UP))
        k |= K_J;
    keys_at[rt_frames & 255] = k;
    if (want_tsel >= 0) {
        video_ctrl(want_tsel ? VC_TSEL : 0, VC_TSEL);
        if (cursor_bird) {
            VID_CURX = cur_x;
            VID_CURY = cur_y;
            VID_CURIMG = cur_img;
        }
        want_tsel = -1;
        shown++;
    }
}

static void cursor_frame(int view)
{
    int x = (bird_x >> FX) - view;
    if (!cursor_bird)
        return;
    /* VGA pixels: the cursor's image has the bird from its row 4 */
    cur_x = (2 * x) & 0xFFF;
    cur_y = (2 * bird_y - 4) & 0xFFF;
    cur_img = video_word(bird_cursor[1][(tick >> 3) & 1]);
}

/* ---- measuring the kernels on their own ---- */

static void bench_copy(const char *name, void (*f)(unsigned *, const unsigned *, int),
                       unsigned *d, const unsigned *s)
{
    int y;
    perf_start();
    for (y = 0; y < PF_H; y++)
        f(d + y * 88, s + y * 88, LW);
    perf_end(name);
}

static void bench_shift(const char *name, void (*f)(unsigned *, const unsigned *, int, int),
                        unsigned *d, const unsigned *s, int p)
{
    int y;
    perf_start();
    for (y = 0; y < PF_H; y++)
        f(d + y * 88, s + y * 88, LW, p);
    perf_end(name);
}

static void bench_sprite(const char *name, void (*f)(const SprJob *), unsigned *d)
{
    static unsigned save[24 * 5];
    unsigned *rows[24];
    SprJob j;
    int k, y;
    perf_start();
    for (k = 0; k < 64; k++) {
        const Sprite *s = &sprites[0][S_FOX_RUN0];
        for (y = 0; y < 24; y++)
            rows[y] = d + y * 88 + k % 16;
        j.rows = rows;
        j.data = s->ph[k & 3];
        j.h = 24;
        j.n = 5;
        j.stride = 10;
        j.save = save;
        f(&j);
    }
    perf_end(name);
}

static void bench_redraw(const char *name, void (*f)(const RedrawJob *), unsigned *d)
{
    const unsigned *tiles[22];
    RedrawJob j;
    int r, i;
    perf_start();
    for (r = 0; r < ROWS; r++) {
        for (i = 0; i < 22; i++)
            tiles[i] = timg(level[r][20 + i], r, 1);
        j.d = d + 16 * r * 88 + 2;
        j.pitch = 88;
        j.h = 16;
        j.tiles = tiles;
        f(&j);
    }
    perf_end(name);
}

static void run_bench(void)
{
    unsigned *a = vram_alloc(PF_H * 88 * 4), *b = vram_alloc(PF_H * 88 * 4);
    int y, k;
    char name[32];
    for (y = 0; y < PF_H * 88; y++)
        a[y] = y * 0x01010101;
    /* the same 10,240 words (128 lines of 80) each way */
    bench_copy("copy_c", k_copy_c, b, a);
    bench_copy("copy_asm", k_copy_asm, b, a);
    bench_copy("copy_ldm", k_copy_ldm, b, a);
    bench_copy("copy_blk", k_copy_blk, b, a);
    perf_start();
    for (y = 0; y < PF_H; y++)
        k_fill_blk(b + y * 88, 0x11223344, LW);
    perf_end("fill_blk");
    for (k = 1; k < 4; k++) {
        sprintf(name, "shift%d_c", k);
        bench_shift(name, k_shift_c, b, a, k);
        sprintf(name, "shift%d_asm", k);
        bench_shift(name, k_shift_asm, b, a, k);
        sprintf(name, "shift%d_blk", k);
        bench_shift(name, k_shift_blk, b, a, k);
    }
    /* 64 foxes, 16 x 24, the four phases */
    bench_sprite("sprite64_c", k_sprite_c, b);
    bench_sprite("sprite64_asm", k_sprite_asm, b);
    bench_sprite("sprite64_save_c", k_sprite_save_c, b);
    bench_sprite("sprite64_save_asm", k_sprite_save_asm, b);
    bench_sprite("restore64_c", k_restore_c, b);
    bench_sprite("restore64_asm", k_restore_asm, b);
    /* a playfield's 8 tile rows */
    bench_redraw("redraw_c", k_redraw_c, b);
    bench_redraw("redraw_asm", k_redraw_asm, b);
    /* a frame's descriptors */
    for (y = 0; y < SH; y++)
        line_src[y] = a + (y & 127) * 88;
    perf_start();
    descriptors_c(0);
    perf_end("descriptors_c");
    perf_start();
    k_desc_asm(video_table(0), line_src, SH);
    perf_end("descriptors_asm");
    perf_start();
    for (k = 0; k < 100; k++)
        video_ticks();
    perf_end("video_ticks100");
    /* the HUD's 34 characters: the library's cell font, and hud_text */
    {
        static const char str[] = "000120 $07 x3    PRESHIFT BLK  27%";
        Surface s;
        gfx_init(&s, b, SW, HUD_H, LW, gfx_screen_format());
        perf_start();
        font_cells(&s, 8, 0, str, strlen(str), HUD_GOLD, HUD_BG);
        perf_end("hud_font_cells");
        perf_start();
        hud_text(b, 1, str, 0);
        perf_end("hud_text");
    }
}

/* ---- the program ---- */

int main(void)
{
    int t = 1, k;
    unsigned frames0;
    video_init(1, 0);
    palette_init();
    input_init();
    font_init();
    level_init();
    art_init();
    hud_init();
    if (bench) {
        run_bench();
        printf("@done\n");
        return 0;
    }
    if (strategy == SC_BLIT && board_layout)
        printf("BLIT shifts L0's bytes: its picture is wrong in L1\n");
    scroll_init();
    for (k = 0; k < 2; k++) {
        scratch[k] = vram_alloc(SCRATCH_N * LW * 4);
        hud[k] = vram_alloc(HUD_H * LW * 4);
        for (t = 0; t < HUD_H * LW; t++)
            hud[k][t] = t < (HUD_H - 1) * LW ? pack4(HUD_BG, HUD_BG, HUD_BG, HUD_BG)
                                              : pack4(HUD_DIM, HUD_DIM, HUD_DIM, HUD_DIM);
    }
    t = 1;
    race_on = race && (strategy == SC_COARSE || strategy == SC_PRESHIFT);
    game_init();
    if (cursor_bird)
        video_cursor(bird_cursor[1][0]);
    /* the rings filled for the first view at every phase, both tables built */
    for (k = 0; k < 4; k++) {
        render(k & 1);
        cam++;
    }
    cam -= 4;
    for (k = 0; k < P_N; k++)
        ptime[k] = pframe[k] = 0;
    rt_frame_hook = frame_hook;
    printf("init done at frame %u\n", rt_frames);
    while (rt_frames < (unsigned)start_frame)
        video_wait();
    tick = rt_frames;
    frames0 = rt_frames;
    for (;;) {
        perf_frame_begin();
        plast = video_ticks();
        if (race_on) {
            /* first, while the beam is above the picture: the sprites of
               the frame now shown, built last time */
            race_stage(t ^ 1);
            pmark(P_SPRITES);
        }
        while (tick < (int)rt_frames && tick < end_tick) {
            tick++;
            game_tick(keys_at[tick & 255], keys_at[(tick - 1) & 255]);
        }
        pmark(P_LOGIC);
        render(t);
        cursor_frame(strategy == SC_COARSE ? cam & ~3 : cam);
        perf_frame_end();
        pframe_end();
        if (shown % 32 == 31) {
            /* the HUD's figure: the work of the frames so far, per frame */
            unsigned sum = 0;
            for (k = 0; k < P_N; k++)
                sum += ptime[k];
            pct = sum / (shown + 1) / 8400;
        }
        /* shown at the next frame's start: until then, nothing to build */
        want_tsel = t;
        t ^= 1;
        while (want_tsel >= 0)
            rt_wait_frame_after(rt_frames);
        if (tick >= end_tick)
            break;
    }
    /* the results: work a frame built, by part, and frames shown a second */
    perf_frames("frame");
    for (k = 0; k < P_N; k++) {
        char name[24];
        perf_value(pnames[k], ptime[k] / shown);
        sprintf(name, "max_%s", pnames[k]);
        perf_value(name, pmax[k]);
    }
    perf_value("shown", shown);
    perf_value("ticks", rt_frames - frames0);
    perf_value("fps_x10", shown * 600 / (rt_frames - frames0));
    if (race_on)
        perf_value("race_late", late);
    printf("score %d coins %d lives %d fox %d %d\n", score, coins, lives, fox.x >> FX,
           fox.y >> FX);
    printf("@done\n");
    return 0;
}
