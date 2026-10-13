/* The graphics library: surfaces at 1, 2, 4 or 8 bits per pixel, and what
   draws on them. studies/graphics/README.md has the overview.

   Coordinates are integers, y down. Rectangles are half-open: (x0, y0) is
   the first pixel, (x1, y1) the first one past the end, so the width is
   x1 - x0. Every drawing operation is clipped to the surface's clip
   rectangle. Coordinates are expected to stay within +-8191 (lines work
   out their clipped start with products that must fit in 32 bits). */

#ifndef GFX_H
#define GFX_H

/* A surface: rows of pixels, `pitch` bytes apart, each row starting on a
   word boundary. Pixel x of a row is bits x*bpp to x*bpp + bpp - 1 of the
   row, counting from bit 0 of its first byte: the first pixel is in the
   low bits, so a 32-bit (little-endian) word holds 32/bpp pixels in
   order, and shifting a word left moves its pixels right. */
typedef struct {
    unsigned char *bits;
    int w, h;
    int pitch;                  /* bytes per row, a multiple of 4 */
    int depth;                  /* log2 of the bits per pixel: 0 to 3 */
    int cx0, cy0, cx1, cy1;     /* the clip rectangle */
} Surface;

typedef struct {
    int x0, y0, x1, y1;
} Rect;

/* Raster operations: what a drawing operation does with the pixels
   already there. */
enum { GFX_COPY, GFX_XOR, GFX_OR, GFX_AND };

/* ---- surfaces (gfx.c) ---- */
void gfx_init(Surface *s, void *bits, int w, int h, int pitch, int depth);
void gfx_clip(Surface *s, int x0, int y0, int x1, int y1);   /* within the surface */
void gfx_clip_rect(Surface *s, const Rect *r);
void gfx_noclip(Surface *s);
unsigned gfx_pat(int depth, unsigned color);   /* a word of `color` pixels */
int gfx_maxcolor(int depth);

/* ---- pixels, rectangles, patterns (gfx.c) ---- */
void gfx_pixel(Surface *s, int x, int y, unsigned color, int rop);
unsigned gfx_get(const Surface *s, int x, int y);
void gfx_fill(Surface *s, int x0, int y0, int x1, int y1, unsigned color, int rop);
void gfx_fill_rect(Surface *s, const Rect *r, unsigned color, int rop);
/* one row, with the colour already a word of pixels (gfx_pat's): the
   spans of polygons and ellipses; a kernel (below) */
void gfx_span_c(Surface *s, int y, int x0, int x1, unsigned pat, int rop);
/* pat: 8 rows of words as gfx_pat makes them; the pattern repeats every
   32/bpp pixels across and 8 rows down, fixed to the surface */
void gfx_fill_pat(Surface *s, int x0, int y0, int x1, int y1, const unsigned *pat, int rop);
void gfx_frame(Surface *s, int x0, int y0, int x1, int y1, int t, unsigned color, int rop);

/* ---- lines and ellipses (line.c, ellipse.c) ---- */
void gfx_line(Surface *s, int x0, int y0, int x1, int y1, unsigned color, int rop);
/* centred on pixel (xc, yc), with radii a across and b down; up to 600 */
void gfx_ellipse(Surface *s, int xc, int yc, int a, int b, unsigned color, int rop);
void gfx_fill_ellipse(Surface *s, int xc, int yc, int a, int b, unsigned color, int rop);

/* ---- polygons and scan conversion (raster.c) ---- */
/* Edges are in 24.8 fixed point (256 to a pixel); pixel (x, y) is the
   square from (x, y) to (x + 1, y + 1), and is filled if its centre is
   inside. */
typedef struct Edge Edge;
struct Edge {
    int x0, y0, x1, y1;         /* y0 < y1 */
    int dir;                    /* 1 if the edge went down, -1 if up */
    int k0, k1;                 /* its first and last sample rows */
    int x, q, r, err, dy;       /* x at the current sample row; per row, x += q + r/dy */
    Edge *next;
};

typedef struct {
    Edge *edges;
    int n, max;
    int ymin, ymax;             /* of all edges, 24.8 */
    int xmin, xmax;
} Raster;

#define GFX_EVENODD 0
#define GFX_NONZERO 1

