/* The art, all original and drawn here as strings of characters, one a
   pixel ('.' is transparent), and its conversion at the start into words
   in the screen's format: tiles and sprites pre-shifted to the 4 pixel
   phases of a word, with masks for the sprites; the parallax bands
   painted procedurally and pre-shifted too. The format comes from the
   library (gfx_bitpos), so the same code makes L0's bytes or L1's
   scattered bits. */

#include <stdlib.h>
#include <string.h>
#include "gfx.h"
#include "video.h"
#include "game.h"

/* ---- the palette (M1: the pixel is the palette index) ---- */

/* the art's characters and their colours, palette entries from 128 */
static const struct {
    char ch;
    unsigned char r, g, b;
} art_colours[] = {
    {'k', 30, 22, 32},    {'g', 165, 232, 75},  {'G', 95, 190, 48},   {'h', 42, 122, 44},
    {'d', 168, 108, 62},  {'D', 118, 72, 42},   {'l', 204, 148, 92},  {'s', 150, 152, 165},
    {'S', 96, 98, 115},   {'t', 200, 202, 214}, {'r', 204, 88, 52},   {'R', 138, 52, 36},
    {'m', 228, 208, 178}, {'y', 255, 214, 60},  {'Y', 206, 140, 30},  {'z', 255, 246, 196},
    {'w', 250, 250, 246}, {'o', 242, 138, 36},  {'O', 186, 86, 26},   {'e', 18, 14, 26},
    {'p', 156, 82, 204},  {'P', 96, 46, 138},   {'q', 210, 165, 244}, {'c', 226, 46, 56},
    {'C', 150, 26, 36},   {'n', 172, 116, 66},  {'N', 112, 74, 44},   {'f', 252, 128, 188},
    {'x', 188, 188, 198}, {'X', 112, 112, 124}, {'u', 86, 158, 92},   {'v', 64, 132, 78},
    {'V', 44, 102, 64},   {'b', 104, 78, 58},   {'B', 74, 56, 44},    {0, 0, 0, 0},
};
#define ART_BASE 128

/* the bands' and the HUD's colours */
#define SKY_C 16                /* 16 shades down the sky and behind the mountains */
#define CLOUD_C 32              /* white, light, shadow */
#define MTN_C 40                /* far, far shadow, near, near shadow, snow, snow shadow, haze */
#define HILL_C 48               /* light, hill, dark, tree, tree dark */
#define PF_C 64                 /* 16 shades down the playfield */
#define HUD_C 8                 /* background, text, dim, gold, bar */

static int art_index[128];      /* character -> palette entry, -1 transparent */

static unsigned char lerp(int a, int b, int i, int n)
{
    return a + (b - a) * i / n;
}

static void ramp(int base, int n, int r0, int g0, int b0, int r1, int g1, int b1)
{
    int i;
    for (i = 0; i < n; i++)
        video_pal_rgb(base + i, lerp(r0, r1, i, n - 1), lerp(g0, g1, i, n - 1),
                      lerp(b0, b1, i, n - 1));
}

