/* Cells of text with their own colours (text.h).

   The library's way (font_cells) puts a string's glyph rows together as
   1-bit rows and expands each through gfx_expand, one colour a call: a
   line with C's colours is a call for each run of one colour, and each
   call is 16 expansions. Our own way knows that a cell on an 8-pixel
   boundary is whole bytes of the row's words, so it writes each cell
   (or each word's cells) down its 16 rows at once:

     4 bits a pixel     a cell is a word: the word for a glyph row (a byte)
                        comes from a table of 256 for the cell's colours
     2 bits, 1 bit      a word holds 2 or 4 cells. A word whose cells have
                        one colour pair is bg ^ (fg ^ bg) & (the OR of each
                        cell's pixel mask), the masks from a mask font: the
                        glyphs' rows as the masks of their pixels, made for
                        each place of a cell in a word from the format's
                        expansion tables (24 KB at 1 bit, 12 KB at 2), so
                        L0's interleaved pixels cost what F1's or L1's do.
                        A word whose cells differ takes each cell's word
                        from its colours' table for its place, OR'd (at 1
                        bit linear, a byte a cell: the glyph row itself)

   The colour tables (256 words for each place of a cell in a word) are
   made when a colour pair is first used. A run of spaces at the end is a
   fill. The columns are C, or draft 2 assembly (textcol.s) in the asm and
   blk variants. */

#include <stdlib.h>
#include "text.h"

int text_lib;
int text_bytes;                 /* 1 bit linear: a byte a cell, no mask font */

/* a character's glyph: its index in the cell font */
#define GLYPH_INDEX(c) ((c) < 32 || (c) > 126 ? (c) ? '?' - 32 : 0 : (c) - 32)
#define GLYPH(c) (font_cell8 + 16 * GLYPH_INDEX(c))

typedef struct {
    const unsigned char *g[4];
    const unsigned *t[4];
    int pitch;                  /* bytes */
} ColJob;

typedef struct {
    const unsigned *m[4];       /* the cells' masks in the mask font */
    unsigned fx, bg;
    int pitch;                  /* bytes */
} MaskJob;

/* words of cells of one colour pair: the mask font, each character's
   glyph's offset in a place's masks (bytes; place j's masks 6144 j on) */
typedef struct {
    const unsigned *mf;
    const int *gofs;
    unsigned fx, bg;
    int pitch;                  /* bytes */
} MaskRun;

#ifdef GFX_ASM
void text_col1(unsigned *d, const unsigned char *g, const unsigned *t, int pitch);
void text_lin1(unsigned char *d, const unsigned char *g, unsigned inv, int pitch);
void text_col2(unsigned *d, const ColJob *j);
void text_col4(unsigned *d, const ColJob *j);
void text_mask2(unsigned *d, const MaskJob *j);
void text_mask4(unsigned *d, const MaskJob *j);
void text_run2(unsigned *d, const char *t, int nw, const MaskRun *run);
void text_run4(unsigned *d, const char *t, int nw, const MaskRun *run);
#else
static void text_col1(unsigned *d, const unsigned char *g, const unsigned *t, int pitch)
{
    int r;
    pitch >>= 2;
    for (r = 0; r < 16; r++, d += pitch)
        *d = t[g[r]];
}

static void text_lin1(unsigned char *d, const unsigned char *g, unsigned inv, int pitch)
{
    int r;
    for (r = 0; r < 16; r++, d += pitch)
        *d = g[r] ^ inv;
}

static void text_col2(unsigned *d, const ColJob *j)
{
    const unsigned char *g0 = j->g[0], *g1 = j->g[1];
    const unsigned *t0 = j->t[0], *t1 = j->t[1];
    int r, pitch = j->pitch >> 2;
    for (r = 0; r < 16; r++, d += pitch)
        *d = t0[g0[r]] | t1[g1[r]];
}

static void text_col4(unsigned *d, const ColJob *j)
{
    const unsigned char *g0 = j->g[0], *g1 = j->g[1], *g2 = j->g[2], *g3 = j->g[3];
    const unsigned *t0 = j->t[0], *t1 = j->t[1], *t2 = j->t[2], *t3 = j->t[3];
    int r, pitch = j->pitch >> 2;
    for (r = 0; r < 16; r++, d += pitch)
        *d = t0[g0[r]] | t1[g1[r]] | t2[g2[r]] | t3[g3[r]];
}

static void text_mask2(unsigned *d, const MaskJob *j)
{
    const unsigned *m0 = j->m[0], *m1 = j->m[1];
    unsigned fx = j->fx, bg = j->bg;
    int r, pitch = j->pitch >> 2;
    for (r = 0; r < 16; r++, d += pitch)
        *d = bg ^ (fx & (m0[r] | m1[r]));
}

static void text_mask4(unsigned *d, const MaskJob *j)
{
    const unsigned *m0 = j->m[0], *m1 = j->m[1], *m2 = j->m[2], *m3 = j->m[3];
    unsigned fx = j->fx, bg = j->bg;
    int r, pitch = j->pitch >> 2;
    for (r = 0; r < 16; r++, d += pitch)
        *d = bg ^ (fx & (m0[r] | m1[r] | m2[r] | m3[r]));
}

