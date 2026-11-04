/* The editor (ed.h): the line index, the caret's moves, the edits, the
   search and replace, and undo.

   Every change to the text goes through ins() and del(), which keep the
   line count, the line index and the record of what changed for the
   redisplay, and log the change for undo. */

#include <limits.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "ed.h"

struct Undo {
    int group;                  /* the command it was part of */
    int ins;                    /* 1: text was inserted (undone by deleting it) */
    int pos, len;
    int text;                   /* where the text is in utext */
    int cur;                    /* the caret before */
};

/* ---- the line index ---- */

/* lines after `line` are no longer known */
static void index_cut(Ed *e, int line)
{
    if (e->valid > line + 1)
        e->valid = line + 1;
    if (e->from >= e->valid - 1)
        e->delta = 0;           /* no known line is after `from`: nothing to shift */
}

/* the index to line `upto`, a line at a time from the last known one:
   where it ends is where the next starts, and the colouring's state at
   its end is the next's at its start */
static void index_extend(Ed *e, int upto)
{
    char text[LINEMAX];
    int i, n, next;
    if (upto >= e->nlines)
        upto = e->nlines - 1;
    while (e->valid <= upto) {
        i = e->valid;
        n = gap_line(&e->g, line_pos(e, i - 1), text, LINEMAX, &next);
        if (i == e->cap) {
            e->cap *= 2;
            e->li = realloc(e->li, e->cap * sizeof(LineInfo));
        }
        e->li[i].cin = syn_state(text, n, e->li[i - 1].cin);
        e->li[i].pos = i > e->from ? next - e->delta : next;
        e->valid++;
    }
}

int line_pos(Ed *e, int i)
{
    if (i >= e->valid)
        index_extend(e, i);
    return e->li[i].pos + (i > e->from ? e->delta : 0);
}

int line_cin(Ed *e, int i)
{
    if (i >= e->valid)
        index_extend(e, i);
    return e->li[i].cin;
}

/* the line pos is on */
static int line_of(Ed *e, int pos)
{
    int lo = 0, hi, mid;
    while (e->valid < e->nlines && line_pos(e, e->valid - 1) <= pos)
        index_extend(e, e->valid);
    hi = e->valid - 1;
    while (lo < hi) {
        mid = (lo + hi + 1) / 2;
        if (line_pos(e, mid) <= pos)
            lo = mid;
        else
            hi = mid - 1;
    }
    return lo;
}

/* the newlines in text[a..b) */
static int count_lines(const Gap *g, int a, int b)
{
    int n = 0, len, k;
    const char *s;
    while (a < b) {
        s = gap_run(g, a, &len);
        if (len > b - a)
            len = b - a;
        for (k = 0; k < len; k++)
            n += s[k] == '\n';
        a += len;
    }
    return n;
}

void ed_open(Ed *e, const char *name, const char *text, int n)
{
    memset(e, 0, sizeof *e);
    strncpy(e->name, name, sizeof e->name - 1);
    gap_init(&e->g, text, n);
    e->nlines = count_lines(&e->g, 0, n) + 1;  /* after a final newline, an empty line */
    e->cap = 256;
    e->li = malloc(e->cap * sizeof(LineInfo));
    e->li[0].pos = 0;
    e->li[0].cin = 0;
    e->valid = 1;
    e->chg0 = INT_MAX;
    e->chg1 = -1;
    e->capundo = 64;
    e->undo = malloc(e->capundo * sizeof(struct Undo));
    e->caputext = 1024;
    e->utext = malloc(e->caputext);
}

/* ---- changes ---- */

void touch(Ed *e, int line, int shifted)
{
    if (line < e->chg0)
        e->chg0 = line;
    if (line > e->chg1)
        e->chg1 = line;
    e->shifted |= shifted;
}

/* line `line` changed by n bytes, nl lines more (or fewer) in it */
static void changed(Ed *e, int line, int nl, int n)
{
    char text[LINEMAX];
    int len, next;
    e->modified = 1;
    touch(e, line, nl != 0);
    if (nl) {
        e->nlines += nl;
        index_cut(e, line);
        return;
    }
    if (line + 1 >= e->valid)
        return;
    if (e->delta && line != e->from) {
        /* one pending shift only: the lines after the earlier of the two
           are found again when they're needed */
        index_cut(e, line < e->from ? line : e->from);
        if (line + 1 >= e->valid)
            return;
    }
    e->from = line;
    e->delta += n;
    /* the next line starts where it did, n on; and in the same state, unless
       a comment mark was typed or deleted */
    len = gap_line(&e->g, line_pos(e, line), text, LINEMAX, &next);
    if (syn_state(text, len, e->li[line].cin) != e->li[line + 1].cin)
        index_cut(e, line);
}