void palette_init(void)
{
    int i;
    for (i = 0; i < 128; i++)
        art_index[i] = -1;
    for (i = 0; art_colours[i].ch; i++) {
        art_index[(int)art_colours[i].ch] = ART_BASE + i;
        video_pal_rgb(ART_BASE + i, art_colours[i].r, art_colours[i].g, art_colours[i].b);
    }
    video_pal_rgb(0, 0, 0, 0);
    /* the HUD */
    video_pal_rgb(HUD_C, 24, 26, 48);
    video_pal_rgb(HUD_C + 1, 245, 245, 250);
    video_pal_rgb(HUD_C + 2, 140, 150, 190);
    video_pal_rgb(HUD_C + 3, 255, 210, 70);
    video_pal_rgb(HUD_C + 4, 70, 76, 120);
    /* the sky, deep blue to pale over lines 16-95 */
    ramp(SKY_C, 16, 52, 98, 196, 182, 216, 246);
    video_pal_rgb(CLOUD_C, 252, 252, 255);
    video_pal_rgb(CLOUD_C + 1, 222, 232, 250);
    video_pal_rgb(CLOUD_C + 2, 172, 188, 228);
    /* the mountains */
    video_pal_rgb(MTN_C, 150, 156, 210);
    video_pal_rgb(MTN_C + 1, 122, 126, 186);
    video_pal_rgb(MTN_C + 2, 104, 104, 168);
    video_pal_rgb(MTN_C + 3, 80, 80, 140);
    video_pal_rgb(MTN_C + 4, 244, 246, 255);
    video_pal_rgb(MTN_C + 5, 196, 204, 238);
    video_pal_rgb(MTN_C + 6, 132, 164, 168);
    /* the hills */
    video_pal_rgb(HILL_C, 128, 196, 104);
    video_pal_rgb(HILL_C + 1, 96, 170, 88);
    video_pal_rgb(HILL_C + 2, 70, 140, 80);
    video_pal_rgb(HILL_C + 3, 52, 112, 72);
    video_pal_rgb(HILL_C + 4, 36, 86, 60);
    /* the playfield: a forest's shade, light at the top */
    ramp(PF_C, 16, 112, 178, 132, 58, 120, 96);
    /* the cursor's (C1): the bird */
    video_pal_rgb(253, 30, 22, 32);
    video_pal_rgb(254, 226, 46, 56);
    video_pal_rgb(255, 250, 250, 246);
}

unsigned pf_bg(int y)
{
    return PF_C + (y >> 3);
}

/* ---- pixels in the screen's format ---- */

static unsigned pix_tab[4][256];
unsigned pix_mask[4];

static void pix_init(void)
{
    int fmt = gfx_screen_format(), p, c, i;
    for (p = 0; p < 4; p++)
        for (c = 0; c < 256; c++) {
            unsigned w = 0;
            for (i = 0; i < 8; i++)
                if (c >> i & 1)
                    w |= 1u << gfx_bitpos(fmt, p, i);
            pix_tab[p][c] = w;
        }
    for (p = 0; p < 4; p++)
        pix_mask[p] = pix_tab[p][255];
}

unsigned pix(int p, int c)
{
    return pix_tab[p][c & 255];
}

unsigned pack4(int c0, int c1, int c2, int c3)
{
    return pix_tab[0][c0] | pix_tab[1][c1] | pix_tab[2][c2] | pix_tab[3][c3];
}

/* ---- tiles: 16 x 16 ---- */

