/* The text editor on the whole screen, without the window manager: the
   same editing core as apps/editor (edit.c, text.c), in M6 (1024 x 768
   x 1, 128 x 48 cells of 8 x 16) by default, or M5, M4, M3, M0.

   Each text row's 16 lines are a buffer of their own in bank 1, and the
   line descriptors (D0) say which buffer each row shows. Rows that only
   move (a scroll, a line inserted above them) are moved by rewriting
   descriptors, not by copying pixels: the new table goes into the table
   not shown and TSEL switches at the frame's end, so the move is
   atomic. A row drawn while the old table still shows its buffer at
   another row is copied to a fresh buffer first. The palette banks
   colour what 1 bit can't: the caret's line is tinted (bank 1) and the
   status line is white on blue (bank 2), however many bits a pixel.

   With scroll_copy, the screen is one framebuffer and rows move by
   copying pixels (gfx_blit), for comparison. Keys are timed from their
   arrival to the screen's memory updated, and to the table's switch. */

#include <stdio.h>
#include <string.h>
#include "gfx.h"
#include "video.h"
#include "input.h"
#include "mini.h"
#include "perf.h"
#include "edit.h"
#include "text.h"

int mode = 6;                   /* M6; M5, M4, M3 or M0 */
int f1 = 1;                     /* F1 in the 1- and 2-bit modes (on an L0 board) */
int scroll_copy;                /* rows move by copying pixels, not descriptors */
int tint = 1;                   /* the caret's line in palette bank 1 */
int bench;                      /* the measuring script: no blink, a summary at the end */
int colours = 1;                /* C's colours at 2 and 4 bits a pixel */

extern const char sample_c[];
extern void (*rt_uart1_irq)(void);

#define MAXROWS 48
#define SPARE 4

static Ed ed;
static int rows, cols;          /* the text's rows (the status line is under them) */
static int fmt, caret_xor;
static unsigned char status_attr;

/* ---- the rows' buffers and the descriptors ---- */

static int nbuf;
static Surface bufs[MAXROWS + SPARE];   /* a text row's 16 lines each */
static Surface status_s;
static int map[MAXROWS];                /* the buffer each row shows (the next table) */
static int disp_row[MAXROWS + SPARE];   /* the row the shown table has a buffer at, or -1 */
static int map_dirty;                   /* map or the tint changed: a table to write */
static int tint_row = -1;
static int cur_t;                       /* the table being shown */
static volatile int flip_pending;
static volatile unsigned flip_at;       /* when the last switch happened */
static Surface screen;                  /* scroll_copy: one framebuffer */
static unsigned table_rows;             /* rows of descriptors written */

/* at each frame's end: the new table, if one is waiting */
static void frame_hook(void)
{
    if (flip_pending) {
        cur_t ^= 1;
        video_ctrl(cur_t ? VC_TSEL : 0, VC_TSEL);
        flip_pending = 0;
        flip_at = video_ticks();
    }
}

/* after a switch: what's shown is the map */
static void sync_disp(void)
{
    int r, b;
    for (b = 0; b < nbuf; b++)
        disp_row[b] = -1;
    for (r = 0; r < rows; r++)
        disp_row[map[r]] = r;
}

/* the rows of the map that show each buffer */
static int refs[MAXROWS + SPARE];

static void count_refs(void)
{
    int r;
    memset(refs, 0, sizeof refs);
    for (r = 0; r < rows; r++)
        refs[map[r]]++;
}

/* a buffer neither shown nor in the map */
static int free_buffer(void)
{
    int b;
    for (b = 0; b < nbuf; b++)
        if (!refs[b] && disp_row[b] < 0)
            return b;
    return -1;
}

/* the surface row r is drawn into, and its y there. A buffer that the
   map shares with another row, or that the shown table has at another
   row, is copied to a fresh one first (unless all of it is redrawn) */
static Surface *row_surface(int r, int *y, int whole)
{
    int b;
    if (scroll_copy) {
        *y = 16 * r;
        return &screen;
    }
    *y = 0;
    b = map[r];
    if (refs[b] > 1 || (disp_row[b] >= 0 && disp_row[b] != r)) {
        int nb = free_buffer();
        if (nb >= 0) {
            if (!whole)
                gfx_blit(&bufs[nb], 0, 0, &bufs[b], 0, 0, vid.w, 16, ROP_COPY);
            map[r] = nb;
            refs[b]--;
            refs[nb]++;
            map_dirty = 1;
        }
    }
    return &bufs[map[r]];
}

