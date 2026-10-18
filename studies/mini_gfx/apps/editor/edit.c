/* The editing core (edit.h): the document, the editing, the selection,
   the clipboard, the search, C's colours, and the redisplay. */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "edit.h"

static unsigned version = 1;    /* every line's text gets a new one when it changes */
static char *clip;              /* the clipboard, shared by every editor: lines joined by '\n' */
static int nclip;

/* ---- lines ---- */

static Line *line_new(const char *s, int n)
{
    Line *l = malloc(sizeof(Line));
    l->cap = n + 8;
    l->s = malloc(l->cap);
    memcpy(l->s, s, n);
    l->len = n;
    l->ver = version++;
    l->sver = 0;
    l->cin = l->cout = 0;
    return l;
}

static void line_free(Line *l)
{
    free(l->s);
    free(l);
}

/* room for n characters */
static void line_room(Line *l, int n)
{
    if (n > l->cap) {
        l->cap = n + 16;
        l->s = realloc(l->s, l->cap);
    }
}

/* line i's text changed */
static void touched(Ed *e, int i)
{
    e->ln[i]->ver = version++;
    if (i < e->syn_from)
        e->syn_from = i;
    e->modified = 1;
}

static void lines_insert(Ed *e, int at, Line *l)
{
    if (e->n == e->cap) {
        e->cap = e->cap * 2 + 16;
        e->ln = realloc(e->ln, e->cap * sizeof(Line *));
    }
    memmove(e->ln + at + 1, e->ln + at, (e->n - at) * sizeof(Line *));
    e->ln[at] = l;
    e->n++;
    e->moved_n++;
    if (at < e->syn_from)
        e->syn_from = at;
}

static void lines_remove(Ed *e, int at)
{
    line_free(e->ln[at]);
    memmove(e->ln + at, e->ln + at + 1, (e->n - at - 1) * sizeof(Line *));
    e->n--;
    e->moved_n--;
    if (at < e->syn_from)
        e->syn_from = at;
}

void ed_init(Ed *e, const char *name, const char *text, int rows, int cols, const EdOps *ops,
             void *fe)
{
    const char *p = text, *q;
    int k;
    memset(e, 0, sizeof *e);
    strncpy(e->name, name, sizeof e->name - 1);
    e->rows = rows;
    e->cols = cols;
    e->status_w = cols;
    e->ops = ops;
    e->fe = fe;
    e->syn_from = 0;
    for (;;) {
        q = p;
        while (*q && *q != '\n')
            q++;
        if (!*q && q == p && e->n > 0)
            break;
        lines_insert(e, e->n, line_new(p, q - p > ED_LINEMAX ? ED_LINEMAX : q - p));
        if (!*q)
            break;
        p = q + 1;
    }
    e->shown = calloc(rows, sizeof(Stamp));
    e->stext = malloc(rows * sizeof(char *));
    e->sattr = malloc(rows * sizeof(unsigned char *));
    e->unknown = calloc(rows, 1);
    for (k = 0; k < rows; k++) {
        e->stext[k] = malloc(cols);
        e->sattr[k] = malloc(cols);
    }
    e->rtext = malloc(cols + 8);
    e->rattr = malloc(cols + 8);
    e->modified = 0;
    e->moved_n = 0;
    e->tint_row = -1;
    ed_invalidate(e);
}

void ed_invalidate(Ed *e)
{
    e->full = 1;
    e->status_ok = 0;
    e->bar_n = -1;
    e->dirty = 1;
}

/* ---- positions and the selection ---- */

static int pos_cmp(Pos a, Pos b)
{
    return a.line != b.line ? a.line - b.line : a.col - b.col;
}

/* the selection's ends in order; 0 if there's none */
static int sel_range(Ed *e, Pos *a, Pos *b)
{
    if (!e->sel || !pos_cmp(e->caret, e->anchor))
        return 0;
    if (pos_cmp(e->caret, e->anchor) < 0) {
        *a = e->caret;
        *b = e->anchor;
    } else {
        *a = e->anchor;
        *b = e->caret;
    }
    return 1;
}

