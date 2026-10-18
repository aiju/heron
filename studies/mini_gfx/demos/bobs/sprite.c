/* Sprites (sprite.h): the image and mask in the screen's format, the
   pre-shifted forms made with the library (so any pixel format works),
   and the C kernels. */

#include <stdlib.h>
#include <string.h>
#include "sprite.h"

int bob_pitch;

/* a surface of w x h pixels in format fmt, cleared */
static void surface(Surface *s, int w, int h, int fmt)
{
    const Format *f = gfx_format(fmt);
    int pitch = (w * f->bpp + 31) >> 5;
    void *bits = malloc(pitch * h * 4);
    memset(bits, 0, pitch * h * 4);
    gfx_init(s, bits, w, h, pitch, fmt);
}

void sprite_make(Sprite *s, int w, int h, const unsigned char *pix, const unsigned char *mask,
                 int fmt)
{
    const Format *f = gfx_format(fmt);
    int ppw = 1 << f->pshift, all = (1 << f->bpp) - 1, x, y, p, k;
    unsigned *mb;
    memset(s, 0, sizeof *s);
    s->w = w;
    s->h = h;
    s->nph = ppw;
    /* the image (0 where transparent) and the 1-bit mask */
    surface(&s->img, w, h, fmt);
    s->mask.pitch = (w + 31) >> 5;
    mb = malloc(s->mask.pitch * h * 4);
    memset(mb, 0, s->mask.pitch * h * 4);
    s->mask.bits = mb;
    for (y = 0; y < h; y++)
        for (x = 0; x < w; x++)
            if (mask[y * w + x]) {
                gfx_pixel(&s->img, x, y, pix[y * w + x], ROP_COPY);
                mb[y * s->mask.pitch + (x >> 5)] |= 1u << (x & 31);
            }
    /* each phase: the sprite drawn at x = p into a cleared surface, and
       its mask expanded in the colour with every bit set: the pixels'
       mask in whatever format */
    for (p = 0; p < ppw; p++) {
        Surface ti, tm;
        int ww = (p + w + ppw - 1) / ppw, r;
        unsigned *sh, *sp;
        s->ww[p] = ww;
        s->words[p] = ww * h;
        surface(&ti, (ww + 1) * ppw, h, fmt);
        surface(&tm, (ww + 1) * ppw, h, fmt);
        gfx_masked(&ti, p, 0, &s->img, &s->mask, 0, 0, w, h);
        gfx_expand(&tm, p, 0, &s->mask, 0, 0, w, h, all, 0, 0);
        sh = s->shifted[p] = malloc(h * ww * 8);
        sp = s->spans[p] = malloc(h * (ww * 8 + 4));
        for (r = 0; r < h; r++) {
            const unsigned *im = ti.bits + r * ti.pitch, *mm = tm.bits + r * tm.pitch;
            int first = -1, last = -1, nl, no, nr;
            for (k = 0; k < ww; k++) {
                *sh++ = ~mm[k];
                *sh++ = im[k] & mm[k];
                if (mm[k]) {
                    if (first < 0)
                        first = k;
                    last = k;
                    if (mm[k] == ~0u)
                        s->opaque++;
                    else
                        s->masked++;
                }
            }
            /* the spans: masked words up to the first opaque one, the
               opaque run, the rest as masked */
            if (first < 0) {
                *sp++ = SPAN(0, 0, 0, 0);
                continue;
            }
            k = first;
            while (k <= last && mm[k] != ~0u)
                k++;
            nl = k - first;
            while (k <= last && mm[k] == ~0u)
                k++;
            no = k - first - nl;
            nr = last + 1 - k;
            *sp++ = SPAN(first * 4, nl, no, nr);
            for (k = first; k <= last; k++) {
                if (k < first + nl || k >= first + nl + no)
                    *sp++ = ~mm[k];
                *sp++ = im[k] & mm[k];
            }
        }
        s->code[p] = jit_sprite(s->shifted[p], ww, h, bob_pitch, 0, &k);
        s->codesize += k;
        if (fmt == PF_LIN8) {
            s->bcode[p] = jit_sprite(s->shifted[p], ww, h, bob_pitch, 1, &k);
            s->codesize += k;
        } else
            s->bcode[p] = s->code[p];
        s->rcode[p] = jit_restore(s->shifted[p], ww, h, bob_pitch, &k);
        s->codesize += k;
        free(ti.bits);
        free(tm.bits);
    }
}

/* ---- the C kernels ---- */

void draw_shifted_c(const Blt *b, int n)
{
    for (; n > 0; n--, b++) {
        unsigned *d = b->d;
        const unsigned *s = b->s;
        int w = b->w, h = b->h, skip = bob_pitch - w, k;
        while (h-- > 0) {
            for (k = w; k > 0; k--) {
                *d = (*d & s[0]) | s[1];
                d++;
                s += 2;
            }
            d += skip;
        }
    }
}

void draw_spans_c(const Blt *b, int n)
{
    for (; n > 0; n--, b++) {
        unsigned *row = b->d;
        const unsigned *s = b->s;
        int h = b->h, k;
        while (h-- > 0) {
            unsigned hd = *s++;
            unsigned *d = (unsigned *)((char *)row + (hd & 255));
            for (k = (hd >> 8) & 255; k > 0; k--) {
                *d = (*d & s[0]) | s[1];
                d++;
                s += 2;
            }
            for (k = (hd >> 16) & 255; k > 0; k--)
                *d++ = *s++;
            for (k = hd >> 24; k > 0; k--) {
                *d = (*d & s[0]) | s[1];
                d++;
                s += 2;
            }
            row += bob_pitch;
        }
    }
}

void restore_c(const Blt *b, int n)
{
    for (; n > 0; n--, b++) {
        unsigned *d = b->d;
        const unsigned *s = b->s;
        int w = b->w, h = b->h, skip = bob_pitch - w, k;
        while (h-- > 0) {
            for (k = w; k > 0; k--)
                *d++ = *s++;
            d += skip;
            s += skip;
        }
    }
}

void save_c(const Blt *b, int n)
{
    for (; n > 0; n--, b++) {
        const unsigned *d = b->d;
        unsigned *s = (unsigned *)b->s;
        int w = b->w, h = b->h, skip = bob_pitch - w, k;
        while (h-- > 0) {
            for (k = w; k > 0; k--)
                *s++ = *d++;
            d += skip;
        }
    }
}

/* the saves put back in the reverse order: where sprites overlapped, the
   first one's save holds the background */
void unsave_c(const Blt *b, int n)
{
    for (b += n - 1; n > 0; n--, b--) {
        unsigned *d = b->d;
        const unsigned *s = b->s;
        int w = b->w, h = b->h, skip = bob_pitch - w, k;
        while (h-- > 0) {
            for (k = w; k > 0; k--)
                *d++ = *s++;
            d += skip;
        }
    }
}
