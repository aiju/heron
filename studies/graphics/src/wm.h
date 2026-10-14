/* The graphics side of a window manager: overlapping windows with frames
   and title bars, drawn through their visible regions; moving, raising,
   closing and scrolling them with as little redrawing as possible; and
   the mouse cursor. */

#ifndef WM_H
#define WM_H

#include "gfx.h"

#define MAXRECT 64

/* A region: a list of rectangles that don't overlap. */
typedef struct {
    int n;
    Rect r[MAXRECT];
} Region;

void rgn_rect(Region *g, const Rect *r);
void rgn_sub(Region *g, const Rect *cut);           /* g = g minus cut */
void rgn_and(Region *g, const Rect *r);             /* g = g within r */

typedef struct Window Window;
struct Window {
    Rect frame;                 /* on the screen, title bar and border included */
    const char *title;
    /* draw the content; s is clipped to a part of content that's visible */
    void (*paint)(Window *w, Surface *s, const Rect *content);
    void *data;
};

#define TITLE_H 18              /* the title bar, without the borders */

void wm_init(Surface *screen, Font *ui);
Window *wm_open(int x0, int y0, int x1, int y1, const char *title,
                void (*paint)(Window *, Surface *, const Rect *), void *data);
void wm_content(Window *w, Rect *r);                /* the content rectangle */
void wm_visible(Window *w, Region *g);              /* what of its frame is on show */
void wm_repaint(const Region *damage);              /* the desktop and windows there */
void wm_paint_all(void);
void wm_raise(Window *w);
void wm_move(Window *w, int dx, int dy);            /* w must be the top window */
void wm_close(Window *w);
/* Scroll w's content up by dy pixels: blit what can be, then paint (the
   content's model must already have moved) */
void wm_scroll(Window *w, int dy);
void wm_outline(const Rect *r);                     /* XOR a frame, for dragging */
Window *wm_top(void);

/* the cursor: drawn over everything, with what's under it kept */
void cursor_show(int x, int y);
void cursor_hide(void);
void cursor_move(int x, int y);

#endif
