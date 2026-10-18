/* The art, all original and made at start-up: the palettes, the terrain
   tiles (drawn with the library from a few rules and the random numbers),
   the units (string art), pre-shifted into sprites at every pixel phase
   of a word, the buildings and the two cursors. */

#include <stdlib.h>
#include <string.h>
#include "rts.h"

/* ---- the palettes: the map's 16 and the HUD's 16 ----
   M0 puts the map in palette bank 0 and the HUD in bank 1 (the
   descriptors pick a line's bank); M1 has 256 entries, the map at 0-15
   and the HUD at 16-31. The cursor's are 253-255 in both. */

/* the map's colours, by the letters the art uses */
enum {
    C_BLACK, C_GRASS, C_GRASS_L, C_WATER, C_WATER_L, C_SAND, C_TREE, C_TREE_L, C_BROWN, C_ROCK,
    C_ROCK_L, C_STONE, C_BLUE, C_RED, C_YELLOW, C_WHITE
};
static const unsigned char map_rgb[16][3] = {
    {12, 12, 16}, {58, 112, 42}, {94, 150, 60}, {32, 72, 150}, {86, 146, 214}, {214, 192, 124},
    {22, 72, 34}, {54, 124, 50}, {112, 72, 36}, {98, 98, 104}, {168, 168, 172}, {218, 206, 178},
    {52, 98, 236}, {214, 44, 40}, {250, 222, 64}, {255, 255, 255},
};

/* the HUD's */
enum {
    H_BLACK, H_DARK, H_MID, H_LIGHT, H_TEXT, H_YELLOW, H_GRASS, H_WATER, H_TREE, H_ROCK, H_SAND,
    H_BLUE, H_RED, H_BROWN, H_GREEN, H_WHITE
};
static const unsigned char hud_rgb[16][3] = {
    {0, 0, 0}, {36, 40, 50}, {74, 80, 94}, {128, 136, 150}, {226, 228, 218}, {250, 210, 64},
    {64, 132, 54}, {44, 94, 186}, {24, 82, 36}, {126, 126, 130}, {204, 182, 112}, {74, 124, 255},
    {240, 64, 60}, {112, 72, 36}, {84, 224, 84}, {255, 255, 255},
};

void palette_init(void)
{
    int n;
    for (n = 0; n < 16; n++) {
        video_pal_rgb(n, map_rgb[n][0], map_rgb[n][1], map_rgb[n][2]);
        video_pal_rgb(16 + n, hud_rgb[n][0], hud_rgb[n][1], hud_rgb[n][2]);
    }
    video_pal(253, rgb565(0, 0, 0));
    video_pal(254, rgb565(255, 255, 255));
    video_pal(255, rgb565(255, 224, 40));
}

/* ---- the tiles ---- */
unsigned *tiles;
int tile_words;
static Surface ts;              /* the tiles as one surface, 16 wide, tile k at row 16k */

static void tile_grass(int k, int tufts, int flowers)
{
    int y0 = TILE * k, n;
    gfx_fill(&ts, 0, y0, TILE, y0 + TILE, C_GRASS, ROP_COPY);
    for (n = 0; n < tufts; n++) {
        int x = rnd_n(TILE), y = y0 + 1 + rnd_n(TILE - 1);
        gfx_pixel(&ts, x, y, C_GRASS_L, ROP_COPY);
        gfx_pixel(&ts, x, y - 1, C_GRASS_L, ROP_COPY);
        if (x + 1 < TILE && rnd_n(2))
            gfx_pixel(&ts, x + 1, y, C_GRASS_L, ROP_COPY);
    }
    for (n = 0; n < flowers; n++) {
        int x = 1 + rnd_n(TILE - 2), y = y0 + 1 + rnd_n(TILE - 2);
        unsigned c = rnd_n(2) ? C_YELLOW : C_WHITE;
        gfx_pixel(&ts, x, y, c, ROP_COPY);
        gfx_pixel(&ts, x, y + 1, C_TREE, ROP_COPY);
    }
}

static void tile_sand(int k)
{
    int y0 = TILE * k, n;
    gfx_fill(&ts, 0, y0, TILE, y0 + TILE, C_SAND, ROP_COPY);
    for (n = 0; n < 7; n++)
        gfx_pixel(&ts, rnd_n(TILE), y0 + rnd_n(TILE), n & 1 ? C_BROWN : C_STONE, ROP_COPY);
}

