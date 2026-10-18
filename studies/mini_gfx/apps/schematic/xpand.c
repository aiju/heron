/* The editor's own kernels (sch.h), for what the library does slowly at
   1 and 2 bits a pixel:

   - sch_expand: a 1-bit bitmap (a sprite, a label) into the surface in a
     colour, transparent, opaque or in XOR. The library's expansion has
     assembly only for 8 pixels a word; at 1 and 2 bits it's C that calls
     gfx_xmask for every word. Here each row's bits are lined up first,
     then turned into masks the way the format wants (LIN1: the bits
     themselves; PL2: a half and itself 16 higher; LIN2, CHK2, CHK1:
     through a table of 256), then applied, words with no pixels skipped.
     In C, and in draft 2 (xpand.s) with GFX_ASM.
   - sch_vline: a line down, a word a row with the pixel's mask; the
     library's fill does the same with a whole fill's set-up and edge
     tests for every row.

   Other formats (4 and 8 bits) go to the library, but for XOR, which it
   hasn't: that's C here, through gfx_xmask. */

#include <stdlib.h>
#include "sch.h"

/* the formats the kernels know */
enum { XF_LIN1, XF_CHK1, XF_LIN2, XF_CHK2, XF_PL2, XF_NONE };
/* XOR at 4 and 8 bits, which the library's expansion hasn't: the C
   kernel with the format's own masks (gfx_xmask), a word at a time */
#define XF_GEN XF_NONE

static int xformat(int fmt)
{
    switch (fmt) {
    case PF_LIN1: return XF_LIN1;
    case PF_CHK1: return XF_CHK1;
    case PF_LIN2: return XF_LIN2;
    case PF_CHK2: return XF_CHK2;
    case PF_PL2: return XF_PL2;
    default: return XF_NONE;
    }
}

/* the tables: a byte's 8 pixels to their mask, LIN2 (bits 2b, 2b + 1),
   CHK2 (4b and 4b + 2) and CHK1 (4b) */
static unsigned *tabs[XF_NONE];

static const unsigned *table(int xf)
{
    int v, b;
    if (xf == XF_LIN1 || xf == XF_PL2)
        return 0;
    if (!tabs[xf]) {
        unsigned *t = malloc(256 * 4);
        for (v = 0; v < 256; v++) {
            unsigned m = 0;
            for (b = 0; b < 8; b++)
                if (v >> b & 1)
                    m |= xf == XF_LIN2 ? 3u << 2 * b : xf == XF_CHK2 ? 5u << 4 * b : 1u << 4 * b;
            t[v] = m;
        }
        tabs[xf] = t;
    }
    return tabs[xf];
}

#define XBUF 132                /* words: a row of 2048 pixels and a spare */
unsigned sch_xbuf[XBUF], sch_mbuf[XBUF];

void sch_expand_c(const XJob *j)
{
    const unsigned *s = j->s, *t = j->tab;
    unsigned *d = j->d, fg = j->fg, bg = j->bg, *bits, m, e;
    int h = j->h, n = j->n, k, words, o = j->soff;
    if (j->fmt == XF_GEN)
        words = (((n + 1) << ((const Format *)t)->pshift) + 31) >> 5;
    else
        words = j->fmt <= XF_CHK1 ? n + 1 : (n + 2) >> 1;
    while (h-- > 0) {
        /* the row's bits from bit 0 */
        if (o) {
            for (k = 0; k < words; k++)
                sch_xbuf[k] = s[k] >> o | s[k + 1] << (32 - o);
            bits = sch_xbuf;
        } else {
            bits = (unsigned *)s;
        }
        /* the masks */
        switch (j->fmt) {
        case XF_LIN1:
            break;
        case XF_CHK1:
            for (k = 0; k <= n; k++) {
                unsigned b = bits[k];
                sch_mbuf[k] = t[b & 255] | t[b >> 8 & 255] << 1 | t[b >> 16 & 255] << 2 |
                              t[b >> 24] << 3;
            }
            bits = sch_mbuf;
            break;
        case XF_GEN: {
            const Format *f = (const Format *)t;
            int ppw = 1 << f->pshift;
            unsigned keep = (1u << ppw) - 1;
            for (k = 0; k <= n; k++)
                sch_mbuf[k] = gfx_xmask(f, bits[(k * ppw) >> 5] >> ((k * ppw) & 31) & keep);
            bits = sch_mbuf;
            break;
        }
        default:
            for (k = 0; k <= n; k++) {
                unsigned b = k & 1 ? bits[k >> 1] >> 16 : bits[k >> 1] & 0xFFFF;
                if (j->fmt == XF_PL2)
                    m = b | b << 16;
                else if (j->fmt == XF_LIN2)
                    m = t[b & 255] | t[b >> 8] << 16;
                else
                    m = t[b & 255] | t[b >> 8] << 1;
                sch_mbuf[k] = m;
            }
            bits = sch_mbuf;
            break;
        }
        /* the pixels */
        for (k = 0; k <= n; k++) {
            m = bits[k];
            e = k == 0 ? j->lmask : k == n ? j->rmask : ~0u;
            if (j->mode == XM_OPAQUE) {
                unsigned v = bg ^ ((fg ^ bg) & m);
                d[k] ^= (d[k] ^ v) & e;
            } else if ((m &= e) != 0) {
                if (j->mode == XM_XOR)
                    d[k] ^= fg & m;
                else
                    d[k] ^= (d[k] ^ fg) & m;
            }
        }
        d = (unsigned *)((char *)d + j->dpitch);
        s = (const unsigned *)((const char *)s + j->spitch);
    }
}

