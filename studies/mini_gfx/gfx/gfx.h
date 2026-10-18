/* The graphics library: surfaces in every pixel layout of RFC 0042, and
   what draws on them. studies/mini_gfx/README.md has the overview.

   A pixel format is where each pixel's bits are in a word (gfx/format.c):

     PF_LIN1 .. PF_LIN8   pixel p at bits p*bpp up: L0 at 4 and 8 bits, F1
                          at 1 and 2, L1 at 1
     PF_CHK1, PF_CHK2     L0 without F1: pixel p's bit i at 4(p mod 8) + p/8,
                          + 2i at 2 bits
     PF_PL2, PF_PL4, PF_PL8   L1's planes: byte (or half) k holds bit k of
                          the word's pixels

   Everything that depends on the format comes from that one description
   at the start of an operation: masks, solid colours, the terms a
   shifted copy merges its words with, the tables a 1-bit source expands
   through. The kernels (the inner loops: fill, copy, shifted copy,
   expansion, lines) take jobs with all of it worked out, and come in C,
   in draft 2 assembly (GFX_ASM) and with the block instructions (GFX_BLK).

   Coordinates are integers, y down; rectangles are half-open (x0, y0)
   to (x1, y1). Every operation is clipped to the surface's clip. */

#ifndef GFX_H
#define GFX_H

enum { PF_LIN1, PF_LIN2, PF_LIN4, PF_LIN8, PF_CHK1, PF_CHK2, PF_PL2, PF_PL4, PF_PL8, PF_N };

/* raster operations */
enum { ROP_COPY, ROP_XOR, ROP_OR, ROP_AND };

typedef struct {
    int x0, y0, x1, y1;
} Rect;

/* ---- formats (format.c) ---- */
typedef struct {
    int bpp, pshift;
    unsigned pmask[32];         /* each pixel's bits */
    unsigned lsb[32];           /* each pixel's bit 0 */
    int lin;                    /* PF_LINn: the identity */
    /* expanding 1-bit pixels: a word's ppw source bits (bit 0 the first
       pixel) to the mask of their pixels, through nx tables of 256 */
    int nx;
    unsigned *xt;               /* nx * 256 words, built when first used */
    unsigned *solid;            /* each colour's word */
    unsigned from[33];          /* the mask of pixels i on (gfx_from) */
    int ready;
} Format;

typedef struct {
    unsigned *bits;             /* row 0's first word */
    int w, h;
    int pitch;                  /* words a row */
    int fmt;
    int bpp, pshift;            /* bits a pixel; log2 of the pixels a word */
    Rect clip;
    const Format *f;
} Surface;

extern Format gfx_formats[PF_N];
extern int board_layout;        /* 0: L0, 1: L1; the harness sets it */
const Format *gfx_format(int fmt);
/* the format the screen has in the current mode (video.h's vid) */
int gfx_screen_format(void);
int gfx_format_of(int bpp, int layout, int f1);
/* a word of colour c in every pixel */
unsigned gfx_solid(int fmt, unsigned c);
/* a linear 1-bit word (ppw pixels) to its pixels' mask */
unsigned gfx_xmask(const Format *f, unsigned bits);
/* the bit position of pixel p's bit i */
int gfx_bitpos(int fmt, int p, int i);

/* ---- surfaces (gfx.c) ---- */
void gfx_init(Surface *s, void *bits, int w, int h, int pitch, int fmt);
void gfx_sub(Surface *s, const Surface *parent, int x0, int y0, int x1, int y1);  /* a view */
void gfx_clip(Surface *s, int x0, int y0, int x1, int y1);
void gfx_clip_rect(Surface *s, const Rect *r);
void gfx_noclip(Surface *s);
/* the screen: a surface over a framebuffer in bank 1 */
void gfx_screen(Surface *s, void *bits, int pitch);

/* ---- drawing (gfx.c, line.c) ---- */
void gfx_pixel(Surface *s, int x, int y, unsigned c, int rop);
unsigned gfx_get(const Surface *s, int x, int y);
void gfx_fill(Surface *s, int x0, int y0, int x1, int y1, unsigned c, int rop);
void gfx_fill_rect(Surface *s, const Rect *r, unsigned c, int rop);
/* an 8 x 8 pattern of two colours, its rows' bits (bit 0 left), fixed to the surface */
void gfx_fill_pat(Surface *s, int x0, int y0, int x1, int y1, const unsigned char *rows,
                  unsigned fg, unsigned bg);