static void log_undo(Ed *e, int ins, int pos, int n)
{
    struct Undo *u;
    int k;
    if (e->nundo == e->capundo) {
        e->capundo *= 2;
        e->undo = realloc(e->undo, e->capundo * sizeof(struct Undo));
    }
    if (e->nutext + n > e->caputext) {
        while (e->nutext + n > e->caputext)
            e->caputext *= 2;
        e->utext = realloc(e->utext, e->caputext);
    }
    u = &e->undo[e->nundo++];
    u->group = e->group;
    u->ins = ins;
    u->pos = pos;
    u->len = n;
    u->text = e->nutext;
    u->cur = e->cur;
    for (k = 0; k < n; k++)
        e->utext[e->nutext++] = gap_at(&e->g, pos + k);
}

/* s[0..n) inserted at pos, on line `line` */
static void ins(Ed *e, int pos, int line, const char *s, int n, int record)
{
    int nl = 0, k;
    for (k = 0; k < n; k++)
        nl += s[k] == '\n';
    gap_insert(&e->g, pos, s, n);
    if (record)
        log_undo(e, 1, pos, n);
    changed(e, line, nl, n);
}

/* n bytes deleted at pos, on line `line` */
static void del(Ed *e, int pos, int line, int n, int record)
{
    int nl = count_lines(&e->g, pos, pos + n);
    if (record)
        log_undo(e, 0, pos, n);
    gap_delete(&e->g, pos, n);
    changed(e, line, -nl, -n);
}

void ed_begin(Ed *e)
{
    e->group++;
    e->msg[0] = 0;
    if (e->mlen) {
        /* the last match is lit until the next command */
        touch(e, line_of(e, e->mpos), 0);
        e->mlen = 0;
    }
}

/* ---- columns and moves ---- */

/* the column of pos on a line starting at start */
static int col_at(Ed *e, int start, int pos)
{
    int col = 0;
    for (; start < pos; start++)
        col = gap_at(&e->g, start) == '\t' ? (col + TABW) & ~(TABW - 1) : col + 1;
    return col;
}

int column(Ed *e, int pos)
{
    return col_at(e, line_pos(e, e->line), pos);
}

/* where on line `line` column `want` is, or the line's end if it's shorter */
static int pos_at_col(Ed *e, int line, int want)
{
    int pos = line_pos(e, line), end = gap_len(&e->g), col = 0, c, w;
    for (; pos < end; pos++) {
        c = gap_at(&e->g, pos);
        if (c == '\n')
            break;
        w = c == '\t' ? TABW - (col & (TABW - 1)) : 1;
        if (col + w > want)
            break;
        col += w;
    }
    return pos;
}

void ed_left(Ed *e, int n)
{
    while (n-- > 0 && e->cur > 0) {
        e->cur--;
        if (gap_at(&e->g, e->cur) == '\n')
            e->line--;
    }
    e->want = column(e, e->cur);
}

void ed_right(Ed *e, int n)
{
    int end = gap_len(&e->g);
    while (n-- > 0 && e->cur < end) {
        if (gap_at(&e->g, e->cur) == '\n')
            e->line++;
        e->cur++;
    }
    e->want = column(e, e->cur);
}

void ed_up(Ed *e, int n)
{
    e->line = e->line - n < 0 ? 0 : e->line - n;
    e->cur = pos_at_col(e, e->line, e->want);
}

void ed_down(Ed *e, int n)
{
    e->line = e->line + n >= e->nlines ? e->nlines - 1 : e->line + n;
    e->cur = pos_at_col(e, e->line, e->want);
}

void ed_home(Ed *e)
{
    e->cur = line_pos(e, e->line);
    e->want = 0;
}

void ed_end(Ed *e)
{
    e->cur = pos_at_col(e, e->line, 1 << 30);
    e->want = column(e, e->cur);
}

static int word_char(int c)
{
    return (unsigned)((c | 32) - 'a') < 26 || (unsigned)(c - '0') < 10 || c == '_';
}

/* as vi's w: to the start of the next word, n times */
void ed_word(Ed *e, int n)
{
    int end = gap_len(&e->g), c;
    while (n-- > 0) {
        while (e->cur < end && word_char(gap_at(&e->g, e->cur)))
            e->cur++;
        while (e->cur < end && !word_char(c = gap_at(&e->g, e->cur))) {
            e->line += c == '\n';
            e->cur++;
        }
    }
    e->want = column(e, e->cur);
}

/* as vi's b: to the start of this word or the one before, n times */
void ed_back_word(Ed *e, int n)
{
    int c;
    while (n-- > 0) {
        while (e->cur > 0 && !word_char(c = gap_at(&e->g, e->cur - 1))) {
            e->line -= c == '\n';
            e->cur--;
        }
        while (e->cur > 0 && word_char(gap_at(&e->g, e->cur - 1)))
            e->cur--;
    }
    e->want = column(e, e->cur);
}

void ed_goto(Ed *e, int line)
{
    e->line = line < 1 ? 0 : line > e->nlines ? e->nlines - 1 : line - 1;
    e->cur = line_pos(e, e->line);
    e->want = 0;
}

