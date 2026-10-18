/* The scene in bank 1: the road rows, the sky and the mountains, drawn
   once, and the descriptors that show them (racer.h).

   The road rows are RP words wide (1024 pixels in M0, 512 in M1), the
   road centred, with grass either side, so that a screen line shows any
   80 words of a row (or a little into its neighbours, which are grass
   there too). A descriptor starts on a word, so each row is there once
   per pixel phase, shifted left by 0..7 pixels (M0) or 0..3 (M1): a
   line's start address then puts the road at any pixel. M0 colours the
   stripes with the palette bank (bank 0 light, 1 dark); M1 has no banks,
   so its rows are there twice, light and dark, and the start address
   picks one.

   The background is two bands (clouds, mountains) whose rows wrap with
   a period of PB words; they scroll by start addresses too, in pixel
   phases. Rows with only sky in them all show one line of sky colour:
   in M0 their palette bank makes the gradient (14 banks, dithered by
   line), or a line interrupt every 4 lines rewrites a bank's sky entry
   (sky_irq); in M1 they show one of 64 lines of the gradient's colours. */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "racer.h"
#include "mini.h"

#define RP 128                  /* a road row's words */
#define CL0 44                  /* the clouds' band */
#define CL1 72
#define MT0 140                 /* the mountains' band, to the horizon */
#define SKY_BANK 2              /* M0: banks 2-15 the sky's gradient */
#define NGRAD 56                /* the line interrupts' gradient: groups of 4 lines */

unsigned char col_index[C_N];
unsigned grass_desc;
int bg_scroll[2];
unsigned bank1_used;
unsigned sky_irqs;
unsigned *pool[2];              /* the scratch lines (sprites.c), SLACK words in */
int pool_lines;

static unsigned *road_mem;      /* the road rows: copy c, row k at road_mem + c * copyw + (k + 1) * RP */
static int copyw, rpx, row_c;
/* a road line's descriptor from tables (the assembly's projection reads
   them too): row k's word in the first copy, how far its window may go
   either way (so it shows no other row's road), each phase's copy, the
   stripe's bank (M0) or copy (M1), the row's pixel at the screen's left
   edge for a centred road */
unsigned road_rowbase[NROWS];
int road_lim[NROWS];
unsigned road_phw[8], road_stripe[5];  /* the stripe's at 0 and 4 */
int road_ws0;
static unsigned span_cw[2][9];  /* the road's spans' colour words, each stripe */
int road_rw[NROWS], road_rm[NROWS], road_ln[NROWS], road_l3[NROWS];
unsigned road_cw4[2][4];
int half_w;
static unsigned *sky_mem;       /* M0: one line of sky; M1: 64, the gradient */
static unsigned *bg_mem;        /* the bands: phase j, band row r at bg_mem + j * bgphw + r * bgw */
static int pb, bgw, bgphw, bg_rows;
static unsigned bg_word[NLINES];    /* each background line's descriptor, unscrolled */
static unsigned char bg_band[NLINES];  /* 0 sky only, 1 clouds, 2 mountains */
static unsigned *hud_mem[2];
static unsigned grad[NGRAD + 1];
static void hud_glyphs(void);

/* the colours, RGB */
static const unsigned char rgb_const[C_N][3] = {
    {0, 0, 0}, {250, 250, 252}, {196, 204, 224}, {116, 128, 168}, {76, 82, 124},
    {240, 242, 250}, {44, 104, 60}, {0, 0, 0}, {0, 0, 0}, {0, 0, 0}, {0, 0, 0},
    {16, 16, 20}, {214, 36, 30}, {120, 22, 26}, {104, 196, 76}, {250, 206, 40},
};
/* the road's colours, light and dark stripe */
static const unsigned char rgb_road[4][2][3] = {
    {{72, 176, 64}, {56, 148, 52}},     /* grass */
    {{112, 112, 118}, {102, 102, 108}}, /* road */
    {{210, 34, 30}, {236, 236, 236}},   /* rumble */
    {{236, 236, 236}, {102, 102, 108}}, /* lane */
};
static const unsigned char sky_top[3] = {34, 74, 172}, sky_low[3] = {176, 210, 238};