static const char *const tile_grass[] = {
    "..h......h....h.", ".hgh..h.hgh..hg.", "hgGgh.hhgGghhgGh", "gGGGghgGGGGggGGg",
    "GGGGGGGGGGGGGGGG", "GGhGGGGGhGGGGhGG", "hGdhGGhGdhGhGdGh", "dhdddhdddddhdddd",
    "dddddddddddddddd", "ddlddddDddddlddd", "dddddDdddddddddD", "dDddddddlddDdddd",
    "ddddlddddddddddd", "ddddddDddddldddd", "dlddddddddDddddd", "ddddDddldddddddl",
};
static const char *const tile_grass_l[] = {
    "................", "......h....h...h", "...hhhgh.hhgh.hg", "..hgGGGghgGGghgG",
    ".hgGGGGGGGGGGGGG", ".hGGGhGGGGGhGGGG", "hGGdhGGhGdhGGhGd", "hdhdddhdddddhddd",
    "Dddddddddddddddd", "Ddlddddddddlddld", "DdddddDddddddddd", "DDddddddlddDdddd",
    "Dddlddddddddddld", "DdddddDddddldddd", "Dldddddddddddddd", "DDddDddldddddddl",
};
static const char *const tile_dirt[] = {
    "dddddDdddddddddd", "ddlddddddddldddd", "dddddddddDdddddd", "dDddddlddddddddD",
    "ddddddddddddlddd", "ddddsSdddddddddd", "dldddddddDdddddd", "ddddddddddddddld",
    "dddDddddlddddddd", "ddddddddddddDddd", "lddddddDdddddddd", "ddddddddddsSdddd",
    "ddDdddlddddddddd", "dddddddddddddDdd", "ddddlddDdddddddd", "dDdddddddddlddDd",
};
static const char *const tile_brick[] = {
    "mmmmmmmmmmmmmmmm", "rrrrrrrmrrrrrrrm", "rrrrrrRmrrrrrrRm", "rrrrrrRmrrrrrrRm",
    "rrrrrrRmrrrrrrRm", "rrrrrrRmrrrrrrRm", "rrrrrrRmrrrrrrRm", "RRRRRRRmRRRRRRRm",
    "mmmmmmmmmmmmmmmm", "rrrmrrrrrrrmrrrr", "rrRmrrrrrrRmrrrr", "rrRmrrrrrrRmrrrr",
    "rrRmrrrrrrRmrrrr", "rrRmrrrrrrRmrrrr", "rrRmrrrrrrRmrrrr", "RRRmRRRRRRRmRRRR",
};
static const char *const tile_block[] = {
    "kkkkkkkkkkkkkkkk", "kzzzzzzzzzzzzzyk", "kzyyyyyyyyyyyyYk", "kzyyyyyywyyyyyYk",
    "kzyyyyywwwyyyyYk", "kzywwwwwwwwwwwYk", "kzyywwwwwwwwwyYk", "kzyyywwwwwwwyyYk",
    "kzyyywwwwwwwyyYk", "kzyywwwwywwwwyYk", "kzyywwwyyywwwyYk", "kzywwyyyyyyywwYk",
    "kzyyyyyyyyyyyyYk", "kzyyyyyyyyyyyyYk", "kyYYYYYYYYYYYYYk", "kkkkkkkkkkkkkkkk",
};
static const char *const tile_used[] = {
    "kkkkkkkkkkkkkkkk", "knnnnnnnnnnnnnNk", "knNnnnnnnnnnNnNk", "knnnnnnnnnnnnnNk",
    "knnnnnnnnnnnnnNk", "knnnnnnnnnnnnnNk", "knnnnnnnnnnnnnNk", "knnnnnnnnnnnnnNk",
    "knnnnnnnnnnnnnNk", "knnnnnnnnnnnnnNk", "knnnnnnnnnnnnnNk", "knnnnnnnnnnnnnNk",
    "knNnnnnnnnnnNnNk", "knnnnnnnnnnnnnNk", "kNNNNNNNNNNNNNNk", "kkkkkkkkkkkkkkkk",
};
static const char *const tile_coin[] = {
    "................", "................", "......kkkk......", ".....kyyyyk.....",
    "....kyzzyyYk....", "....kyzyyyYk....", "....kyzyYyYk....", "....kyzyYyYk....",
    "....kyzyYyYk....", "....kyzyYyYk....", "....kyyyyyYk....", "....kyyyyYYk....",
    ".....kYYYYk.....", "......kkkk......", "................", "................",
};
static const char *const tile_bush[] = {
    "................", "................", "................", "..........hhhh..",
    "........hhGGGGhh", "......hhGGGgGGGG", ".....hGGgGGGGGGG", "....hGGGGGGGGgGG",
    "...hGGgGGGhGGGGG", "..hGGGGGGGGGGGGh", "..hGGGGGhGGGgGGG", ".hGGgGGGGGGGGGGh",
    ".hGGGGGGGhGGGGGG", "hGGGhGGGGGGGGhGG", "hhGGGGGGGGGGGGGh", "hhhhhhhhhhhhhhhh",
};
static const char *const tile_flower[] = {
    "................", "................", "................", "................",
    "................", "................", "................", "................",
    "................", ".......f........", "......fyf.......", ".......f....f...",
    ".......h...fyf..", "......hh....f...", ".......h...hh...", "......h.h...h...",
};
static const char *const tile_fence[] = {
    "................", "................", "................", "................",
    "..n.......n.....", ".nnN.....nnN....", ".nnN.....nnN....", "nnnnnnnnnnnnnnnn",
    "NNNNNNNNNNNNNNNN", ".nnN.....nnN....", ".nnN.....nnN....", ".nnN.....nnN....",
    "nnnnnnnnnnnnnnnn", "NNNNNNNNNNNNNNNN", ".nnN.....nnN....", ".nnN.....nnN....",
};
static const char *const tile_plank[] = {
    "kkkkkkkkkkkkkkkk", "nnnnnnnnnnnnnnnn", "nnNnnnnnnnnnNnnn", "NNNNNNNNNNNNNNNN",
    "kkkkkkkkkkkkkkkk", "..kN.......kN...", "...k........k...", "................",
    "................", "................", "................", "................",
    "................", "................", "................", "................",
};
static const char *const tile_stone[] = {
    "ttttttttttttttts", "tsssssssssssssSS", "tssssssssXssssSS", "tsssssssssssssSS",
    "tssXssssssssssSS", "tsssssssssssXsSS", "tsssssssssssssSS", "tssssssXssssssSS",
    "tsssssssssssssSS", "tsXsssssssssssSS", "tssssssssssXssSS", "tsssssssssssssSS",
    "tssssXssssssssSS", "tsssssssssssssSS", "sSSSSSSSSSSSSSSS", "SSSSSSSSSSSSSSSS",
};
static const char *const tile_spikes[] = {
    "................", "................", "................", "................",
    "................", "................", "................", "................",
    ".x...x...x...x..", ".x...x...x...x..", "xtX.xtX.xtX.xtX.", "xtX.xtX.xtX.xtX.",
    "xttXxttXxttXxttX", "xttXxttXxttXxttX", "SSSSSSSSSSSSSSSS", "XXXXXXXXXXXXXXXX",
};
static const char *const tile_pole[] = {
    "......kxXk......", "......kxXk......", "......kxXk......", "......kxXk......",
    "......kxXk......", "......kxXk......", "......kxXk......", "......kxXk......",
    "......kxXk......", "......kxXk......", "......kxXk......", "......kxXk......",
    "......kxXk......", "......kxXk......", "......kxXk......", "......kxXk......",
};
static const char *const tile_flag[] = {
    "......kyyk......", "......kyYk......", "......kxXk......", "kkkkkkkxXk......",
    "kcyycckxXk......", "kcyycckxXk......", "kccccckxXk......", ".kcccckxXk......",
    "..kccckxXk......", "...kkkkxXk......", "......kxXk......", "......kxXk......",
    "......kxXk......", "......kxXk......", "......kxXk......", "......kxXk......",
};