static void tile_tree(int k, int small)
{
    int y0 = TILE * k;
    tile_grass(k, 4, 0);
    if (small) {
        /* two small trees */
        gfx_fill(&ts, 4, y0 + 7, 6, y0 + 10, C_BROWN, ROP_COPY);
        gfx_fill_circle(&ts, 5, y0 + 5, 4, C_TREE, ROP_COPY);
        gfx_circle(&ts, 5, y0 + 5, 4, C_BLACK, ROP_COPY);
        gfx_fill_circle(&ts, 4, y0 + 4, 1, C_TREE_L, ROP_COPY);
        gfx_fill(&ts, 10, y0 + 13, 12, y0 + 16, C_BROWN, ROP_COPY);
        gfx_fill_circle(&ts, 11, y0 + 10, 4, C_TREE, ROP_COPY);
        gfx_circle(&ts, 11, y0 + 10, 4, C_BLACK, ROP_COPY);
        gfx_fill_circle(&ts, 10, y0 + 9, 1, C_TREE_L, ROP_COPY);
        return;
    }
    gfx_fill(&ts, 7, y0 + 11, 9, y0 + 16, C_BROWN, ROP_COPY);
    gfx_fill_circle(&ts, 8, y0 + 7, 6, C_TREE, ROP_COPY);
    gfx_circle(&ts, 8, y0 + 7, 6, C_BLACK, ROP_COPY);
    gfx_fill_circle(&ts, 6, y0 + 5, 2, C_TREE_L, ROP_COPY);
    gfx_pixel(&ts, 10, y0 + 8, C_TREE_L, ROP_COPY);
    gfx_pixel(&ts, 9, y0 + 4, C_TREE_L, ROP_COPY);
}

static void tile_rock(int k, int small)
{
    int y0 = TILE * k;
    tile_grass(k, 5, 0);
    if (small) {
        gfx_fill_circle(&ts, 5, y0 + 10, 3, C_ROCK, ROP_COPY);
        gfx_circle(&ts, 5, y0 + 10, 3, C_BLACK, ROP_COPY);
        gfx_pixel(&ts, 4, y0 + 9, C_ROCK_L, ROP_COPY);
        gfx_fill_circle(&ts, 11, y0 + 6, 3, C_ROCK, ROP_COPY);
        gfx_circle(&ts, 11, y0 + 6, 3, C_BLACK, ROP_COPY);
        gfx_fill(&ts, 10, y0 + 5, 12, y0 + 6, C_ROCK_L, ROP_COPY);
        return;
    }
    gfx_fill_circle(&ts, 8, y0 + 9, 6, C_ROCK, ROP_COPY);
    gfx_circle(&ts, 8, y0 + 9, 6, C_BLACK, ROP_COPY);
    gfx_fill_circle(&ts, 6, y0 + 7, 2, C_ROCK_L, ROP_COPY);
    gfx_line(&ts, 9, y0 + 6, 12, y0 + 10, C_BLACK, ROP_COPY);
}

/* water, with a shore on its land sides (bit 0 north, 1 east, 2 south, 3 west) */
static void tile_water(int k, int sides)
{
    int y0 = TILE * k, n;
    gfx_fill(&ts, 0, y0, TILE, y0 + TILE, C_WATER, ROP_COPY);
    for (n = 0; n < 3; n++) {
        int x = rnd_n(TILE - 4), y = y0 + 2 + rnd_n(TILE - 4);
        gfx_hline(&ts, x, x + 3, y, C_WATER_L, ROP_COPY);
    }
    if (sides & 1) {
        gfx_hline(&ts, 0, TILE, y0, C_SAND, ROP_COPY);
        gfx_hline(&ts, 0, TILE, y0 + 1, C_WATER_L, ROP_COPY);
    }
    if (sides & 4) {
        gfx_hline(&ts, 0, TILE, y0 + TILE - 1, C_SAND, ROP_COPY);
        gfx_hline(&ts, 0, TILE, y0 + TILE - 2, C_WATER_L, ROP_COPY);
    }
    if (sides & 2) {
        gfx_vline(&ts, TILE - 1, y0, y0 + TILE, C_SAND, ROP_COPY);
        gfx_vline(&ts, TILE - 2, y0 + (sides & 1 ? 1 : 0), y0 + TILE - (sides & 4 ? 1 : 0),
                  C_WATER_L, ROP_COPY);
    }
    if (sides & 8) {
        gfx_vline(&ts, 0, y0, y0 + TILE, C_SAND, ROP_COPY);
        gfx_vline(&ts, 1, y0 + (sides & 1 ? 1 : 0), y0 + TILE - (sides & 4 ? 1 : 0), C_WATER_L,
                  ROP_COPY);
    }
}

