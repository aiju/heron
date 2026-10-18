/* Sprites: the cars, trees, bushes and signs (racer.h).

   Each picture is pre-scaled at init to a few sizes (levels a factor 0.8
   apart), and each size pre-shifted to every pixel phase, so drawing one
   is whole words: per row, runs of words that are opaque (stored) or
   mixed (kept under a mask, then ORed). Transparent words are skipped.

   Each frame: the objects in view are placed on the road (their step's
   line and centre), sorted far to near; every line one covers gets a
   scratch line from this table's pool, made from the line's own picture
   (the road rendered by spans, or the descriptor's source copied), and
   its descriptor points there; then the sprites are drawn into the
   scratch lines. A sprite's lines are consecutive in the pool, so it's
   drawn as rows SPITCH words apart, and it may hang over a line's ends
   into the SLACK words between the lines: no clipping but at the
   sprite's top and bottom. */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "racer.h"

#define NLEV 10
#define TRANSP 255

/* the pictures, by character: logical colours */
static int colour_of(char c)
{
    switch (c) {
    case 'k': return C_BLACK;
    case 'r': return C_RED;
    case 'd': return C_DRED;
    case 'y': return C_YELLOW;
    case 'b': return C_MTN;
    case 's': return C_MTNSH;
    case 'w': return C_SNOW;
    case 'G': return C_HILL;
    case 'g': return C_LGREEN;
    default: return TRANSP;
    }
}

/* a car from behind: 'r' the body, 'd' its shade, 'L' the lights */
static const char *car_art[] = {
    "...........kkkkkkkkkkkkkkkkkk...........",
    ".........kkbbbbbbbbbbbbbbbbbbkk.........",
    "........kbbwwbbbbbbbbbbbbbbbbbbk........",
    ".......kbbwwbbbbbbbbbbbbbbbbbbbbk.......",
    "......kbbwbbbbbbbbbbbbbbbbbbbbbbbk......",
    ".....krrrrrrrrrrrrrrrrrrrrrrrrrrrrk.....",
    "...kkrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrkk...",
    "..krrrwwrrrrrrrrrrrrrrrrrrrrrrrrrrrrrk..",
    ".krrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrk.",
    "krLLLLLrrrrrrrrrrrrrrrrrrrrrrrrrrLLLLLrk",
    "krLLLLLrrrrrrrkkkkkkkkkkkkrrrrrrrLLLLLrk",
    "krrrrrrrrrrrrrkwwwwwwwwwwkrrrrrrrrrrrrrk",
    "kddddddddddddddkkkkkkkkkkddddddddddddddk",
    "kddddddddddddddddddddddddddddddddddddddk",
    "kksssssssssssssssssssssssssssssssssssskk",
    "kkkkkkkkkkkkkkkkkkkkkkkkkkkkkkkkkkkkkkkk",
    "kkkkkkkk........................kkkkkkkk",
    "kkkkkkkk........................kkkkkkkk",
    0,
};

/* a chevron sign, pointing right */
static const char *sign_art[] = {
    "kkkkkkkkkkkkkkkkkk",
    "kyyyyyyyyyyyyyyyyk",
    "kykkyyyyykkyyyyyyk",
    "kyykkyyyyykkyyyyyk",
    "kyyykkyyyyykkyyyyk",
    "kyyyykkyyyyykkyyyk",
    "kyyyyykkyyyyykkyyk",
    "kyyyykkyyyyykkyyyk",
    "kyyykkyyyyykkyyyyk",
    "kyykkyyyyykkyyyyyk",
    "kykkyyyyykkyyyyyyk",
    "kyyyyyyyyyyyyyyyyk",
    "kkkkkkkkkkkkkkkkkk",
    "...ss........ss...",
    "...ss........ss...",
    "...ss........ss...",
    "...ss........ss...",
    "...ss........ss...",
    "...ss........ss...",
    0,
};

/* the start: a chequered board on a post */
static const char *flag_art[] = {
    "kkkkkkkkkkkkkkkkkkkkkk",
    "kwwwkkkwwwkkkwwwkkkwwk",
    "kwwwkkkwwwkkkwwwkkkwwk",
    "kkkkwwwkkkwwwkkkwwwkkk",
    "kkkkwwwkkkwwwkkkwwwkkk",
    "kwwwkkkwwwkkkwwwkkkwwk",
    "kwwwkkkwwwkkkwwwkkkwwk",
    "kkkkkkkkkkkkkkkkkkkkkk",
    "..........ss..........",
    "..........ss..........",
    "..........ss..........",
    "..........ss..........",
    "..........ss..........",
    "..........ss..........",
    "..........ss..........",
    "..........ss..........",
    "..........ss..........",
    "..........ss..........",
    0,
};