static unsigned sky_rgb(int i, int n)
{
    int r = sky_top[0] + (sky_low[0] - sky_top[0]) * i / n;
    int g = sky_top[1] + (sky_low[1] - sky_top[1]) * i / n;
    int b = sky_top[2] + (sky_low[2] - sky_top[2]) * i / n;
    return rgb565(r, g, b);
}

static int is_road_col(int c)
{
    return c >= C_GRASS && c <= C_LANE;
}

void scene_palette(void)
{
    int b, c;
    if (!M1) {
        for (b = 0; b < 16; b++)
            for (c = 0; c < C_N; c++) {
                unsigned v;
                if (is_road_col(c)) {
                    int s = b == 0 ? 0 : 1;
                    v = rgb565(rgb_road[c - C_GRASS][s][0], rgb_road[c - C_GRASS][s][1],
                               rgb_road[c - C_GRASS][s][2]);
                } else if (c == C_SKY) {
                    v = b >= SKY_BANK ? sky_rgb(b - SKY_BANK, 13) : sky_rgb(0, 13);
                } else {
                    v = rgb565(rgb_const[c][0], rgb_const[c][1], rgb_const[c][2]);
                }
                video_pal(16 * b + c, v);
            }
        for (c = 0; c < C_N; c++)
            col_index[c] = c;
        for (c = 0; c <= NGRAD; c++)
            grad[c] = sky_rgb(c, NGRAD - 1);
        return;
    }
    /* M1: 0-63 the sky, then the rest */
    for (c = 0; c < 64; c++)
        video_pal(c, sky_rgb(c, 63));
    for (c = 0; c < C_N; c++) {
        if (c == C_SKY) {
            col_index[c] = 0;
        } else if (is_road_col(c)) {
            int i = 70 + 2 * (c - C_GRASS), s;
            col_index[c] = i;
            for (s = 0; s < 2; s++)
                video_pal(i + s, rgb565(rgb_road[c - C_GRASS][s][0], rgb_road[c - C_GRASS][s][1],
                                        rgb_road[c - C_GRASS][s][2]));
        } else {
            int i = c < C_GRASS ? 63 + c : 69 + c;
            col_index[c] = i;
            video_pal(i, rgb565(rgb_const[c][0], rgb_const[c][1], rgb_const[c][2]));
        }
    }
}

unsigned colour_word(int c, int stripe)
{
    int i = col_index[c];
    if (M1 && is_road_col(c))
        i += stripe;
    return gfx_solidf(F, i);
}

/* ---- the road ---- */

/* a row's 8 boundaries around centre c: rumble, road, two lane lines,
   road, rumble, grass */
void road_bounds(int *b, int k, int c)
{
    int rw = road_rw[k], rm = road_rm[k], ln = road_ln[k], l3 = rw / 3;
    b[0] = c - rw - rm;
    b[1] = c - rw;
    b[2] = c - l3 - ln / 2;
    b[3] = b[2] + ln;
    b[4] = c + l3 - ln / 2;
    b[5] = b[4] + ln;
    b[6] = c + rw;
    b[7] = c + rw + rm;
}

static const unsigned char span_col[9] = {
    C_GRASS, C_RUMBLE, C_ROAD, C_LANE, C_ROAD, C_LANE, C_ROAD, C_RUMBLE, C_GRASS,
};

/* the road's spans over a line of nw words, centre c: clipped and handed
   to the span kernel */
static void road_spans(unsigned *line, int nw, int k, int c, int stripe)
{
    int b[10], bb[8], i, end = nw * PPW, prev = 0;
    road_bounds(bb, k, c);
    b[0] = 0;
    for (i = 0; i < 8; i++) {
        int x = bb[i];
        if (x < prev)
            x = prev;
        if (x > end)
            x = end;
        b[i + 1] = prev = x;
    }
    b[9] = end;
    spans(line, b, span_cw[stripe], 9);
}

/* a screen line of road, rendered: the scratch lines and the software road */
void road_line_c(unsigned *line, int k, int sx, int stripe)
{
    road_spans(line, LW, k, W / 2 + sx, stripe);
}