/* a base: a 3 x 3 tile hall in the team's colour, drawn whole and cut into tiles */
static void tile_base(int team)
{
    Surface b;
    int words = 3 * TILE / ppw, k, x, y;
    unsigned *bits = malloc(words * 4 * 3 * TILE);
    unsigned roof = team ? C_RED : C_BLUE;
    gfx_init(&b, bits, 3 * TILE, 3 * TILE, words, fmt);
    gfx_fill(&b, 0, 0, 48, 48, C_GRASS, ROP_COPY);
    for (k = 0; k < 30; k++) {
        x = rnd_n(48);
        y = 1 + rnd_n(47);
        gfx_pixel(&b, x, y, C_GRASS_L, ROP_COPY);
        gfx_pixel(&b, x, y - 1, C_GRASS_L, ROP_COPY);
    }
    /* a yard of sand, the walls, the roof, a door, windows and a flag */
    gfx_fill(&b, 2, 30, 46, 47, C_SAND, ROP_COPY);
    gfx_fill(&b, 6, 18, 42, 42, C_STONE, ROP_COPY);
    gfx_frame(&b, 6, 18, 42, 42, 1, C_BLACK, ROP_COPY);
    for (y = 22; y < 42; y += 5)
        gfx_hline(&b, 7, 41, y, C_ROCK_L, ROP_COPY);
    for (k = 0; k < 14; k++) {
        gfx_hline(&b, 6 + k, 42 - k, 18 - k, roof, ROP_COPY);
        gfx_pixel(&b, 6 + k, 18 - k, C_BLACK, ROP_COPY);
        gfx_pixel(&b, 41 - k, 18 - k, C_BLACK, ROP_COPY);
    }
    gfx_hline(&b, 3, 45, 18, C_BLACK, ROP_COPY);
    gfx_hline(&b, 4, 44, 19, C_BROWN, ROP_COPY);
    gfx_fill(&b, 20, 30, 28, 42, C_BROWN, ROP_COPY);
    gfx_frame(&b, 20, 30, 28, 42, 1, C_BLACK, ROP_COPY);
    gfx_fill(&b, 10, 26, 16, 31, C_WATER, ROP_COPY);
    gfx_frame(&b, 10, 26, 16, 31, 1, C_BLACK, ROP_COPY);
    gfx_fill(&b, 32, 26, 38, 31, C_WATER, ROP_COPY);
    gfx_frame(&b, 32, 26, 38, 31, 1, C_BLACK, ROP_COPY);
    gfx_vline(&b, 24, 0, 6, C_BLACK, ROP_COPY);
    gfx_fill(&b, 25, 0, 32, 4, roof, ROP_COPY);
    gfx_pixel(&b, 28, 1, C_WHITE, ROP_COPY);
    for (y = 0; y < 3; y++)
        for (x = 0; x < 3; x++)
            gfx_blit(&ts, 0, TILE * (T_BASE + 9 * team + 3 * y + x), &b, TILE * x, TILE * y, TILE,
                     TILE, ROP_COPY);
    free(bits);
}

void tiles_make(void)
{
    int k;
    tile_words = TILE * TILE / ppw;
    tiles = malloc(T_N * tile_words * 4);
    gfx_init(&ts, tiles, TILE, TILE * T_N, TILE / ppw, fmt);
    tile_grass(T_GRASS, 6, 0);
    tile_grass(T_GRASS2, 10, 0);
    tile_grass(T_GRASS3, 3, 0);
    tile_grass(T_GRASS4, 8, 0);
    tile_grass(T_FLOWER, 4, 3);
    tile_sand(T_SAND);
    tile_sand(T_SAND2);
    tile_tree(T_TREE, 0);
    tile_tree(T_TREE2, 1);
    tile_rock(T_ROCK, 0);
    tile_rock(T_ROCK2, 1);
    for (k = 0; k < 16; k++)
        tile_water(T_WATER + k, k);
    tile_base(0);
    tile_base(1);
}

/* ---- the units: 12 x 12, facing right, two steps each ----
   k black (the outline: yellow when selected), s skin, B the team's
   colour, b brown, R and r light and dark grey, o white */