/* the caret on the screen, the view following it */
static void follow(Ed *e)
{
    if (e->caret.line < e->top)
        e->top = e->caret.line;
    if (e->caret.line >= e->top + e->rows)
        e->top = e->caret.line - e->rows + 1;
    if (e->caret.col < e->left)
        e->left = e->caret.col & ~7;
    if (e->caret.col >= e->left + e->cols)
        e->left = (e->caret.col - e->cols + 16) & ~7;
    e->dirty = 1;
}

static void clamp(Ed *e, Pos *p)
{
    if (p->line < 0)
        p->line = 0;
    if (p->line >= e->n)
        p->line = e->n - 1;
    if (p->col < 0)
        p->col = 0;
    if (p->col > e->ln[p->line]->len)
        p->col = e->ln[p->line]->len;
}

/* ---- editing ---- */

static void delete_range(Ed *e, Pos a, Pos b)
{
    Line *l = e->ln[a.line], *m = e->ln[b.line];
    int k;
    if (a.line == b.line) {
        memmove(l->s + a.col, l->s + b.col, l->len - b.col);
        l->len -= b.col - a.col;
    } else {
        int rest = m->len - b.col;
        if (a.col + rest > ED_LINEMAX)
            rest = ED_LINEMAX - a.col;
        line_room(l, a.col + rest);
        memcpy(l->s + a.col, m->s + b.col, rest);
        l->len = a.col + rest;
        for (k = b.line; k > a.line; k--)
            lines_remove(e, k);
    }
    touched(e, a.line);
    e->caret = a;
    e->sel = 0;
}

static int delete_sel(Ed *e)
{
    Pos a, b;
    if (!sel_range(e, &a, &b)) {
        e->sel = 0;
        return 0;
    }
    delete_range(e, a, b);
    return 1;
}

static void insert_char(Ed *e, int c)
{
    Line *l = e->ln[e->caret.line];
    int col = e->caret.col;
    if (l->len >= ED_LINEMAX)
        return;
    line_room(l, l->len + 1);
    memmove(l->s + col + 1, l->s + col, l->len - col);
    l->s[col] = c;
    l->len++;
    e->caret.col++;
    touched(e, e->caret.line);
}

/* split the line at the caret; indent: the new line starts as indented as this one */
static void newline(Ed *e, int indent)
{
    Line *l = e->ln[e->caret.line], *nl;
    int col = e->caret.col, sp = 0;
    if (indent)
        while (sp < col && l->s[sp] == ' ')
            sp++;
    nl = line_new(l->s, sp);
    line_room(nl, sp + l->len - col);
    memcpy(nl->s + sp, l->s + col, l->len - col);
    nl->len = sp + l->len - col;
    l->len = col;
    touched(e, e->caret.line);
    lines_insert(e, e->caret.line + 1, nl);
    e->caret.line++;
    e->caret.col = sp;
}

/* line i and the next as one */
static void join(Ed *e, int i)
{
    Line *a = e->ln[i], *b = e->ln[i + 1];
    int n = b->len;
    if (a->len + n > ED_LINEMAX)
        n = ED_LINEMAX - a->len;
    line_room(a, a->len + n);
    memcpy(a->s + a->len, b->s, n);
    a->len += n;
    touched(e, i);
    lines_remove(e, i + 1);
}

static void insert_text(Ed *e, const char *s, int n)
{
    int k;
    for (k = 0; k < n; k++) {
        if (s[k] == '\n')
            newline(e, 0);
        else
            insert_char(e, s[k]);
    }
}