/* a tree in the background, 2 x 3 tiles: the left halves, the right ones
   mirrored */
static const char *const tile_crown_top[] = {
    "................", "................", "...........VVVVV", "........VVVvvvvv",
    "......VVvvvuvvvv", ".....Vvvvvvvvvuv", "....Vvvuvvvvvvvv", "...Vvvvvvvvvvvvv",
    "...Vvvvvvvuvvvvv", "..Vvvuvvvvvvvvvv", "..Vvvvvvvvvvvvuv", ".Vvvvvvvvvvvvvvv",
    ".Vvvvvuvvvvvvvvv", ".Vvvvvvvvvvvuvvv", "Vvvvvvvvvvvvvvvv", "Vvvuvvvvvvvvvvvv",
};
static const char *const tile_crown_bot[] = {
    "Vvvvvvvvvvvvvvvv", "Vvvvvvvvvvuvvvvv", "Vvvvvvvvvvvvvvvv", ".Vvvvuvvvvvvvvvv",
    ".VvvvvvvvvvvvvvV", ".VVvvvvvvvvvvvvV", "..VvvvvvVvvvvVVV", "...VVvvvVVvvVbbb",
    "....VVVV..VVVbbB", "............bbbB", "............bbbB", "............bbBB",
    "............bbbB", "............bbbB", "............bbBB", "............bbbB",
};
static const char *const tile_trunk[] = {
    "............bbbB", "............bbBB", "............bbbB", "............bbbB",
    "............bbBB", "............bbbB", "............bbbB", "............bbBB",
    "............bbbB", "............bbbB", "............bbBB", "............bbbB",
    "...........bbbbB", "..........bbbbBB", ".........bbbbbbB", "........bbbbbbBB",
};