#define MASKS(run, j, c) ((const unsigned *)((const char *)(run)->mf + 6144 * (j) + \
                                             (run)->gofs[(unsigned char)(c)]))

static void text_run2(unsigned *d, const char *t, int nw, const MaskRun *run)
{
    MaskJob mj;
    mj.fx = run->fx;
    mj.bg = run->bg;
    mj.pitch = run->pitch;
    for (; nw > 0; nw--, d++, t += 2) {
        mj.m[0] = MASKS(run, 0, t[0]);
        mj.m[1] = MASKS(run, 1, t[1]);
        text_mask2(d, &mj);
    }
}

static void text_run4(unsigned *d, const char *t, int nw, const MaskRun *run)
{
    MaskJob mj;
    mj.fx = run->fx;
    mj.bg = run->bg;
    mj.pitch = run->pitch;
    for (; nw > 0; nw--, d++, t += 4) {
        mj.m[0] = MASKS(run, 0, t[0]);
        mj.m[1] = MASKS(run, 1, t[1]);
        mj.m[2] = MASKS(run, 2, t[2]);
        mj.m[3] = MASKS(run, 3, t[3]);
        text_mask4(d, &mj);
    }
}
#endif

/* ---- the colour pairs' tables ---- */

static const Format *tab_f;
static unsigned *tab_of[256];   /* by attribute, for tab_f */

/* attr's table: for each place j of a cell in a word, 256 words: the
   cell's pixels for a glyph row, in its colours, the rest 0 */
static const unsigned *colour_table(const Format *f, int attr)
{
    int j, b, cpw = (1 << f->pshift) >> 3;
    unsigned cm = (1u << f->bpp) - 1, bg, fx, *t;
    if (f != tab_f) {
        for (j = 0; j < 256; j++) {
            free(tab_of[j]);
            tab_of[j] = 0;
        }
        tab_f = f;
    }
    if (tab_of[attr])
        return tab_of[attr];
    t = tab_of[attr] = malloc(256 * cpw * sizeof(unsigned));
    bg = f->solid[(attr >> 4) & cm];
    fx = f->solid[attr & cm] ^ bg;
    for (j = 0; j < cpw; j++) {
        const unsigned *x = f->xt + 256 * j;
        unsigned m = x[255];
        for (b = 0; b < 256; b++)
            t[256 * j + b] = (bg & m) ^ (fx & x[b]);
    }
    return t;
}

/* ---- the mask font ---- */

static const Format *mf_f;
static unsigned *mf;            /* place j, glyph c, row r: mf[(96 * j + c) * 16 + r] */
static int gofs[256];           /* a character's glyph's offset in a place's masks, bytes */

static void mask_font(const Format *f)
{
    int cpw = (1 << f->pshift) >> 3, j, c, r;
    unsigned *p;
    if (f == mf_f)
        return;
    for (c = 0; c < 256; c++)
        gofs[c] = 64 * GLYPH_INDEX(c);
    free(mf);
    p = mf = malloc(cpw * 96 * 16 * sizeof(unsigned));
    mf_f = f;
    for (j = 0; j < cpw; j++)
        for (c = 0; c < 96; c++)
            for (r = 0; r < 16; r++) {
                unsigned g = c < 95 ? font_cell8[16 * c + r] : 0;
                *p++ = f->lin ? g << (8 * j) : f->xt[256 * j + g];
            }
}

/* ---- the library's way: a font_cells call for each run of one attribute ---- */

static void cells_lib(Surface *s, int x, int y, const char *t, const unsigned char *a, int n)
{
    int i = 0, j;
    while (i < n) {
        for (j = i + 1; j < n && a[j] == a[i]; j++)
            ;
        font_cells(s, x + 8 * i, y, t + i, j - i, a[i] & 15, a[i] >> 4);
        i = j;
    }
}

/* ---- our own ---- */

/* 4 bits a pixel: a word a cell */
static void cells4(Surface *s, int x, int y, const char *t, const unsigned char *a, int n)
{
    unsigned *d = s->bits + y * s->pitch + (x >> 3);
    int k = 0, pitch = s->pitch * 4;
    while (k < n) {
        /* a run of one attribute: its table once */
        const unsigned *tab = colour_table(s->f, a[k]);
        do {
            text_col1(d++, GLYPH(t[k]), tab, pitch);
            k++;
        } while (k < n && a[k] == a[k - 1]);
    }
}

/* 1 bit a pixel, linear, cells k0..k1-1: a byte a cell, pixel 0 its bit 0
   as in the font */
