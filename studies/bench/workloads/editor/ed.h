/* A text editor's core: a gap buffer, C's colouring, a window laid out
   into a grid of cells and sent to a terminal as what changed, and the
   editing commands with undo.

   It follows Heron Mini's editor (studies/mini_gfx/apps/editor on the
   claude/trusting-fermi-7diz0f branch): the same colouring, a redisplay
   that only redraws rows that changed, a status line. Where the Mini's
   document is an array of lines, this one is a gap buffer, as in Emacs:
   the text in one block with a hole at the caret, so typing is a store
   and moving the caret a block move. A line index with the colouring's
   state at each line's start finds lines and colours the window without
   scanning from the top. */

#ifndef ED_H
#define ED_H

#ifndef ROWS
#define ROWS 30                 /* the window: text rows (workload.py may say), */
#endif
#define COLS 80                 /* of this many cells, */
#define TABW 8                  /* tab stops every 8 */
#define LINEMAX 512             /* longer lines are clipped (and coloured as if cut) */

/* ---- the gap buffer (gap.c) ---- */

typedef struct {
    char *buf;
    int size;                   /* bytes allocated */
    int gap0, gap1;             /* buf[gap0..gap1) is the gap */
} Gap;

void gap_init(Gap *g, const char *s, int n);
int gap_len(const Gap *g);
int gap_at(const Gap *g, int pos);
void gap_insert(Gap *g, int pos, const char *s, int n);
void gap_delete(Gap *g, int pos, int n);
/* the text from pos to the next gap or the end, in one piece: its address,
   and its length in *n */
const char *gap_run(const Gap *g, int pos, int *n);
/* the line starting at pos into out[0..max) without its '\n': its length
   (at most max); *next is where the next line starts */
int gap_line(const Gap *g, int pos, char *out, int max, int *next);
/* the first pos >= from with text[pos..pos+n) == s, or -1 */
int gap_find(const Gap *g, int from, const char *s, int n);

/* ---- C's colouring (syntax.c) ---- */

/* the colour classes of a cell */
enum { A_TEXT, A_KEYWORD, A_COMMENT, A_STRING, A_NUMBER, A_PREPROC, A_MATCH, A_STATUS, A_N };

/* line s[0..n)'s classes into cls[], from its state at the start (in a
   block comment or not); the state at its end */
int syn_line(const char *s, int n, int cin, unsigned char *cls);
/* only the state at its end */
int syn_state(const char *s, int n, int cin);

/* ---- the editor ---- */

/* what the line index knows of a line: where it starts, and whether it
   starts inside a block comment */
typedef struct {
    int pos;
    int cin;
} LineInfo;

typedef struct {
    Gap g;
    char name[32];
    int cur, line;              /* the caret: its position, and its line */
    int want;                   /* the column Up and Down aim for */
    int nlines;
    int modified;

    /* The line index: lines 0..valid-1 are known. Typing within a line
       moves every later line's start, so the index has a pending shift
       of its own: the lines after line `from` start `delta` further on
       than li[] says (a gap, as the text's). */
    LineInfo *li;
    int valid, cap, from, delta;

    /* the view: the first line and column shown */
    int top, left;
    /* what changed since the last frame: lines chg0..chg1, and whether
       lines were added or removed there (every row below then moved) */
    int chg0, chg1, shifted;

    /* the search: the last match, highlighted */
    char find[64];
    int nfind, mpos, mlen;
    char msg[48];

    /* undo: records of what was done, in groups, one for each command */
    struct Undo *undo;
    int nundo, capundo, group;
    char *utext;                /* the text deleted or inserted */
    int nutext, caputext;
} Ed;

/* edit.c */
void ed_open(Ed *e, const char *name, const char *text, int n);
int line_pos(Ed *e, int i);     /* where line i starts */
int line_cin(Ed *e, int i);
int column(Ed *e, int pos);     /* pos's column, tabs expanded */
void touch(Ed *e, int line, int shifted);

void ed_left(Ed *e, int n);
void ed_right(Ed *e, int n);
void ed_up(Ed *e, int n);
void ed_down(Ed *e, int n);
void ed_home(Ed *e);
void ed_end(Ed *e);
void ed_word(Ed *e, int n);
void ed_back_word(Ed *e, int n);
void ed_goto(Ed *e, int line);
void ed_page(Ed *e, int n);     /* n pages down (up if negative) */

void ed_begin(Ed *e);           /* a command starts: its edits are undone together */
void ed_type(Ed *e, int c);
void ed_enter(Ed *e);           /* a new line, indented as this one */
void ed_backspace(Ed *e);
void ed_delete(Ed *e);
void ed_kill_line(Ed *e);
void ed_join(Ed *e);
int ed_find(Ed *e, const char *s);   /* the next match after the caret, wrapping */
int ed_replace(Ed *e, const char *a, const char *b);   /* every a by b: how many */
int ed_undo(Ed *e);

/* view.c */
void view_init(void);
/* the window as it should be now, sent to the terminal as what changed */
void frame(Ed *e);
extern unsigned term_hash, term_bytes, frames, rows_drawn;

#endif
