/* The schematic editor: what its files share.

   The sheet is in units, four to a grid step; parts sit on grid points and
   wires run between them, across or down. The canvas shows unit u at pixel
   u * zoom - origin, zoom 1-4 (a grid step of 4, 8, 12 or 16 pixels).

   sheet.c has the model (parts, wires, net labels, junctions, nets, hit
   tests, the example circuit); symbols.c the symbols, drawn from lines,
   arcs and circles, and their 1-bit sprites at the zoom, and the label
   text; view.c the canvas (regions redrawn from the model, the grid, the
   XOR overlay of rubber bands and ghosts, panning and zooming, the status
   line); schematic.c the windows, the tools and the input; bench.c the
   measurements. */

#ifndef SCH_H
#define SCH_H

#include "wm.h"

#define GRID 4                  /* units a grid step */
#define GU(g) ((g) * GRID)      /* grid steps to units */

/* ---- the model (sheet.c) ---- */

enum { T_RES, T_CAP, T_NAND, T_NOR, T_INV, T_DIP14, T_CONN, T_LED, T_GND, T_VCC, T_N };

typedef struct {
    unsigned char type, rot;    /* rot: quarter turns clockwise */
    unsigned char sel, hl;      /* selected; on the highlighted net */
    unsigned char hide;         /* being moved: not drawn in the store */
    short x, y;                 /* the origin (pin 1), units */
    char ref[8], val[12];
    /* the labels' bitmaps at the current text size (view.c) */
    unsigned *lbits[2];
    short lw[2], lh, lgen;
} Part;

typedef struct {
    short x0, y0, x1, y1;       /* units, x0 <= x1 and y0 <= y1, across or down */
    unsigned char sel, hl, hide;
} Wire;

typedef struct {
    short x, y;                 /* the point of a wire it names */
    char text[10];
    unsigned char hl;
    unsigned *bits;
    short w, h, gen;
} NetLabel;

#define MAXPARTS 160
#define MAXWIRES 600
#define MAXLABELS 48
#define MAXJUNC 400

typedef struct {
    Part parts[MAXPARTS];
    int nparts;
    Wire wires[MAXWIRES];
    int nwires;
    NetLabel labels[MAXLABELS];
    int nlabels;
    short jx[MAXJUNC], jy[MAXJUNC];
    int njunc;
} Sheet;

extern Sheet sh;

Part *part_add(int type, int x, int y, int rot, const char *ref, const char *val);
void part_delete(int i);
Wire *wire_add(int x0, int y0, int x1, int y1);
void wire_delete(int i);
NetLabel *label_add(int x, int y, const char *text);
/* a part's pin k in sheet units, and how many it has */
int part_pins(const Part *p);
void part_pin(const Part *p, int k, int *x, int *y);
const char *pin_name(const Part *p, int k);
/* its box in units (the symbol's lines, rotated, at its place) */
void part_box(const Part *p, int *x0, int *y0, int *x1, int *y1);
/* the junction dots, from scratch */
void junctions(void);
/* highlight the net through the point (units), or nothing: the wires and
   pins on it; returns its wire count, and describes it in buf */
int net_highlight(int x, int y, char *buf, int n);
void net_clear(void);
/* hit tests at a point in units, within tol units: the index or -1 */
int hit_part(int x, int y);
int hit_wire(int x, int y, int tol);
/* the example circuit, at grid offset (gx, gy), its references numbered from n */
void example(int gx, int gy, int n);
void sheet_clear(void);
int on_wire(const Wire *w, int x, int y);

/* ---- symbols (symbols.c) ---- */

/* a symbol's drawing, in units, pin 1 at the origin: a list of primitives */
enum { P_END, P_LINE, P_ARC, P_CIRC, P_DISC, P_RECT, P_PIN };

typedef struct {
    signed char op, a, b, c, d, e, f, g;
} Prim;

/* where the reference and value go */
enum { LS_AUTO, LS_ABOVE, LS_VALUE_ABOVE, LS_NONE };

typedef struct {
    const char *name;           /* in the palette */
    const char *prefix;         /* the reference's */
    const char *val;            /* the value's */
    const Prim *prims;
    int labels;                 /* LS_ */
    const char *pins;           /* the pins' names, '|' between */
} Symbol;

extern const Symbol symbols[T_N];
extern signed char sym_box[T_N][4];     /* each symbol's box, units, unrotated */