/* each tile's art, and whether it's drawn mirrored */
static const struct {
    const char *const *art;
    int mirror;
} tile_art[T_N] = {
    {0, 0},             {tile_grass, 0}, {tile_grass_l, 0}, {tile_grass_l, 1},
    {tile_dirt, 0},     {tile_brick, 0}, {tile_block, 0},   {tile_used, 0},
    {tile_coin, 0},     {tile_bush, 0},  {tile_bush, 1},    {tile_flower, 0},
    {tile_fence, 0},    {tile_plank, 0}, {tile_stone, 0},   {tile_spikes, 0},
    {tile_pole, 0},     {tile_flag, 0},     {tile_crown_top, 0}, {tile_crown_top, 1},
    {tile_crown_bot, 0}, {tile_crown_bot, 1}, {tile_trunk, 0},  {tile_trunk, 1},
};

/* tile t in row r at phase p: TIMG_WORDS words */
static unsigned *tile_words;

const unsigned *timg(int t, int row, int phase)
{
    return tile_words + ((t * ROWS + row) * 4 + phase) * TIMG_WORDS;
}

/* an art pixel's palette entry, or -1 */
static int art_pixel(const char *const *art, int mirror, int w, int x, int y)
{
    char ch = art[y][mirror ? w - 1 - x : x];
    return ch == '.' ? -1 : art_index[ch & 127];
}

static void tiles_init(void)
{
    int t, r, p, l, k, opaque, n = T_N * ROWS * 4 * TIMG_WORDS;
    /* a line's pixels with 4 of colour 0 (no bits) either side: word k at
       phase p is pixels 4k + p .. 4k + p + 3 of it, the tile's pixels
       4k - 4 + p .. 4k - 1 + p, with no tests */
    unsigned char px[24];
    tile_words = malloc(n * sizeof(unsigned));
    memset(px, 0, sizeof px);
    for (t = 0; t < T_N; t++) {
        /* a tile without transparent pixels is the same in every row */
        opaque = tile_art[t].art != 0;
        for (l = 0; l < 16 && opaque; l++)
            opaque = strchr(tile_art[t].art[l], '.') == 0;
        for (r = 0; r < ROWS; r++) {
            if (opaque && r > 0) {
                memcpy(tile_words + (t * ROWS + r) * 4 * TIMG_WORDS,
                       tile_words + t * ROWS * 4 * TIMG_WORDS, 4 * TIMG_WORDS * sizeof(unsigned));
                continue;
            }
            for (l = 0; l < 16; l++) {
                /* the line over the playfield's background */
                int bg = pf_bg(16 * r + l);
                for (k = 0; k < 16; k++) {
                    int c = tile_art[t].art ? art_pixel(tile_art[t].art, tile_art[t].mirror,
                                                        16, k, l) : -1;
                    px[4 + k] = c < 0 ? bg : c;
                }
                for (p = 0; p < 4; p++) {
                    unsigned *w = tile_words + ((t * ROWS + r) * 4 + p) * TIMG_WORDS + 5 * l;
                    const unsigned char *q = px + p;
                    for (k = 0; k < 5; k++, q += 4)
                        w[k] = pix_tab[0][q[0]] | pix_tab[1][q[1]] | pix_tab[2][q[2]] |
                               pix_tab[3][q[3]];
                }
            }
        }
    }
}

/* ---- sprites ---- */