static const char *worker_art[2][12] = {
    {
        "    kkkk    ",
        "   kbbbbk   ",
        "  kbbbbbbk  ",
        "   kssksk RR",
        "   kssssk b ",
        "  kkBBBBkkb ",
        " kBBBBBBBsb ",
        " kBBBBBBkkb ",
        "  kBBBBBk  b",
        "   kb kb    ",
        "   kb kb    ",
        "   kk kk    ",
    },
    {
        "    kkkk    ",
        "   kbbbbk   ",
        "  kbbbbbbk  ",
        "   kssksk   ",
        "   kssssk RR",
        "  kkBBBBkkb ",
        " kBBBBBBBsb ",
        " kBBBBBBkkb ",
        "  kBBBBBk  b",
        "  kb   kb   ",
        " kb     kb  ",
        " kk     kk  ",
    },
};

static const char *soldier_art[2][12] = {
    {
        "    kkk   o ",
        "   kRRRk  o ",
        "  kRRRRRk o ",
        "   ksksk  o ",
        "   kssk   o ",
        "  kkBBBkkkso",
        " kBBBBBBk o ",
        " kBRRRRBk o ",
        " kBBBBBBk o ",
        "  kbkkbk  o ",
        "  kb  kb    ",
        "  kk  kk    ",
    },
    {
        "    kkk     ",
        "   kRRRk  o ",
        "  kRRRRRk o ",
        "   ksksk  o ",
        "   kssk   o ",
        "  kkBBBkkkso",
        " kBBBBBBk o ",
        " kBRRRRBk o ",
        " kBBBBBBk o ",
        "  kbkkbk  o ",
        " kb    kb o ",
        " kk    kk   ",
    },
};

/* a letter's colour: the map's index; -1 transparent */
static int art_colour(char ch, int team, int sel)
{
    switch (ch) {
    case 'k': return sel ? C_YELLOW : C_BLACK;
    case 's': return C_SAND;
    case 'B': return team ? C_RED : C_BLUE;
    case 'b': return C_BROWN;
    case 'R': return C_ROCK_L;
    case 'r': return C_ROCK;
    case 'o': return C_WHITE;
    default: return -1;
    }
}

Sprite sprites[32];

/* one unit picture pre-shifted to every phase: for phase p it starts p
   pixels into its first word; each row is n (keep, image) word pairs */
static void sprite_make(Sprite *sp, const char *const *art, int team, int facing, int sel)
{
    Surface img, keep, img0, keep0;
    int maxw = (ppw - 1 + SPR_W + ppw - 1) / ppw;
    unsigned *ib = malloc(maxw * 4 * SPR_H), *kb = malloc(maxw * 4 * SPR_H);
    unsigned *ib0 = malloc(maxw * 4 * SPR_H), *kb0 = malloc(maxw * 4 * SPR_H);
    int p, x, y, top = SPR_H, bot = 0, w;
    unsigned all = (1u << bpp) - 1;
    /* the picture once, at phase 0, pixel by pixel; the other phases are
       shifted copies of it */
    gfx_init(&img0, ib0, maxw * ppw, SPR_H, maxw, fmt);
    gfx_init(&keep0, kb0, maxw * ppw, SPR_H, maxw, fmt);
    gfx_fill(&img0, 0, 0, maxw * ppw, SPR_H, 0, ROP_COPY);
    gfx_fill(&keep0, 0, 0, maxw * ppw, SPR_H, all, ROP_COPY);
    for (y = 0; y < SPR_H; y++)
        for (x = 0; x < SPR_W; x++) {
            int c = art_colour(art[y][facing ? SPR_W - 1 - x : x], team, sel);
            if (c >= 0) {
                gfx_pixel(&img0, x, y, c, ROP_COPY);
                gfx_pixel(&keep0, x, y, 0, ROP_COPY);
            }
        }
    for (y = 0; y < SPR_H; y++)
        for (x = 0; x < SPR_W; x++)
            if (art[y][x] != ' ') {
                if (y < top)
                    top = y;
                if (y + 1 > bot)
                    bot = y + 1;
            }
    sp->y0 = top + (16 - SPR_H);    /* the 12 rows sit at the bottom of the 16-pixel cell */
    sp->h = bot - top;
    for (p = 0; p < ppw; p++) {
        int n = (p + SPR_W - 1) / ppw + 1;
        unsigned *d;
        gfx_init(&img, ib, n * ppw, SPR_H, n, fmt);
        gfx_init(&keep, kb, n * ppw, SPR_H, n, fmt);
        gfx_fill(&img, 0, 0, n * ppw, SPR_H, 0, ROP_COPY);
        gfx_fill(&keep, 0, 0, n * ppw, SPR_H, all, ROP_COPY);
        gfx_blit(&img, p, 0, &img0, 0, 0, SPR_W, SPR_H, ROP_COPY);
        gfx_blit(&keep, p, 0, &keep0, 0, 0, SPR_W, SPR_H, ROP_COPY);
        sp->n[p] = n;
        sp->data[p] = d = malloc(sp->h * n * 8);
        for (y = top; y < bot; y++)
            for (w = 0; w < n; w++) {
                *d++ = kb[y * n + w];
                *d++ = ib[y * n + w];
            }
    }
    free(ib);
    free(kb);
    free(ib0);
    free(kb0);
}