void gfx_frame(Surface *s, int x0, int y0, int x1, int y1, int t, unsigned c, int rop);
void gfx_hline(Surface *s, int x0, int x1, int y, unsigned c, int rop);
void gfx_vline(Surface *s, int x, int y0, int y1, unsigned c, int rop);
void gfx_line(Surface *s, int x0, int y0, int x1, int y1, unsigned c, int rop);
void gfx_circle(Surface *s, int xc, int yc, int r, unsigned c, int rop);
void gfx_fill_circle(Surface *s, int xc, int yc, int r, unsigned c, int rop);
/* a 3D box: light top left, dark bottom right */
void gfx_bevel(Surface *s, int x0, int y0, int x1, int y1, unsigned light, unsigned dark);

/* ---- copying (blit.c) ---- */
/* a w x h rectangle from (sx, sy) in src to (dx, dy) in dst, the same
   format; the same surface, overlapping, is fine */
void gfx_blit(Surface *dst, int dx, int dy, const Surface *src, int sx, int sy, int w, int h,
              int rop);
/* a 1-bit source (linear, bit 0 the leftmost) in colour: its 1s in fg,
   its 0s in bg if opaque, else left alone */
typedef struct {
    const unsigned *bits;
    int pitch;                  /* words a row */
} Bitmap;
void gfx_expand(Surface *dst, int dx, int dy, const Bitmap *src, int sx, int sy, int w, int h,
                unsigned fg, unsigned bg, int opaque);
/* a sprite: an image in dst's format and a 1-bit mask (1: drawn) */
void gfx_masked(Surface *dst, int dx, int dy, const Surface *img, const Bitmap *mask, int sx,
                int sy, int w, int h);

/* ---- fonts (font.c) ---- */
typedef struct {
    short sx;                   /* in the strike, in pixels */
    unsigned char w, h, adv;
    signed char xoff, yoff;     /* from the pen on the baseline to the box's top left */
} Glyph;

typedef struct {
    int first, count, ascent, descent, height;
    int cell;                   /* a cell font: 8 wide, every glyph a byte a row */
    Glyph *glyphs;
    Bitmap strike;
} Font;

extern const unsigned char font_sans12[], font_mono12[], font_cell8[];
extern Font *font_sans, *font_mono, *font_cell;
void font_init(void);                       /* the three fonts */
int font_width(const Font *f, const char *s);
int font_widthn(const Font *f, const char *s, int n);
/* a string, its baseline at y: transparent (bg < 0) or opaque in its
   line's box; returns the pen after it */
int font_draw(Surface *s, const Font *f, int x, int y, const char *str, unsigned fg, int bg);
int font_drawn(Surface *s, const Font *f, int x, int y, const char *str, int n, unsigned fg,
               int bg);
/* a cell font's string, the cells' top at y, transparent if bg < 0: the
   text's rows put together as 1-bit rows, each expanded at once */
void font_cells(Surface *s, int x, int y, const char *str, int n, unsigned fg, int bg);

/* ---- kernels ---- */

/* fill: h rows from word p, pitch words apart; in each the first word
   under lmask, then n whole words, then one under rmask (none if 0). The
   pattern is pat, or pats[(row0 + y) & 7] if pats */
typedef struct {
    unsigned *p;
    int pitch, h;
    unsigned lmask;
    int n;
    unsigned rmask, pat;
    int rop;
    const unsigned *pats;
    int row0;
} FillJob;

/* copy: h rows of n + 1 words (the first under lmask, the last under
   rmask; one word: lmask & rmask, rmask 0), from s to d, pitches in
   words (negative: bottom up). back: each row right to left, d and s at
   its last word */
typedef struct {
    unsigned *d;
    const unsigned *s;
    int dpitch, spitch, h, n;
    unsigned lmask, rmask;
    int back, rop;
} CopyJob;

/* shift: as copy, but each destination word made of two source words,
   lo and the next, hi: d = OR over the terms of ((lo or hi) shifted) &
   mask. The source row starts at s with lo = s[0]. nterm 2 is
   ((lo >> sh0) & m0) | ((hi << sh1) & m1); back is never needed: an
   overlapping shifted copy goes through a row buffer */