/* the fox: its head and body, then its legs in five poses */
static const char *const fox_top[16] = {
    "................", ".........k..k...", "........kok.kok.", "........kookook.",
    "........koooook.", "........kooooeok", "........kooooooe", "..kk....kowwwwwk",
    ".kwwk...kowwwwk.", "kwwook.kooowwk..", "kooook.koooowwk.", ".kooookoooooowk.",
    "..koooooooooowk.", "...koooooooooOk.", "...kOoooooooOk..", "...kOOoooooOOk..",
};
static const char *const fox_legs[5][8] = {
    {"...kOk....kOk...", "...kOk....kOk...", "...kOk....kOk...", "...kOk....kOk...",
     "...kOk....kOk...", "...kek....kek...", "..kkek...kkek...", "................"},
    {"...kOk....kOk...", "..kOk......kOk..", "..kOk......kOk..", ".kOk........kOk.",
     ".kek........kek.", "kkk..........kkk", "................", "................"},
    {"...kOk....kOk...", "...kOk...kOk....", "....kOk..kOk....", "....kOk.kOk.....",
     "....kek.kek.....", "...kkk.kkk......", "................", "................"},
    {"...kOk....kOk...", "..kOOk...kOOk...", ".kekk...kekk....", "................",
     "................", "................", "................", "................"},
    {"...kOk....kOk...", "..kOk......kOOk.", ".kOk........kek.", ".kek............",
     "................", "................", "................", "................"},
};
static const char *const bug_art[3][16] = {
    {"................", "................", "................", "................",
     "................", ".....kkkkkk.....", "...kkqqpppkk....", "..kqqppppppPk...",
     ".kqppppppppPPk..", ".kpppppppppPPkk.", "kpppppppppPPkwek", "kPpppppppPPPkwwk",
     "kPPPPPPPPPPPkkk.", ".kkkkkkkkkkkk...", "..k.k...k.k.....", ".k...k.k...k...."},
    {"................", "................", "................", "................",
     "................", "................", ".....kkkkkk.....", "...kkqqpppkk....",
     "..kqqppppppPk...", ".kqppppppppPPk..", ".kpppppppppPPkk.", "kpppppppppPPkwek",
     "kPpppppppPPPkwwk", "kPPPPPPPPPPPkkk.", ".kkkkkkkkkkkk...", "..k..k..k..k...."},
    {"................", "................", "................", "................",
     "................", "................", "................", "................",
     "................", "................", "................", "................",
     ".....kkkkkk.....", "..kkqpppppPPkk..", ".kPPPPPPPPPPPPk.", "..kkkkkkkkkkkk.."},
};
static const char *const bird_art[2][12] = {
    {"................", "......kk........", ".....kcck.......", "....kcCck.......",
     "...kcCck...kkk..", "kk.kkkkkkkkccwk.", "kckcccccccccceyy", ".kcccccccccccck.",
     "..kwwwwwwwwcck..", "...kkwwwwwwkk...", ".....kkkkkk.....", "................"},
    {"................", "................", "................", "................",
     "...........kkk..", "kk.kkkkkkkkccwk.", "kckcccccccccceyy", ".kcccCCCcccccck.",
     "..kwwkCCckwcck..", "...kkwkCCkwkk...", ".....kkCCk......", "......kk........"},
};

Sprite sprites[2][S_N];

/* a sprite from rows of art: at phase q (moved right by q pixels) word k's
   pixel j is the art's pixel 4k + j - q; each word as the mask of what it
   keeps of the background, then the image */
static void sprite_make(Sprite *s, const char *const *rows, int h, int mirror)
{
    unsigned *d = malloc(4 * h * 10 * sizeof(unsigned));
    int q, y, k, j;
    s->h = h;
    for (q = 0; q < 4; q++) {
        s->ph[q] = d;
        for (y = 0; y < h; y++)
            for (k = 0; k < 5; k++) {
                unsigned img = 0, m = 0;
                for (j = 0; j < 4; j++) {
                    int i = 4 * k + j - q, c;
                    if (i < 0 || i >= 16)
                        continue;
                    c = art_pixel(rows, mirror, 16, i, y);
                    if (c >= 0) {
                        img |= pix(j, c);
                        m |= pix_mask[j];
                    }
                }
                *d++ = ~m;
                *d++ = img;
            }
    }
}