void ed_page(Ed *e, int n)
{
    int d = n * (ROWS - 2);
    e->top += d;
    if (e->top > e->nlines - ROWS)
        e->top = e->nlines - ROWS;
    if (e->top < 0)
        e->top = 0;
    if (d > 0)
        ed_down(e, d);
    else
        ed_up(e, -d);
}

/* ---- editing ---- */

void ed_type(Ed *e, int c)
{
    char ch = c;
    ins(e, e->cur, e->line, &ch, 1, 1);
    e->cur++;
    e->want = column(e, e->cur);
}

void ed_enter(Ed *e)
{
    char text[LINEMAX + 1];
    int n = 1, pos = line_pos(e, e->line), c;
    text[0] = '\n';
    /* the new line indented as this one, as far as the caret */
    while (pos < e->cur && n < LINEMAX && ((c = gap_at(&e->g, pos)) == ' ' || c == '\t')) {
        text[n++] = c;
        pos++;
    }
    ins(e, e->cur, e->line, text, n, 1);
    e->cur += n;
    e->line++;
    e->want = column(e, e->cur);
}

void ed_backspace(Ed *e)
{
    if (e->cur == 0)
        return;
    if (gap_at(&e->g, e->cur - 1) == '\n')
        e->line--;
    e->cur--;
    del(e, e->cur, e->line, 1, 1);
    e->want = column(e, e->cur);
}

void ed_delete(Ed *e)
{
    if (e->cur < gap_len(&e->g))
        del(e, e->cur, e->line, 1, 1);
}

void ed_kill_line(Ed *e)
{
    int start = line_pos(e, e->line), end;
    if (e->line + 1 < e->nlines) {
        end = line_pos(e, e->line + 1);
    } else {
        /* the last line: it goes with the newline before it */
        end = gap_len(&e->g);
        if (e->line > 0) {
            start--;
            e->line--;
        }
    }
    del(e, start, e->line, end - start, 1);
    e->cur = line_pos(e, e->line);
    e->want = 0;
}

/* this line and the next as one, the next's indentation as one space */
void ed_join(Ed *e)
{
    int nl, end, ws = 0, c;
    if (e->line + 1 >= e->nlines)
        return;
    nl = line_pos(e, e->line + 1) - 1;
    end = gap_len(&e->g);
    while (nl + 1 + ws < end && ((c = gap_at(&e->g, nl + 1 + ws)) == ' ' || c == '\t'))
        ws++;
    del(e, nl, e->line, 1 + ws, 1);
    ins(e, nl, e->line, " ", 1, 1);
    e->cur = nl;
    e->want = column(e, e->cur);
}

/* ---- search ---- */

int ed_find(Ed *e, const char *s)
{
    int n = strlen(s), p;
    if (n == 0 || n >= (int)sizeof e->find)
        return 0;
    if (s != e->find) {
        strcpy(e->find, s);
        e->nfind = n;
    }
    p = gap_find(&e->g, e->cur + 1, s, n);
    if (p < 0)
        p = gap_find(&e->g, 0, s, n);           /* from the top */
    if (p < 0) {
        sprintf(e->msg, "\"%s\" not found", s);
        return 0;
    }
    e->cur = e->mpos = p;
    e->mlen = n;
    e->line = line_of(e, p);
    e->want = column(e, p);
    touch(e, e->line, 0);
    return 1;
}

int ed_replace(Ed *e, const char *a, const char *b)
{
    int na = strlen(a), nb = strlen(b), p = 0, at = 0, line = 0, n = 0;
    if (!na)
        return 0;
    /* the line of each match by counting from the last: the index is cut
       at the first and found again for the window afterwards */
    while ((p = gap_find(&e->g, p, a, na)) >= 0) {
        line += count_lines(&e->g, at, p);
        if (n == 0)
            index_cut(e, line);
        del(e, p, line, na, 1);
        ins(e, p, line, b, nb, 1);
        p += nb;
        at = p;
        n++;
    }
    if (n) {
        e->line = line_of(e, e->cur < gap_len(&e->g) ? e->cur : gap_len(&e->g));
        if (e->cur > gap_len(&e->g))
            e->cur = gap_len(&e->g);
        e->want = column(e, e->cur);
    }
    sprintf(e->msg, "%d replaced", n);
    return n;
}

int ed_undo(Ed *e)
{
    int g, n = 0;
    if (!e->nundo) {
        strcpy(e->msg, "nothing to undo");
        return 0;
    }
    g = e->undo[e->nundo - 1].group;
    while (e->nundo && e->undo[e->nundo - 1].group == g) {
        struct Undo *u = &e->undo[--e->nundo];
        int line = line_of(e, u->pos);
        if (u->ins)
            del(e, u->pos, line, u->len, 0);
        else
            ins(e, u->pos, line, e->utext + u->text, u->len, 0);
        e->nutext = u->text;
        e->cur = u->cur;
        n++;
    }
    e->line = line_of(e, e->cur);
    e->want = column(e, e->cur);
    sprintf(e->msg, "undid %d", n);
    return n;
}