int lib_kernels;

void sch_expand(Surface *dst, int dx, int dy, const Bitmap *src, int sx, int sy, int w, int h,
                unsigned fg, unsigned bg, int mode)
{
    const Format *f = dst->f;
    int ps = dst->pshift, last = (1 << ps) - 1, w0, w1, base, d, xf = xformat(dst->fmt);
    XJob j;
    /* clipped to the destination's clip */
    if ((d = dst->clip.x0 - dx) > 0) { dx += d; sx += d; w -= d; }
    if ((d = dst->clip.y0 - dy) > 0) { dy += d; sy += d; h -= d; }
    if ((d = dx + w - dst->clip.x1) > 0) w -= d;
    if ((d = dy + h - dst->clip.y1) > 0) h -= d;
    if (w <= 0 || h <= 0)
        return;
    if (w > 2000 || (mode != XM_XOR && (xf == XF_NONE || lib_kernels))) {
        gfx_expand(dst, dx, dy, src, sx, sy, w, h, fg, bg, mode == XM_OPAQUE);
        return;
    }
    w0 = dx >> ps;
    w1 = (dx + w - 1) >> ps;
    j.n = w1 - w0;
    j.lmask = gfx_from(f, dx & last);
    j.rmask = gfx_before(f, ((dx + w - 1) & last) + 1);
    if (j.n == 0) {
        j.lmask &= j.rmask;
        j.rmask = 0;
    }
    /* the source bit under the first word's first pixel (perhaps before
       the row: those bits are under lmask's zeros) */
    base = (w0 << ps) - dx + sx;
    j.s = src->bits + sy * src->pitch + (base >> 5);
    j.soff = base & 31;
    j.spitch = src->pitch * 4;
    j.d = dst->bits + dy * dst->pitch + w0;
    j.dpitch = dst->pitch * 4;
    j.h = h;
    j.fg = gfx_solidf(f, fg);
    j.bg = gfx_solidf(f, bg);
    j.mode = mode;
    j.fmt = xf;
    if (xf == XF_GEN) {
        /* XOR at 4 and 8 bits: C, the format's own masks */
        gfx_xmask(f, 0);
        j.tab = (const unsigned *)f;
        sch_expand_c(&j);
        return;
    }
    j.tab = table(xf);
    sch_expand_kernel(&j);
}

/* a line down from y0 to y1 inclusive */
void sch_vline(Surface *s, int x, int y0, int y1, unsigned c, int rop)
{
    const Format *f = s->f;
    unsigned m, v, *p;
    int n;
    if (y0 > y1) {
        n = y0; y0 = y1; y1 = n;
    }
    if (x < s->clip.x0 || x >= s->clip.x1)
        return;
    if (y0 < s->clip.y0)
        y0 = s->clip.y0;
    if (y1 >= s->clip.y1)
        y1 = s->clip.y1 - 1;
    if (y0 > y1)
        return;
    if (lib_kernels) {
        gfx_fill(s, x, y0, x + 1, y1 + 1, c, rop);
        return;
    }
    m = f->pmask[x & ((1 << s->pshift) - 1)];
    v = gfx_solidf(f, c) & m;
    p = s->bits + y0 * s->pitch + (x >> s->pshift);
    n = y1 - y0 + 1;
#ifdef GFX_ASM
    sch_vline_asm(p, s->pitch * 4, n, rop == ROP_XOR ? 0 : m, v);
#else
    if (rop == ROP_XOR) {
        while (n-- > 0) {
            *p ^= v;
            p += s->pitch;
        }
    } else {
        while (n-- > 0) {
            *p = (*p & ~m) | v;
            p += s->pitch;
        }
    }
#endif
}
