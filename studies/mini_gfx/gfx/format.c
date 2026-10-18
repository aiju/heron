/* Pixel formats (gfx.h): each is where pixel p's bit i is in a word
   (gfx_bitpos); the masks, the solid colours and the expansion tables
   all come from that. */

#include <stdlib.h>
#include "gfx.h"
#include "video.h"

Format gfx_formats[PF_N];
int board_layout;

static const unsigned char bpps[PF_N] = {1, 2, 4, 8, 1, 2, 2, 4, 8};

int gfx_bitpos(int fmt, int p, int i)
{
    switch (fmt) {
    case PF_LIN1: return p;
    case PF_LIN2: return 2 * p + i;
    case PF_LIN4: return 4 * p + i;
    case PF_LIN8: return 8 * p + i;
    case PF_CHK1: return 4 * (p & 7) + (p >> 3);
    case PF_CHK2: return 4 * (p & 7) + (p >> 3) + 2 * i;
    case PF_PL2: return 16 * i + p;
    case PF_PL4: return 8 * i + p;
    default: return i < 4 ? 8 * i + 2 * p : 8 * (i - 4) + 2 * p + 1;
    }
}

static void setup(int fmt)
{
    Format *f = &gfx_formats[fmt];
    int p, i, ppw, n;
    unsigned planes[8];
    f->bpp = bpps[fmt];
    f->pshift = f->bpp == 1 ? 5 : f->bpp == 2 ? 4 : f->bpp == 4 ? 3 : 2;
    f->lin = fmt <= PF_LIN8;
    ppw = 1 << f->pshift;
    for (i = 0; i < f->bpp; i++)
        planes[i] = 0;
    for (p = 0; p < ppw; p++) {
        f->pmask[p] = 0;
        for (i = 0; i < f->bpp; i++) {
            unsigned b = 1u << gfx_bitpos(fmt, p, i);
            f->pmask[p] |= b;
            planes[i] |= b;     /* bit i of every pixel */
        }
        f->lsb[p] = 1u << gfx_bitpos(fmt, p, 0);
    }
    f->from[ppw] = 0;
    for (p = ppw - 1; p >= 0; p--)
        f->from[p] = f->from[p + 1] | f->pmask[p];
    f->nx = (ppw + 7) >> 3;
    f->xt = 0;
    f->solid = malloc((1 << f->bpp) * sizeof(unsigned));
    for (n = 0; n < 1 << f->bpp; n++) {
        unsigned w = 0;
        for (i = 0; i < f->bpp; i++)
            if (n >> i & 1)
                w |= planes[i];
        f->solid[n] = w;
    }
    f->ready = 1;
}

const Format *gfx_format(int fmt)
{
    if (!gfx_formats[fmt].ready)
        setup(fmt);
    return &gfx_formats[fmt];
}

int gfx_format_of(int bpp, int layout, int f1)
{
    if (layout)
        return bpp == 1 ? PF_LIN1 : bpp == 2 ? PF_PL2 : bpp == 4 ? PF_PL4 : PF_PL8;
    if (bpp == 1)
        return f1 ? PF_LIN1 : PF_CHK1;
    if (bpp == 2)
        return f1 ? PF_LIN2 : PF_CHK2;
    return bpp == 4 ? PF_LIN4 : PF_LIN8;
}

int gfx_screen_format(void)
{
    return gfx_format_of(vid.bpp, board_layout, (vid.ctrl & VC_F1) != 0);
}

unsigned gfx_solid(int fmt, unsigned c)
{
    const Format *f = gfx_format(fmt);
    return gfx_solidf(f, c);
}

/* the expansion tables: table j, entry v: the mask of pixels 8j..8j+7
   whose bits are set in v */
static void xtables(Format *f)
{
    int fmt = f - gfx_formats, j, v, b, ppw = 1 << f->pshift;
    unsigned *t = malloc(f->nx * 256 * sizeof(unsigned));
    for (j = 0; j < f->nx; j++)
        for (v = 0; v < 256; v++) {
            unsigned m = 0;
            for (b = 0; b < 8 && 8 * j + b < ppw; b++)
                if (v >> b & 1)
                    m |= f->pmask[8 * j + b];
            t[256 * j + v] = m;
        }
    (void)fmt;
    f->xt = t;
}

unsigned gfx_xmask(const Format *f, unsigned bits)
{
    unsigned m;
    if (f->bpp == 1 && f->lin)
        return bits;
    if (!f->xt)
        xtables((Format *)f);
    m = f->xt[bits & 255];
    if (f->nx > 1) {
        m |= f->xt[256 + (bits >> 8 & 255)];
        if (f->nx > 2)
            m |= f->xt[512 + (bits >> 16 & 255)] | f->xt[768 + (bits >> 24)];
    }
    return m;
}
