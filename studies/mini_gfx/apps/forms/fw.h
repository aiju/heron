/* Form widgets on the window manager: what a forms application needs
   beyond wm.h's ui_*, kept apart from the application so the study can
   fold them into wm/.

   - Text strips: a line of text in the sans font (or the cell font) put
     together as a 1-bit strip, 16 rows, from glyphs shifted ahead of
     time, then expanded into a surface in one call, background and all.
     A table's row or a field's text is one expansion instead of one per
     glyph.
   - A table: a header that sorts, rows from a callback, a selection, a
     scroll bar; scrolling a few rows copies the rows in the window's
     store and draws the new ones. The selection can be drawn by the
     line descriptors' palette banks instead (at 4 bits a pixel).
   - A form: text, number and money fields with a caret, a drop-down,
     check boxes, radio buttons and buttons, with Tab between them.
   - A popup list (the drop-down's), keyboard and mouse.
   - A modal dialog: kept on top, the other windows' input ignored.
   - Horizontal bars. */

#ifndef FW_H
#define FW_H

#include "wm.h"

/* ---- text strips ---- */
#define STRIP_H     16          /* rows */
#define STRIP_BASE  12          /* the baseline's row */
#define STRIP_MAXW  1024        /* pixels */
extern Bitmap strip;            /* linear 1-bit rows, bit 0 the leftmost */

void strip_init(void);                          /* the sans font's glyphs, shifted 8 ways */
void strip_begin(int w);                        /* a clear strip w pixels wide */
int strip_text(int x, int xmax, const char *s); /* s from x, the glyphs that end by xmax; the pen */
int strip_width(const char *s);                 /* s's width in the sans font */
int strip_widthn(const char *s, int n);
int strip_index(const char *s, int x);          /* the character nearest pixel x */
void strip_cells(int x, const char *s, int n);  /* in the cell font, x a multiple of 8 */
/* the strip's columns sx..sx+w at (dx, dy), its 1s in fg, 0s in bg */
void strip_put(Surface *s, int dx, int dy, int sx, int w, unsigned fg, unsigned bg);
/* the same from any STRIP_H rows of 1-bit pixels */
void bits_put(Surface *s, int dx, int dy, const Bitmap *b, int sx, int w, unsigned fg,
              unsigned bg);

/* ---- a table ---- */
typedef struct {
    const char *title;
    short w;                    /* pixels */
    char right;                 /* right-aligned */
    char key;                   /* what it sorts by (the application's) */
} Column;

typedef struct Table Table;
struct Table {
    Window *win;
    int x, y, w;                /* in the window: header and rows, the scroll bar at the right */
    int rows;                   /* rows shown */
    const Column *cols;
    int ncol;
    int total;                  /* rows in the model */
    int first, sel;             /* the first shown, the selected (-1: none) */
    int sort_col, sort_desc;
    int cellfont;               /* rows in the cell font (8 x 16) instead of the sans */
    int glyphs;                 /* rows drawn a glyph at a time with font_draw (the slow way) */
    /* the application's: cell c of row r's text into buf; returns a
       colour for it, or -1 for the row's */
    int (*cell)(Table *t, int r, int c, char *buf);
    unsigned fg, bg, bg2, sel_fg, sel_bg;   /* the rows', zebra striped (bg2: odd rows) */
    /* the row cache (table_cache): each record's strip, kept */
    int (*id)(Table *t, int r);             /* the application's: row r's record */
    struct RowCache *cache;
    int ncache, cache_words;
    unsigned hits, misses;
    /* the selection by palette bank (table_banks) */
    int banks, bank_y, bank_n;
    /* the scroll bar's drag */
    int drag, drag_y, drag_first;
    unsigned copied, drawn;     /* rows copied and drawn by the last change */
};

#define TBL_HDR_H 18
#define TBL_ROW_H 16
#define TBL_SB_W  16

void table_draw(Table *t);                  /* everything */
void table_header(Table *t);
void table_row(Table *t, int i);            /* shown row i (0 .. rows - 1) */
void table_rows(Table *t);                  /* every row and the scroll bar */
void table_scrollbar(Table *t);
/* the selection to r, scrolled into view */
void table_select(Table *t, int r);
/* the first row shown to f: a few rows by copying, more by drawing */
void table_scroll(Table *t, int f);
/* where (x, y) is: TH_HEADER (*col), TH_ROW (*row: the model's), TH_SB_UP,
   TH_SB_DOWN, TH_SB_THUMB, or TH_NONE */
