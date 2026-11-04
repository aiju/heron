/* The graphics library's interface, as much of it as TrueType text needs:
   surfaces, the scan converter, glyphs, TrueType fonts and the kernels
   that draw glyphs. Copied from studies/graphics/src/gfx.h and trimmed
   (no lines, ellipses, blits, patterns or assembly kernels); the
   TrueType part adds kerning and the glyph cache (ttf.c, text.c).

   Coordinates are integers, y down. Rectangles are half-open: (x0, y0) is
   the first pixel, (x1, y1) the first one past the end. */

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

/* Raster operations: what a drawing operation does with the pixels
   already there. */
enum { GFX_COPY, GFX_XOR, GFX_OR, GFX_AND };

/* ---- surfaces (gfx.c) ---- */
void gfx_init(Surface *s, void *bits, int w, int h, int pitch, int depth);
void gfx_clip(Surface *s, int x0, int y0, int x1, int y1);   /* within the surface */
void gfx_noclip(Surface *s);
unsigned gfx_pat(int depth, unsigned color);   /* a word of `color` pixels */
int gfx_maxcolor(int depth);
void gfx_fill(Surface *s, int x0, int y0, int x1, int y1, unsigned color, int rop);
/* one row, with the colour already a word of pixels (gfx_pat's): the
   spans of glyph outlines */
void gfx_span(Surface *s, int y, int x0, int x1, unsigned pat, int rop);

/* ---- scan conversion (raster.c) ---- */
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

/* ---- drawing glyphs (expand.c) ---- */
/* Draw a 1-bit source (a glyph's bitmap) in colour on an 8-bit surface
   (the 1-, 2- and 4-bit ones of studies/graphics are left out): its 1
   pixels in fg, its 0 pixels untouched. */
void gfx_expand(Surface *dst, int dx, int dy, const Surface *src, int sx, int sy,
                int w, int h, unsigned fg);
/* Draw coverage bytes (0..64, from rs_fill_aa) through a 65-entry ramp
   of pixel values; pixels with coverage 0 are left alone. */
void gfx_ramp(Surface *dst, int dx, int dy, const unsigned char *cov, int cpitch,
              int w, int h, const unsigned char *ramp);

/* ---- glyphs and fonts (ttf.c, text.c) ---- */
typedef struct {
    unsigned char w, h;         /* the bitmap's size */
    signed char xoff, yoff;     /* from the pen position (on the baseline) to its top left */
    unsigned char adv;          /* how far the pen moves, whole pixels */
    unsigned char pad;
    unsigned short adv8;        /* the same in 24.8, for layout */
    unsigned char *bits;        /* coverage bytes, or a 1-bit bitmap a word per row */
} Glyph;

/* TrueType (ttf.c) */
typedef struct {
    const unsigned char *data;
    int upem, nglyphs, loca_long, nhmetrics;
    int ascent, descent, linegap;
    const unsigned char *cmap, *loca, *glyf, *hmtx;
    const unsigned char *kern;  /* format 0 pairs, or 0 */
    int nkern;
} TTF;

int ttf_open(TTF *t, const unsigned char *data);
int ttf_glyph_index(TTF *t, int c);
/* Outline of a glyph at a size in pixels (per em), as edges, with the
   pen at (px, py) in 24.8; returns the advance in 24.8, or -1 */
int ttf_outline(TTF *t, int gi, int size, int px, int py, Raster *r);
int ttf_advance(TTF *t, int gi, int size);               /* 24.8 */
/* The kerning between two glyphs at a size, 24.8 (0 if none) */
int ttf_kern(TTF *t, int left, int right, int size);
/* Rasterise one glyph into buf (bufsize bytes); fills in g but its bits;
   returns the bytes used, 0 for a glyph with no outline, -1 if it
   doesn't fit */
int ttf_render(TTF *t, int gi, int size, int aa, unsigned char *buf, int bufsize, Glyph *g);

/* An outline font at a size, its glyphs rasterised the first time
   they're drawn and kept in the glyph cache (text.c) */
typedef struct {
    TTF *ttf;
    int size, aa;
    int ascent, descent, height;
    int id;                     /* in the cache's keys */
    short gidx[96];             /* the glyph of each character from 32 ('?' for the
                                   rest), looked up when first needed; -1 before */
} Font;

void font_open(Font *f, TTF *t, int size, int aa);
Glyph *font_glyph(Font *f, int c);
/* Draw a string with its baseline at y, kerned; returns the pen position
   after it. ramp is used by anti-aliased fonts, fg by the others. */
int font_draw(Surface *s, Font *f, int x, int y, const char *str, int n, unsigned fg,
              const unsigned char *ramp);
/* The width of n characters as font_draw lays them out */
int font_width(Font *f, const char *str, int n);

/* the glyph cache's counts */
extern int cache_hits, cache_misses, cache_bytes, cache_flushes;
void cache_init(void);

/* ---- kernels: the inner loops (gfx.c, expand.c) ---- */

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

/* expand (8-bit pixels): h rows from destination word d and source word s. Source
   bit soff of s[0] (-32 < soff < 32) lines up with the first pixel of
   d[0], and source words after s[slast] count as 0. The source is read
   in 32-bit chunks, lined up that way: nch of them per row, the first
   under cfirst and the last under clast, which clear the bits outside
   the rectangle. */
typedef struct {
    unsigned *d;
    const unsigned *s;
    int dpitch, spitch, h;
    int soff, slast;
    unsigned fg;                /* as a word of pixels */
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

void fill_rows(const FillJob *j);
void expand_rows(const ExpandJob *j);
void ramp_rows(const RampJob *j);

/* the expansion table, built by gfx_tables() (gfx.c) */
extern unsigned gfx_x8[512];    /* 8 bits to 8 8-bit pixels (2 words, at 2i and 2i + 1) */
void gfx_tables(void);

#endif
