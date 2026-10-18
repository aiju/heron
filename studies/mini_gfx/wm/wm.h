/* The window manager: overlapping windows with backing stores, composited
   onto the screen through damage rectangles, a theme for 1, 2, 4 and 8
   bits a pixel, the hardware cursor or a software one, menus, and the
   event loop that hands keys and the mouse to the window that wants them.

   A window's content is a surface of its own in bank 1 (its backing
   store), in the screen's pixel format, which its application draws into
   at any time; wm_damage says what changed, and the compositor copies
   the visible parts to the screen at the next frame, drawing the frames
   and title bars as it goes. Moving a window, raising it or uncovering
   another needs no repaint from the applications. */

#ifndef WM_H
#define WM_H

#include "gfx.h"
#include "input.h"

/* the theme's colours, as pixel values of the mode */
typedef struct {
    unsigned desk_fg, desk_bg;          /* the desktop's pattern */
    unsigned frame;                     /* the windows' outline */
    unsigned title_bg, title_fg;        /* the active window's title bar */
    unsigned title_bg2, title_fg2;      /* the others' */
    unsigned face, light, dark, shadow; /* buttons and panels: 3D */
    unsigned bg, text;                  /* content */
    unsigned sel_bg, sel_fg;            /* selected text, items */
    unsigned accent, accent2;           /* a colour each, or the nearest grey */
    unsigned char desk_pat[8];          /* the desktop's 8 x 8 pattern */
} Theme;

extern Theme th;

typedef struct Window Window;

struct Window {
    Rect r;                     /* the frame, on the screen */
    Rect c;                     /* the content area, on the screen */
    Surface s;                  /* the content: the backing store */
    char title[48];
    int flags;
    void *app;
    /* the application's: any may be 0 */
    void (*key)(Window *w, const Event *e);
    void (*mouse)(Window *w, const Event *e, int x, int y);   /* in content coordinates */
    void (*tick)(Window *w);                                  /* every frame */
    void (*close)(Window *w);
    Window *above, *below;      /* the stack: wm.top first */
};

/* flags */
#define WF_TITLE    1           /* a title bar, a close box */
#define WF_MENU     2           /* a menu: no frame but a line, closes when clicked outside */
#define WF_FIXED    4           /* can't be moved */

/* wm_init's options, also measured against each other */
#define WM_SOFTCURSOR  1        /* the cursor drawn in software, not C1 */
#define WM_OUTLINE     2        /* moves show an outline until the button is released */
#define WM_SNAP        4        /* windows' content starts on a word: copies, never shifts */
#define WM_F1          8        /* F1: the linear 1- and 2-bit layout */

typedef struct {
    Surface screen;
    Window *top;                /* the stack, top first */
    Window *focus;              /* keys go here */
    int opts;
    int quit;
    unsigned frame_work;        /* ticks of work in the last frame */
    unsigned frames;
} WM;

extern WM wm;

/* the mode and the options; the screen, the theme, the fonts, the input */
void wm_init(int mode, int opts);
/* a window whose content is w x h at (x, y) on the screen (its frame
   around it); on top, with the focus */
Window *wm_open(int x, int y, int w, int h, const char *title, int flags);
void wm_close(Window *w);
void wm_raise(Window *w);
void wm_move(Window *w, int x, int y);              /* the content's top left */
void wm_title(Window *w, const char *title);
/* the content changed in this rectangle (content coordinates) */
void wm_damage(Window *w, int x0, int y0, int x1, int y1);
void wm_damage_all(Window *w);
/* the screen changed in this rectangle */
void wm_damage_screen(int x0, int y0, int x1, int y1);
/* run until wm.quit: events, ticks, composition, a frame at a time */
void wm_run(void);
/* one frame of it, for programs with a loop of their own */
void wm_frame(void);
/* the composition alone: the damage copied to the screen, the cursor */
void wm_compose(void);
/* the frame's size around a content area */
#define WM_BORDER 1
#define WM_TITLE_H 18

/* a popup menu at (x, y): items separated by '|'; returns at once, and
   calls pick(index) when one is chosen */
void wm_menu(int x, int y, const char *items, void (*pick)(int item));
/* the desktop's menu, on a click on the desktop */
extern void (*wm_desktop_click)(const Event *e);

/* ---- widgets (ui.c): drawn into a surface, in the theme ---- */
void ui_panel(Surface *s, int x0, int y0, int x1, int y1, int sunken);
void ui_button(Surface *s, int x0, int y0, int x1, int y1, const char *label, int pressed);
void ui_check(Surface *s, int x, int y, const char *label, int on);
void ui_field(Surface *s, int x0, int y0, int x1, int y1, const char *text, int caret, int focus);
void ui_label(Surface *s, int x, int y, const char *text);
void ui_scrollbar(Surface *s, int x0, int y0, int x1, int y1, int total, int first, int shown);
int ui_hit(int x, int y, int x0, int y0, int x1, int y1);

#endif
