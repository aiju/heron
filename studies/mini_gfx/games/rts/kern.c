/* The drawing kernels in C (the c variant's; kern.s has them in
   assembly, kern_blk.s with the block instructions). They work on words,
   whatever the pixel format: the sprites are pre-shifted into the
   screen's format, and a tile is always whole words. */

#include "rts.h"

/* h rows of n words from s to d; pitches in bytes */
void k_copy_c(unsigned *d, const unsigned *s, int n, int h, int dpitch, int spitch)
{
    while (h-- > 0) {
        unsigned *q = d;
        const unsigned *r = s;
        int k = n;
        while (k-- > 0)
            *q++ = *r++;
        d = (unsigned *)((char *)d + dpitch);
        s = (const unsigned *)((const char *)s + spitch);
    }
}

/* a pre-shifted sprite: each row n (keep, image) pairs; the destination
   keeps its pixels under keep and takes image's elsewhere */
void k_sprite_c(unsigned *d, const unsigned *s, int n, int h, int dpitch)
{
    while (h-- > 0) {
        unsigned *q = d;
        int k = n;
        while (k-- > 0) {
            *q = (*q & s[0]) | s[1];
            q++;
            s += 2;
        }
        d = (unsigned *)((char *)d + dpitch);
    }
}

/* a tile: 16 rows of n words, one after the other from s */
void k_tile_c(unsigned *d, const unsigned *s, int n, int dpitch)
{
    int h = TILE;
    while (h-- > 0) {
        unsigned *q = d;
        int k = n;
        while (k-- > 0)
            *q++ = *s++;
        d = (unsigned *)((char *)d + dpitch);
    }
}

/* the viewport's descriptors: n lines' words from base, step words apart,
   each line rep times (M1's doubled lines) */
void k_desc_c(unsigned *t, unsigned base, int step, int n, int rep)
{
    if (rep == 2) {
        while (n-- > 0) {
            t[0] = base;
            t[1] = base;
            t += 2;
            base += step;
        }
        return;
    }
    while (n-- > 0) {
        *t++ = base;
        base += step;
    }
}