/* a picture as logical colours */
typedef struct {
    int w, h;
    unsigned char *px;
} Art;

/* a picture at one size, in every phase: per phase, h row offsets and the
   rows' runs (racer.h's spr_draw) */
typedef struct {
    int w, h, nw;
    unsigned *ph[8];
} Img;

/* the kinds: 0 tree, 1 bush, 2 sign left, 3 sign right, 4 flag, 5 car
   yellow, 6 car white; the player's car (straight, left, right) apart */
#define NKIND 7
static Img lev[NKIND][NLEV];
static unsigned char lev_of[NKIND][NROWS + 1];   /* the level for distance d, or 255 */
static const Img **lev_at[NKIND];               /* its picture, or 0 */
static Img player[3];
static unsigned short d_of[4096];       /* PROJ / z for z = 8i */
/* the size at d = 256, in 640-unit pixels, and the farthest level's d */
static const short kind_w[NKIND] = {76, 120, 64, 64, 88, 120, 120};
static const short kind_top[NKIND] = {200, 256, 220, 220, 220, 256, 256};

unsigned spr_lines, spr_words, spr_count;

/* bank 0 above the heap (which malloc keeps under 0xF0000), below the
   stack: room for the pictures */
static char *big = (char *)0x100000;
static void *big_alloc(unsigned n)
{
    void *p = big;
    big += (n + 3) & ~3u;
    if ((unsigned)big > 0x1E0000) {
        printf("sprites: out of room\n@done\n");
        for (;;)
            ;
    }
    return p;
}

static Art art_from(const char **rows, int flip, const char *body)
{
    Art a;
    int x, y;
    a.h = 0;
    a.w = 0;
    while (rows[a.h]) {
        int n = strlen(rows[a.h]);
        if (n > a.w)
            a.w = n;
        a.h++;
    }
    a.px = malloc(a.w * a.h);
    for (y = 0; y < a.h; y++)
        for (x = 0; x < a.w; x++) {
            int sx = flip ? a.w - 1 - x : x, n = strlen(rows[y]);
            char c = sx < n ? rows[y][sx] : '.';
            int col;
            if (c == 'r')
                col = body[0];
            else if (c == 'd')
                col = body[1];
            else if (c == 'L')
                col = body[2];
            else
                col = colour_of(c);
            a.px[y * a.w + x] = col;
        }
    return a;
}

/* a tree: a tall canopy, lit from the left, on a trunk */
static Art art_tree(void)
{
    Art a;
    int x, y;
    a.w = 22;
    a.h = 46;
    a.px = malloc(a.w * a.h);
    for (y = 0; y < a.h; y++)
        for (x = 0; x < a.w; x++) {
            int dx = 2 * x - 21, dy = y - 17, c = TRANSP;
            /* the canopy: an ellipse 21 x 34, a little ragged */
            int e = dx * dx * 289 + dy * dy * 4 * 110;
            int rag = ((x * 7 + y * 13) % 5) * 1200;
            if (e < 289 * 441 - rag) {
                int lx = 2 * x - 13, ly = y - 10;
                c = C_HILL;
                if (lx * lx + ly * ly * 3 < 160 && ((x + y) & 1 || lx * lx + ly * ly * 3 < 70))
                    c = C_LGREEN;
                if (e > 289 * 441 - 289 * 60 && dx > 4)
                    c = C_BLACK;
            } else if (y >= 30 && x >= 10 && x <= 12) {
                c = x == 12 ? C_BLACK : C_DRED;
            }
            a.px[y * a.w + x] = c;
        }
    return a;
}

/* a bush: a low mound */
static Art art_bush(void)
{
    Art a;
    int x, y;
    a.w = 30;
    a.h = 12;
    a.px = malloc(a.w * a.h);
    for (y = 0; y < a.h; y++)
        for (x = 0; x < a.w; x++) {
            int dx = 2 * x - 29, dy = 2 * (y - 11), c = TRANSP;
            if (dx * dx * 22 * 22 + dy * dy * 29 * 29 < 29 * 29 * 22 * 22) {
                c = C_HILL;
                if (y < 6 && dx < 4 && ((x + y) & 1))
                    c = C_LGREEN;
            }
            a.px[y * a.w + x] = c;
        }
    return a;
}