/* a sprite: a symbol drawn at a zoom and rotation as 1-bit pixels, and
   where in it the origin is */
typedef struct {
    unsigned *bits;
    short w, h, pitch;          /* pixels; words a row */
    short ox, oy;
    short zoom;
} Sprite;

void symbols_init(void);
/* the rotation of a point in units */
void rot_pt(int rot, int x, int y, int *rx, int *ry);
/* a symbol's lines on a surface: its origin at pixel (px, py), at zoom z */
void sym_draw(Surface *s, int type, int rot, int px, int py, int z, unsigned c, int rop);
/* the sprite of a symbol at the zoom (made when first asked for) */
const Sprite *sym_sprite(int type, int rot, int z);
void sprite_make(Sprite *sp, int type, int rot, int z);
void sym_flush(void);           /* the zoom changed: every sprite again */
extern unsigned sprite_ticks;   /* the time spent making sprites */

/* text as a 1-bit bitmap: the 3 x 5 font (big 0) or sans12 (big 1) */
typedef struct {
    unsigned *bits;
    short w, h, pitch;
} TextBm;
void text_make(TextBm *t, const char *str, int big);
void text_free(TextBm *t);
void text_draw(Surface *s, int x, int y, const char *str, int big, unsigned c);
int text_width(const char *str, int big);

/* ---- the canvas (view.c) ---- */

/* colours of the mode: pixel values */
typedef struct {
    unsigned bg, grid, wire, part, text, sel, hl, ones;
} Ink;

/* the overlay: what is drawn over the sheet, in XOR, while dragging */
enum { OV_HLINE, OV_VLINE, OV_FRAME, OV_GHOST, OV_SPRITE };

typedef struct {
    int kind;
    int x0, y0, x1, y1;         /* pixels in the drawing area; lines inclusive; GHOST
                                   and SPRITE: the top left (SPRITE: x1 the type, y1 the
                                   rotation) */
} OvItem;

#define MAXOV 80

/* how the overlay is drawn: XOR into the store and damage (0), XOR on
   the screen (1), the store redrawn from the model under it (2) */
enum { BAND_STORE, BAND_SCREEN, BAND_REDRAW };

typedef struct {
    Window *win;
    Surface d;                  /* the drawing area: the store's top */
    Surface status;             /* the status line: the store's bottom */
    int w, h;                   /* the drawing area */
    int zoom;                   /* pixels a unit */
    int ox, oy;                 /* the drawing area's top left, in pixels at the zoom */
    int gridstep;               /* pixels between the grid's dots */
    int grid_on, vector, band;  /* options: the grid; parts drawn as lines, not sprites; BAND_ */
    int layers;                 /* what a region draws (LY_): all but for measuring */
    int pan_word, pan_rem;      /* pans across rounded to words; what's left over */
    int sheet;                  /* the sheet view: V.d is the whole sheet, shown by the
                                   descriptors (sheetview.c) */
    int textgen;                /* the labels' bitmaps' generation: the text size */
    Ink ink;
    Surface ghost;              /* the moving parts, in the screen's format (ghost_blit) */
    int ghost_x, ghost_y, ghost_w, ghost_h;     /* where they are, unmoved */
    int ghost_blit;             /* the ghost a copy in XOR, not the parts' sprites in XOR */
    OvItem ov[MAXOV];
    int nov;
    int ov_on_screen;           /* the overlay is on the screen, not in the store */
    unsigned last_redraw;       /* ticks of the last redraw */
} View;

extern View V;

#define STATUS_H 16

/* the layers of a redraw, for measuring them one at a time */
#define LY_CLEAR  1
#define LY_GRID   2
#define LY_WIRES  4
#define LY_PARTS  8
#define LY_LABELS 16
#define LY_DOTS   32
#define LY_ALL    63

/* the scale: units to pixels at V.zoom (shifts and an add, no multiply) */
#define ZS(u) (V.zoom == 3 ? ((u) << 1) + (u) : (u) << (V.zoom >> 1))
#define PX(u) (ZS(u) - V.ox)
#define PY(u) (ZS(u) - V.oy)

