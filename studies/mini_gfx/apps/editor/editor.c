/* A text editor on the window manager: two windows, a C file in C's
   colours and some notes, each an editor (edit.c) whose rows are drawn
   into the window's backing store. Rows that only moved are copied
   within the store (gfx_blit) and only the cells that changed are
   drawn; the window manager copies the damage to the screen.

   Every key is timed from its arrival (the UART's interrupt) to the end
   of the frame's composition, when the screen has it; the editor's own
   part (the redisplay into the store) and the compositor's are kept
   apart. The mode, the window manager's options and the drawing are
   pokes, so one program measures them all (measure.py). */

#include <stdio.h>
#include <string.h>
#include "wm.h"
#include "video.h"
#include "mini.h"
#include "perf.h"
#include "edit.h"
#include "text.h"

int wm_mode = 0, wm_options = 0;
int bench;                      /* the measuring script: no blink, a summary at the end */
int no_move;                    /* rows that moved are drawn again, not copied */
int colours = 1;                /* C's colours (at 2 and 4 bits a pixel) */
int win_x = 32;                 /* the C file's text: on a word in every mode, or not */

extern const char sample_c[], sample_notes[];
extern void (*rt_uart1_irq)(void);

typedef struct {
    Ed ed;
    Window *w;
    int tw, th;                 /* the text area in pixels */
    int bar_grab;               /* the scroll bar is being dragged */
    int down;                   /* the button is down */
    unsigned blink_at;          /* the frame the caret blinks next */
    unsigned char status_attr;
} EdWin;

static EdWin wins[2];
static int caret_xor;

/* ---- the measurements ---- */

enum { OP_TYPE, OP_ENTER, OP_DELETE, OP_CARET, OP_SCROLL, OP_PAGE, OP_REDRAW, OP_SELECT,
       OP_CLIP, OP_FIND, OP_MOUSE, OP_N };
static const char *op_names[OP_N] = {
    "type", "enter", "delete", "caret", "scroll", "page", "redraw", "select", "clip", "find",
    "mouse",
};

typedef struct {
    unsigned n, sum, max, app, comp, cells, rows, moved;
} Stat;

static Stat stats[OP_N];
static volatile unsigned arrived;       /* the last input's arrival, in ticks */
static void (*uart_irq)(void);
static int op = -1;                     /* this frame's first operation */
static unsigned t_event, t_app;

static void timed_uart_irq(void)
{
    arrived = video_ticks();
    uart_irq();
}

/* an operation starts: the first in a frame is the one measured */
static void op_begin(int k)
{
    if (op < 0) {
        op = k;
        t_event = arrived;
    }
}

/* ---- the editor's drawing, into the window's store ---- */

static void fe_move(Ed *e, int dst, int src, int n)
{
    EdWin *ew = e->fe;
    Surface *s = &ew->w->s;
    gfx_blit(s, 0, 16 * dst, s, 0, 16 * src, ew->tw, 16 * n, ROP_COPY);
    wm_damage(ew->w, 0, 16 * dst, ew->tw, 16 * (dst + n));
}

static void fe_cells(Ed *e, int r, int c0, int c1, const char *t, const unsigned char *a)
{
    EdWin *ew = e->fe;
    text_cells(&ew->w->s, 8 * c0, 16 * r, t + c0, a + c0, c1 - c0);
    wm_damage(ew->w, 8 * c0, 16 * r, 8 * c1, 16 * r + 16);
}

static void fe_caret(Ed *e, int r, int c, int on)
{
    EdWin *ew = e->fe;
    text_caret(&ew->w->s, 8 * c, 16 * r, caret_xor);
    wm_damage(ew->w, 8 * c, 16 * r, 8 * c + 2, 16 * r + 16);
    (void)on;
}

/* the status line under the text and the scroll bar */
static void fe_status(Ed *e, int c0, int c1, const char *text)
{
    EdWin *ew = e->fe;
    unsigned char attr[128];
    memset(attr, ew->status_attr, c1 - c0);
    text_cells(&ew->w->s, 8 * c0, ew->th, text + c0, attr, c1 - c0);
    wm_damage(ew->w, 8 * c0, ew->th, 8 * c1, ew->th + 16);
}