static void sprites_init(void)
{
    const char *rows[24];
    int f, y, m;
    for (m = 0; m < 2; m++) {
        for (f = 0; f < 7; f++) {
            /* stand, run 0-3, jump, fall: the legs' poses */
            static const unsigned char pose[7] = {0, 1, 2, 3, 2, 4, 0};
            for (y = 0; y < 16; y++)
                rows[y] = fox_top[y];
            for (y = 0; y < 8; y++)
                rows[16 + y] = fox_legs[pose[f]][y];
            sprite_make(&sprites[m][S_FOX_STAND + f], rows, 24, m);
        }
        for (f = 0; f < 3; f++)
            sprite_make(&sprites[m][S_BUG0 + f], bug_art[f], 16, m);
        for (f = 0; f < 2; f++)
            sprite_make(&sprites[m][S_BIRD0 + f], bird_art[f], 12, m);
        sprite_make(&sprites[m][S_COIN], tile_coin, 16, m);
    }
}

/* the cursor's images (C1: 32 x 32, 2 bits a pixel, pixel p of a row at
   bits 2p of its two words): the bird, each art pixel 2 x 2 VGA pixels;
   outline 1 (palette 253), red 2 (254), white 3 (255) */
unsigned *bird_cursor[2][2];

static void cursor_init(void)
{
    int m, f, x, y;
    for (m = 0; m < 2; m++)
        for (f = 0; f < 2; f++) {
            unsigned *img = vram_alloc(32 * 8);
            memset(img, 0, 32 * 8);
            for (y = 0; y < 12; y++)
                for (x = 0; x < 16; x++) {
                    char ch = bird_art[f][y][m ? 15 - x : x];
                    unsigned v = ch == '.' ? 0 : ch == 'c' || ch == 'C' ? 2 :
                                 ch == 'w' || ch == 'y' ? 3 : 1;
                    int k;
                    for (k = 0; k < 4; k++) {
                        int cx = 2 * x + (k & 1), cy = 2 * y + (k >> 1) + 4;
                        img[2 * cy + cx / 16] |= v << (2 * (cx % 16));
                    }
                }
            bird_cursor[m][f] = img;
        }
}

/* ---- the parallax bands, painted into a row of bytes a line, the period
   and a screen's width more, then packed at each phase ---- */

unsigned *band_sky[4], *band_mtn[4], *band_hill[4];

#define BAND_X (BAND_P + SW + 4)

static unsigned char *bandpix;  /* lines x BAND_X */

static void span(int line, int x0, int x1, int c)
{
    unsigned char *row = bandpix + line * BAND_X;
    int x;
    for (x = x0; x < x1; x++)
        row[x & (BAND_P - 1)] = c;
}

static int isqrt(int v)
{
    int r = 0;
    while ((r + 1) * (r + 1) <= v)
        r++;
    return r;
}

/* a disc of colour c, its lines from top to bottom (clipped to the band) */
static void disc(int h, int cx, int cy, int r, int c)
{
    int dy;
    for (dy = -r; dy <= r; dy++) {
        int y = cy + dy, dx;
        if (y < 0 || y >= h)
            continue;
        dx = isqrt(r * r - dy * dy) * 3 / 2;    /* clouds and canopies are wide */
        span(y, cx - dx, cx + dx + 1, c);
    }
}

/* the period's pixels repeated after it, then each phase's words */
static void band_pack(unsigned **out, int h)
{
    int y, x, p, w;
    for (y = 0; y < h; y++)
        for (x = BAND_P; x < BAND_X; x++)
            bandpix[y * BAND_X + x] = bandpix[y * BAND_X + x - BAND_P];
    for (p = 0; p < 4; p++) {
        unsigned *d = vram_alloc(h * BAND_PITCH * 4);
        out[p] = d;
        for (y = 0; y < h; y++) {
            const unsigned char *s = bandpix + y * BAND_X + p;
            for (w = 0; w < BAND_PITCH; w++, s += 4)
                *d++ = pix_tab[0][s[0]] | pix_tab[1][s[1]] | pix_tab[2][s[2]] | pix_tab[3][s[3]];
        }
    }
}

/* a pseudo-random sequence, so the scenery is the same every run */
static unsigned seed = 12345;

static int rnd(int n)
{
    seed = seed * 1103515245 + 12345;
    return (seed >> 16) % n;
}