static void copy_sel(Ed *e)
{
    Pos a, b;
    int i, n = 0;
    if (!sel_range(e, &a, &b))
        return;
    free(clip);
    for (i = a.line; i <= b.line; i++)
        n += e->ln[i]->len + 1;
    clip = malloc(n);
    nclip = 0;
    for (i = a.line; i <= b.line; i++) {
        Line *l = e->ln[i];
        int c0 = i == a.line ? a.col : 0, c1 = i == b.line ? b.col : l->len;
        memcpy(clip + nclip, l->s + c0, c1 - c0);
        nclip += c1 - c0;
        if (i < b.line)
            clip[nclip++] = '\n';
    }
}

/* ---- the search ---- */

static int find_in(const Line *l, int from, const char *w, int n)
{
    int k;
    for (k = from; k + n <= l->len; k++)
        if (l->s[k] == w[0] && !memcmp(l->s + k, w, n))
            return k;
    return -1;
}

/* the next match after the caret, wrapping; selected */
static void find_next(Ed *e)
{
    int i = e->caret.line, from = e->caret.col, k, c;
    if (!e->nfind)
        return;
    for (k = 0; k <= e->n; k++) {
        c = find_in(e->ln[i], from, e->find, e->nfind);
        if (c >= 0) {
            e->anchor.line = e->caret.line = i;
            e->anchor.col = c;
            e->caret.col = c + e->nfind;
            e->sel = 1;
            e->want = e->caret.col;
            /* the match in the view's middle if it wasn't in view */
            if (i < e->top || i >= e->top + e->rows) {
                e->top = i - e->rows / 2;
                if (e->top < 0)
                    e->top = 0;
            }
            follow(e);
            e->msg[0] = 0;
            return;
        }
        i = i + 1 < e->n ? i + 1 : 0;
        from = 0;
    }
    sprintf(e->msg, "\"%s\" not found", e->find);
}

static int find_key(Ed *e, const Event *ev)
{
    if (ev->key == K_ESC) {
        e->finding = 0;
    } else if (ev->key == K_ENTER || (ev->key == 'f' && (ev->mods & M_CTRL))) {
        find_next(e);
    } else if (ev->key == K_BACKSPACE) {
        if (e->nfind)
            e->find[--e->nfind] = 0;
    } else if (ev->ch >= 32 && ev->ch < 127 && !(ev->mods & M_CTRL)) {
        if (e->nfind < (int)sizeof e->find - 1) {
            e->find[e->nfind++] = ev->ch;
            e->find[e->nfind] = 0;
        }
    } else {
        /* any other key ends the search and does what it does */
        e->finding = 0;
        return ed_key(e, ev);
    }
    e->dirty = 1;
    return 1;
}

/* ---- keys ---- */

/* before a move: Shift starts or extends the selection, no Shift drops it */
static void move_sel(Ed *e, int shift)
{
    if (shift) {
        if (!e->sel) {
            e->sel = 1;
            e->anchor = e->caret;
        }
    } else {
        e->sel = 0;
    }
}