/* a road line's descriptor: row k, its centre sx from the screen's */
unsigned road_desc(int k, int sx, int stripe)
{
    int ws, lim = road_lim[k];
    if (sx > lim)
        sx = lim;
    if (sx < -lim)
        sx = -lim;
    ws = road_ws0 - sx;         /* the row's pixel at the screen's left edge */
    return road_rowbase[k] + road_phw[ws & (PPW - 1)] + (ws >> PS) + road_stripe[4 * stripe];
}

static void build_road(void)
{
    int cpy, k, ncopy = 8;
    for (k = 0; k < NROWS; k++) {
        int d = k + 1, rw = ROAD_W * d / CAM_H;
        road_rw[k] = rw >> XS;
        road_rm[k] = (rw / 6) >> XS;
        road_ln[k] = (rw / 24) >> XS;
    }
    for (k = 0; k < NROWS; k++) {
        int n = k + 1 < NROWS ? k + 1 : k;
        road_lim[k] = rpx - road_rw[n] - road_rm[n] - W / 2 - PPW;
    }
    for (k = 0; k < 18; k++)
        span_cw[k / 9][k % 9] = colour_word(span_col[k % 9], k / 9);
    for (k = 0; k < 8; k++)
        road_cw4[k / 4][k % 4] = span_cw[k / 4][k % 4];
    for (k = 0; k < NROWS; k++)
        road_l3[k] = road_rw[k] / 3;
    half_w = W / 2;
    if (soft)
        return;
    for (k = 0; k < NROWS; k++)
        road_rowbase[k] = video_word(road_mem + (k + 1) * RP);
    for (k = 0; k < 8; k++)
        road_phw[k] = k * copyw;
    road_stripe[0] = 0;
    road_stripe[4] = M1 ? 4 * copyw : 1u << 19;
    road_ws0 = row_c - W / 2;
    for (cpy = 0; cpy < ncopy; cpy++) {
        int phase = cpy & (PPW - 1), stripe = cpy / PPW;
        unsigned *base = road_mem + cpy * copyw;
        unsigned g = colour_word(C_GRASS, stripe);
        int b[2];
        unsigned cw[1];
        b[0] = 0;
        b[1] = RP * PPW;
        cw[0] = g;
        spans(base, b, cw, 1);              /* the grass rows either end */
        spans(base + (NROWS + 1) * RP, b, cw, 1);
        for (k = 0; k < NROWS; k++)
            road_spans(base + (k + 1) * RP, RP, k, row_c - phase, stripe);
    }
}

/* ---- the background ---- */

/* the mountains' and the hills' heights over a period, in rows: sums
   of triangle waves of whole numbers of periods, so they wrap */
static unsigned char *mtn_hgt, *hill_hgt;

static void heights(void)
{
    static const short wave[5][3] = {
        /* periods, amplitude (rows), phase (pixels), for the mountains then the hills */
        {3, 46, 0}, {7, 22, 100}, {17, 7, 37}, {5, 14, 50}, {13, 6, 999},
    };
    int pbx = pb * PPW, x, k, t[5];
    mtn_hgt = malloc(pbx);
    hill_hgt = malloc(pbx);
    for (k = 0; k < 5; k++)
        t[k] = wave[k][2] % pbx;
    for (x = 0; x < pbx; x++) {
        int h[2];
        h[0] = h[1] = 0;
        for (k = 0; k < 5; k++) {
            /* t[k] = x * n + phase, mod the period: a triangle wave */
            int u = 2 * t[k] - pbx;
            if (u < 0)
                u = -u;
            h[k >= 3] += wave[k][1] * (pbx - u);
            t[k] += wave[k][0];
            if (t[k] >= pbx)
                t[k] -= pbx;
        }
        mtn_hgt[x] = h[0] / pbx;
        hill_hgt[x] = h[1] / pbx;
    }
}

static int sky_index(int y)
{
    return y * 64 / HY;
}