static void cells_lin1(Surface *s, int x, int y, const char *t, const unsigned char *a, int k0,
                       int k1)
{
    unsigned char *d = (unsigned char *)(s->bits + y * s->pitch) + (x >> 3) + k0;
    int k, pb = s->pitch * 4;
    for (k = k0; k < k1; k++, d++) {
        int fg = a[k] & 1, bg = a[k] >> 4 & 1;
        text_lin1(d, GLYPH(fg == bg ? ' ' : t[k]), bg ? 0xFF : 0, pb);
    }
}

/* 2 or 4 cells a word (2 bits a pixel, 1 bit) */
static void cells_words(Surface *s, int x, int y, const char *t, const unsigned char *a, int n)
{
    const Format *f = s->f;
    int cpw = 1 << (s->pshift - 3), c0 = x >> 3, c1 = c0 + n, cw, j, r, pitch = s->pitch;
    int lin1 = s->fmt == PF_LIN1;
    unsigned cm = (1u << f->bpp) - 1;
    ColJob job;
    MaskRun run;
    job.pitch = run.pitch = pitch * 4;
    mask_font(f);
    run.mf = mf;
    run.gofs = gofs;
    for (cw = c0 & ~(cpw - 1); cw < c1; cw += cpw) {
        unsigned *d = s->bits + y * pitch + cw / cpw, keep = ~0u;
        int k = cw - c0, m = 0;
        if (k >= 0 && k + cpw <= n) {
            /* whole words of one colour pair, as many as there are in a
               row: through the mask font */
            int e = k + 1, nw;
            while (e < n && a[e] == a[k])
                e++;
            nw = (e - k) / cpw;
            if (nw > 0) {
                run.bg = f->solid[(a[k] >> 4) & cm];
                run.fx = f->solid[a[k] & cm] ^ run.bg;
                if (cpw == 2)
                    text_run2(d, t + k, nw, &run);
                else
                    text_run4(d, t + k, nw, &run);
                cw += (nw - 1) * cpw;
                continue;
            }
        }
        if (lin1) {
            /* 1 bit linear: the cells' bytes */
            cells_lin1(s, x, y, t, a, k < 0 ? 0 : k, k + cpw > n ? n : k + cpw);
            continue;
        }
        /* each cell through its colours' table */
        for (j = 0; j < cpw; j++) {
            int i = k + j;
            if (i < 0 || i >= n)
                continue;
            job.t[m] = colour_table(f, a[i]) + 256 * j;
            job.g[m] = GLYPH(t[i]);
            keep &= ~f->xt[256 * j + 255];      /* the cell's pixels */
            m++;
        }
        if (m == cpw) {
            if (m == 2)
                text_col2(d, &job);
            else
                text_col4(d, &job);
            continue;
        }
        /* a word only partly ours: its other cells kept */
        for (r = 0; r < 16; r++, d += pitch) {
            unsigned v = *d & keep;
            for (j = 0; j < m; j++)
                v |= job.t[j][job.g[j][r]];
            *d = v;
        }
    }
}

/* the caret: a bar two pixels wide down a cell's left edge, XOR'd with c */
void text_caret(Surface *s, int x, int y, unsigned c)
{
    const Format *f = s->f;
    unsigned *d = s->bits + y * s->pitch + (x >> s->pshift), v;
    int p = x & ((1 << s->pshift) - 1), r;
    v = gfx_solidf(f, c) & (f->pmask[p] | f->pmask[p + 1]);
    for (r = 0; r < 16; r++, d += s->pitch)
        *d ^= v;
}

void text_cells(Surface *s, int x, int y, const char *t, const unsigned char *a, int n)
{
    int m;
    if (n <= 0)
        return;
    if (text_lib || s->pshift < 3 || (x & 7) || x < 0 || y < 0 || x + 8 * n > s->w ||
        y + 16 > s->h) {
        cells_lib(s, x, y, t, a, n);
        return;
    }
    /* trailing spaces of one colour: a fill (looked for a word at a time
       where the text and the attributes are aligned) */
    {
        unsigned aa = a[n - 1];
        aa |= aa << 8;
        aa |= aa << 16;
        for (m = n; m > 0 && ((unsigned)(t + m) & 3) && t[m - 1] == ' ' && a[m - 1] == a[n - 1];
             m--)
            ;
        if (!(((unsigned)(t + m) | (unsigned)(a + m)) & 3))
            while (m >= 4 && *(const unsigned *)(t + m - 4) == 0x20202020 &&
                   *(const unsigned *)(a + m - 4) == aa)
                m -= 4;
        for (; m > 0 && t[m - 1] == ' ' && a[m - 1] == a[n - 1]; m--)
            ;
    }
    if (n - m >= 2) {
        gfx_fill(s, x + 8 * m, y, x + 8 * n, y + 16, a[n - 1] >> 4, ROP_COPY);
        n = m;
        if (!n)
            return;
    }
    if (s->fmt == PF_LIN1 && text_bytes) {
        cells_lin1(s, x, y, t, a, 0, n);
        return;
    }
    gfx_xmask(s->f, 0);         /* the format's tables, made when first used */
    if (s->pshift == 3)
        cells4(s, x, y, t, a, n);
    else
        cells_words(s, x, y, t, a, n);
}