static void fe_bar(Ed *e, int total, int first, int shown)
{
    EdWin *ew = e->fe;
    ui_scrollbar(&ew->w->s, ew->tw, 0, ew->tw + 16, ew->th, total, first, shown);
    wm_damage(ew->w, ew->tw, 0, ew->tw + 16, ew->th);
}

static const EdOps ops = {fe_move, fe_cells, fe_caret, fe_status, fe_bar, 0};
static const EdOps ops_nomove = {0, fe_cells, fe_caret, fe_status, fe_bar, 0};

/* ---- the window's events ---- */

static int key_op(const Event *ev)
{
    int k = ev->key, shift = ev->mods & M_SHIFT, ctrl = ev->mods & M_CTRL;
    if (k == K_ENTER)
        return OP_ENTER;
    if (k == K_BACKSPACE || k == K_DEL)
        return OP_DELETE;
    if (k == K_PGUP || k == K_PGDN)
        return OP_PAGE;
    if ((k == K_UP || k == K_DOWN) && ctrl)
        return OP_SCROLL;
    if (k >= K_UP && k <= K_RIGHT)
        return shift ? OP_SELECT : OP_CARET;
    if (k == K_HOME || k == K_END)
        return shift ? OP_SELECT : OP_CARET;
    if (ctrl && k == 'l')
        return OP_REDRAW;
    if (ctrl && (k == 'x' || k == 'c' || k == 'v'))
        return OP_CLIP;
    if (ctrl && k == 'f')
        return OP_FIND;
    return OP_TYPE;
}

static void win_key(Window *w, const Event *ev)
{
    EdWin *ew = w->app;
    int top = ew->ed.top, k;
    if (ev->type != EV_KEY)
        return;
    if (ev->key == 'q' && (ev->mods & M_CTRL)) {
        wm.quit = 1;            /* Ctrl+Q: the end, and the measurements */
        return;
    }
    k = ew->ed.finding ? OP_FIND : key_op(ev);
    if (ed_key(&ew->ed, ev)) {
        /* a caret's move that scrolled is a scroll */
        if (k == OP_CARET && ew->ed.top != top)
            k = ew->ed.top - top == 1 || top - ew->ed.top == 1 ? OP_SCROLL : OP_PAGE;
        op_begin(k);
        /* the caret stays on while typing */
        ew->blink_at = wm.frames + 30;
        ed_blink(&ew->ed, 1);
    }
}

/* the window manager sends the press, then the moves and the release */
static void win_mouse(Window *w, const Event *ev, int x, int y)
{
    EdWin *ew = w->app;
    Ed *e = &ew->ed;
    int press = (ev->buttons & 1) && !ew->down, row, col;
    ew->down = ev->buttons & 1;
    if (!ew->down) {
        ew->bar_grab = 0;
        return;
    }
    op_begin(OP_MOUSE);
    if (press && x >= ew->tw && y < ew->th)
        ew->bar_grab = 1;
    if (ew->bar_grab) {
        /* the scroll bar: the line under the pointer to the view's middle */
        ed_scroll_to(e, y * e->n / ew->th - e->rows / 2);
        return;
    }
    /* past the text's edges: a row beyond, so the view follows */
    row = y < 0 ? -1 : y >= ew->th ? e->rows : y / 16;
    col = x < 0 ? 0 : x >= ew->tw ? e->cols : (x + 4) / 8;
    if (press)
        ed_press(e, row, col, ev->mods & M_SHIFT);
    else
        ed_drag(e, row, col);
    ew->blink_at = wm.frames + 30;
    ed_blink(e, 1);
}

static void win_tick(Window *w)
{
    EdWin *ew = w->app;
    Ed *e = &ew->ed;
    /* the caret blinks in the window with the focus (always on when
       measuring), and is off in the other */
    if (wm.focus == w) {
        if (bench && e->blink_off)
            ed_blink(e, 1);
        else if (!bench && wm.frames >= ew->blink_at) {
            ed_blink(e, e->blink_off);
            ew->blink_at = wm.frames + 30;
        }
    } else if (!e->blink_off) {
        ed_blink(e, 0);
    }
    if (e->dirty) {
        ed_redisplay(e);
        if (op >= 0) {
            Stat *s = &stats[op];
            s->cells += e->w_cells;
            s->rows += e->w_rows;
            s->moved += e->w_moved;
        }
        t_app = video_ticks();
    }
}

