/* What the demos share (fx.h). */

#include <stdlib.h>
#include <string.h>
#include "fx.h"
#include "video.h"

int fx_sin[256];
unsigned fx_orig;
int fx_idle_base;
unsigned fx_seed = 12345;

/* Bhaskara's approximation, in whole degrees d of 0..180:
   sin d ~ 4d(180 - d) / (40500 - d(180 - d)), within 0.2% */
static int sin_deg(int d)
{
    int p = d * (180 - d);
    return 4 * 256 * p / (40500 - p);
}

void fx_init(void)
{
    int i, d;
    for (i = 0; i < 128; i++) {
        d = (i * 360 + 128) / 256;
        fx_sin[i] = sin_deg(d);
        fx_sin[i + 128] = -fx_sin[i];
    }
    font_init();
}

/* the vector is "JMP rel16" at 4: F2 E0, then the offset in parcels from 8 */
void fx_vector(void (*h)(void))
{
    volatile unsigned short *v = (unsigned short *)4;
    if (!fx_orig)
        fx_orig = 8 + 2 * (int)(short)v[1];
    v[1] = ((unsigned)h - 8) >> 1;
}

void fx_vector_off(void)
{
    volatile unsigned short *v = (unsigned short *)4;
    if (fx_orig)
        v[1] = (fx_orig - 8) >> 1;
}

/* a unit of work: about 600 ticks of short instructions */
static volatile int sink;
static void unit(void)
{
    int i, a = sink;
    for (i = 0; i < 24; i++)
        a = (a + i) ^ (a >> 1);
    sink = a;
}

int fx_idle(void)
{
    unsigned f = rt_frames;
    int n = 0;
    while (rt_frames == f) {
        unit();
        n++;
    }
    return n;
}

void fx_calibrate(void)
{
    int k, n;
    fx_idle();
    fx_idle_base = 0;
    for (k = 0; k < 3; k++) {
        n = fx_idle();
        if (n > fx_idle_base)
            fx_idle_base = n;
    }
}

int fx_used(int units)
{
    return 1000 - 1000 * units / fx_idle_base;
}

int fx_logo_width(const char *str, int cell)
{
    return (font_width(font_sans, str) + 1) * cell;
}

int fx_logo(Surface *s, int x, int y, const char *str, int cell, int gap, unsigned face,
            unsigned light, unsigned dark)
{
    Surface t;
    int w = font_width(font_sans, str) + 1, h = font_sans->height, pitch = (w + 31) / 32, i, j;
    unsigned *bits = calloc(pitch * h, 4);
    gfx_init(&t, bits, w, h, pitch, PF_LIN1);
    font_draw(&t, font_sans, 0, font_sans->ascent, str, 1, -1);
    font_draw(&t, font_sans, 1, font_sans->ascent, str, 1, -1);     /* bold: twice, a pixel apart */
    for (j = 0; j < h; j++)
        for (i = 0; i < w; i++)
            if (gfx_get(&t, i, j)) {
                int x0 = x + i * cell, y0 = y + j * cell;
                int x1 = x0 + cell - gap, y1 = y0 + cell - gap;
                gfx_fill(s, x0, y0, x1, y1, face, ROP_COPY);
                if (cell - gap >= 4)
                    gfx_bevel(s, x0, y0, x1, y1, light, dark);
            }
    free(bits);
    return w * cell;
}

unsigned fx_dim(int r, int g, int b, int level)
{
    return rgb565(r * level / 15, g * level / 15, b * level / 15);
}

int fx_rand(void)
{
    fx_seed = fx_seed * 1103515245 + 12345;
    return (fx_seed >> 16) & 0x7FFF;
}
