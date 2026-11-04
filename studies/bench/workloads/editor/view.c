/* The redisplay (ed.h): the window laid out as a grid of cells, each a
   character and a colour class, and sent to a terminal as what changed,
   as a curses program would: for each row, the cells from the first that
   differs from the screen to the last, after a cursor move, with colour
   changes as the class changes.

   A row is laid out again only when its line changed, the lines above it
   were added to or removed, the view moved, or the colouring's state at
   its start changed (a comment opened above it). The terminal's output is
   hashed a frame at a time, as it would be sent. */

#include <limits.h>
#include <stdio.h>
#include <string.h>
#include "bench.h"
#include "ed.h"

unsigned term_hash = BENCH_HASH0, term_bytes, frames, rows_drawn;

/* what the terminal shows: the text rows and the status line */
static char scr_ch[ROWS + 1][COLS];
static unsigned char scr_at[ROWS + 1][COLS];
static int row_line[ROWS];      /* the line each row was laid out from, -1 none */
static int row_cin[ROWS];       /* and the colouring's state it started in */
static int shown_top, shown_left;
static int term_attr;           /* the terminal's colour now */

/* the terminal's output, sent (hashed) at the end of each frame */
static char out[8192];
static int nout;

/* a class's colours as SGR parameters */
static const char *const sgr[A_N] = {"0", "1;34", "32", "31", "35", "36", "7", "0;7"};

static void flush_out(void)
{
#ifdef SHOW
    /* on the host, -DSHOW: the terminal's output itself, to look at */
    fwrite(out, 1, nout, stdout);
#endif
    term_hash = bench_hash(term_hash, out, nout);
    term_bytes += nout;
    nout = 0;
}

/* a byte to the terminal: a macro, as stdio's putc */
#define put(c) do { if (nout == sizeof out) flush_out(); out[nout++] = (c); } while (0)

static void put_str(const char *s)
{
    while (*s)
        put(*s++);
}

static void put_num(int v)
{
    char d[12];
    int n = 0;
    do {
        d[n++] = '0' + v % 10;
        v /= 10;
    } while (v);
    while (n)
        put(d[--n]);
}

/* ESC [ row ; col H, from 1 */
static void move_to(int r, int c)
{
    put(27);
    put('[');
    put_num(r + 1);
    put(';');
    put_num(c + 1);
    put('H');
}

void view_init(void)
{
    int r;
    memset(scr_ch, ' ', sizeof scr_ch);
    memset(scr_at, A_TEXT, sizeof scr_at);
    for (r = 0; r < ROWS; r++)
        row_line[r] = -1;
    shown_top = -1;
    term_attr = A_TEXT;
    put_str("\033[H\033[2J");   /* the screen cleared */
}

/* row r of the screen to be ch[], at[]: the cells that differ sent */
static void draw_row(int r, const char *ch, const unsigned char *at)
{
    char *sc = scr_ch[r];
    unsigned char *sa = scr_at[r];
    int c0, c1, k;
    for (c0 = 0; c0 < COLS && sc[c0] == ch[c0] && sa[c0] == at[c0]; c0++)
        ;
    if (c0 == COLS)
        return;
    for (c1 = COLS; sc[c1 - 1] == ch[c1 - 1] && sa[c1 - 1] == at[c1 - 1]; c1--)
        ;
    move_to(r, c0);
    for (k = c0; k < c1; k++) {
        if (at[k] != term_attr) {
            term_attr = at[k];
            put(27);
            put('[');
            put_str(sgr[term_attr]);
            put('m');
        }
        put(ch[k]);
    }
    memcpy(sc + c0, ch + c0, c1 - c0);
    memcpy(sa + c0, at + c0, c1 - c0);
    rows_drawn++;
}

/* line `line` laid out into a row: coloured, the search's match lit, tabs
   expanded, the columns from e->left on */
static void layout(Ed *e, int line, char *ch, unsigned char *at)
{
    static char text[LINEMAX];
    static unsigned char cls[LINEMAX];
    int pos = line_pos(e, line), n, next, k, c, a, w;
    int col = 0, left = e->left, end = e->left + COLS, m0 = -1, m1 = -1;
    n = gap_line(&e->g, pos, text, LINEMAX, &next);
    syn_line(text, n, line_cin(e, line), cls);
    if (e->mlen && e->mpos >= pos && e->mpos < pos + n) {
        m0 = e->mpos - pos;
        m1 = m0 + e->mlen;
    }
    for (k = 0; k < n && col < end; k++) {
        c = (unsigned char)text[k];
        a = k >= m0 && k < m1 ? A_MATCH : cls[k];
        if (c == '\t') {
            /* spaces to the next tab stop */
            for (w = TABW - (col & (TABW - 1)); w > 0 && col < end; w--, col++)
                if (col >= left) {
                    ch[col - left] = ' ';
                    at[col - left] = a;
                }
            continue;
        }
        if (c < 32 || c > 126)
            c = '?';
        if (col >= left) {
            ch[col - left] = c;
            at[col - left] = a;
        }
        col++;
    }
    /* the rest blank */
    k = col > left ? col - left : 0;
    if (k < COLS) {
        memset(ch + k, ' ', COLS - k);
        memset(at + k, A_TEXT, COLS - k);
    }
}

/* the view moved so the caret's in it: a jump further than a window puts
   it in the middle */
static void follow(Ed *e, int col)
{
    if (e->line < e->top - ROWS || e->line >= e->top + 2 * ROWS) {
        e->top = e->line - ROWS / 2;
    } else if (e->line < e->top) {
        e->top = e->line;
    } else if (e->line >= e->top + ROWS) {
        e->top = e->line - ROWS + 1;
    }
    if (e->top < 0)
        e->top = 0;
    if (col < e->left)
        e->left = col < COLS ? 0 : (col - COLS / 2) & ~(TABW - 1);
    else if (col >= e->left + COLS)
        e->left = (col - COLS / 2) & ~(TABW - 1);
}

static void status(Ed *e, int col)
{
    char line[COLS + 64];
    unsigned char at[COLS];
    int n;
    n = sprintf(line, " %s%s  Ln %d, Col %d  %d lines  %s", e->name, e->modified ? " *" : "",
                e->line + 1, col + 1, e->nlines, e->msg);
    if (n < COLS)
        memset(line + n, ' ', COLS - n);
    memset(at, A_STATUS, COLS);
    draw_row(ROWS, line, at);
}

void frame(Ed *e)
{
    char ch[COLS];
    unsigned char at[COLS];
    int r, line, cin, full, col = column(e, e->cur);
    follow(e, col);
    full = e->top != shown_top || e->left != shown_left;
    for (r = 0; r < ROWS; r++) {
        line = e->top + r;
        if (line >= e->nlines) {
            /* past the end: blank */
            if (row_line[r] < 0 && !full)
                continue;
            memset(ch, ' ', COLS);
            memset(at, A_TEXT, COLS);
            draw_row(r, ch, at);
            row_line[r] = -1;
            continue;
        }
        cin = line_cin(e, line);
        if (!full && row_line[r] == line && row_cin[r] == cin &&
            !(line >= e->chg0 && (e->shifted || line <= e->chg1)))
            continue;
        layout(e, line, ch, at);
        draw_row(r, ch, at);
        row_line[r] = line;
        row_cin[r] = cin;
    }
    status(e, col);
    move_to(e->line - e->top, col - e->left);
    flush_out();
    frames++;
    shown_top = e->top;
    shown_left = e->left;
    e->chg0 = INT_MAX;
    e->chg1 = -1;
    e->shifted = 0;
}