static void bands_init(void)
{
    int y, x, k;
    bandpix = malloc(SKY_H * BAND_X);
    /* the sky: its gradient, then clouds of overlapping discs */
    for (y = 0; y < SKY_H; y++)
        span(y, 0, BAND_P, SKY_C + y / 5);
    for (k = 0; k < 7; k++) {
        int cx = k * 73 + rnd(30), cy = 10 + rnd(26), r = 4 + rnd(4), n = 3 + rnd(3), i;
        for (i = 0; i < n; i++) {
            int dx = (i - n / 2) * r * 2 + rnd(5), dr = r + rnd(4) - (i == 0 || i == n - 1) * 2;
            disc(SKY_H, cx + dx, cy + 1, dr, CLOUD_C + 2);
            disc(SKY_H, cx + dx, cy, dr, CLOUD_C + 1);
            disc(SKY_H, cx + dx - 1, cy - 1, dr - 2, CLOUD_C);
        }
    }
    band_pack(band_sky, SKY_H);

    /* the mountains: two ranges of peaks against the sky, snow on the far ones */
    for (y = 0; y < MTN_H; y++)
        span(y, 0, BAND_P, SKY_C + (y + SKY_H) / 5);
    for (x = 0; x < BAND_P; x++) {
        int far = 0, near = 0, fside = 0, nside = 0, j;
        /* heights as the highest of a few triangles, periodic in BAND_P; a
           peak's left slope in the light, its right in shadow */
        static const short pf[6][2] = {{40, 30}, {130, 22}, {215, 28}, {300, 19}, {380, 31}, {470, 24}};
        static const short pn[5][2] = {{0, 14}, {95, 17}, {190, 12}, {290, 16}, {400, 13}};
        for (j = 0; j < 6; j++) {
            int d = x - pf[j][0], hgt;
            d = d < -BAND_P / 2 ? d + BAND_P : d > BAND_P / 2 ? d - BAND_P : d;
            hgt = pf[j][1] - (d < 0 ? -d : d) * 2 / 3;
            if (hgt > far) {
                far = hgt;
                fside = d > 0;
            }
        }
        for (j = 0; j < 5; j++) {
            int d = x - pn[j][0], hgt;
            d = d < -BAND_P / 2 ? d + BAND_P : d > BAND_P / 2 ? d - BAND_P : d;
            hgt = pn[j][1] - (d < 0 ? -d : d) / 2;
            if (hgt > near) {
                near = hgt;
                nside = d > 0;
            }
        }
        for (y = MTN_H - far; y < MTN_H; y++) {
            int c = MTN_C + fside;
            if (y < MTN_H - far + 6 && far > 20)
                c = MTN_C + 4 + fside;
            span(y, x, x + 1, c);
        }
        for (y = MTN_H - near; y < MTN_H; y++)
            span(y, x, x + 1, MTN_C + 2 + nside);
        span(MTN_H - 1, x, x + 1, MTN_C + 6);
        span(MTN_H - 2, x, x + 1, MTN_C + 6);
    }
    band_pack(band_mtn, MTN_H);

    /* the hills: rolling ground and round trees, over the mountains' haze */
    for (y = 0; y < HILL_H; y++)
        span(y, 0, BAND_P, MTN_C + 6);
    for (x = 0; x < BAND_P; x++) {
        int t = x % 128, hgt = 6 + (t < 64 ? t * (64 - t) : (t - 64) * (128 - t) / 2) / 160;
        for (y = HILL_H - hgt; y < HILL_H; y++)
            span(y, x, x + 1, y == HILL_H - hgt ? HILL_C : HILL_C + 1 + (y > HILL_H - 4));
    }
    for (k = 0; k < 14; k++) {
        int cx = k * 37 + rnd(12), cy = 6 + rnd(4);
        span(cy + 2, cx, cx + 1, HILL_C + 4);
        span(cy + 3, cx, cx + 1, HILL_C + 4);
        disc(HILL_H, cx, cy, 3, HILL_C + 4);
        disc(HILL_H, cx, cy - 1, 2, HILL_C + 3);
    }
    band_pack(band_hill, HILL_H);
    free(bandpix);
}

void art_init(void)
{
    pix_init();
    tiles_init();
    sprites_init();
    cursor_init();
    bands_init();
}