int ed_key(Ed *e, const Event *ev)
{
    int k = ev->key, shift = ev->mods & M_SHIFT, ctrl = ev->mods & M_CTRL, vert = 0;
    Pos a, b;
    Line *l;
    if (ev->type != EV_KEY || k == K_SHIFT || k == K_CTRL || k == K_ALT)
        return 0;
    if (e->finding)
        return find_key(e, ev);
    e->msg[0] = 0;
    l = e->ln[e->caret.line];
    switch (k) {
    case K_LEFT:
        if (e->sel && !shift && sel_range(e, &a, &b)) {
            /* the selection dropped, the caret at its start */
            e->caret = a;
            e->sel = 0;
            break;
        }
        move_sel(e, shift);
        if (e->caret.col > 0)
            e->caret.col--;
        else if (e->caret.line > 0) {
            e->caret.line--;
            e->caret.col = e->ln[e->caret.line]->len;
        }
        break;
    case K_RIGHT:
        if (e->sel && !shift && sel_range(e, &a, &b)) {
            e->caret = b;
            e->sel = 0;
            break;
        }
        move_sel(e, shift);
        if (e->caret.col < l->len)
            e->caret.col++;
        else if (e->caret.line < e->n - 1) {
            e->caret.line++;
            e->caret.col = 0;
        }
        break;
    case K_UP:
    case K_DOWN:
        if (ctrl) {
            /* the view by a line, the caret staying in it */
            e->top += k == K_UP ? -1 : 1;
            if (e->top > e->n - 1)
                e->top = e->n - 1;
            if (e->top < 0)
                e->top = 0;
            if (e->caret.line < e->top)
                e->caret.line = e->top;
            if (e->caret.line >= e->top + e->rows)
                e->caret.line = e->top + e->rows - 1;
            e->caret.col = e->want;
            clamp(e, &e->caret);
            e->sel = 0;
            e->dirty = 1;
            return 1;
        }
        move_sel(e, shift);
        e->caret.line += k == K_UP ? -1 : 1;
        vert = 1;
        break;
    case K_PGUP:
    case K_PGDN: {
        int d = k == K_PGUP ? -(e->rows - 1) : e->rows - 1;
        move_sel(e, shift);
        e->top += d;
        if (e->top > e->n - e->rows)
            e->top = e->n - e->rows;
        if (e->top < 0)
            e->top = 0;
        e->caret.line += d;
        vert = 1;
        break;
    }
    case K_HOME:
        move_sel(e, shift);
        if (ctrl)
            e->caret.line = 0;
        e->caret.col = 0;
        break;
    case K_END:
        move_sel(e, shift);
        if (ctrl)
            e->caret.line = e->n - 1;
        e->caret.col = e->ln[e->caret.line]->len;
        break;
    case K_BACKSPACE:
        if (!delete_sel(e)) {
            if (e->caret.col > 0) {
                e->caret.col--;
                memmove(l->s + e->caret.col, l->s + e->caret.col + 1, l->len - e->caret.col - 1);
                l->len--;
                touched(e, e->caret.line);
            } else if (e->caret.line > 0) {
                e->caret.line--;
                e->caret.col = e->ln[e->caret.line]->len;
                join(e, e->caret.line);
            }
        }
        break;
    case K_DEL:
        if (!delete_sel(e)) {
            if (e->caret.col < l->len) {
                memmove(l->s + e->caret.col, l->s + e->caret.col + 1, l->len - e->caret.col - 1);
                l->len--;
                touched(e, e->caret.line);
            } else if (e->caret.line < e->n - 1) {
                join(e, e->caret.line);
            }
        }
        break;
    case K_ENTER:
        delete_sel(e);
        newline(e, 1);
        break;
    case K_TAB:
        delete_sel(e);
        do
            insert_char(e, ' ');
        while (e->caret.col & 3);
        break;
    case K_ESC:
        e->sel = 0;
        break;
    default:
        if (ctrl) {
            if (k == 'c' || k == 'x') {
                copy_sel(e);
                if (k == 'x')
                    delete_sel(e);
            } else if (k == 'v') {
                delete_sel(e);
                insert_text(e, clip, nclip);
            } else if (k == 'a') {
                e->anchor.line = e->anchor.col = 0;
                e->caret.line = e->n - 1;
                e->caret.col = e->ln[e->n - 1]->len;
                e->sel = 1;
            } else if (k == 'f') {
                e->finding = 1;
            } else if (k == 'l') {
                ed_invalidate(e);
            } else {
                return 0;
            }
        } else if (ev->ch >= 32 && ev->ch < 127) {
            delete_sel(e);
            insert_char(e, ev->ch);
        } else {
            return 0;
        }
        break;
    }
    if (vert) {
        e->caret.col = e->want;
        clamp(e, &e->caret);
    } else {
        e->want = e->caret.col;
    }
    follow(e);
    return 1;
}

/* ---- the mouse ---- */

