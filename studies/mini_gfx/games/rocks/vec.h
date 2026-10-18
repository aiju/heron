/* Vector drawing for the rocks game (and the wireframe demo): polylines
   on a double-buffered screen in any 1-, 2- or 4-bit pixel format, with
   no clipping: each buffer has a guard band round the picture that
   catches whatever hangs off it (the descriptors' start addresses let a
   row be wider than the picture: D0). Each frame's polylines and
   objects' boxes are recorded, so the next time the buffer comes round
   it can be erased by one of four strategies.

   Three line kernels draw the same pixels: the library's gfx_line, the
   C kernel here (vec.c) and the assembly one (vline.s). Ours keep a
   word's pixels in a register until the line leaves the word or its
   row, and take each pixel's mask from a table (vl_masks), so they work
   in every format at the same speed; the assembly one draws a whole
   polyline a call. */

#ifndef VEC_H
#define VEC_H

#include "gfx.h"

/* erasing the back buffer before a frame is drawn into it */
enum {
    ER_FILL,        /* the picture's rows filled with 0 (the library's fill: FILL in blk) */
    ER_REDRAW,      /* the polylines drawn into it last time drawn again, clearing their pixels */
    ER_XOR,         /* lines are drawn with XOR, and erased by drawing them again */
    ER_BOX,         /* each object's box from last time filled with 0 (the library's fill) */
    ER_WBOX,        /* ... widened to whole words and cleared by stores */
    ER_N
};

/* the line kernels */
enum { VK_LIB, VK_C, VK_ASM, VK_N };

/* what a line does to its pixels: OR the colour in, XOR it, clear them */
enum { VOP_OR, VOP_XOR, VOP_CLR };

#define VEC_MAXP 1200           /* polylines recorded a frame */
#define VEC_POOL 16000          /* the coordinates of those that were copied */
#define VEC_MAXB 600            /* boxes recorded a frame */

/* a recorded polyline: its points (in the pool, or the caller's if they
   stay put), offset, closed or not, its colour */
typedef struct {
    const short *pts;
    short ox, oy;
    unsigned char n, closed, c, half;
} VPoly;

typedef struct {
    int mode, w, h, bpp, ppw, pshift, fmt;
    int gx, gy;                 /* the guard band: pixels left and right, rows above and below */
    int pitch;                  /* a row's words, the guard band's included */
    int vwords;                 /* a row's words in the picture */
    int erase, kernel;
    int back;                   /* the buffer being drawn: 0 or 1, its descriptor table's number */
    unsigned *org[2];           /* each buffer's pixel (0, 0) */
    unsigned **rows[2];         /* each buffer's rows, from -gy to h + gy - 1 */
    Surface s[2];               /* each buffer, the guard band included, for the library */
    Surface flat[2];            /* the picture's rows as one row of words, for the fill */
    int colour, op;
    /* this frame's records, and the ones each buffer holds */
    VPoly *polys[2];
    int npolys[2];
    short *pool[2];
    int npool[2];
    Rect *boxes[2];
    int nboxes[2];
    int recp, recb;             /* recording polylines, boxes */
    Rect cur;                   /* the object being drawn's box (vec_line) */
    int drawn;                  /* lines drawn this frame (erasing not counted) */
    unsigned t_erase;           /* the last erase's ticks */
} Vec;

extern Vec vec;

/* the line kernels' state (vec.c sets it; vline.s reads it) */
extern unsigned **vl_rows;      /* the back buffer's row table, at row 0 */
extern unsigned *vl_masks;      /* each pixel of a word's mask, in the colour and op */
extern unsigned *vl_mend;       /* past the last */
extern int vl_ppwm1, vl_pshift, vl_pitchw, vl_pitchb, vl_half;

/* the mode (M0, M3-M6) and the video's flags (VC_F1), an erase strategy,
   a line kernel and the guard band in pixels; both buffers cleared */
void vec_init(int mode, unsigned flags, int erase, int kernel, int guard);
/* a palette bank for picture rows y0..y1-1 in both tables */
void vec_bank(int y0, int y1, int bank);
/* the start of a frame: the back buffer erased */
void vec_frame(void);
/* the end of a frame: the back buffer shown from the next frame, at the
   end of this one; returns the frames waited for (more than 1: missed) */
int vec_show(void);

void vec_colour(int c);
void vec_op(int op);
/* lines leave out their last point (x1, y1), so closed polylines drawn
   with XOR have every point once */
void vec_half(int on);
/* a polyline of n points (x, y pairs) offset by (ox, oy), closed: back to
   the first. The caller keeps it inside the guard band. vec_spoly's
   points stay put for two frames (a table), so they aren't copied for
   the erase */
void vec_poly(const short *pts, int n, int ox, int oy, int closed);
void vec_spoly(const short *pts, int n, int ox, int oy, int closed);
/* a line, dropped if it leaves the guard band; its ends count toward the
   box between vec_obj_begin and vec_obj_end */
void vec_line(int x0, int y0, int x1, int y1);
void vec_obj_begin(void);
void vec_obj_end(void);
/* an object's box, for ER_BOX: x0..x1, y0..y1 inclusive */
void vec_box(int x0, int y0, int x1, int y1);

/* the kernels */
void vl_line_or_c(int x0, int y0, int x1, int y1);
void vl_line_xor_c(int x0, int y0, int x1, int y1);
void vl_line_clr_c(int x0, int y0, int x1, int y1);
void vl_line_asm(int x0, int y0, int x1, int y1);
void vl_poly_asm(const short *pts, int n, int ox, int oy, int closed);
void vl_asm_op(int op);         /* patches vline.s's operation */
void vl_asm_setup(int pshift);  /* ... and its shift, for the format */
/* a box (the library surface's coordinates) widened to words, cleared */
void vec_clear_wbox(int b, const Rect *r);
/* h rows of nw words (1-16) from p, pitchb bytes apart, cleared */
void vl_clear_box_asm(unsigned *p, int nw, int h, int pitchb);
/* a line, a polyline with the chosen kernel and the state as it is: no
   records, no checks */
void vec_kernel_line(int x0, int y0, int x1, int y1);
void vec_kernel_poly(const short *pts, int n, int ox, int oy, int closed);
void vec_select(int b);         /* draw into buffer b (benchmarks) */

#endif
