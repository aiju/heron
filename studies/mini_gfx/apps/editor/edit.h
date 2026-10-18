/* The editing core the two editors share: apps/editor (windows on the
   window manager) and apps/fsedit (the whole screen, no window manager).

   A document is an array of lines. The core does the editing (typing,
   Backspace and Delete, Enter, the caret's moves, the selection from
   the keys and the mouse, cut, copy and paste, a search) and the
   redisplay: it remembers what each row of the view last showed, and
   asks the front end to move rows that only moved (a line scrolled, a
   line inserted above them) and to draw only the cells that changed.
   How rows are moved (copying pixels, rewriting line descriptors) and
   how cells are drawn is the front end's business (EdOps).

   The view is `rows` rows of `cols` cells; the status line and the
   scroll bar are the front end's, drawn when their contents change. */

#ifndef EDIT_H
#define EDIT_H

#include "input.h"

#define ED_LINEMAX 250          /* characters a line at most */

typedef struct Line {
    char *s;
    int len, cap;
    unsigned ver;               /* a new number whenever the text changes */
    unsigned sver;              /* the version cin and cout were worked out for */
    unsigned char cin, cout;    /* C colouring: inside a comment at the start, at the end */
} Line;

typedef struct {
    int line, col;
} Pos;

/* what a row showed when it was drawn: a row whose stamp hasn't changed
   needn't be looked at again */
typedef struct {
    Line *line;                 /* 0: past the document's end */
    unsigned ver;
    short s0, s1;               /* the selected columns in it */
    unsigned char cin;
} Stamp;

/* the colour classes of a cell; the front end gives each an attribute,
   foreground | background << 4 */
enum { A_TEXT, A_KEYWORD, A_COMMENT, A_STRING, A_NUMBER, A_PREPROC, A_SEL, A_N };

typedef struct Ed Ed;

typedef struct {
    /* rows src..src+n-1 now show what dst..dst+n-1 must: move them; 0 if
       the front end would rather redraw */
    void (*move)(Ed *e, int dst, int src, int n);
    /* cells c0..c1-1 of row r: text[c0..c1), attributes attr[c0..c1) */
    void (*cells)(Ed *e, int r, int c0, int c1, const char *text, const unsigned char *attr);
    /* the caret at (row, col) on or off (drawn with XOR, so the same call) */
    void (*caret)(Ed *e, int r, int c, int on);
    /* the status line's characters c0..c1-1 changed: text[c0..c1) */
    void (*status)(Ed *e, int c0, int c1, const char *text);
    /* the scroll bar: `shown` of `total` lines from `first` */
    void (*bar)(Ed *e, int total, int first, int shown);
    /* the caret moved to another row (the full-screen editor tints its line) */
    void (*caret_row)(Ed *e, int r);
} EdOps;

struct Ed {
    Line **ln;
    int n, cap;
    Pos caret, anchor;          /* the selection is between them, when sel */
    int sel;
    int want;                   /* the column Up and Down aim for */
    int top, left;              /* the first line and column shown */
    int rows, cols;
    int modified, syntax;
    char name[24];
    /* the search: Ctrl+F, then a word and Enter */
    int finding, nfind;
    char find[32];
    char msg[48];
    /* the front end */
    const EdOps *ops;
    void *fe;
    unsigned char attr[A_N];
    /* the redisplay's memory */
    Stamp *shown;
    char **stext;               /* each row's cells as drawn: moved with the rows, */
    unsigned char **sattr;      /* by moving the pointers */
    unsigned char *unknown;     /* a row whose memory was handed on: drawn whole */
    char *rtext;                /* one row, being built */
    unsigned char *rattr;
    int shown_top, shown_left, full;
    int moved_n;                /* lines inserted (deleted, < 0) since the last redisplay */
    int syn_from;               /* the first line whose colouring state may be stale */
    int crow, ccol, con;        /* where the caret is drawn, and whether it is */
    int blink_off;
    int status_w, status_ok;    /* the status line's width in cells (the front end's), drawn */
    int status_len;             /* its text's length, the rest blank */
    char status[128];
    int bar_n, bar_top, bar_rows, tint_row;
    int dirty;                  /* something changed since the last redisplay */
    /* the last redisplay's work, for the measurements */
    int w_rows, w_cells, w_moved;
};

/* a document from text (lines split at '\n') in a view of rows x cols */
void ed_init(Ed *e, const char *name, const char *text, int rows, int cols, const EdOps *ops,
             void *fe);
/* a key; returns 1 if it was the editor's */
int ed_key(Ed *e, const Event *ev);
/* the mouse in the text: press (shift: extend), drag, at row and column */
void ed_press(Ed *e, int row, int col, int shift);
void ed_drag(Ed *e, int row, int col);
/* show line `first` at the top */
void ed_scroll_to(Ed *e, int first);
/* the caret's blink */
void ed_blink(Ed *e, int on);
/* everything is to be drawn again */
void ed_invalidate(Ed *e);
/* draw what changed */
void ed_redisplay(Ed *e);

/* the view's cells: a row of `cols` cells, colour classes per cell */
int ed_syn_line(const char *s, int n, int cin, unsigned char *cls);

#endif
