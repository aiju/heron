/* The wif variant's kernels: the blk variant's, with the what-if block
   instructions (whatif.py) where they apply: FILLX for XOR fills,
   EXPANDT for transparent expansion at 8 pixels a word, EXPAND2, EXPAND1
   and EXPAND8 (RFC 0042's X1) for opaque expansion at 16, 32 (linear) and
   4 pixels a word. C for the rows, the instructions for each row's whole
   words; everything else goes to the blk kernels. BLITN (X1's BLIT by a
   bit count) is shift.s's. */

#include <stdlib.h>
#include "gfx.h"

void wif_fillx(unsigned *d, unsigned v, int n);
void wif_expandt(unsigned *d, const unsigned char *s, int n, const unsigned *table, unsigned fg);
void wif_expand2(unsigned *d, const unsigned char *s, int n, const unsigned *t0,
                 const unsigned *t1, unsigned fg_xor_bg, unsigned bg);
void wif_expand1(unsigned *d, const unsigned *s, int n, unsigned fg_xor_bg, unsigned bg);
void wif_expand8(unsigned *d, const unsigned char *s, int n, const unsigned *table2,
                 unsigned fg_xor_bg, unsigned bg);
void wif_patch(const ExpandJob *j);
const unsigned char *wif_align(const unsigned *s, int bytes);

void fill_rows_wif(const FillJob *j)
{
    unsigned *p = j->p;
    int h = j->h;
    if (j->rop != ROP_XOR || j->pats || j->n < 2) {
        fill_rows_blk(j);
        return;
    }
    while (h-- > 0) {
        p[0] ^= j->pat & j->lmask;
        wif_fillx(p + 1, j->pat, j->n);
        if (j->rmask)
            p[j->n + 1] ^= j->pat & j->rmask;
        p += j->pitch;
    }
}

/* the 8-bit formats' table for EXPAND8: a byte's two words of masks */
static unsigned *x8[PF_N];

static const unsigned *table8(const ExpandJob *j)
{
    if (!x8[j->fmt]) {
        unsigned *t = malloc(512 * sizeof(unsigned));
        int b;
        for (b = 0; b < 256; b++) {
            t[2 * b] = j->f->xt[b & 15];
            t[2 * b + 1] = j->f->xt[b >> 4];
        }
        x8[j->fmt] = t;
    }
    return x8[j->fmt];
}

/* a row's first or last word: its pixels from mask m, under edge mask e */
static void edge(unsigned *d, unsigned m, unsigned e, const ExpandJob *j)
{
    if (j->opaque)
        *d = (*d & ~e) | ((j->bg ^ ((j->fg ^ j->bg) & m)) & e);
    else
        *d ^= (*d ^ j->fg) & m & e;
}

void expand_rows_wif(const ExpandJob *j)
{
    const Format *f = j->f;
    int ps = f->pshift, bytes, h = j->h, n = j->n;
    unsigned *d = j->d;
    const unsigned *s = j->s;
    if (n < 2 || n > 240 || (ps == 3 ? j->opaque : !j->opaque) || (ps == 5 && !f->lin)) {
        expand_rows_blk(j);
        return;
    }
    bytes = ps == 2 ? (n + 2) / 2 : (n + 1) << (ps - 3);
    wif_patch(j);
    while (h-- > 0) {
        const unsigned char *b = wif_align(s, bytes);
        if (ps == 3) {
            /* transparent, 8 pixels a word */
            edge(d, f->xt[b[0]], j->lmask, j);
            wif_expandt(d + 1, b + 1, n - 1, f->xt, j->fg);
            edge(d + n, f->xt[b[n]], j->rmask, j);
        } else if (ps == 4) {
            edge(d, f->xt[b[0]] | f->xt[256 + b[1]], j->lmask, j);
            wif_expand2(d + 1, b + 2, n - 1, f->xt, f->xt + 256, j->fg ^ j->bg, j->bg);
            edge(d + n, f->xt[b[2 * n]] | f->xt[256 + b[2 * n + 1]], j->rmask, j);
        } else if (ps == 5) {
            const unsigned *w = (const unsigned *)b;
            edge(d, w[0], j->lmask, j);
            wif_expand1(d + 1, w + 1, n - 1, j->fg ^ j->bg, j->bg);
            edge(d + n, w[n], j->rmask, j);
        } else {
            /* 4 pixels a word, two a byte: the first two words by hand,
               whole bytes' pairs with EXPAND8, then what's left by hand */
            const unsigned *t = table8(j);
            int whole = (n - 2) / 2, k;
            edge(d, t[2 * b[0]], j->lmask, j);
            edge(d + 1, t[2 * b[0] + 1], ~0u, j);
            wif_expand8(d + 2, b + 1, whole, t, j->fg ^ j->bg, j->bg);
            for (k = 2 + 2 * whole; k <= n; k++)
                edge(d + k, t[2 * b[k >> 1] + (k & 1)], k == n ? j->rmask : ~0u, j);
        }
        d += j->dpitch;
        s += j->spitch;
    }
}
