/* The inner loops in plain C (the c variant; kernels.s has them in draft 2
   and with the block instructions). Everything is whole words: the
   images were shifted and masked when they were made (art.c). */

#include "game.h"

/* n words */
void k_copy_c(unsigned *d, const unsigned *s, int n)
{
    while (n-- > 0)
        *d++ = *s++;
}

/* n words from n + 1, shifted left by p pixels of 8 bits (L0: pixel 0 is
   the low byte): d[i] = s[i] >> 8p | s[i + 1] << 32 - 8p. A shift by a
   variable count costs a cycle a bit, so each phase has its own loop with
   constants. */
void k_shift_c(unsigned *d, const unsigned *s, int n, int p)
{
    unsigned lo = *s++, hi;
    switch (p) {
    case 1:
        while (n-- > 0) {
            hi = *s++;
            *d++ = lo >> 8 | hi << 24;
            lo = hi;
        }
        break;
    case 2:
        while (n-- > 0) {
            hi = *s++;
            *d++ = lo >> 16 | hi << 16;
            lo = hi;
        }
        break;
    case 3:
        while (n-- > 0) {
            hi = *s++;
            *d++ = lo >> 24 | hi << 8;
            lo = hi;
        }
        break;
    default:
        k_copy_c(d, s - 1, n);
    }
}

/* a sprite: each word (d & keep) | image */
void k_sprite_c(const SprJob *j)
{
    const unsigned *data = j->data;
    int i, k;
    for (i = 0; i < j->h; i++) {
        unsigned *q = j->rows[i];
        if (q)
            for (k = 0; k < j->n; k++)
                q[k] = (q[k] & data[2 * k]) | data[2 * k + 1];
        data += j->stride;
    }
}

/* the same, each row's words saved first (j->save, n a row in order) */
void k_sprite_save_c(const SprJob *j)
{
    const unsigned *data = j->data;
    unsigned *save = j->save;
    int i, k;
    for (i = 0; i < j->h; i++) {
        unsigned *q = j->rows[i];
        for (k = 0; k < j->n; k++) {
            unsigned v = q[k];
            *save++ = v;
            q[k] = (v & data[2 * k]) | data[2 * k + 1];
        }
        data += j->stride;
    }
}

/* what k_sprite_save kept put back */
void k_restore_c(const SprJob *j)
{
    const unsigned *save = j->save;
    int i, k;
    for (i = 0; i < j->h; i++) {
        unsigned *q = j->rows[i];
        for (k = 0; k < j->n; k++)
            q[k] = *save++;
    }
}

/* a tile row's lines from the tiles' pre-shifted images: each tile's
   words 1-3, then its word 4 with the next tile's word 0 */
void k_redraw_c(const RedrawJob *j)
{
    int l, i;
    for (l = 0; l < j->h; l++) {
        unsigned *q = j->d + l * j->pitch, pend;
        const unsigned *t = j->tiles[0] + 5 * l;
        q[0] = t[1];
        q[1] = t[2];
        q[2] = t[3];
        pend = t[4];
        q += 3;
        for (i = 1; i < 21; i++) {
            t = j->tiles[i] + 5 * l;
            q[0] = pend | t[0];
            q[1] = t[1];
            q[2] = t[2];
            q[3] = t[3];
            pend = t[4];
            q += 4;
        }
        *q = pend | j->tiles[21][5 * l];
    }
}