void rs_init(Raster *r, Edge *edges, int max);
void rs_edge(Raster *r, int x0, int y0, int x1, int y1);      /* 24.8 */
void rs_fill(Raster *r, Surface *s, unsigned color, int rop, int rule);
/* Anti-aliased: 4 sample rows per pixel and 16 steps across; coverage
   0 to 64 per pixel into cov (w x h bytes, cpitch apart, cleared first),
   whose top left is the origin of the edges */
void rs_fill_aa(Raster *r, unsigned char *cov, int cpitch, int w, int h, int rule);
/* a polygon with integer vertices: xy holds n (x, y) pairs */
void gfx_poly(Surface *s, const int *xy, int n, unsigned color, int rop, int rule);

/* ---- copying (blit.c) ---- */
/* Copy a w x h rectangle from (sx, sy) in src to (dx, dy) in dst, which
   have the same depth; they may be the same surface, overlapping. */
void gfx_blit(Surface *dst, int dx, int dy, const Surface *src, int sx, int sy,
              int w, int h, int rop);

/* ---- expansion (expand.c) ---- */
/* Draw a 1-bit source (a font strike, an icon, a cursor mask) in colour:
   its 1 pixels in fg, and its 0 pixels in bg if opaque, else untouched. */
void gfx_expand(Surface *dst, int dx, int dy, const Surface *src, int sx, int sy,
                int w, int h, unsigned fg, unsigned bg, int opaque);
/* Draw coverage bytes (0..64, from rs_fill_aa) through a 65-entry ramp
   of pixel values; pixels with coverage 0 are left alone. */
void gfx_ramp(Surface *dst, int dx, int dy, const unsigned char *cov, int cpitch,
              int w, int h, const unsigned char *ramp);

/* ---- fonts (font.c, ttf.c) ---- */
typedef struct {
    short sx;                   /* in the strike (bitmap fonts) */
    unsigned char w, h;         /* the bitmap's size */
    signed char xoff, yoff;     /* from the pen position (on the baseline) to its top left */
    unsigned char adv;          /* how far the pen moves */
    unsigned char pad;
    unsigned char *bits;        /* coverage bytes or a 1-bit bitmap (cached glyphs) */
} Glyph;

typedef struct Font Font;
struct Font {
    int first, count;           /* the characters it has */
    int ascent, descent, height;
    int aa;                     /* glyphs are coverage, not 1-bit */
    Glyph *glyphs;
    Surface strike;             /* bitmap fonts: all glyphs side by side */
    void *ttf;                  /* outline fonts: the TrueType file, and the size */
    int size;
    Glyph *(*get)(Font *f, int c);
};

/* A bitmap font from its compiled-in description (see fonts/README.md and
   fonts.py): */
void font_bitmap(Font *f, const unsigned char *data);
Glyph *font_glyph(Font *f, int c);
int font_width(Font *f, const char *s);
/* Draw a string with its baseline at y; returns the pen position after
   it. ramp is used by anti-aliased fonts, fg by the others. */
int font_draw(Surface *s, Font *f, int x, int y, const char *str, unsigned fg,
              const unsigned char *ramp);

/* TrueType (ttf.c) */
typedef struct {
    const unsigned char *data;
    int upem, nglyphs, loca_long, nhmetrics;
    int ascent, descent, linegap;
    const unsigned char *cmap, *loca, *glyf, *hmtx;
} TTF;

int ttf_open(TTF *t, const unsigned char *data);
int ttf_glyph_index(TTF *t, int c);
/* Outline of a glyph at a size in pixels (per em), as edges, with the
   pen at (px, py) in 24.8; returns the advance in 24.8, or -1 */
int ttf_outline(TTF *t, int gi, int size, int px, int py, Raster *r);
int ttf_advance(TTF *t, int gi, int size);
/* An outline font at a size; glyphs are rasterised the first time
   they're drawn and cached */
void font_ttf(Font *f, TTF *t, int size, int aa);
/* Rasterise one glyph without caching it, into the given buffer (sized
   w x h, enough for the glyph): returns the glyph's box (benchmarks) */
int ttf_render(TTF *t, int gi, int size, int aa, unsigned char *buf, int bufsize, Glyph *g);

/* ---- kernels: the inner loops, in C and in assembly for each ISA
   (asm/v1a, asm/v1b) ---- */