static Pos pos_at(Ed *e, int row, int col)
{
    Pos p;
    p.line = e->top + row;
    p.col = e->left + col;
    clamp(e, &p);
    return p;
}

void ed_press(Ed *e, int row, int col, int shift)
{
    Pos p = pos_at(e, row, col);
    if (shift) {
        if (!e->sel) {
            e->sel = 1;
            e->anchor = e->caret;
        }
    } else {
        e->anchor = p;
        e->sel = 0;
    }
    e->caret = p;
    e->want = p.col;
    e->finding = 0;
    follow(e);
}

void ed_drag(Ed *e, int row, int col)
{
    Pos p = pos_at(e, row, col);
    if (!pos_cmp(p, e->caret))
        return;
    e->caret = p;
    e->want = p.col;
    e->sel = pos_cmp(p, e->anchor) != 0;
    follow(e);
}

void ed_scroll_to(Ed *e, int first)
{
    if (first > e->n - e->rows)
        first = e->n - e->rows;
    if (first < 0)
        first = 0;
    if (first == e->top)
        return;
    e->top = first;
    if (e->caret.line < e->top)
        e->caret.line = e->top;
    if (e->caret.line >= e->top + e->rows)
        e->caret.line = e->top + e->rows - 1;
    clamp(e, &e->caret);
    e->dirty = 1;
}

void ed_blink(Ed *e, int on)
{
    e->blink_off = !on;
    e->dirty = 1;
}

/* ---- C's colours ---- */

static const char *const keywords[] = {
    "auto", "break", "case", "char", "const", "continue", "default", "do", "else", "enum",
    "extern", "for", "goto", "if", "int", "long", "register", "return", "short", "signed",
    "sizeof", "static", "struct", "switch", "typedef", "union", "unsigned", "void", "volatile",
    "while", 0,
};

/* each character's kind: 1 a letter or '_', 2 a digit; 4 a keyword's first letter */
static unsigned char ctype[256];

static void ctype_init(void)
{
    int c, k;
    for (c = 'a'; c <= 'z'; c++)
        ctype[c] = ctype[c - 'a' + 'A'] = 1;
    ctype['_'] = 1;
    for (c = '0'; c <= '9'; c++)
        ctype[c] = 2;
    for (k = 0; keywords[k]; k++)
        ctype[(unsigned char)keywords[k][0]] |= 4;
}

static int keyword(const char *s, int n)
{
    int k;
    if (n < 2 || n > 8 || !(ctype[(unsigned char)s[0]] & 4))
        return 0;
    for (k = 0; keywords[k]; k++)
        if (keywords[k][0] == s[0] && keywords[k][1] == s[1] && !keywords[k][n] &&
            !memcmp(keywords[k], s, n))
            return 1;
    return 0;
}

/* a line's colour classes from its state at the start (in a comment);
   returns the state at its end */
int ed_syn_line(const char *s, int n, int cin, unsigned char *cls)
{
    int i = 0, j, base = A_TEXT, c;
    if (!ctype['a'])
        ctype_init();
    for (j = 0; j < n && s[j] == ' '; j++)
        cls[j] = A_TEXT;
    if (!cin && j < n && s[j] == '#')
        base = A_PREPROC;
    i = cin ? 0 : j;
    while (i < n) {
        c = (unsigned char)s[i];
        if (cin) {
            cls[i++] = A_COMMENT;
            if (c == '*' && i < n && s[i] == '/') {
                cls[i++] = A_COMMENT;
                cin = 0;
            }
        } else if (c == '/' && i + 1 < n && s[i + 1] == '*') {
            cls[i] = cls[i + 1] = A_COMMENT;
            i += 2;
            cin = 1;
        } else if (c == '/' && i + 1 < n && s[i + 1] == '/') {
            while (i < n)
                cls[i++] = A_COMMENT;
        } else if (c == '"' || c == '\'') {
            j = i + 1;
            while (j < n && s[j] != c)
                j += s[j] == '\\' ? 2 : 1;
            if (j < n)
                j++;
            if (j > n)
                j = n;
            while (i < j)
                cls[i++] = A_STRING;
        } else if (ctype[c] & 3) {
            int k = A_NUMBER;
            j = i;
            while (j < n && (ctype[(unsigned char)s[j]] & 3))
                j++;
            if (ctype[c] & 1)
                k = base == A_TEXT && keyword(s + i, j - i) ? A_KEYWORD : base;
            else if (base == A_PREPROC)
                k = base;
            while (i < j)
                cls[i++] = k;
        } else {
            cls[i++] = base;
        }
    }
    return cin;
}