/* a row's 16 descriptors */
static unsigned *desc_row(unsigned *d, const Surface *s, int bank)
{
    unsigned w = video_desc(s->bits, bank), step = vid.words;
    int k;
    for (k = 0; k < 16; k++, w += step)
        *d++ = w;
    return d;
}

/* what each table's rows show as written: the buffer and the bank (-1:
   not written yet) */
static int tmap[2][MAXROWS], tbank[2][MAXROWS], tstatus[2];

/* the table not shown, from the map: the rows it doesn't already have
   right; it's shown from the next frame */
static void write_table(void)
{
    int t = cur_t ^ 1, r;
    unsigned *d = video_table(t);
    for (r = 0; r < rows; r++) {
        int bank = tint && r == tint_row;
        if (tmap[t][r] != map[r] || tbank[t][r] != bank) {
            desc_row(d + 16 * r, &bufs[map[r]], bank);
            tmap[t][r] = map[r];
            tbank[t][r] = bank;
            table_rows++;
        }
    }
    if (!tstatus[t]) {
        desc_row(d + 16 * rows, &status_s, 2);
        tstatus[t] = 1;
    }
    flip_pending = 1;
    map_dirty = 0;
}

/* ---- the editor's drawing ---- */

static void fe_move(Ed *e, int dst, int src, int n)
{
    int k, old[MAXROWS];
    if (scroll_copy) {
        gfx_blit(&screen, 0, 16 * dst, &screen, 0, 16 * src, vid.w, 16 * n, ROP_COPY);
        return;
    }
    memcpy(old, map, sizeof old);
    for (k = 0; k < n; k++)
        map[dst + k] = old[src + k];
    count_refs();
    map_dirty = 1;
    (void)e;
}

static void fe_cells(Ed *e, int r, int c0, int c1, const char *t, const unsigned char *a)
{
    int y;
    Surface *s = row_surface(r, &y, c0 == 0 && c1 == e->cols);
    text_cells(s, 8 * c0, y, t + c0, a + c0, c1 - c0);
}

static void fe_caret(Ed *e, int r, int c, int on)
{
    int y;
    Surface *s = row_surface(r, &y, 0);
    text_caret(s, 8 * c, y, caret_xor);
    (void)e;
    (void)on;
}

static void fe_status(Ed *e, int c0, int c1, const char *text)
{
    unsigned char attr[160];
    Surface *s = scroll_copy ? &screen : &status_s;
    memset(attr, status_attr, c1 - c0);
    text_cells(s, 8 * c0, scroll_copy ? 16 * rows : 0, text + c0, attr, c1 - c0);
    (void)e;
}

/* the caret's line in bank 1: its descriptors (with the copy, in place) */
static void fe_caret_row(Ed *e, int r)
{
    if (!tint)
        return;
    if (scroll_copy) {
        /* one framebuffer: the rows' descriptors in place, the bank changed */
        int p = screen.pitch * 4;
        if (tint_row >= 0 && tint_row < rows)
            video_lines(0, 16 * tint_row, 16, screen.bits + 16 * tint_row * screen.pitch, p, 0);
        if (r >= 0 && r < rows)
            video_lines(0, 16 * r, 16, screen.bits + 16 * r * screen.pitch, p, 1);
    } else {
        map_dirty = 1;
    }
    tint_row = r;
    (void)e;
}

static const EdOps ops = {fe_move, fe_cells, fe_caret, fe_status, 0, fe_caret_row};

/* ---- set-up ---- */

/* palette banks: 0 the text, 1 the caret's line (the paper tinted), 2 the
   status line (white on blue) */
static void palette(void)
{
    unsigned white = rgb565(255, 255, 255), black = rgb565(0, 0, 0);
    unsigned paper = rgb565(255, 248, 200), blue = rgb565(30, 60, 150);
    int k;
    video_default_palette();
    if (vid.bpp == 1) {
        video_pal(0, black);
        video_pal(1, white);
        video_pal(16, black);
        video_pal(17, paper);
        video_pal(32, white);
        video_pal(33, blue);
    } else if (vid.bpp == 2) {
        /* black, a green for comments, a red for strings, white */
        unsigned c[4];
        c[0] = black;
        c[1] = rgb565(0, 120, 0);
        c[2] = rgb565(170, 0, 0);
        c[3] = white;
        for (k = 0; k < 4; k++) {
            video_pal(k, c[k]);
            video_pal(16 + k, k == 3 ? paper : c[k]);
            video_pal(32 + k, k == 0 ? white : k == 3 ? blue : c[k]);
        }
    } else {
        for (k = 0; k < 16; k++) {
            unsigned c = rgb565(pal16[k][0], pal16[k][1], pal16[k][2]);
            video_pal(k, c);
            video_pal(16 + k, k == 15 ? paper : c);
            video_pal(32 + k, k == 0 ? white : k == 15 ? blue : c);
        }
    }
}