/* the picture scaled to w x h (nearest), the cabin rows (above `lean_rows`)
   shifted by `lean` art pixels: the player's car turning */
static unsigned char *scale(const Art *a, int w, int h, int lean, int lean_rows)
{
    unsigned char *p = malloc(w * h);
    int x, y, step = (a->w << 16) / w;
    for (y = 0; y < h; y++) {
        int sy = y * a->h / h, sh = sy < lean_rows ? lean : 0, fx = 0;
        const unsigned char *src = a->px + sy * a->w;
        unsigned char *dst = p + y * w;
        for (x = 0; x < w; x++, fx += step) {
            int sx = (fx >> 16) - sh;
            dst[x] = sx >= 0 && sx < a->w ? src[sx] : TRANSP;
        }
    }
    return p;
}

/* a row's opaque pixels (m) and their colours (v) at a phase, nw words,
   pixel by pixel (any format) */
static void pack_row(const unsigned char *row, int w, int phase, unsigned *m, unsigned *v,
                     int nw, const unsigned *sol)
{
    int x, i;
    for (i = 0; i < nw; i++)
        m[i] = v[i] = 0;
    for (x = 0; x < w; x++) {
        int c = row[x], px = x + phase;
        unsigned pm;
        if (c == TRANSP)
            continue;
        pm = F->pmask[px & (PPW - 1)];
        m[px >> PS] |= pm;
        v[px >> PS] |= sol[c] & pm;
    }
}

/* a row's words shifted right a pixel more: in the linear formats a
   shift of the whole row by a pixel's bits (a constant, so cheap) */
static void shift1(unsigned *w, int nw)
{
    int i;
    if (PPW == 8) {
        for (i = nw - 1; i > 0; i--)
            w[i] = w[i] << 4 | w[i - 1] >> 28;
        w[0] <<= 4;
    } else {
        for (i = nw - 1; i > 0; i--)
            w[i] = w[i] << 8 | w[i - 1] >> 24;
        w[0] <<= 8;
    }
}

/* a row's runs: words are transparent (skipped), opaque (stored) or
   mixed (a keep mask and the colours) */
#define T_ 0                     /* a word's class: transparent, mixed, opaque */
#define M_ 1
#define O_ 2

static unsigned *runs(unsigned *q, const unsigned *m, const unsigned *v, int nw)
{
    unsigned char cls[24];
    int i = 0, k;
    /* a run costs a header and its setup, so: a lone transparent word
       between others is drawn as mixed, and an opaque stretch shorter
       than 3 words too (COPY and plain stores pay off from about there) */
    for (i = 0; i < nw; i++)
        cls[i] = !m[i] ? T_ : m[i] == ~0u ? O_ : M_;
    for (i = 1; i + 1 < nw; i++)
        if (cls[i] == T_ && cls[i - 1] != T_ && cls[i + 1] != T_)
            cls[i] = M_;
    for (i = 0; i < nw;) {
        int j = i;
        if (cls[i] != O_) {
            i++;
            continue;
        }
        while (j < nw && cls[j] == O_)
            j++;
        if (j - i < 3)
            for (k = i; k < j; k++)
                cls[k] = M_;
        i = j;
    }
    i = 0;
    while (i < nw) {
        int start, opaque;
        if (cls[i] == T_) {
            i++;
            continue;
        }
        start = i;
        opaque = cls[i] == O_;
        while (i < nw && cls[i] == cls[start] && i - start < 255)
            i++;
        *q++ = (unsigned)opaque << 31 | (unsigned)(i - start) << 16 | start * 4;
        for (k = start; k < i; k++) {
            if (!opaque)
                *q++ = ~m[k];
            *q++ = v[k];
        }
    }
    *q++ = 0;                   /* the row's end */
    return q;
}

/* a picture at one size in `phases` phases: per phase, h row offsets and
   the rows' runs, in the room above the heap */