/* a line's classes: lexed once for the colouring's state, then reused for
   its row as long as it doesn't change */
static unsigned char lex_cls[ED_LINEMAX + 1];
static const Line *lex_line;
static unsigned lex_ver;
static int lex_cin = -1;

static int lex(Line *l, int cin)
{
    int out = ed_syn_line(l->s, l->len, cin, lex_cls);
    lex_line = l;
    lex_ver = l->ver;
    lex_cin = cin;
    return out;
}

static const unsigned char *line_classes(Line *l)
{
    if (l != lex_line || l->ver != lex_ver || l->cin != lex_cin)
        lex(l, l->cin);
    return lex_cls;
}

/* the colouring's states from the first stale line down to the view's end */
static void syn_update(Ed *e)
{
    int i, end = e->top + e->rows;
    if (end > e->n)
        end = e->n;
    for (i = e->syn_from; i < end; i++) {
        Line *l = e->ln[i];
        int cin = i ? e->ln[i - 1]->cout : 0;
        if (l->sver == l->ver && l->cin == cin)
            continue;
        l->cin = cin;
        l->cout = lex(l, cin);
        l->sver = l->ver;
    }
    if (i > e->syn_from)
        e->syn_from = i;
}

/* ---- the redisplay ---- */


static Stamp *new_stamps;
static int new_cap;

#define STAMP_EQ(a, b)                                                                          \
    ((a)->line == (b)->line && (a)->ver == (b)->ver && (a)->s0 == (b)->s0 &&                    \
     (a)->s1 == (b)->s1 && (a)->cin == (b)->cin)

/* what each row should show: its line, the line's version, the selected
   columns, the colouring's state */
static void stamps(Ed *e, Stamp *st)
{
    Pos a, b;
    int r, i, sel = sel_range(e, &a, &b);
    for (r = 0, i = e->top; r < e->rows; r++, i++, st++) {
        Line *l;
        if (i >= e->n) {
            st->line = 0;
            st->ver = 0;
            st->s0 = st->s1 = 0;
            st->cin = 0;
            continue;
        }
        l = e->ln[i];
        st->line = l;
        st->ver = l->ver;
        st->cin = e->syntax ? l->cin : 0;
        st->s0 = st->s1 = 0;
        if (sel && i >= a.line && i <= b.line) {
            st->s0 = i == a.line ? a.col : 0;
            st->s1 = i == b.line ? b.col : l->len + 1;
        }
    }
}

/* a row's cells as they should be, in rtext and rattr */
static void build_row(Ed *e, const Stamp *st)
{
    char *t = e->rtext;
    unsigned char *a = e->rattr;
    int cols = e->cols, n = 0, k;
    memset(a, e->attr[A_TEXT], cols);
    if (st->line) {
        Line *l = st->line;
        n = l->len - e->left;
        if (n > cols)
            n = cols;
        if (n > 0) {
            memcpy(t, l->s + e->left, n);
            if (e->syntax) {
                const unsigned char *c = line_classes(l) + e->left;
                for (k = 0; k < n; k++)
                    a[k] = e->attr[c[k]];
            }
        } else {
            n = 0;
        }
        for (k = st->s0 - e->left; k < st->s1 - e->left; k++)
            if (k >= 0 && k < cols)
                a[k] = e->attr[A_SEL];
    }
    memset(t + n, ' ', cols - n);
}