/* the cursor: an I-beam, in colours 253 (outline) and 254 */
static const char *ibeam[] = {
    "..... .....", ".###...###.", "....#.#....", "....#.#....", "....#.#....",
    "....#.#....", "....#.#....", "....#.#....", "....#.#....", "....#.#....",
    "....#.#....", "....#.#....", "....#.#....", "....#.#....", ".###...###.",
    "..... .....", 0,
};

static void cursor(void)
{
    unsigned *img = vram_alloc(32 * 8);
    int y, x;
    memset(img, 0, 32 * 8);
    for (y = 0; ibeam[y]; y++)
        for (x = 0; ibeam[y][x]; x++) {
            unsigned v = ibeam[y][x] == '#' ? 1 : ibeam[y][x] == '.' ? 2 : 0;
            img[2 * y + x / 16] |= v << (2 * (x % 16));
        }
    video_cursor(img);
}

static void setup(void)
{
    int r, bpp, words;
    unsigned flags = VC_CURSOR;
    vram_reset();
    video_init(mode, 0);
    if (vid.bpp < 4 && f1)
        flags |= VC_F1;
    video_init(mode, flags);
    palette();
    cursor();
    bpp = vid.bpp;
    words = vid.words;
    fmt = gfx_screen_format();
    cols = vid.w / 8;
    rows = vid.h / 16 - 1;
    caret_xor = (1 << bpp) - 1;
    if (scroll_copy) {
        void *fb = vram_alloc(words * 4 * vid.h);
        gfx_screen(&screen, fb, words);
        video_lines(0, 0, vid.h, fb, words * 4, 0);
        video_lines(0, 16 * rows, 16, (char *)fb + 16 * rows * words * 4, words * 4, 2);
    } else {
        nbuf = rows + SPARE;
        for (r = 0; r < nbuf; r++)
            gfx_init(&bufs[r], vram_alloc(words * 4 * 16), vid.w, 16, words, fmt);
        gfx_init(&status_s, vram_alloc(words * 4 * 16), vid.w, 16, words, fmt);
        for (r = 0; r < rows; r++) {
            map[r] = r;
            tmap[0][r] = tmap[1][r] = -1;
        }
        count_refs();
        sync_disp();
        /* both tables, so either may be shown first */
        write_table();
        cur_t ^= 1;
        write_table();
        cur_t ^= 1;
        flip_pending = 0;
        video_ctrl(cur_t ? VC_TSEL : 0, VC_TSEL);
        rt_frame_hook = frame_hook;
    }
    /* the colours: fg | bg << 4, in the mode's pixel values */
    {
        int a;
        unsigned char text, sel;
        if (bpp == 1) {
            text = 0 | 1 << 4;
            sel = 1 | 0 << 4;
        } else if (bpp == 2) {
            text = 0 | 3 << 4;
            sel = 3 | 0 << 4;
        } else {
            text = 0 | 15 << 4;
            sel = 15 | 1 << 4;
        }
        ed_init(&ed, "console.c", sample_c, rows, cols, &ops, 0);
        for (a = 0; a < A_N; a++)
            ed.attr[a] = text;
        ed.attr[A_SEL] = sel;
        status_attr = text;     /* bank 2 makes it white on blue */
        if (colours && bpp >= 2) {
            ed.syntax = 1;
            if (bpp == 2) {
                ed.attr[A_COMMENT] = 1 | 3 << 4;
                ed.attr[A_STRING] = 2 | 3 << 4;
                ed.attr[A_PREPROC] = 2 | 3 << 4;
                ed.attr[A_NUMBER] = 2 | 3 << 4;
            } else {
                ed.attr[A_KEYWORD] = 1 | 15 << 4;
                ed.attr[A_COMMENT] = 2 | 15 << 4;
                ed.attr[A_STRING] = 4 | 15 << 4;
                ed.attr[A_NUMBER] = 5 | 15 << 4;
                ed.attr[A_PREPROC] = 6 | 15 << 4;
            }
        }
    }
}

/* ---- the measurements ---- */

enum { OP_TYPE, OP_ENTER, OP_DELETE, OP_CARET, OP_SCROLL, OP_PAGE, OP_REDRAW, OP_SELECT,
       OP_CLIP, OP_FIND, OP_MOUSE, OP_N };
static const char *op_names[OP_N] = {
    "type", "enter", "delete", "caret", "scroll", "page", "redraw", "select", "clip", "find",
    "mouse",
};

typedef struct {
    unsigned n, sum, max, shown, nshown, cells, rows, moved, table;
} Stat;