static void make_img(Img *im, const Art *a, int w, int h, int phases, int lean, int lean_rows)
{
    unsigned char *p;
    unsigned sol[256], *buf[8], *q[8], m0[24], v0[24], m[24], v[24];
    int j, y, k, nw;
    if (w < 1)
        w = 1;
    if (h < 1)
        h = 1;
    p = scale(a, w, h, lean, lean_rows);
    for (k = 0; k < C_N; k++)
        sol[k] = gfx_solidf(F, col_index[k]);
    nw = (w + 2 * PPW - 2) / PPW;
    im->w = w;
    im->h = h;
    im->nw = nw;
    for (j = 0; j < 8; j++)
        im->ph[j] = 0;
    for (j = 0; j < phases; j++)
        q[j] = (buf[j] = malloc((h + h * (1 + nw * 3) + h) * 4)) + h;
    for (y = 0; y < h; y++) {
        const unsigned char *row = p + y * w;
        pack_row(row, w, 0, m0, v0, nw, sol);
        for (j = 0; j < phases; j++) {
            buf[j][y] = q[j] - buf[j];
            if (j == 0) {
                q[j] = runs(q[j], m0, v0, nw);
                continue;
            }
            if (F->lin) {
                shift1(m0, nw);
                shift1(v0, nw);
                q[j] = runs(q[j], m0, v0, nw);
                continue;
            } else {
                pack_row(row, w, j, m, v, nw, sol);
            }
            q[j] = runs(q[j], m, v, nw);
        }
    }
    for (j = 0; j < phases; j++) {
        int size = q[j] - buf[j];
        im->ph[j] = big_alloc(size * 4);
        memcpy(im->ph[j], buf[j], size * 4);
        for (y = 0; y < h; y++)
            im->ph[j][y] = (unsigned)(im->ph[j] + im->ph[j][y]);   /* the rows' addresses */
        free(buf[j]);
    }
    free(p);
}

static const unsigned short lev_f[NLEV] = {256, 205, 164, 131, 105, 84, 67, 54, 43, 34};

void sprites_build(void)
{
    static const char body[3][3] = {
        {C_RED, C_DRED, C_YELLOW}, {C_YELLOW, C_DRED, C_RED}, {C_SNOW, C_MTNSH, C_RED},
    };
    Art arts[NKIND], pa;
    int k, l, d;
    arts[0] = art_tree();
    arts[1] = art_bush();
    arts[2] = art_from(sign_art, 1, body[0]);
    arts[3] = art_from(sign_art, 0, body[0]);
    arts[4] = art_from(flag_art, 0, body[0]);
    arts[5] = art_from(car_art, 0, (const char *)body[1]);
    arts[6] = art_from(car_art, 0, (const char *)body[2]);
    for (k = 0; k < NKIND; k++) {
        const Art *a = &arts[k];
        /* the top level is the size at the farthest d it's used at */
        int w0 = kind_w[k] * kind_top[k] / 256, h0 = w0 * a->h / a->w;
        for (l = 0; l < NLEV; l++)
            make_img(&lev[k][l], a, (w0 * lev_f[l] >> 8) >> XS, h0 * lev_f[l] >> 8, NPH, 0, 0);
        /* the level for each d: the nearest in size */
        for (d = 0; d <= NROWS; d++) {
            int f = d * 256 / kind_top[k], best = 255, bd = 1 << 30;
            if (f > 256)
                f = 256;
            for (l = 0; l < NLEV; l++) {
                int e = f - lev_f[l];
                if (e < 0)
                    e = -e;
                if (e < bd)
                    bd = e, best = l;
            }
            if (f < 24)
                best = 255;     /* too small to bother */
            lev_of[k][d] = best;
        }
        lev_at[k] = malloc((NROWS + 1) * sizeof(Img *));
        for (d = 0; d <= NROWS; d++)
            lev_at[k][d] = lev_of[k][d] == 255 ? 0 : &lev[k][lev_of[k][d]];
    }
    /* the player's car: phase 0 only (it stays put), leaning into turns */
    pa = art_from(car_art, 0, body[0]);
    {
        int w = 120 * D_CAR / 256, h = w * pa.h / pa.w;
        make_img(&player[0], &pa, w >> XS, h, 1, 0, 0);
        make_img(&player[1], &pa, w >> XS, h, 1, -2, 9);
        make_img(&player[2], &pa, w >> XS, h, 1, 2, 9);
    }
    for (d = 1; d < 4096; d++)
        d_of[d] = PROJ / (8 * d);
    d_of[0] = 65535;
    printf("sprites: %u bytes\n", (unsigned)(big - (char *)0x100000));
}