typedef struct {
    int src;                    /* 0 lo, 1 hi */
    int sh;                     /* > 0 left, < 0 right */
    unsigned m;
} Term;

typedef struct {
    unsigned *d;
    const unsigned *s;
    int dpitch, spitch, h, n;
    unsigned lmask, rmask;
    int rop;
    int nterm;
    Term t[6];
    int phase, bpp, fmt;        /* the shift in pixels, for the kernels that use it */
} ShiftJob;

/* expand: h rows; in each, destination words d[0..n] (the first under
   lmask, the last under rmask, as for copy), the source's bits from bit
   soff of s[0] (0 <= soff < 32) on, ppw bits a word, through the
   format's tables to a mask; transparent: d = d ^ ((d ^ fg) & mask);
   opaque: bg ^ ((fg ^ bg) & mask) */
typedef struct {
    unsigned *d;
    const unsigned *s;
    int dpitch, spitch, h, n;
    unsigned lmask, rmask;
    int soff;
    unsigned fg, bg;
    int opaque;
    const Format *f;
    int fmt;
} ExpandJob;

/* line: n pixels from word p, pixel index i (of ppw), each changed as
   v = (v & ~(m & ka)) ^ (m & kx), m the pixel's mask (masks[i]); the
   major step is +1 pixel (dir 0) or ystep words (dir != 0); the minor
   step, when e >= 0, ystep words (dir 0) or dir pixels; e += inc a step,
   -= dec on a minor step */
typedef struct {
    unsigned *p;
    int i, ppw;
    const unsigned *masks;
    unsigned ka, kx;
    int n, e, inc, dec, ystep, dir;
} LineJob;

void fill_rows_c(const FillJob *j);
void copy_rows_c(const CopyJob *j);
void shift_rows_c(const ShiftJob *j);
void expand_rows_c(const ExpandJob *j);
void line_run_c(const LineJob *j);

#ifdef GFX_ASM
void fill_rows_asm(const FillJob *j);
void copy_rows_asm(const CopyJob *j);
void shift_rows_asm(const ShiftJob *j);
void expand_rows_asm(const ExpandJob *j);
void line_run_asm(const LineJob *j);
#ifdef GFX_BLK
/* the block instructions from C (gfx/blk/blk.s), any count */
void blk_fill(unsigned *d, unsigned v, int n);
void blk_copy(unsigned *d, const unsigned *s, int n);
void blk_expand(unsigned *d, const unsigned char *s, int n, const unsigned *table,
                unsigned fg_xor_bg, unsigned bg);
unsigned blk_blit(unsigned *d, const unsigned *s, int n, int k, unsigned lo, unsigned mask);
void fill_rows_blk(const FillJob *j);
void copy_rows_blk(const CopyJob *j);
void shift_rows_blk(const ShiftJob *j);
void expand_rows_blk(const ExpandJob *j);
#ifdef GFX_WIF
/* the what-if block instructions (whatif.py, gfx/wif) */
void fill_rows_wif(const FillJob *j);
void shift_rows_wif(const ShiftJob *j);
void expand_rows_wif(const ExpandJob *j);
#define fill_rows fill_rows_wif
#define shift_rows shift_rows_wif
#define expand_rows expand_rows_wif
#else
#define fill_rows fill_rows_blk
#define shift_rows shift_rows_blk
#define expand_rows expand_rows_blk
#endif
#define copy_rows copy_rows_blk
#else
#define fill_rows fill_rows_asm
#define copy_rows copy_rows_asm
#define shift_rows shift_rows_asm
#define expand_rows expand_rows_asm
#endif
#define line_run line_run_asm
#else
#define fill_rows fill_rows_c
#define copy_rows copy_rows_c
#define shift_rows shift_rows_c
#define expand_rows expand_rows_c
#define line_run line_run_c
#endif

/* edges: the mask of pixels from i on, and before i (0 <= i <= ppw) */
#define gfx_from(f, i) ((f)->from[i])
#define gfx_before(f, i) (~(f)->from[i])
/* a word of colour c in every pixel */
#define gfx_solidf(f, c) ((f)->solid[(c) & ((1u << (f)->bpp) - 1)])

#endif