static unsigned table_rows0;

static Stat stats[OP_N];
static volatile unsigned arrived;
static void (*uart_irq)(void);
static int op;
static unsigned t_event;

static void timed_uart_irq(void)
{
    arrived = video_ticks();
    uart_irq();
}

static void op_begin(int k)
{
    if (op < 0) {
        op = k;
        t_event = arrived;
    }
}

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
    if ((k >= K_UP && k <= K_RIGHT) || k == K_HOME || k == K_END)
        return shift ? OP_SELECT : OP_CARET;
    if (ctrl && k == 'l')
        return OP_REDRAW;
    if (ctrl && (k == 'x' || k == 'c' || k == 'v'))
        return OP_CLIP;
    if (ctrl && k == 'f')
        return OP_FIND;
    return OP_TYPE;
}

static void summary(void)
{
    char name[32];
    int k;
    for (k = 0; k < OP_N; k++) {
        Stat *s = &stats[k];
        if (!s->n)
            continue;
        /* "@perf NAME AVG MAX N": from the key to the memory drawn; then to
           the table's switch (when rows were moved by descriptors), and the
           work: cells and rows drawn, rows moved, descriptor rows written (16
           descriptors each) */
        printf("@perf %s %u %u %u\n", op_names[k], s->sum / s->n, s->max, s->n);
        if (s->nshown) {
            sprintf(name, "%s_shown", op_names[k]);
            printf("@perf %s %u %u %u\n", name, s->shown / s->nshown, 0, s->nshown);
        }
        sprintf(name, "%s_work", op_names[k]);
        printf("@perf %s %u %u %u %u\n", name, s->cells / s->n, s->rows / s->n, s->moved / s->n,
               s->table / s->n);
    }
}

/* ---- the loop ---- */

int main(void)
{
    Event ev;
    int down = 0, quit = 0, top;
    unsigned blink_at = 0, t0, t;
    font_init();
    input_init();
    uart_irq = rt_uart1_irq;
    rt_uart1_irq = timed_uart_irq;
    setup();
    t0 = video_ticks();
    ed_redisplay(&ed);
    if (map_dirty)
        write_table();
    perf_value("first_draw", video_ticks() - t0);
    while (!quit) {
        int k, tables = 0;
        video_wait();
        while (flip_pending)
            rt_wait_frame_after(rt_frames);
        if (!scroll_copy)
            sync_disp();
        video_cursor_at(mouse_x - 5, mouse_y - 8);
        op = -1;
        while (input_next(&ev)) {
            if (ev.type == EV_KEY) {
                if (ev.key == 'q' && (ev.mods & M_CTRL)) {
                    quit = 1;
                    break;
                }
                k = ed.finding ? OP_FIND : key_op(&ev);
                top = ed.top;
                if (ed_key(&ed, &ev)) {
                    if (k == OP_CARET && ed.top != top)
                        k = ed.top - top == 1 || top - ed.top == 1 ? OP_SCROLL : OP_PAGE;
                    op_begin(k);
                    ed_blink(&ed, 1);
                    blink_at = rt_frames + 30;
                }
            } else if (ev.type == EV_MOUSE) {
                int press = (ev.buttons & 1) && !down, row = ev.y / 16, col = (ev.x + 4) / 8;
                down = ev.buttons & 1;
                if (!down)
                    continue;
                op_begin(OP_MOUSE);
                if (press)
                    ed_press(&ed, row, col, ev.mods & M_SHIFT);
                else
                    ed_drag(&ed, row, col);
            }
        }
        if (!bench && rt_frames >= blink_at) {
            ed_blink(&ed, ed.blink_off);
            blink_at = rt_frames + 30;
        }
        if (ed.dirty) {
            ed_redisplay(&ed);
            if (op >= 0) {
                Stat *s = &stats[op];
                s->cells += ed.w_cells;
                s->rows += ed.w_rows;
                s->moved += ed.w_moved;
            }
            if (map_dirty) {
                table_rows0 = table_rows;
                write_table();
                tables = 1;
            }
        }
        if (op >= 0) {
            Stat *s = &stats[op];
            unsigned lat;
            t = video_ticks();
            lat = t - t_event;
            s->n++;
            s->sum += lat;
            if (lat > s->max)
                s->max = lat;
            if (tables) {
                /* shown when the table switches, at the frame's end */
                while (flip_pending)
                    rt_wait_frame_after(rt_frames);
                s->shown += flip_at - t_event;
                s->nshown++;
                s->table += table_rows - table_rows0;
            }
        }
    }
    summary();
    printf("@done\n");
    return 0;
}
