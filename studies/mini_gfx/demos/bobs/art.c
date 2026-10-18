/* The bobs' pixel art, in logical colours (art.h): a shaded ball, a
   ring (transparent in the middle), a cut gem, and a critter drawn as
   string art. All in integers: a size s's pixel centres are at odd
   coordinates from -(s - 1) to s - 1, so the radius is s. */

#include "art.h"

static int isqrt(int n)
{
    int r = 0, b = 1 << 14;
    while (b > n)
        b >>= 2;
    while (b) {
        if (n >= r + b) {
            n -= r + b;
            r = (r >> 1) + b;
        } else
            r >>= 1;
        b >>= 2;
    }
    return r;
}

/* a shade 0-7 (or white) from a light value v in -100..100: the light from
   the top left and the front */
static int shade(int ramp, int v)
{
    if (v > 90)
        return C_WHITE;
    if (v < -50)
        v = -50;
    v = (v + 50) * 8 / 141;
    return ramp + (v > 7 ? 7 : v);
}

void art_ball(int s, unsigned char *pix, unsigned char *mask)
{
    int i, j, R = s;
    for (j = 0; j < s; j++)
        for (i = 0; i < s; i++) {
            int dx = 2 * i - (s - 1), dy = 2 * j - (s - 1), d2 = dx * dx + dy * dy, z;
            *mask = d2 < R * R;
            z = *mask ? isqrt(R * R - d2) : 0;
            /* the normal (dx, dy, z) / R against (-1, -1, 1.5) / 2.06 */
            *pix++ = shade(C_RED, (-dx - dy + 3 * z / 2) * 100 / (R * 206 / 100));
            mask++;
        }
}

void art_ring(int s, unsigned char *pix, unsigned char *mask)
{
    int i, j, R = s, Ri = s * 9 / 20, rc = (R + Ri) / 2, t = (R - Ri) / 2;
    for (j = 0; j < s; j++)
        for (i = 0; i < s; i++) {
            int dx = 2 * i - (s - 1), dy = 2 * j - (s - 1), d2 = dx * dx + dy * dy;
            int dd = isqrt(d2), u = dd - rc, z, v = 0;
            *mask = d2 < R * R && d2 >= Ri * Ri;
            if (*mask && dd) {
                /* the tube's normal: out from its centre line */
                z = t * t > u * u ? isqrt(t * t - u * u) : 0;
                v = (-(dx * u / dd) - (dy * u / dd) + 3 * z / 2) * 100 / (t * 206 / 100);
            }
            *pix++ = shade(C_GOLD, v);
            mask++;
        }
}

void art_gem(int s, unsigned char *pix, unsigned char *mask)
{
    int i, j, R = s;
    for (j = 0; j < s; j++)
        for (i = 0; i < s; i++) {
            int dx = 2 * i - (s - 1), dy = 2 * j - (s - 1);
            int a = (dx < 0 ? -dx : dx) + (dy < 0 ? -dy : dy), c;
            *mask++ = a < R;
            if (a >= R - 3)
                c = C_CYAN;                     /* the rim */
            else if (a < R / 2)
                c = C_CYAN + 6;                 /* the table */
            else if (dy < 0)
                c = C_CYAN + (dx < 0 ? 7 : 5);  /* the facets, lit from the top left */
            else
                c = C_CYAN + (dx < 0 ? 4 : 2);
            if (a < R / 2 && dx < -R / 6 && dy < -R / 6 && dx > -R / 3)
                c = C_WHITE;                    /* a glint */
            *pix++ = c;
        }
}

/* the critter, 16 x 16: o outline, # body, + its light side, W eyes, K
   pupils, m mouth, f feet */
static const char *critter[16] = {
    "................",
    "....oooooooo....",
    "...o++######o...",
    "..o++########o..",
    "..o+WWW##WWW#o..",
    ".o#WKKW##WKKW#o.",
    ".o#WKKW##WKKW#o.",
    ".o#WWWW##WWWW#o.",
    ".o############o.",
    ".o###mmmmmm###o.",
    ".o####mmmm####o.",
    "..o##########o..",
    "...o########o...",
    "....oooooooo....",
    "...ff......ff...",
    "..fff......fff..",
};

void art_critter(int s, unsigned char *pix, unsigned char *mask)
{
    int i, j, k = s / 16;
    for (j = 0; j < s; j++)
        for (i = 0; i < s; i++) {
            char ch = critter[j / k][i / k];
            *mask++ = ch != '.';
            *pix++ = ch == 'o' ? C_OUTLINE : ch == '+' ? C_GREEN + 7 : ch == 'W' ? C_WHITE
                   : ch == 'K' ? C_BLACK : ch == 'm' ? C_MOUTH : ch == 'f' ? C_FEET
                   : C_GREEN + 4;
        }
}