void view_init(Window *w, int zoom);
void view_colours(void);
/* the drawing area's pixel to sheet units, and the nearest grid point */
int view_ux(int px);
int view_uy(int py);
int snap(int u);
/* redraw a rectangle (drawing area pixels) from the model and damage it */
void view_region(int x0, int y0, int x1, int y1);
void view_redraw(void);
/* a part's or a wire's pixels, labels included */
void part_rect(Part *p, Rect *r);
void wire_rect(const Wire *w, Rect *r);
void view_part(Part *p);        /* redraw what's under a part */
void view_draw_part(Part *p);   /* just the part, no damage (for measuring) */
void view_wire(const Wire *w);
/* panning (pixels; the store copied, the new strips drawn) and zooming
   (about a point of the drawing area) */
void view_pan(int dx, int dy);
void view_zoom(int z, int cx, int cy);
/* the overlay: set the items (OvItem list), XOR'd off and on */
void ov_set(const OvItem *items, int n);
void ov_clear(void);
void ov_show(void);
void ov_hide(void);
/* on the screen: off now, back a frame after the store was copied over it */
void ov_suspend(void);
void ov_tick(void);
/* an orthogonal L from (x0, y0) to (x1, y1), pixels: across first, or
   down first; returns the items added */
int ov_ell(OvItem *it, int x0, int y0, int x1, int y1, int down_first);
/* the ghost: the hidden parts and wires, drawn at their place into V.ghost;
   its box in the drawing area */
void ghost_make(Rect *r);
void ghost_free(void);
/* the status line */
void status(const char *fmt, ...);
void status_draw(void);
extern char status_text[128];
/* the labels' bitmaps of a part (made for the current text size) */
void part_labels(Part *p);

/* ---- the editor's kernels (xpand.c, xpand.s) ---- */

enum { XM_TRANS, XM_XOR, XM_OPAQUE };

/* a 1-bit source into 1- or 2-bit pixels (xpand.s has the offsets) */
typedef struct {
    unsigned *d;
    const unsigned *s;
    int dpitch, spitch;         /* bytes */
    int h, n;
    unsigned lmask, rmask;
    int soff;
    unsigned fg, bg;
    int mode;                   /* XM_ */
    int fmt;                    /* 0 LIN1, 1 CHK1, 2 LIN2, 3 CHK2, 4 PL2 */
    const unsigned *tab;
} XJob;

/* gfx_expand's arguments, and XOR; any format (but 1 and 2 bits are ours) */
void sch_expand(Surface *dst, int dx, int dy, const Bitmap *src, int sx, int sy, int w, int h,
                unsigned fg, unsigned bg, int mode);
void sch_expand_c(const XJob *j);
/* a line down, y0 to y1 inclusive; ROP_XOR or a copy */
void sch_vline(Surface *s, int x, int y0, int y1, unsigned c, int rop);
#ifdef GFX_ASM
void sch_expand_asm(const XJob *j);
void sch_vline_asm(unsigned *p, int pitch, int n, unsigned m, unsigned v);
#define sch_expand_kernel sch_expand_asm
#else
#define sch_expand_kernel sch_expand_c
#endif
/* the library's kernels instead of these, to measure them (lib_kernels) */
extern int lib_kernels;
/* spfill.s: fills and copies with SAVE and RESTORE, sp borrowed */
void sch_fill_save(unsigned *p, unsigned v, int n);
void sch_copy_rs(unsigned *d, const unsigned *s, int n);

/* ---- the editor (schematic.c) ---- */

extern int sch_mode, sch_opts, band_mode, bench;
/* for bench.c: the canvas's input, a tool, a mouse event at a pixel of
   the drawing area (buttons as they are now) */
enum { TOOL_SELECT, TOOL_WIRE, TOOL_NET, TOOL_PLACE };
void sch_tool(int t, int type);
void sch_mouse(int buttons, int x, int y);
void sch_key(Window *w, const Event *e);
/* a mouse event at a pixel of the drawing area */
void sch_canvas_event(const Event *e, int x, int y);
/* the cursor the tool wants over the sheet, and its hotspot */
const unsigned *sch_cursor(int *hx, int *hy);
extern Window *sch_canvas;
void wm_cursor(const unsigned *img, int hx, int hy);    /* sch_wm.c */

/* ---- the sheet view (sheetview.c) ---- */
void sheet_view(void);
void sheet_pan(int dx, int dy);
int sheet_enter(void);          /* 0: no room in bank 1 */
void sheet_leave(void);
void sheet_flip(void);          /* at a frame's start: show the table a pan wrote */
extern unsigned sheet_pan_ticks, sheet_render_ticks;

/* ---- timing ---- */
unsigned ticks_now(void);
void bench_run(void);

#endif
