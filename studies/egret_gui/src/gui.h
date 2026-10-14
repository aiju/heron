/* The GUI's C side: the devices, the window manager (gwm.c) and Egret's
   primitives for them (gui_prims.c). README.md has the overview. */

#ifndef GUI_H
#define GUI_H

#include "gfx.h"

/* ---- the devices (studies/v1_isa/isa/src/display.rs) ---- */

#define VRAM ((unsigned char *)0x01000000)       /* 1 MB, outside RAM */
#define VRAM_SIZE 0x100000
#define SCREEN_W 640
#define SCREEN_H 480

#define IO(off) (*(volatile unsigned *)(0xFFFFFF00 + (off)))
#define GUI_EVENT     IO(0x20)    /* the next input event, or -1 */
#define GUI_MOUSE     IO(0x24)    /* x | y << 16 */
#define GUI_BUTTONS   IO(0x28)    /* buttons | modifiers << 8 */
#define GUI_MODE      IO(0x2C)    /* log2 of the bits per pixel */
#define GUI_PAL_INDEX IO(0x30)
#define GUI_PAL_RGB   IO(0x34)    /* 0xRRGGBB, then the index moves on */
#define GUI_TIME      IO(0x38)    /* the time of day, in seconds */
#define GUI_POINTER   IO(0x3C)    /* the pointer's shape */

#define TICK_HZ 60
#define CLOCK_HZ 3000000          /* the timer counts the reference configuration's cycles */

/* VRAM past the screen: the font cache, the save-under for menus, where
   the lines of the source start (for the Browser), and a window's two
   layers (for Gadgets) */
#define FONT_ARENA (VRAM + 0x4B000)
#define FONT_ARENA_END (VRAM + 0x60000)
#define SAVE_UNDER (VRAM + 0x60000)
#define SAVE_UNDER_SIZE 0x1C000
#define LINE_INDEX ((unsigned *)(VRAM + 0x80000))          /* 32 KB */
#define BACKING (VRAM + 0x88000)
#define BACKING_SIZE 0x78000

void gui_wait(void);              /* EI; HALT; DI: sleep until the next tick (rt_v1b.s) */
void gui_setup(int depth);        /* the screen, palette, fonts, window manager, timer */
unsigned gui_nearest(int r, int g, int b);   /* the colour at the screen's depth */
void *gui_alloc(unsigned n);      /* the font cache's malloc */

/* ---- the window manager (gwm.c) ----

   Windows are numbered 1 to MAXWIN; 0 is the screen itself. A window's
   content is drawn by Egret: whatever of it comes into view is filled
   with the window's background and becomes the window's pending update,
   which Egret gets as an event and paints. */

#define MAXWIN 24
#define TITLE_H 18

enum { PART_NONE, PART_CONTENT, PART_TITLE, PART_CLOSE, PART_GROW };

extern Surface screen;
/* (sized here: the C compiler gives an array declared with [] the size of
   its declaration, not of its definition) */
#define MAXFONTS 8
extern Font fonts[MAXFONTS];
extern int nfonts;

void gwm_init(int depth);
int gwm_open(int x0, int y0, int x1, int y1, const char *title, unsigned bg);
void gwm_close(int id);
void gwm_raise(int id);
void gwm_move(int id, int x0, int y0);            /* raises it first */
void gwm_resize(int id, int w, int h);           /* the content's new size */
void gwm_set_title(int id, const char *title);
int gwm_top(void);
int gwm_exists(int id);
int gwm_hit(int x, int y, int *part);
void gwm_frame(int id, Rect *r);
void gwm_content(int id, Rect *r);               /* on the screen */
void gwm_scroll(int id, int x0, int y0, int x1, int y1, int dy);   /* content coordinates */
void gwm_invalidate(int id, const Rect *r);      /* content coordinates; 0: all of it */
int gwm_next_update(Rect *r);                    /* a window with an update: its id, and the rect */
void gwm_repaint_all(void);
void gwm_outline(const Rect *r);
unsigned gwm_bg(int id);

/* Drawing in a window: content coordinates, clipped to what's visible
   (and to the paint clip, if one is set). gwm_clips gives the rectangles
   to draw through and the content's origin on the screen. */
int gwm_clips(int id, Rect **clips, int *ox, int *oy);
void gwm_paint_clip(int id, const Rect *r);      /* 0: none */


#endif