void sprites_make(void)
{
    int type, team, facing, step, sel;
    for (type = 0; type < 2; type++)
        for (team = 0; team < 2; team++)
            for (facing = 0; facing < 2; facing++)
                for (step = 0; step < 2; step++)
                    for (sel = 0; sel < 2; sel++)
                        sprite_make(&sprites[SPR_INDEX(type, team, facing, step, sel)],
                                    type ? soldier_art[step] : worker_art[step], team, facing, sel);
}

/* a unit's icon in the HUD, at twice the size (M1: twice the height, its
   pixels being two wide already) */
void icon_draw(Surface *s, int x, int y, int type, int team)
{
    const char *const *art = type ? soldier_art[0] : worker_art[0];
    int sx = mode ? 1 : 2, sy = 2, i, j;
    static const unsigned char to_hud[16] = {
        H_BLACK, H_GRASS, H_GRASS, H_WATER, H_WATER, H_SAND, H_TREE, H_TREE, H_BROWN, H_ROCK,
        H_LIGHT, H_TEXT, H_BLUE, H_RED, H_YELLOW, H_WHITE,
    };
    for (j = 0; j < SPR_H; j++)
        for (i = 0; i < SPR_W; i++) {
            int c = art_colour(art[j][i], team, 0);
            if (c >= 0)
                gfx_fill(s, x + sx * i, y + sy * j, x + sx * (i + 1), y + sy * (j + 1),
                         hud_base + to_hud[c], ROP_COPY);
        }
}

/* ---- the cursors (C1): 32 x 32, 2 bits a pixel; 1 black, 2 white, 3 yellow ---- */
unsigned *cursor_arrow, *cursor_target;

static const char *arrow_art[] = {
    "1", "11", "121", "1221", "12221", "122221", "1222221", "12222221", "122222221",
    "1222222221", "12222211111", "1221221", "121 1221", "11  1221", "1    1221", "     1221",
    "      11", 0,
};

static unsigned *cursor_image(const char **art)
{
    unsigned *img = vram_alloc(32 * 8);
    int y, x;
    memset(img, 0, 32 * 8);
    for (y = 0; art[y]; y++)
        for (x = 0; art[y][x]; x++)
            if (art[y][x] >= '1' && art[y][x] <= '3')
                img[2 * y + x / 16] |= (unsigned)(art[y][x] - '0') << (2 * (x % 16));
    return img;
}

/* the target: a yellow ring outlined in black and four ticks toward the
   hotspot, (15, 15) */
static unsigned *target_image(void)
{
    unsigned *img = vram_alloc(32 * 8);
    int y, x;
    memset(img, 0, 32 * 8);
    for (y = 0; y < 31; y++)
        for (x = 0; x < 31; x++) {
            int dx = x - 15, dy = y - 15, d2 = dx * dx + dy * dy, ax = dx < 0 ? -dx : dx;
            int ay = dy < 0 ? -dy : dy, v = 0;
            if (d2 >= 81 && d2 <= 110)
                v = 3;
            else if ((d2 >= 64 && d2 < 81) || (d2 > 110 && d2 <= 132))
                v = 1;
            if ((ax == 0 && ay >= 4 && ay <= 9) || (ay == 0 && ax >= 4 && ax <= 9))
                v = 3;
            else if (((ax == 1 && ay >= 3 && ay <= 9) || (ay == 1 && ax >= 3 && ax <= 9)) && !v)
                v = 1;
            if (d2 == 0)
                v = 3;
            else if (d2 <= 2 && !v)
                v = 1;
            img[2 * y + x / 16] |= (unsigned)v << (2 * (x % 16));
        }
    return img;
}

void cursors_make(void)
{
    cursor_arrow = cursor_image(arrow_art);
    cursor_target = target_image();
}