static void build_background(Surface *ph0)
{
    int x, y, bx = bgw * PPW, j, i;
    Surface s = *ph0;
    /* the clouds' sky: index C_SKY in M0 (the bank colours it), the
       gradient in M1 */
    for (y = 0; y < CL1 - CL0; y++) {
        int sy = y < CL1 - CL0 ? CL0 + y : MT0 + y - (CL1 - CL0);
        gfx_fill(&s, 0, y, bx, y + 1, M1 ? sky_index(sy) : C_SKY, ROP_COPY);
    }
    /* clouds: puffs of circles, shade below; drawn at x and a period on */
    for (i = 0; i < 9; i++) {
        int cx = (i * 211 + 37) % (pb * PPW), cy = 12 + (i * 7) % 10, r = (10 + (i * 5) % 9) >> XS;
        int w = (34 + (i * 13) % 30) >> XS, rep;
        for (rep = -1; rep < 2; rep++) {
            int ox = cx + rep * pb * PPW;
            gfx_fill_circle(&s, ox, cy + 3, r, col_index[C_CLOUDSH], ROP_COPY);
            gfx_fill_circle(&s, ox + w, cy + 4, r - (2 >> XS), col_index[C_CLOUDSH], ROP_COPY);
            gfx_fill(&s, ox - w / 2, cy + 3, ox + w + w / 2, cy + 3 + r, col_index[C_CLOUDSH],
                     ROP_COPY);
            gfx_fill_circle(&s, ox, cy, r, col_index[C_CLOUD], ROP_COPY);
            gfx_fill_circle(&s, ox + w / 2, cy - r / 2, r, col_index[C_CLOUD], ROP_COPY);
            gfx_fill_circle(&s, ox + w, cy + 1, r - (2 >> XS), col_index[C_CLOUD], ROP_COPY);
        }
    }
    /* the mountains, row by row from the heights: lit and shaded slopes,
       snow on the peaks, the hills in front; a pixel's colour word under
       its mask */
    heights();
    {
        int top = CL1 - CL0, rows = HY - MT0, pbx = pb * PPW, r;
        unsigned sol[C_N];
        for (i = 0; i < C_N; i++)
            sol[i] = gfx_solidf(F, col_index[i]);
        for (r = 0; r < rows; r++) {
            int above = rows - r, xp = 0;     /* rows above the horizon */
            unsigned *row = bg_mem + (top + r) * bgw, w = 0;
            unsigned sky = M1 ? gfx_solidf(F, sky_index(MT0 + r)) : sol[C_SKY];
            for (x = 0; x < bx; x++) {
                int h = mtn_hgt[xp], xn = xp + 1 == pbx ? 0 : xp + 1;
                unsigned c = sky;
                if (hill_hgt[xp] + 2 >= above)
                    c = sol[C_HILL];
                else if (h >= above)
                    c = sol[above > 44 ? C_SNOW
                            : (mtn_hgt[xn] > h || (mtn_hgt[xn] == h && (xp & 1))) ? C_MTN
                            : C_MTNSH];
                w |= c & F->pmask[x & (PPW - 1)];
                if ((x & (PPW - 1)) == PPW - 1) {
                    row[x >> PS] = w;
                    w = 0;
                }
                xp = xn;
            }
        }
    }
    /* the other phases: each shifted left a pixel more; in the linear
       formats a shift of each row's words, else the library's copy */
    for (j = 1; j < NPH; j++) {
        if (F->lin) {
            /* from the phase before, a pixel's bits: shifts by constants */
            int n = bg_rows * bgw;
            const unsigned *src = bg_mem + (j - 1) * bgphw;
            unsigned *dst = bg_mem + j * bgphw;
            if (PPW == 8)
                for (i = 0; i < n - 1; i++)
                    dst[i] = src[i] >> 4 | src[i + 1] << 28;
            else
                for (i = 0; i < n - 1; i++)
                    dst[i] = src[i] >> 8 | src[i + 1] << 24;
            dst[n - 1] = 0;
        } else {
            Surface d;
            gfx_init(&d, bg_mem + j * bgphw, bx, bg_rows, bgw, ph0->fmt);
            gfx_blit(&d, 0, 0, ph0, j, 0, bx - j, bg_rows, ROP_COPY);
        }
    }
    /* each background line's descriptor, unscrolled */
    for (y = 0; y < HY; y++) {
        int r = -1;
        if (y >= CL0 && y < CL1)
            r = y - CL0, bg_band[y] = 1;
        else if (y >= MT0)
            r = CL1 - CL0 + y - MT0, bg_band[y] = 2;
        else
            bg_band[y] = 0;
        if (r >= 0)
            bg_word[y] = video_word(bg_mem + r * bgw);
        else
            bg_word[y] = video_word(M1 ? sky_mem + sky_index(y) * LW : sky_mem);
        if (!M1) {
            int bank;
            if (sky_irq) {
                bank = SKY_BANK + ((y >> 2) & 1);
                if ((y & 3) == 0 && y > 0)
                    bg_word[y] |= 1u << 23;
            } else {
                /* 14 levels, an ordered dither between them by line */
                static const unsigned char dith[4] = {0, 2, 1, 3};
                int t = y * 13 * 4 / HY;
                bank = SKY_BANK + (t >> 2) + ((t & 3) > dith[y & 3]);
            }
            bg_word[y] |= (unsigned)bank << 19;
        }
    }
}

