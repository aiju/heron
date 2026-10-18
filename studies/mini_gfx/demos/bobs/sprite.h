/* Software sprites ("bobs", blitter objects) for a screen with guard
   bands: the sprites' images and masks, their pre-shifted copies, the
   sprite compiler, and the kernels that draw and erase them.

   A sprite is drawn at its top left word d (in a buffer of `bob_pitch`
   words a row) and its pixel phase p within that word (x mod pixels a
   word). Pre-shifting does all the work that depends on the pixel
   format once, at start-up: every phase's rows are whole words of an
   inverted mask and an image, so drawing a row is

       d = (d & ~mask) | image

   a word at a time, whatever the format (linear, chunky or planar).

   Three forms of the pre-shifted data, fastest last:

     shifted    every row ww words, each a pair (~mask, image)
     spans      a row is a header (its first word, then counts of masked,
                opaque and masked words) and only those words: the
                transparent words are skipped, the opaque ones stored
                without reading the screen
     compiled   machine code (jit.c): each word a store or a
                read-modify-write with its constants in the instructions
                or in registers, the transparent words not there at all

   The screen has guard bands (bob_pitch words a row, more than the
   picture's) so a sprite can hang off any edge without clipping; the
   line descriptors show the picture's part. */

#ifndef SPRITE_H
#define SPRITE_H

#include "gfx.h"

#define MAXPH 8                 /* phases: pixels a word (4 at 8 bits, 8 at 4) */

typedef struct {
    int w, h;                   /* pixels */
    Surface img;                /* the image in the screen's format, 0 where transparent */
    Bitmap mask;                /* 1-bit, linear: 1 drawn */
    int nph;                    /* phases */
    int ww[MAXPH];              /* words a row at each phase */
    int words[MAXPH];           /* ww * h */
    unsigned *shifted[MAXPH];   /* rows of ww pairs (~mask, image) */
    unsigned *spans[MAXPH];     /* rows of a header and their words */
    void *code[MAXPH];          /* compiled: draws with r1 the first word */
    void *bcode[MAXPH];         /* compiled with byte stores (8 bits, linear), else code */
    void *rcode[MAXPH];         /* compiled restore: r1 the first word, r2 the background's */
    int codesize;               /* bytes of code, every phase */
    int masked, opaque;         /* words of each kind, every phase */
} Sprite;

/* a blit: rows of w words from d (the buffer's pitch apart), from s */
typedef struct {
    unsigned *d;
    const void *s;
    int w, h;
} Blt;

extern int bob_pitch;           /* the buffers' words a row */

/* the sprite from its pixels (screen colours) and mask, in the screen's
   format: the pre-shifted forms and the compiled code */
void sprite_make(Sprite *s, int w, int h, const unsigned char *pix, const unsigned char *mask,
                 int fmt);

/* a span row's header: the first word, then the counts */
#define SPAN(off, nl, no, nr) ((off) | (nl) << 8 | (no) << 16 | (unsigned)(nr) << 24)

/* the kernels: a list of n blits each.
   draw_*: d the sprite's first word, s its phase's data (or code), w its words a row
   restore_*: d in the screen, s the same place in the background
   save_*: the screen's words at d packed into s (a save area); unsave_*:
   back, the list's last first */
void draw_shifted_c(const Blt *b, int n);
void draw_spans_c(const Blt *b, int n);
void restore_c(const Blt *b, int n);
void save_c(const Blt *b, int n);
void unsave_c(const Blt *b, int n);

void draw_compiled(const Blt *b, int n);       /* draw.s: any variant */
void restore_compiled(const Blt *b, int n, int off);   /* s the code, r2 = d + off bytes */
void draw_shifted_asm(const Blt *b, int n);
void draw_spans_asm(const Blt *b, int n);
void restore_asm(const Blt *b, int n);
void save_asm(const Blt *b, int n);
void unsave_asm(const Blt *b, int n);

void draw_spans_blk(const Blt *b, int n);      /* blk.s: COPY for the opaque runs */
void restore_blk(const Blt *b, int n);
void save_blk(const Blt *b, int n);
void unsave_blk(const Blt *b, int n);

/* jit.c: compile a phase's pre-shifted rows (ww pairs a row, h rows) for
   a buffer of `pitch` words a row, with byte and half stores where a
   masked word's pixels are whole bytes if bytes_ok; returns the code, its
   size in *bytes. jit_restore: the code that copies the words it draws
   back from the background */
void *jit_sprite(const unsigned *rows, int ww, int h, int pitch, int bytes_ok, int *bytes);
void *jit_restore(const unsigned *rows, int ww, int h, int pitch, int *bytes);

#endif