/* ---- each frame ---- */

typedef struct {
    int d;                      /* sorting: far first */
    int x, ya, yb, r0;          /* left pixel; lines ya..yb-1; the image row at ya */
    const Img *m;
    int pad[2];                 /* 32 bytes: other sizes are indexed with a multiply */
} Spr;

#define MAXSPR 48
static Spr spr[MAXSPR];
static Spr *order[MAXSPR];
static int nspr;
static unsigned char cover[NLINES];
static unsigned *slot[NLINES];

/* an object at z_rel ahead of the camera, x from the road's centre */
static void place(int kind, int zr, int ox)
{
    int d, cx, base, clip, ytop;
    const Img *m;
    Spr *s;
    if (zr <= zt[NROWS] || zr >= 8 * 4096 || nspr >= MAXSPR)
        return;
    d = d_of[zr >> 3];          /* PROJ / zr, from a table: a division is a long loop */
    if (d > NROWS || d < 6)
        return;
    m = lev_at[kind][d];
    if (!m)
        return;
    /* (ox * d) >> 10 by an unsigned multiply: MULS takes 32 steps for a
       negative operand, MULU 16 for operands under 65536 */
    cx = ox < 0 ? -(int)(((unsigned)-ox * d) >> 10) : (int)(((unsigned)ox * d) >> 10);
    cx = W / 2 + step_sx[d] + (cx >> XS);
    base = step_yc[2 * d];
    clip = step_yc[2 * d + 1];
    ytop = base - m->h + 1;
    s = spr + nspr;
    s->d = d;
    s->x = cx - m->w / 2;
    s->ya = ytop < HUD_LINES ? HUD_LINES : ytop;
    s->yb = base + 1 < clip ? base + 1 : clip;
    if (s->yb > NLINES)
        s->yb = NLINES;
    if (s->ya >= s->yb || s->x + m->w <= 0 || s->x >= W)
        return;
    s->r0 = s->ya - ytop;
    s->m = m;
    nspr++;
}

extern int shake, lookahead;

void sprites_frame(unsigned *desc, int t)
{
    int i, j, y, n, seg0, zbase;
    unsigned *pl = pool[t];
    nspr = 0;
    /* roadside objects, 8 to 90 segments ahead */
    seg0 = camz >> 8;
    zbase = (seg0 << 8) + SEG / 2 - camz;
    for (i = 8; i < lookahead; i++) {
        const SegObj *o = &seg_obj[(seg0 + i) & (NSEG - 1)];
        int zr = zbase + (i << 8);
        if (o->kind[0] >= 0)
            place(o->kind[0], zr, o->x[0]);
        if (o->kind[1] >= 0)
            place(o->kind[1], zr, o->x[1]);
    }
    for (i = 0; i < NCARS; i++) {
        int zr = cars[i].z - camz;
        if (zr < 0)
            zr += LAP;
        if (zr < 24000)
            place(5 + cars[i].kind, zr, cars[i].x);
    }
    /* far to near: an insertion sort of pointers to them */
    for (i = 0; i < nspr; i++)
        order[i] = spr + i;
    for (i = 1; i < nspr; i++) {
        Spr *x = order[i];
        int dx = x->d;
        for (j = i; j > 0 && order[j - 1]->d > dx; j--)
            order[j] = order[j - 1];
        order[j] = x;
    }
    /* the player's car, nearest */
    if (nspr < MAXSPR) {
        const Img *m = steer_vis < 0 ? &player[1] : steer_vis > 0 ? &player[2] : &player[0];
        Spr *s = spr + nspr;
        order[nspr] = s;
        nspr++;
        int base = HY + D_CAR - 1 + 4 + shake;
        s->m = m;
        s->x = (W / 2 - m->w / 2) & ~(PPW - 1);      /* phase 0: its only one */
        s->ya = base - m->h + 1;
        s->yb = base + 1;
        if (s->yb > NLINES)
            s->yb = NLINES;
        s->r0 = 0;
        s->d = NROWS;
    }
    tmark(T_PLACE);

    /* the lines they cover get scratch lines (the software road: every
       road line, or every line) */
    memset(cover, 0, sizeof cover);
    for (i = 0; i < nspr; i++)
        memset(cover + spr[i].ya, 1, spr[i].yb - spr[i].ya);
    if (soft)
        for (y = HUD_LINES; y < NLINES; y++)
            if (soft == 2 || LI_KIND(line_info[y]) == LK_ROAD)
                cover[y] = 1;
    {
        unsigned *line = pl, *end = pl + pool_lines * SPITCH;
        int render = soft || !prep_copy;
        n = 0;
        for (y = HUD_LINES; y < NLINES; y++) {
            unsigned info;
            slot[y] = 0;
            if (!cover[y] || line == end)
                continue;
            info = line_info[y];
            if (render && LI_KIND(info) == LK_ROAD) {
                /* drawn: its palette bank is its stripe (the software
                   road has no descriptor from the projection) */
                road_line(line, LI_K(info), LI_SX(info), LI_STRIPE(info));
                desc[y] = ((unsigned)line - BANK1) >> 2 | (M1 ? 0 : LI_STRIPE(info) << 19);
            } else {
                copy_line(line, (const unsigned *)(BANK1 + ((desc[y] & 0x7FFFF) << 2)));
                desc[y] = ((unsigned)line - BANK1) >> 2 | (desc[y] & 0xF80000);
            }
            slot[y] = line;
            line += SPITCH;
            n++;
        }
    }
    spr_lines += n;
    tmark(T_LINES);

    /* the sprites, far to near */
    for (i = 0; i < nspr; i++) {
        Spr *s = order[i];
        if (!slot[s->ya] || !slot[s->yb - 1])
            continue;           /* the pool ran out */
        spr_draw(slot[s->ya] + (s->x >> PS), s->m->ph[s->x & (PPW - 1)], s->r0, s->yb - s->ya);
        spr_words += (s->yb - s->ya) * s->m->nw;
    }
    spr_count += nspr;
    tmark(T_DRAW);
}