static void *alloc1(unsigned bytes, const char *what)
{
    void *p = vram_alloc(bytes);
    if (!p) {
        printf("bank 1 is full: %s (%u bytes)\n", what, bytes);
        printf("@done\n");
        for (;;)
            ;
    }
    return p;
}

void scene_build(void)
{
    int i;
    unsigned room, before;
    Surface s;
    rpx = RP * PPW;
    row_c = rpx / 2;
    copyw = (NROWS + 2) * RP;
    before = (unsigned)vram_alloc(0);
    /* the scratch pools: every line in the software road, else as many as
       sprites are likely to cover */
    pool_lines = soft ? NLINES : 320;
    for (i = 0; i < 2; i++)
        pool[i] = (unsigned *)alloc1((pool_lines * SPITCH + 2 * SLACK) * 4, "pool") + SLACK;
    if (!soft)
        road_mem = alloc1(8 * copyw * 4, "road");
    sky_mem = alloc1((M1 ? 64 : 1) * LW * 4, "sky");
    {
        unsigned *g = alloc1(LW * 4, "grass");
        int b[2];
        unsigned cw[1];
        b[0] = 0;
        b[1] = W;
        cw[0] = colour_word(C_GRASS, 1);
        spans(g, b, cw, 1);
        grass_desc = video_word(g) | (M1 ? 0 : 1u << 19);
    }
    for (i = 0; i < 2; i++) {
        hud_mem[i] = alloc1(HUD_LINES * LW * 4, "hud");
        memset(hud_mem[i], 0, HUD_LINES * LW * 4);
    }
    hud_glyphs();
    for (i = 0; i < (M1 ? 64 : 1); i++) {
        int b[2];
        unsigned cw[1];
        b[0] = 0;
        b[1] = W;
        cw[0] = gfx_solidf(F, M1 ? i : C_SKY);
        spans(sky_mem + i * LW, b, cw, 1);
    }
    /* the bands get what's left: the period PB from the room for NPH
       copies of their rows */
    bg_rows = (CL1 - CL0) + (HY - MT0);
    room = (unsigned)BANK1_END - (unsigned)vram_alloc(0) - 64;
    pb = (int)(room / 4 / NPH / bg_rows) - LW - 1;
    pb &= ~7;
    if (pb > 160)
        pb = 160;
    bgw = pb + LW + 1;
    bgphw = bg_rows * bgw;
    bg_mem = alloc1(NPH * bgphw * 4, "background");
    bank1_used = (unsigned)vram_alloc(0) - before;
    printf("bank 1: %u bytes (pools %u, road %u, background %u: period %d words)\n",
           bank1_used + 0x2000, 2 * (pool_lines * SPITCH + 2 * SLACK) * 4,
           soft ? 0 : 8 * copyw * 4, NPH * bgphw * 4, pb);
    build_road();
    gfx_init(&s, bg_mem, bgw * PPW, bg_rows, bgw, gfx_screen_format());
    build_background(&s);
}

/* the background lines from the HUD down to the road (or the horizon),
   scrolled: the clouds at half the mountains' rate */
void scene_bg_desc(unsigned *desc)
{
    int y, end = road_top < HY ? road_top : HY, band;
    unsigned add[3];
    add[0] = 0;
    for (band = 1; band < 3; band++) {
        int pbx = pb * PPW, o = (bg_scroll[band - 1] >> (8 + XS)) % pbx;
        if (o < 0)
            o += pbx;
        add[band] = (o & (PPW - 1)) * bgphw + (o >> PS);
    }
    for (y = HUD_LINES; y < end; y++)
        desc[y] = bg_word[y] + add[bg_band[y]];
}