static void caret_show(Ed *e, int on)
{
    if (on == e->con)
        return;
    e->con = on;
    e->ops->caret(e, e->crow, e->ccol, on);
}

static char *put_str(char *p, const char *s)
{
    while (*s)
        *p++ = *s++;
    return p;
}

/* a number in decimal, without a divide (microcoded, tens of cycles) */
static char *put_num(char *p, int v)
{
    static const int pow10[] = {10000, 1000, 100, 10, 1};
    int k, d, any = 0;
    for (k = 0; k < 5; k++) {
        for (d = 0; v >= pow10[k]; d++)
            v -= pow10[k];
        if (d || any || k == 4) {
            *p++ = '0' + d;
            any = 1;
        }
    }
    return p;
}

/* the status line, padded to its width: only the characters that changed
   are drawn (a caret's move changes two or three) */
static void status_update(Ed *e)
{
    char buf[160], *p = buf;
    int n = e->status_w, c0, c1, m, k;
    if (!e->ops->status)
        return;
    *p++ = ' ';
    if (e->finding) {
        p = put_str(p, "Find: ");
        p = put_str(p, e->find);
        *p++ = '_';
    } else if (e->msg[0]) {
        p = put_str(p, e->msg);
    } else {
        p = put_str(p, e->name);
        p = put_str(p, e->modified ? " *  Ln " : "  Ln ");
        p = put_num(p, e->caret.line + 1);
        p = put_str(p, ", Col ");
        p = put_num(p, e->caret.col + 1);
        p = put_str(p, "  of ");
        p = put_num(p, e->n);
    }
    /* past the longer of the old text and the new, both are blank */
    m = p - buf;
    k = e->status_ok && e->status_len < n ? (m > e->status_len ? m : e->status_len) : n;
    if (k > n)
        k = n;
    if (m < k)
        memset(p, ' ', k - m);
    e->status_len = m;
    if (!e->status_ok) {
        c0 = 0;
        c1 = n;
    } else {
        for (c0 = 0; c0 < k && buf[c0] == e->status[c0]; c0++)
            ;
        if (c0 == k)
            return;
        for (c1 = k; buf[c1 - 1] == e->status[c1 - 1]; c1--)
            ;
    }
    memcpy(e->status + c0, buf + c0, c1 - c0);
    e->status_ok = 1;
    e->ops->status(e, c0, c1, buf);
}

/* rows a..b-1 now show what rows a-k..b-k-1 showed: their memory goes with
   them, by pointer. The rows they came from and no row moved to (the
   rows uncovered) still show what they did on the screen, but get the
   memory left over: they're drawn again, whole */
static void move_memory(Ed *e, int a, int b, int k)
{
    static char *tp[256], *fp[256];
    static unsigned char *ap[256], *fa[256];
    static Stamp ts[256];
    int rows = e->rows, r, nf = 0, j = 0;
    memcpy(tp, e->stext, rows * sizeof(char *));
    memcpy(ap, e->sattr, rows * sizeof(unsigned char *));
    memcpy(ts, e->shown, rows * sizeof(Stamp));
    for (r = a; r < b; r++)
        if (r < a - k || r >= b - k) {
            fp[nf] = tp[r];
            fa[nf++] = ap[r];
        }
    for (r = a; r < b; r++) {
        e->stext[r] = tp[r - k];
        e->sattr[r] = ap[r - k];
        e->shown[r] = ts[r - k];
    }
    for (r = a - k; r < b - k; r++)
        if (r < a || r >= b) {
            e->stext[r] = fp[j];
            e->sattr[r] = fa[j++];
            e->shown[r].line = (Line *)1;   /* matches no line: drawn again */
            e->unknown[r] = 1;
        }
}

/* rows that only moved, if any: the view scrolled by d (shown_top - top),
   and the lines below an insertion or deletion by d + moved_n; moved by
   the front end, and the memory of them with them */