/* fill: h rows from word p, pitch bytes apart; in each, the first word
   under lmask, then n whole words, then one under rmask (none if rmask
   is 0) */
typedef struct {
    unsigned *p;
    int pitch, h;
    unsigned lmask;
    int n;
    unsigned rmask, pat;
    int rop;
} FillJob;

/* blit: h rows of n + 1 destination words from d (the first under lmask,
   the last under rmask; one word: under both), from source words at s.
   The words are put together from the source words with the shifts
   rs and ls (rs + ls = 32; ls = 0: no shift), as described in blit.c.
   back: right to left, with d and s at the last words. */
typedef struct {
    unsigned *d, *s;
    int dpitch, spitch, h, n;
    unsigned lmask, rmask;
    int rs, ls;
    int pre;                    /* read one source word before the first (see blit.c) */
    int last;                   /* the last destination word needs one more source word */
    int back, rop;
} BlitJob;

/* expand: h rows from destination word d and source word s. Source
   bit soff of s[0] (-32 < soff < 32) lines up with the first pixel of
   d[0], and source words after s[slast] (or before s[0]) count as 0.
   The source is read in 32-bit chunks, lined up that way: nch of them
   per row, the first under cfirst and the last under clast, which clear
   the bits outside the rectangle. A transparent expansion needs nothing
   else; an opaque one also uses the destination masks: n + 1 words, the
   first under lmask and the last under rmask, as for blit. */
typedef struct {
    unsigned *d;
    const unsigned *s;
    int dpitch, spitch, h, n;
    unsigned lmask, rmask;
    int soff, slast;
    unsigned fg, bg;            /* as words of pixels */
    int opaque, depth;
    unsigned cfirst, clast;
    int nch;
} ExpandJob;

/* ramp: h rows of w pixels from coverage bytes c (cpitch apart), into
   destination words from d, whose first pixel is lead pixels before the
   first one; pixels with coverage 0 are left alone */
typedef struct {
    unsigned *d;
    const unsigned char *c;
    int dpitch, cpitch, h, n, lead, w;
    const unsigned char *ramp;
    int depth;
} RampJob;

/* line: n pixels from byte p, mask m, each changed as
   v = (v & ~(m & ka)) ^ (m & kx); dir 0: x-major, a step right per pixel
   and ystep bytes when e > 0; dir +1/-1: y-major, ystep bytes per pixel and
   a step right/left when e > 0. e += inc per pixel, -= dec on a minor step. */
typedef struct {
    unsigned char *p;
    unsigned m, ka, kx;
    int n, e, inc, dec, ystep, dir, depth;
} LineJob;

/* The C kernels are always there, as NAME_c; with GFX_ASM the library
   calls the assembly ones, which may hand the cases they don't cover
   to the C ones. */
void fill_rows_c(const FillJob *j);
void line_run_c(const LineJob *j);
void blit_rows_c(const BlitJob *j);
void expand_rows_c(const ExpandJob *j);
void ramp_rows_c(const RampJob *j);
#ifdef GFX_STM
/* the store-multiple experiment (asm/v1b/stm): these hand what they
   don't cover to the assembly kernels */
void fill_rows_stm(const FillJob *j);
void blit_rows_stm(const BlitJob *j);
#define fill_rows fill_rows_stm
#define blit_rows blit_rows_stm
#endif
#ifdef GFX_ASM
void fill_rows(const FillJob *j);
void line_run(const LineJob *j);
void blit_rows(const BlitJob *j);
void expand_rows(const ExpandJob *j);
void ramp_rows(const RampJob *j);
void gfx_span(Surface *s, int y, int x0, int x1, unsigned pat, int rop);
#else
#define fill_rows fill_rows_c
#define line_run line_run_c
#define blit_rows blit_rows_c
#define expand_rows expand_rows_c
#define ramp_rows ramp_rows_c
#define gfx_span gfx_span_c
#endif

/* the expansion tables, built by gfx_tables() (gfx.c) */
extern unsigned gfx_x2[256];    /* 8 bits to 8 2-bit pixels (16 bits) */
extern unsigned gfx_x4[256];    /* 8 bits to 8 4-bit pixels (32 bits) */
extern unsigned gfx_x8[512];    /* 8 bits to 8 8-bit pixels (2 words, at 2i and 2i + 1) */
void gfx_tables(void);

#endif