/* ---- the HUD: text in table t's buffer, a field redrawn when it changes ---- */

static char hud_text[2][4][16];
static int hud_speed, nhud;
/* the HUD's characters drawn once, a cell font's 8 x 16 cell each (a
   word wide in M0, two in M1): a character is then 16 or 32 words */
static const char glyph_chars[] = " 0123456789:.kmh/LAP";
static unsigned *glyphs;
static int glyph_pitch;

static void hud_glyphs(void)
{
    Surface gs;
    int n = sizeof glyph_chars - 1;
    glyph_pitch = n * 8 / PPW;
    glyphs = malloc(glyph_pitch * 16 * 4);
    gfx_init(&gs, glyphs, n * 8, 16, glyph_pitch, gfx_screen_format());
    font_cells(&gs, 0, 0, glyph_chars, n, col_index[C_YELLOW], col_index[C_SKY]);
}

/* a field at x (a multiple of 8): the characters that changed */
static void hud_field(int t, int f, int x, const char *s)
{
    int i, r, cw = 8 / PPW;
    char *old = hud_text[t][f];
    for (i = 0; s[i]; i++) {
        const char *g;
        const unsigned *src;
        unsigned *dst;
        if (old[i] == s[i])
            continue;
        g = strchr(glyph_chars, s[i]);
        src = glyphs + (g ? g - glyph_chars : 0) * cw;
        dst = hud_mem[t] + 2 * LW + (x >> PS) + i * cw;
        for (r = 0; r < 16; r++) {
            dst[0] = src[0];
            if (cw > 1)
                dst[1] = src[1];
            src += glyph_pitch;
            dst += LW;
        }
    }
    strcpy(old, s);
}

/* n as `digits` digits at s (zero-padded if zero, else spaces) */
static char *digits(char *s, int n, int digits, int zero)
{
    int i;
    for (i = digits - 1; i >= 0; i--) {
        s[i] = n || zero || i == digits - 1 ? '0' + n % 10 : ' ';
        n /= 10;
    }
    return s + digits;
}

void hud_draw(int t, unsigned *desc)
{
    char buf[16], *p;
    int y, fr = lap_frames;
    unsigned w = video_word(hud_mem[t]);
    for (y = 0; y < HUD_LINES; y++) {
        unsigned bank = 0;
        if (!M1)
            bank = sky_irq ? SKY_BANK + ((y >> 2) & 1) : SKY_BANK;
        desc[y] = (w + y * LW) | bank << 19 | ((sky_irq && y && !(y & 3)) ? 1u << 23 : 0);
    }
    /* the fields, by hand: sprintf costs more than the rest of the HUD */
    if (!(nhud++ & 3))
        hud_speed = speed * 2;  /* the speed every 4 frames: it's a redraw each change */
    p = digits(buf, hud_speed, 3, 0);
    strcpy(p, " km/h");
    hud_field(t, 0, 8, buf);
    strcpy(buf, "LAP ");
    *digits(buf + 4, lap, 1, 0) = 0;
    hud_field(t, 1, (W / 2 - 20) & ~7, buf);
    p = digits(buf, fr / 3600, 1, 1);
    *p++ = ':';
    p = digits(p, fr / 60 % 60, 2, 1);
    *p++ = '.';
    *digits(p, fr % 60 / 6, 1, 1) = 0;
    hud_field(t, 2, W - 8 * 8 - 8, buf);
}

/* ---- the sky by line interrupts (M0, sky_irq) ---- */

/* the frame's end: groups 0 and 1's colours */
void sky_irq_frame(void)
{
    VID_PAL(16 * SKY_BANK) = grad[0];
    VID_PAL(16 * SKY_BANK + 16) = grad[1];
}

/* group g's first line is being set up: group g + 1's colour into the
   bank group g doesn't show */
void sky_line_hook(int y)
{
    int g = (y + 1) >> 2;
    sky_irqs++;
    if (g < NGRAD)
        VID_PAL(16 * (SKY_BANK + ((g + 1) & 1))) = grad[g + 1];
}