static void moves(Ed *e, const Stamp *ns)
{
    int rows = e->rows, r, ci, cand[2], best = 0, bestk = 0, a = -1, b = -1;
    cand[0] = e->shown_top - e->top;
    cand[1] = cand[0] + e->moved_n;
    for (ci = 0; ci < 2; ci++) {
        int k = cand[ci], m = 0;
        if (!k || k >= rows || k <= -rows || (ci == 1 && k == cand[0]))
            continue;
        for (r = k > 0 ? k : 0; r < rows && r - k < rows; r++)
            if (ns[r].line && STAMP_EQ(&ns[r], &e->shown[r - k]))
                m++;
        if (m > best) {
            best = m;
            bestk = k;
        }
    }
    if (!best)
        return;
    for (r = bestk > 0 ? bestk : 0; r < rows && r - bestk < rows; r++)
        if (ns[r].line && STAMP_EQ(&ns[r], &e->shown[r - bestk])) {
            if (a < 0)
                a = r;
            b = r + 1;
        }
    e->ops->move(e, a, a - bestk, b - a);
    move_memory(e, a, b, bestk);
    e->w_moved = b - a;
}

void ed_redisplay(Ed *e)
{
    const EdOps *ops = e->ops;
    int rows = e->rows, cols = e->cols, r, c0, c1;
    Stamp *ns;
    char *st, *rt;
    unsigned char *sa, *ra;
    e->w_rows = e->w_cells = e->w_moved = 0;
    if (!e->dirty)
        return;
    if (e->syntax)
        syn_update(e);
    if (new_cap < rows) {
        new_cap = rows;
        new_stamps = realloc(new_stamps, rows * sizeof(Stamp));
    }
    ns = new_stamps;
    stamps(e, ns);
    caret_show(e, 0);
    if (e->left != e->shown_left)
        e->full = 1;
    if (!e->full && ops->move)
        moves(e, ns);
    /* rows whose stamps differ: built, and their cells from the first that
       changed to the last drawn */
    rt = e->rtext;
    ra = e->rattr;
    for (r = 0; r < rows; r++) {
        if (!e->full && STAMP_EQ(&ns[r], &e->shown[r]))
            continue;
        st = e->stext[r];
        sa = e->sattr[r];
        build_row(e, &ns[r]);
        e->shown[r] = ns[r];
        if (e->full || e->unknown[r]) {
            e->unknown[r] = 0;
            c0 = 0;
            c1 = cols;
        } else {
            for (c0 = 0; c0 < cols && st[c0] == rt[c0] && sa[c0] == ra[c0]; c0++)
                ;
            if (c0 == cols)
                continue;
            for (c1 = cols; st[c1 - 1] == rt[c1 - 1] && sa[c1 - 1] == ra[c1 - 1]; c1--)
                ;
        }
        memcpy(st + c0, rt + c0, c1 - c0);
        memcpy(sa + c0, ra + c0, c1 - c0);
        ops->cells(e, r, c0, c1, rt, ra);
        e->w_rows++;
        e->w_cells += c1 - c0;
    }
    status_update(e);
    if (ops->bar && (e->bar_n != e->n || e->bar_top != e->top)) {
        e->bar_n = e->n;
        e->bar_top = e->top;
        ops->bar(e, e->n, e->top, rows);
    }
    e->crow = e->caret.line - e->top;
    e->ccol = e->caret.col - e->left;
    if (ops->caret_row && e->crow != e->tint_row) {
        e->tint_row = e->crow;
        ops->caret_row(e, e->crow);
    }
    if (!e->blink_off && e->crow >= 0 && e->crow < rows && e->ccol >= 0 && e->ccol < cols)
        caret_show(e, 1);
    e->shown_top = e->top;
    e->shown_left = e->left;
    e->full = 0;
    e->moved_n = 0;
    e->dirty = 0;
}