static EdWin *open_editor(int k, int x, int y, int cols, int rows, const char *name,
                          const char *text, int syntax)
{
    EdWin *ew = &wins[k];
    int bpp = wm.screen.bpp;
    char title[48];
    ew->tw = 8 * cols;
    ew->th = 16 * rows;
    sprintf(title, "%s", name);
    ew->w = wm_open(x, y, ew->tw + 16, ew->th + 16, title, WF_TITLE);
    ew->w->app = ew;
    ew->w->key = win_key;
    ew->w->mouse = win_mouse;
    ew->w->tick = win_tick;
    ed_init(&ew->ed, name, text, rows, cols, no_move ? &ops_nomove : &ops, ew);
    ew->ed.status_w = cols + 2;
    /* the colours: C's in 16 colours, greys at 2 bits, black and white at 1 */
    {
        Ed *e = &ew->ed;
        unsigned bg = th.bg << 4;
        int a;
        for (a = 0; a < A_N; a++)
            e->attr[a] = th.text | bg;
        e->attr[A_SEL] = th.sel_fg | th.sel_bg << 4;
        if (syntax && colours && bpp >= 2) {
            e->syntax = 1;
            if (bpp >= 4) {
                e->attr[A_KEYWORD] = 1 | bg;
                e->attr[A_COMMENT] = 2 | bg;
                e->attr[A_STRING] = 4 | bg;
                e->attr[A_NUMBER] = 5 | bg;
                e->attr[A_PREPROC] = 6 | bg;
            } else {
                e->attr[A_COMMENT] = 1 | bg;
                e->attr[A_STRING] = 1 | bg;
                e->attr[A_PREPROC] = 1 | bg;
            }
        }
        ew->status_attr = bpp == 1 ? (th.bg | th.text << 4) : (th.text | th.face << 4);
    }
    return ew;
}

static void summary(void)
{
    char name[32];
    int k;
    for (k = 0; k < OP_N; k++) {
        Stat *s = &stats[k];
        if (!s->n)
            continue;
        /* "@perf NAME AVG MAX N": from the key to the screen; then the
           editor's part and the compositor's, and the cells and rows drawn */
        sprintf(name, "%s", op_names[k]);
        printf("@perf %s %u %u %u\n", name, s->sum / s->n, s->max, s->n);
        sprintf(name, "%s_app", op_names[k]);
        printf("@perf %s %u\n", name, s->app / s->n);
        sprintf(name, "%s_comp", op_names[k]);
        printf("@perf %s %u\n", name, s->comp / s->n);
        sprintf(name, "%s_work", op_names[k]);
        printf("@perf %s %u %u %u\n", name, s->cells / s->n, s->rows / s->n, s->moved / s->n);
    }
}

int main(void)
{
    int cols, rows, big;
    unsigned t0;
    wm_init(wm_mode, wm_options);
    caret_xor = (1 << wm.screen.bpp) - 1;
    uart_irq = rt_uart1_irq;
    rt_uart1_irq = timed_uart_irq;
    big = wm.screen.w > 640;
    /* the notes first, under; the C file on top with the focus. The same
       window in every mode, so the modes compare; at 1024 x 768 the notes
       are beside it */
    open_editor(1, big ? 576 : 264, big ? 120 : 262, 44, 12, "notes.txt", sample_notes, 0);
    cols = 60;
    rows = 22;
    open_editor(0, win_x, 40, cols, rows, "console.c", sample_c, 1);
    t0 = video_ticks();
    wm_frame();
    perf_value("first_frame", video_ticks() - t0);
    while (!wm.quit) {
        op = -1;
        t_app = 0;
        wm_frame();
        if (op >= 0) {
            unsigned t = video_ticks();
            Stat *s = &stats[op];
            unsigned lat = t - t_event;
            s->n++;
            s->sum += lat;
            if (lat > s->max)
                s->max = lat;
            if (t_app) {
                s->app += t_app - t_event;
                s->comp += t - t_app;
            }
        }
        if (bench && rt_frames > 100000)
            break;
    }
    summary();
    printf("@done\n");
    return 0;
}
