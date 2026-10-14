/* Colours per depth, the desktop pattern, an icon and the cursor. */

#include "theme.h"

/* The VGA's 16 colours, which are also the first 16 at 8 bits. */
const unsigned char palette16[16 * 3] = {
    0, 0, 0,  0, 0, 170,  0, 170, 0,  0, 170, 170,
    170, 0, 0,  170, 0, 170,  170, 85, 0,  170, 170, 170,
    85, 85, 85,  85, 85, 255,  85, 255, 85,  85, 255, 255,
    255, 85, 85,  255, 85, 255,  255, 255, 85,  255, 255, 255,
};

static const unsigned char cube[6] = { 0, 95, 135, 175, 215, 255 };

void theme_rgb(int depth, int c, int *r, int *g, int *b)
{
    if (depth == 0) {
        *r = *g = *b = c ? 255 : 0;
    } else if (depth == 1) {
        *r = *g = *b = c * 85;
    } else if (c < 16) {
        *r = palette16[3 * c];
        *g = palette16[3 * c + 1];
        *b = palette16[3 * c + 2];
    } else if (c < 232) {
        c -= 16;
        *r = cube[c / 36];
        *g = cube[c / 6 % 6];
        *b = cube[c % 6];
    } else {
        *r = *g = *b = 8 + 10 * (c - 232);
    }
}

unsigned c_black, c_white, c_desk, c_desk2, c_frame, c_title, c_title_text,
    c_title_off, c_window, c_text, c_accent, c_shadow, c_light;

/* black white desk desk2 frame title title_text title_off window text accent shadow light */
static const unsigned char roles[4][13] = {
    { 0, 1, 0, 1, 0, 0, 1, 1, 1, 0, 0, 0, 1 },
    { 0, 3, 1, 2, 0, 0, 3, 2, 3, 0, 1, 1, 3 },
    { 0, 15, 3, 11, 0, 1, 15, 7, 15, 0, 4, 8, 15 },
    { 0, 15, 24, 23, 0, 25, 15, 250, 15, 0, 160, 244, 255 },
};

/* the pictures: the icon is its X pixels; the cursor's mask is every
   marked pixel, and its image the '.' ones (X is black, . white) */
static const char *const icon_rows[16] = {
    "  XXXXXXXXX     ",
    "  X.......XX    ",
    "  X.......X.X   ",
    "  X.......XXXX  ",
    "  X..........X  ",
    "  X..XXXXXX..X  ",
    "  X..........X  ",
    "  X..XXXXXX..X  ",
    "  X..........X  ",
    "  X..XXXXX...X  ",
    "  X..........X  ",
    "  X..XXXXXX..X  ",
    "  X..........X  ",
    "  X..........X  ",
    "  XXXXXXXXXXXX  ",
    "                ",
};

static const char *const cursor_rows[CURSOR_H] = {
    "X           ",
    "XX          ",
    "X.X         ",
    "X..X        ",
    "X...X       ",
    "X....X      ",
    "X.....X     ",
    "X......X    ",
    "X.......X   ",
    "X........X  ",
    "X.........X ",
    "X......XXXXX",
    "X...X..X    ",
    "X..XX..X    ",
    "X.X  X..X   ",
    "XX   X..X   ",
    "X     X..X  ",
    "      X..X  ",
    "       XX   ",
};

static unsigned icon_bits[16], cmask_bits[CURSOR_H], cimage_bits[CURSOR_H];
Surface icon, cursor_mask, cursor_image;

/* one row of a picture into a word: the pixels marked with ch, or with
   anything if ch is 0 */
static unsigned row_bits(const char *row, int ch)
{
    unsigned v = 0;
    int x;
    for (x = 0; row[x]; x++)
        if (ch ? row[x] == ch : row[x] != ' ')
            v |= 1u << x;
    return v;
}

void theme_init(int depth)
{
    const unsigned char *c = roles[depth];
    int y;
    c_black = c[0]; c_white = c[1]; c_desk = c[2]; c_desk2 = c[3];
    c_frame = c[4]; c_title = c[5]; c_title_text = c[6]; c_title_off = c[7];
    c_window = c[8]; c_text = c[9]; c_accent = c[10]; c_shadow = c[11]; c_light = c[12];
    for (y = 0; y < 16; y++)
        icon_bits[y] = row_bits(icon_rows[y], 'X');
    for (y = 0; y < CURSOR_H; y++) {
        cmask_bits[y] = row_bits(cursor_rows[y], 0);
        cimage_bits[y] = row_bits(cursor_rows[y], '.');
    }
    gfx_init(&icon, icon_bits, 16, 16, 4, 0);
    gfx_init(&cursor_mask, cmask_bits, CURSOR_W, CURSOR_H, 4, 0);
    gfx_init(&cursor_image, cimage_bits, CURSOR_W, CURSOR_H, 4, 0);
}

/* a checkerboard of the two desktop colours */
unsigned theme_pattern(int depth, int row)
{
    int bpp = 1 << depth;
    unsigned a = c_desk, b = c_desk2;
    if (row & 1)
        return gfx_pat(depth + 1, b | (a << bpp));
    return gfx_pat(depth + 1, a | (b << bpp));
}

static int sq[511];

static int dist(int depth, int c, int r, int g, int b)
{
    int pr, pg, pb;
    theme_rgb(depth, c, &pr, &pg, &pb);
    return sq[pr - r + 255] + sq[pg - g + 255] + sq[pb - b + 255];
}

unsigned theme_nearest(int depth, int r, int g, int b)
{
    int c, d, best = 0, bd = 0x7FFFFFFF, n = gfx_maxcolor(depth);
    if (sq[0] == 0)
        for (c = 0; c < 511; c++)
            sq[c] = (c - 255) * (c - 255);
    for (c = 0; c <= n; c++) {
        d = dist(depth, c, r, g, b);
        if (d < bd) {
            bd = d;
            best = c;
        }
    }
    return best;
}

void theme_ramp(int depth, unsigned fg, unsigned bg, unsigned char *ramp)
{
    int k, fr, fgg, fb, br, bgg, bb;
    theme_rgb(depth, fg, &fr, &fgg, &fb);
    theme_rgb(depth, bg, &br, &bgg, &bb);
    for (k = 0; k <= 64; k++)
        ramp[k] = theme_nearest(depth, (fr * k + br * (64 - k) + 32) >> 6,
                                (fgg * k + bgg * (64 - k) + 32) >> 6,
                                (fb * k + bb * (64 - k) + 32) >> 6);
}