enum { TH_NONE, TH_HEADER, TH_ROW, TH_SB_UP, TH_SB_DOWN, TH_SB_THUMB };
int table_hit(Table *t, int x, int y, int *row, int *col);
/* the scroll bar's mouse: a press, moves and the release; 1 if it took it */
int table_sb_mouse(Table *t, const Event *e, int x, int y);
int table_sb_drag_to(Table *t, int y);      /* the first row for the thumb dragged to y */
/* the selection by the palette banks of the line descriptors: the rows
   in colours that palette bank 1 maps to the selection's, and the
   selected row's lines in bank 1. Only at 4 bits a pixel. */
int table_banks(Table *t, int on);
/* the row cache: the rows' strips kept for n records (by t->id), so a
   row that was drawn before is only expanded; a changed record's to be
   forgotten (table_forget) */
int table_cache(Table *t, int n);
void table_forget(Table *t, int id);
void table_banks_update(Table *t);          /* after a move of the window */

/* ---- a form ---- */
enum { FT_TEXT, FT_NUM, FT_MONEY, FT_DROP, FT_CHECK, FT_RADIO, FT_BUTTON, FT_LABEL };

typedef struct {
    char type, err, pressed, nofocus;
    short x0, y0, x1, y1;       /* the box: a field's, a check box's, a button's */
    const char *label;          /* left of a field (at lx), right of a check box, on a button */
    short lx;
    char text[40];              /* text, num, money; a label's */
    int len, caret, max;
    int val;                    /* check: on; radio, drop: the item */
    const char **items;
    int nitems;
    short ix[6];                /* radio: each item's x */
    int lo, hi;                 /* num: the range */
} Field;

typedef struct Form Form;
struct Form {
    Window *win;
    Field *f;
    int n, focus;
    int caret_on, blink;        /* the caret drawn; the frame it last changed */
    int popup;                  /* the drop-down's list is open */
    int dirty;
    int mb;                     /* the mouse's buttons at the last event */
    /* the application's: field i changed; -1 - i: field i was checked
       (a number field left) */
    void (*changed)(Form *fm, int i);
};

/* form_key's and form_mouse's results */
enum { FA_NONE, FA_USED, FA_SAVE, FA_REVERT, FA_DELETE, FA_NEW, FA_BUTTON };

void form_draw(Form *fm);                   /* labels and every field */
void form_field(Form *fm, int i);           /* one field */
int form_key(Form *fm, const Event *e);     /* FA_*; FA_BUTTON + i for a button */
int form_mouse(Form *fm, const Event *e, int x, int y);
void form_tick(Form *fm);                   /* the caret's blink */
int form_blink_due(const Form *fm);         /* whether form_tick will blink it */
void form_focus(Form *fm, int i);
void form_set_text(Field *f, const char *s);
/* a number field's value, or an error message */
const char *form_number(Field *f, int *v);
const char *form_money(Field *f, int *cents);

/* ---- a popup list, one at a time ---- */
/* at (x, y) on the screen, w wide, item cur highlighted; pick(item) when
   chosen, pick(-1) when closed without */
void popup_open(int x, int y, int w, const char **items, int n, int cur, void (*pick)(int));
int popup_key(const Event *e);              /* a key while it's open: 1 if it took it */
int popup_is_open(void);
void popup_close(void);                     /* closed without a pick */

/* ---- a modal dialog, one at a time ---- */
extern Window *fw_modal;                    /* input to other windows is ignored while set */
/* buttons "Delete|Cancel": done(0, 1, ...), Enter the first, Esc the last */
void dialog_open(const char *title, const char *line1, const char *line2, const char *buttons,
                 void (*done)(int choice));

/* ---- horizontal bars ---- */
/* n bars in (x0, y0)-(x1, y1): a label, a bar as long as its value of
   max, the value's text; colours[k] or patterns in fewer colours */
void bars_draw(Surface *s, int x0, int y0, int x1, int y1, const char **labels,
               const int *values, const char **texts, int n, int max);

#endif