/* the sprite kernel alone: a picture drawn 10 times, its words (bench) */
static void bench_one(const char *name, const Img *m, int phase)
{
    unsigned *d = pool[0] + 100 * SPITCH + 20;
    int i;
    perf_start();
    for (i = 0; i < 10; i++)
        spr_draw(d, m->ph[phase], 0, m->h);
    perf_end(name);
    printf("%s: %d rows of %d words\n", name, m->h, m->nw);
}

void sprites_bench(void)
{
    bench_one("bench.car_player_x10", &player[0], 0);
    bench_one("bench.car_near_x10", &lev[5][0], 3);
    bench_one("bench.car_far_x10", &lev[5][6], 3);
    bench_one("bench.tree_near_x10", &lev[0][0], 5);
    bench_one("bench.tree_far_x10", &lev[0][6], 5);
}

/* ---- the kernels in C ---- */

void spr_draw_c(unsigned *d, const unsigned *img, int r0, int n)
{
    while (n-- > 0) {
        const unsigned *p = (const unsigned *)img[r0++];
        unsigned h;
        while ((h = *p++) != 0) {
            unsigned *q = (unsigned *)((char *)d + (h & 0xFFFF));
            int c = (h >> 16) & 0x7FFF;
            if (h & 0x80000000u) {
                while (c-- > 0)
                    *q++ = *p++;
            } else {
                while (c-- > 0) {
                    *q = (*q & p[0]) | p[1];
                    q++;
                    p += 2;
                }
            }
        }
        d += SPITCH;
    }
}

void spans_c(unsigned *line, const int *b, const unsigned *cw, int n)
{
    int i;
    for (i = 0; i < n; i++) {
        int x0 = b[i], x1 = b[i + 1], w0, w1;
        unsigned c = cw[i], *p, m;
        if (x0 >= x1)
            continue;
        w0 = x0 >> PS;
        w1 = (x1 - 1) >> PS;
        p = line + w0;
        m = gfx_from(F, x0 & (PPW - 1));
        if (w0 == w1) {
            m &= gfx_before(F, ((x1 - 1) & (PPW - 1)) + 1);
            *p = (*p & ~m) | (c & m);
            continue;
        }
        *p = (*p & ~m) | (c & m);
        p++;
        while (++w0 < w1)
            *p++ = c;
        m = gfx_before(F, ((x1 - 1) & (PPW - 1)) + 1);
        *p = (*p & ~m) | (c & m);
    }
}

void copy_line_c(unsigned *d, const unsigned *s)
{
    int i;
    for (i = 0; i < LW; i++)
        d[i] = s[i];
}
