/* Workshop stores: a forms application on the window manager. A list of
   the parts in stock (a table that sorts by any column, a search box
   that filters it as you type), a record window to edit one (text and
   number fields, a drop-down, radio buttons, check boxes, buttons, the
   keyboard), a confirmation dialog before a delete, and a chart of the
   stock's value by category. The data is made up (data.c) and kept in
   memory.

   Every interaction is measured: from the start of its handling to the
   end of the frame's composition, and the handler's part on its own;
   the counts and averages are printed at the end as @perf lines.

   The run's choices come from pokes: the mode, the window manager's
   options, how the list's text is drawn, whether the selection is drawn
   by palette banks, and data.c's filter_mode. */

#include <stdio.h>
#include <string.h>
#include "wm.h"
#include "video.h"
#include "perf.h"
#include "fw.h"
#include "data.h"

int mode = 0;                   /* M0-M6 */
int options = WM_SNAP;          /* wm_init's */
int list_font = 0;              /* 0 the sans in strips, 1 glyph by glyph (font_draw), 2 cells */
int sel_banks = 0;              /* the selection by palette bank (4 bits a pixel) */
int trace = 0;                  /* each operation's time on the console */
int bench = 0;                  /* the pieces timed on their own first (run_bench) */
int row_cache = 1;              /* the list's rows kept as strips (table_cache) */

static int xga;

/* ---- measuring ---- */

enum { OP_START, OP_TYPE, OP_SEARCH, OP_SEL, OP_SCROLL1, OP_PAGE, OP_DRAG, OP_SORT, OP_OPEN,
       OP_SAVE, OP_REVERT, OP_DIALOG, OP_DELETE, OP_NEW, OP_POPUP, OP_CHART, OP_REDRAW,
       OP_CARET, OP_FIELD, NOP };
static const char *op_names[NOP] = {
    "startup", "type_field", "type_search", "select_move", "scroll_row", "scroll_page",
    "scroll_drag", "sort", "open_record", "save", "revert", "delete_dialog", "delete",
    "new_record", "popup", "chart", "full_redraw", "caret_blink", "field_focus",
};

/* n: the frames an operation was handled in; ev: the events (keys,
   clicks) handled in them, more than n when they came faster than the
   frames went */
typedef struct {
    unsigned n, ev, app, app_max, tot, tot_max, comp, comp_max;
} Stat;

static Stat stats[NOP];
static int op_cur = -1, op_ev;
static unsigned op_t0, op_t1;
/* parts of an operation */
static unsigned filter_ticks, filter_n, filter_scans, sort_ticks, sort_n;

static void op_begin(int op)
{
    if (op_cur < 0) {
        op_cur = op;
        op_ev = 0;
        op_t0 = video_ticks();
    }
    op_ev++;
}

/* what the operation under way turned out to be (a click that was a
   button's), or a new one */
static void op_kind(int op)
{
    if (op_cur >= 0)
        op_cur = op;
    else
        op_begin(op);
}

static void op_end(void)
{
    op_t1 = video_ticks();
}

/* after the frame's composition */
static void op_frame(void)
{
    unsigned t, app, comp;
    Stat *s;
    if (op_cur < 0)
        return;
    t = video_ticks();
    s = &stats[op_cur];
    app = op_t1 - op_t0;
    comp = t - op_t1;
    s->n++;
    s->ev += op_ev;
    s->app += app;
    s->comp += comp;
    s->tot += t - op_t0;
    if (app > s->app_max)
        s->app_max = app;
    if (comp > s->comp_max)
        s->comp_max = comp;
    if (t - op_t0 > s->tot_max)
        s->tot_max = t - op_t0;
    if (trace)
        printf("op %s %u: %u %u ticks\n", op_names[op_cur], op_ev, app, t - op_t0);
    op_cur = -1;
}

static void op_report(void)
{
    int k;
    printf("\noperation      frames events  total ms (max)    handler ms  composition ms\n");
    for (k = 0; k < NOP; k++) {
        Stat *s = &stats[k];
        if (!s->n)
            continue;
        /* hundredths of a millisecond: 503.5 ticks */
        printf("%-14s %4u %4u %6u.%02u (%5u.%02u) %6u.%02u %6u.%02u\n", op_names[k], s->n, s->ev,
               s->tot / s->n / 504 / 100, s->tot / s->n / 504 % 100, s->tot_max / 504 / 100,
               s->tot_max / 504 % 100, s->app / s->n / 504 / 100, s->app / s->n / 504 % 100,
               s->comp / s->n / 504 / 100, s->comp / s->n / 504 % 100);
        printf("@perf %s %u %u %u %u\n", op_names[k], s->tot / s->n, s->tot_max, s->n, s->ev);
        printf("@perf %s.app %u %u %u\n", op_names[k], s->app / s->n, s->app_max, s->n);
        printf("@perf %s.comp %u %u %u\n", op_names[k], s->comp / s->n, s->comp_max, s->n);
    }
    if (filter_n)
        printf("@perf filter %u %u %u\n", filter_ticks / filter_n, filter_scans / filter_n,
               filter_n);
    if (sort_n)
        printf("@perf sort_only %u %u %u\n", sort_ticks / sort_n, 0, sort_n);
}

static void filter(const char *q)
{
    unsigned t = video_ticks();
    data_filter(q);
    filter_ticks += video_ticks() - t;
    filter_scans += filter_scanned;
    filter_n++;
}

static void sort(int k, int desc)
{
    unsigned t = video_ticks();
    data_sort(k, desc);
    sort_ticks += video_ticks() - t;
    sort_n++;
}

/* ---- the list window ---- */

static Window *list_win, *rec_win, *chart_win;
static Table tbl;
static Form lform;
static Field lfields[5];
enum { LF_SEARCH, LF_COUNT, LF_OPEN, LF_NEW, LF_CHART };

static const Column cols_vga[] = {
    {"Part no.", 64, 0, K_CODE}, {"Description", 208, 0, K_DESC}, {"Category", 88, 0, K_CAT},
    {"Bin", 48, 0, K_BIN}, {"Qty", 44, 1, K_QTY}, {"Price", 60, 1, K_PRICE},
    {"Value", 72, 1, K_VALUE},
};
static const Column cols_xga[] = {
    {"Part no.", 64, 0, K_CODE}, {"Description", 216, 0, K_DESC}, {"Category", 88, 0, K_CAT},
    {"Supplier", 136, 0, K_SUPPLIER}, {"Bin", 48, 0, K_BIN}, {"Unit", 40, 0, K_UNIT},
    {"Qty", 44, 1, K_QTY}, {"Reorder", 56, 1, K_REORDER}, {"Price", 60, 1, K_PRICE},
    {"Value", 80, 1, K_VALUE}, {"Status", 104, 0, K_FLAGS},
};

/* cents as 1,234.56; or whole units as 1,234 */
static void money(char *buf, int cents, int whole)
{
    int u = cents / 100;
    if (u >= 1000)
        sprintf(buf, "%d,%03d", u / 1000, u % 1000);
    else
        sprintf(buf, "%d", u);
    if (!whole)
        sprintf(buf + strlen(buf), ".%02d", cents % 100);
}

static int row_id(Table *t, int r)
{
    return view[r];
}

static int cell(Table *t, int r, int c, char *buf)
{
    const Part *p = &parts[view[r]];
    int low = p->qty < p->reorder && !(p->flags & PF_DISCONT);
    switch (t->cols[c].key) {
    case K_CODE: strcpy(buf, p->code); break;
    case K_DESC: strcpy(buf, p->desc); break;
    case K_CAT: strcpy(buf, cat_names[p->cat]); break;
    case K_SUPPLIER: strcpy(buf, p->supplier); break;
    case K_BIN: strcpy(buf, p->bin); break;
    case K_UNIT: strcpy(buf, unit_names[p->unit]); break;
    case K_QTY:
        sprintf(buf, "%d", p->qty);
        return low ? (int)th.accent : -1;
    case K_REORDER: sprintf(buf, "%d", p->reorder); break;
    case K_PRICE: money(buf, p->price, 0); break;
    case K_VALUE: money(buf, p->qty * p->price, 1); break;
    case K_FLAGS:
        strcpy(buf, p->flags & PF_DISCONT ? "Discontinued" : low ? "Low stock" : "");
        if (p->flags & PF_HAZARD)
            strcat(buf, *buf ? ", haz." : "Hazardous");
        return low ? (int)th.accent : -1;
    }
    return -1;
}

static void list_count(void)
{
    Field *f = &lfields[LF_COUNT];
    if (nview == nlive)
        sprintf(f->text, "%d parts", nlive);
    else
        sprintf(f->text, "%d of %d parts", nview, nlive);
    form_field(&lform, LF_COUNT);
}

/* the rows again after the view changed: only those whose record (or
   stripe, or selection) changed, given what the rows showed before */
static int changed_rec = -1;    /* a record whose row is to be drawn even if it didn't move */

static void list_refresh(const int *before, int nbefore, int sel_before, int first_before)
{
    int i, all = (first_before ^ tbl.first) & 1;      /* the stripes moved: every row */
    tbl.total = nview;
    if (tbl.first > nview - tbl.rows)
        tbl.first = nview - tbl.rows > 0 ? nview - tbl.rows : 0;
    if (tbl.sel >= nview)
        tbl.sel = nview - 1;
    for (i = 0; i < tbl.rows; i++) {
        int r = tbl.first + i;
        int now = r < nview ? view[r] : -1, was = i < nbefore ? before[i] : -1;
        if (all || now != was || now == changed_rec ||
            ((r == tbl.sel) != (i == sel_before) && !tbl.banks))
            table_row(&tbl, i);
    }
    table_scrollbar(&tbl);
    if (tbl.banks)
        table_banks_update(&tbl);
    list_count();
    changed_rec = -1;
}

/* what the rows show, to compare after a change */
static int snap_rows(int *out)
{
    int i;
    for (i = 0; i < tbl.rows; i++)
        out[i] = tbl.first + i < nview ? view[tbl.first + i] : -1;
    return tbl.sel - tbl.first;
}

static void list_search(void)
{
    int before[40], selb = snap_rows(before), first = tbl.first;
    filter(lfields[LF_SEARCH].text);
    tbl.first = 0;
    tbl.sel = nview ? 0 : -1;
    list_refresh(before, tbl.rows, selb, first);
}

static void list_sort(int col)
{
    int key = tbl.cols[col].key, rec = tbl.sel >= 0 ? view[tbl.sel] : -1, before[40], selb, k;
    int first = tbl.first;
    selb = snap_rows(before);
    if (col == tbl.sort_col)
        tbl.sort_desc ^= 1;
    else
        tbl.sort_desc = 0;
    tbl.sort_col = col;
    sort(key, tbl.sort_desc);
    table_header(&tbl);
    /* the same record stays selected, and in view */
    k = rec >= 0 ? data_find(rec) : -1;
    tbl.sel = k;
    if (k >= 0 && (k < tbl.first || k >= tbl.first + tbl.rows))
        tbl.first = k - tbl.rows / 2 < 0 ? 0 : k - tbl.rows / 2;
    list_refresh(before, tbl.rows, selb, first);
}

static void open_record(int rec);
static void new_record(void);
static void chart_toggle(void);
static void redraw_all(void);

static int global_key(const Event *e)
{
    if (e->type != EV_KEY)
        return 0;
    if (e->key == K_F1 + 1) {
        op_begin(OP_CHART);
        chart_toggle();
        op_end();
        return 1;
    }
    if (e->key == K_F1 + 4) {
        op_begin(OP_REDRAW);
        redraw_all();
        op_end();
        return 1;
    }
    if ((e->mods & M_CTRL) && e->key == 'q') {
        wm.quit = 1;
        return 1;
    }
    if ((e->mods & M_CTRL) && e->key == 'n') {
        op_begin(OP_NEW);
        new_record();
        op_end();
        return 1;
    }
    return 0;
}

/* Keys and the mouse only say what's wanted; the list's tick does it,
   once a frame however many events came (the window manager hands a
   window every queued event before it composes, so a handler that drew
   would hold the screen back while keys or moves kept coming) */
static int want_sel = -1, want_search, want_first = -1;

/* what's wanted, done now */
static void list_settle(void)
{
    if (want_search) {
        want_search = 0;
        list_search();
    }
    if (want_sel >= 0) {
        table_select(&tbl, want_sel);
        want_sel = -1;
    }
    if (want_first >= 0) {
        table_scroll(&tbl, want_first);
        want_first = -1;
    }
}

static void list_key(Window *w, const Event *e)
{
    int k = e->key, page = tbl.rows - 1, first = tbl.first;
    int sel = want_sel >= 0 ? want_sel : tbl.sel;
    if (fw_modal || e->type != EV_KEY || global_key(e))
        return;
    if (k == K_UP || k == K_DOWN || k == K_PGUP || k == K_PGDN || k == K_HOME || k == K_END) {
        int to = k == K_UP ? sel - 1 : k == K_DOWN ? sel + 1 : k == K_PGUP ? sel - page
               : k == K_PGDN ? sel + page : k == K_HOME ? 0 : nview - 1;
        if (to < 0)
            to = 0;
        if (to >= nview)
            to = nview - 1;
        /* which kind of move it was: by the scroll it needs */
        op_begin(to < first || to >= first + tbl.rows
                 ? (to - first == tbl.rows || first - to == 1 ? OP_SCROLL1 : OP_PAGE) : OP_SEL);
        want_sel = to;
        op_end();
        return;
    }
    if (k == K_ENTER) {
        list_settle();
        if (tbl.sel >= 0) {
            op_begin(OP_OPEN);
            open_record(view[tbl.sel]);
            op_end();
        }
        return;
    }
    if (k == K_ESC) {
        if (lfields[LF_SEARCH].len) {
            op_begin(OP_SEARCH);
            form_set_text(&lfields[LF_SEARCH], "");
            form_field(&lform, LF_SEARCH);
            list_search();
            op_end();
        }
        return;
    }
    if (k == K_TAB && rec_win) {
        wm_raise(rec_win);
        return;
    }
    /* the rest is the search box's: the box now, the filter in the tick */
    op_begin(OP_SEARCH);
    {
        char was[40];
        strcpy(was, lfields[LF_SEARCH].text);
        if (form_key(&lform, e) == FA_USED && strcmp(was, lfields[LF_SEARCH].text))
            want_search = 1;
    }
    op_end();
}

static int last_click_row = -1;
static unsigned last_click_frame;
static int list_mb;

static void list_mouse(Window *w, const Event *e, int x, int y)
{
    int pressed = e->buttons & ~list_mb & 1, row, col, a;
    list_mb = e->buttons;
    if (fw_modal)
        return;
    if (tbl.drag || (pressed && table_hit(&tbl, x, y, &row, &col) >= TH_SB_UP)) {
        /* the thumb's drag: where it's wanted (the tick scrolls); a page
           click at once */
        op_begin(OP_DRAG);
        if (tbl.drag && (e->buttons & 1))
            want_first = table_sb_drag_to(&tbl, y);
        else
            table_sb_mouse(&tbl, e, x, y);
        op_end();
        return;
    }
    op_begin(OP_FIELD);
    a = form_mouse(&lform, e, x, y);
    if (a >= FA_BUTTON) {
        a -= FA_BUTTON;
        if (a == LF_OPEN && tbl.sel >= 0) {
            op_kind(OP_OPEN);
            open_record(view[tbl.sel]);
        } else if (a == LF_NEW) {
            op_kind(OP_NEW);
            new_record();
        } else if (a == LF_CHART) {
            op_kind(OP_CHART);
            chart_toggle();
        }
        op_end();
        return;
    }
    op_end();
    if (a != FA_NONE || !pressed)
        return;
    list_settle();
    switch (table_hit(&tbl, x, y, &row, &col)) {
    case TH_HEADER:
        op_kind(OP_SORT);
        list_sort(col);
        op_end();
        break;
    case TH_ROW:
        if (row == last_click_row && wm.frames - last_click_frame < 20) {
            op_kind(OP_OPEN);
            open_record(view[row]);
            op_end();
            last_click_row = -1;
            break;
        }
        op_kind(OP_SEL);
        table_select(&tbl, row);
        op_end();
        last_click_row = row;
        last_click_frame = wm.frames;
        break;
    }
}

static void list_tick(Window *w)
{
    static int y0;
    list_settle();
    if (tbl.banks && w->c.y0 != y0) {
        y0 = w->c.y0;
        table_banks_update(&tbl);   /* the window moved: the selection's lines with it */
    }
    if (form_blink_due(&lform))
        op_begin(OP_CARET);
    form_tick(&lform);
    op_end();
}

static void list_close(Window *w)
{
    wm.quit = 1;
}

static void list_draw(void)
{
    Surface *s = &list_win->s;
    gfx_fill(s, 0, 0, s->w, s->h, th.bg, ROP_COPY);
    font_draw(s, font_sans, 6, 18, "Find", th.text, -1);
    form_draw(&lform);
    table_draw(&tbl);
}

static void list_open(void)
{
    int w = xga ? 960 : 608, rows = xga ? 26 : 12;
    Field *f = lfields;
    list_win = wm_open(xga ? 32 : 16, xga ? 24 : 22, w, 28 + TBL_HDR_H + rows * TBL_ROW_H + 2,
                       "Workshop stores: parts", WF_TITLE);
    list_win->key = list_key;
    list_win->mouse = list_mouse;
    list_win->tick = list_tick;
    list_win->close = list_close;
    memset(lfields, 0, sizeof lfields);
    f[LF_SEARCH].type = FT_TEXT;
    f[LF_SEARCH].x0 = 40; f[LF_SEARCH].y0 = 4; f[LF_SEARCH].x1 = 240; f[LF_SEARCH].y1 = 24;
    f[LF_SEARCH].max = 30;
    f[LF_COUNT].type = FT_LABEL;
    f[LF_COUNT].x0 = 252; f[LF_COUNT].y0 = 6; f[LF_COUNT].x1 = 400; f[LF_COUNT].y1 = 22;
    f[LF_OPEN].type = FT_BUTTON; f[LF_OPEN].label = "Open";
    f[LF_OPEN].x0 = 404; f[LF_OPEN].x1 = 468;
    f[LF_NEW].type = FT_BUTTON; f[LF_NEW].label = "New";
    f[LF_NEW].x0 = 474; f[LF_NEW].x1 = 538;
    f[LF_CHART].type = FT_BUTTON; f[LF_CHART].label = "Chart";
    f[LF_CHART].x0 = 544; f[LF_CHART].x1 = 604;
    f[LF_OPEN].y0 = f[LF_NEW].y0 = f[LF_CHART].y0 = 3;
    f[LF_OPEN].y1 = f[LF_NEW].y1 = f[LF_CHART].y1 = 25;
    lform.win = list_win;
    lform.f = lfields;
    lform.n = 5;
    lform.focus = LF_SEARCH;
    memset(&tbl, 0, sizeof tbl);
    tbl.win = list_win;
    tbl.x = 4;
    tbl.y = 28;
    tbl.w = xga ? 952 : 600;
    tbl.rows = rows;
    tbl.cols = xga ? cols_xga : cols_vga;
    tbl.ncol = xga ? 11 : 7;
    tbl.total = nview;
    tbl.sel = 0;
    tbl.cell = cell;
    tbl.fg = th.text;
    tbl.bg = th.bg;
    tbl.bg2 = wm.screen.bpp > 1 ? th.face : th.bg;
    tbl.sel_fg = th.sel_fg;
    tbl.sel_bg = th.sel_bg;
    tbl.id = row_id;
    if (row_cache)
        table_cache(&tbl, MAXPARTS);
    tbl.cellfont = list_font == 2;
    tbl.glyphs = list_font == 1;
    table_banks(&tbl, sel_banks);
    list_count();
    list_draw();
}

/* ---- the record window ---- */

static Form rform;
static Field rf[17];
static int rec = -1;            /* the record shown, -1: a new one */
enum { RF_CODE, RF_CAT, RF_BIN, RF_DESC, RF_SUPP, RF_UNIT, RF_QTY, RF_REORDER, RF_PRICE,
       RF_HAZ, RF_DISC, RF_MSG, RF_NEW, RF_SAVE, RF_DELETE, RF_REVERT, RF_INFO, RF_N };

static void field(int i, int type, const char *label, int lx, int x0, int y0, int x1)
{
    Field *f = &rf[i];
    memset(f, 0, sizeof *f);
    f->type = type;
    f->label = label;
    f->lx = lx;
    f->x0 = x0;
    f->y0 = y0;
    f->x1 = x1;
    f->y1 = y0 + (type == FT_BUTTON ? 24 : type == FT_LABEL ? 16 : 20);
    f->max = 34;
}

static void message(const char *text, int error)
{
    Field *f = &rf[RF_MSG];
    strncpy(f->text, text ? text : "", sizeof f->text - 1);
    f->val = error;
    form_field(&rform, RF_MSG);
}

static void rec_title(void)
{
    char t[48];
    if (rec < 0)
        strcpy(t, "New part");
    else
        sprintf(t, "Part %s", parts[rec].code);
    if (rform.dirty)
        strcat(t, " (changed)");
    if (strcmp(t, rec_win->title))
        wm_title(rec_win, t);
}

static void rec_info(void)
{
    Field *f = &rf[RF_INFO];
    int q, c;
    if (form_number(&rf[RF_QTY], &q) || form_money(&rf[RF_PRICE], &c)) {
        f->text[0] = 0;
    } else {
        strcpy(f->text, "Stock value ");
        money(f->text + strlen(f->text), q * c, 0);
    }
    form_field(&rform, RF_INFO);
}

/* the form from record r (or empty for a new one) */
static void rec_load(int r)
{
    const Part *p = &parts[r < 0 ? 0 : r];
    char buf[16];
    int i;
    rec = r;
    for (i = 0; i < RF_N; i++)
        rf[i].err = 0;
    if (r < 0) {
        form_set_text(&rf[RF_CODE], "");
        form_set_text(&rf[RF_BIN], "");
        form_set_text(&rf[RF_DESC], "");
        form_set_text(&rf[RF_SUPP], "");
        form_set_text(&rf[RF_QTY], "0");
        form_set_text(&rf[RF_REORDER], "10");
        form_set_text(&rf[RF_PRICE], "0.00");
        rf[RF_CAT].val = rf[RF_UNIT].val = rf[RF_HAZ].val = rf[RF_DISC].val = 0;
    } else {
        form_set_text(&rf[RF_CODE], p->code);
        form_set_text(&rf[RF_BIN], p->bin);
        form_set_text(&rf[RF_DESC], p->desc);
        form_set_text(&rf[RF_SUPP], p->supplier);
        sprintf(buf, "%d", p->qty);
        form_set_text(&rf[RF_QTY], buf);
        sprintf(buf, "%d", p->reorder);
        form_set_text(&rf[RF_REORDER], buf);
        sprintf(buf, "%d.%02d", p->price / 100, p->price % 100);
        form_set_text(&rf[RF_PRICE], buf);
        rf[RF_CAT].val = p->cat;
        rf[RF_UNIT].val = p->unit;
        rf[RF_HAZ].val = (p->flags & PF_HAZARD) != 0;
        rf[RF_DISC].val = (p->flags & PF_DISCONT) != 0;
    }
    rform.dirty = 0;
    rf[RF_MSG].text[0] = 0;
    rf[RF_INFO].text[0] = 0;
}

static void rec_draw(void)
{
    Surface *s = &rec_win->s;
    gfx_fill(s, 0, 0, s->w, s->h, th.bg, ROP_COPY);
    gfx_hline(s, 4, s->w - 4, 140, th.dark, ROP_COPY);
    form_draw(&rform);
    rec_info();
    rec_title();
}

/* the rows as they were before a change to the data (list_before),
   and the list after it: sorted again, the record `keep` still selected */
static int snap[40], snap_sel, snap_first;

static void list_before(void)
{
    snap_sel = snap_rows(snap);
    snap_first = tbl.first;
}

static void list_after_change(int keep)
{
    int k;
    sort(tbl.cols[tbl.sort_col].key, tbl.sort_desc);
    k = keep >= 0 ? data_find(keep) : -1;
    tbl.total = nview;
    tbl.sel = k >= 0 ? k : tbl.sel < nview ? tbl.sel : nview - 1;
    if (tbl.sel >= 0 && (tbl.sel < tbl.first || tbl.sel >= tbl.first + tbl.rows))
        tbl.first = tbl.sel - tbl.rows / 2 < 0 ? 0 : tbl.sel - tbl.rows / 2;
    changed_rec = keep;
    list_refresh(snap, tbl.rows, snap_sel, snap_first);
}

static void chart_update(void);

static void rec_save(void)
{
    const char *err = 0;
    int q, ro, c, bad = -1;
    Part *p;
    if ((err = form_number(&rf[RF_QTY], &q)) != 0)
        bad = RF_QTY;
    else if ((err = form_number(&rf[RF_REORDER], &ro)) != 0)
        bad = RF_REORDER;
    else if ((err = form_money(&rf[RF_PRICE], &c)) != 0)
        bad = RF_PRICE;
    else if (!rf[RF_CODE].len) {
        err = "Part no.: needed";
        bad = RF_CODE;
    } else if (!rf[RF_DESC].len) {
        err = "Description: needed";
        bad = RF_DESC;
    }
    if (err) {
        rf[bad].err = 1;
        form_focus(&rform, bad);
        form_field(&rform, bad);
        message(err, 1);
        return;
    }
    list_before();
    if (rec < 0) {
        rec = data_new();
        if (rec < 0) {
            message("The store is full", 1);
            return;
        }
    }
    p = &parts[rec];
    strcpy(p->code, rf[RF_CODE].text);
    strcpy(p->bin, rf[RF_BIN].text);
    strncpy(p->desc, rf[RF_DESC].text, sizeof p->desc - 1);
    strncpy(p->supplier, rf[RF_SUPP].text, sizeof p->supplier - 1);
    p->cat = rf[RF_CAT].val;
    p->unit = rf[RF_UNIT].val;
    p->flags = (rf[RF_HAZ].val ? PF_HAZARD : 0) | (rf[RF_DISC].val ? PF_DISCONT : 0);
    p->qty = q;
    p->reorder = ro;
    p->price = c;
    data_key(p);
    table_forget(&tbl, rec);
    rform.dirty = 0;
    message("Saved.", 0);
    rec_title();
    list_after_change(rec);
    chart_update();
}

static void rec_revert(void)
{
    int f = rform.focus;
    rec_load(rec);
    rform.focus = f;
    rec_draw();
}

static void delete_done(int choice)
{
    op_begin(OP_DELETE);
    if (choice == 0 && rec >= 0) {
        list_before();
        data_delete(rec);
        wm_close(rec_win);
        list_after_change(-1);
        chart_update();
    }
    op_end();
}

static void rec_delete(void)
{
    char l1[48];
    if (rec < 0) {
        rec_revert();
        return;
    }
    sprintf(l1, "Delete part %s?", parts[rec].code);
    dialog_open("Delete", l1, parts[rec].desc, "Delete|Cancel", delete_done);
}

static void rec_action(int a)
{
    if (a == FA_SAVE) {
        op_kind(OP_SAVE);
        rec_save();
    } else if (a == FA_REVERT) {
        op_kind(OP_REVERT);
        rec_revert();
    } else if (a == FA_DELETE) {
        op_kind(OP_DIALOG);
        rec_delete();
    } else if (a == FA_NEW) {
        op_kind(OP_NEW);
        new_record();
    } else if (a >= FA_BUTTON) {
        a -= FA_BUTTON;
        rec_action(a == RF_NEW ? FA_NEW : a == RF_SAVE ? FA_SAVE : a == RF_DELETE ? FA_DELETE
                   : FA_REVERT);
        return;
    }
    op_end();
}

static void rec_changed(Form *fm, int i)
{
    if (i < 0) {
        /* field -1 - i was validated: its message, or none */
        Field *f = &rf[-1 - i];
        int v;
        const char *err = f->type == FT_NUM ? form_number(f, &v) : form_money(f, &v);
        message(err ? err : "", err != 0);
        return;
    }
    if (i == RF_QTY || i == RF_PRICE)
        rec_info();
    rec_title();
}

static void rec_key(Window *w, const Event *e)
{
    int a, popup = rform.popup, focus = rform.focus;
    if (fw_modal || e->type != EV_KEY)
        return;
    if (!popup && global_key(e))
        return;
    if (!popup && e->key == K_TAB && (e->mods & M_CTRL)) {
        wm_raise(list_win);
        return;
    }
    op_begin(popup || (e->key == ' ' && rf[focus].type == FT_DROP) ? OP_POPUP
             : e->key == K_TAB ? OP_FIELD : OP_TYPE);
    a = form_key(&rform, e);
    op_end();
    if (a > FA_USED)
        rec_action(a);
}

static void rec_mouse(Window *w, const Event *e, int x, int y)
{
    int a;
    if (fw_modal)
        return;
    op_begin(OP_FIELD);
    a = form_mouse(&rform, e, x, y);
    op_end();
    if (a > FA_USED)
        rec_action(a);
}

static void rec_tick(Window *w)
{
    if (form_blink_due(&rform))
        op_begin(OP_CARET);
    form_tick(&rform);
    op_end();
}

static void rec_close(Window *w)
{
    popup_close();
    rec_win = 0;
}

static void rec_fields(void)
{
    static const char *units[] = {"each", "pack", "m", "kg", "l"};
    Field *f;
    field(RF_CODE, FT_TEXT, "Part no.", 8, 80, 8, 176);
    rf[RF_CODE].max = 9;
    field(RF_CAT, FT_DROP, "Category", 192, 256, 8, 400);
    rf[RF_CAT].items = cat_names;
    rf[RF_CAT].nitems = NCAT;
    field(RF_BIN, FT_TEXT, "Bin", 416, 446, 8, 520);
    rf[RF_BIN].max = 7;
    field(RF_DESC, FT_TEXT, "Description", 8, 80, 34, 520);
    field(RF_SUPP, FT_TEXT, "Supplier", 8, 80, 60, 260);
    rf[RF_SUPP].max = 21;
    field(RF_UNIT, FT_RADIO, "Unit", 276, 310, 64, 560);
    f = &rf[RF_UNIT];
    f->items = units;
    f->nitems = 5;
    f->ix[0] = 310; f->ix[1] = 366; f->ix[2] = 428; f->ix[3] = 468; f->ix[4] = 512;
    field(RF_QTY, FT_NUM, "Quantity", 8, 80, 86, 150);
    rf[RF_QTY].lo = 0;
    rf[RF_QTY].hi = 99999;
    field(RF_REORDER, FT_NUM, "Reorder at", 166, 240, 86, 300);
    rf[RF_REORDER].lo = 0;
    rf[RF_REORDER].hi = 9999;
    field(RF_PRICE, FT_MONEY, "Price", 318, 356, 86, 440);
    field(RF_HAZ, FT_CHECK, "Hazardous", 0, 80, 116, 0);
    field(RF_DISC, FT_CHECK, "Discontinued", 0, 190, 116, 0);
    field(RF_MSG, FT_LABEL, 0, 0, 316, 114, 600);
    field(RF_NEW, FT_BUTTON, "New", 0, 8, 150, 84);
    field(RF_SAVE, FT_BUTTON, "Save", 0, 92, 150, 168);
    field(RF_DELETE, FT_BUTTON, "Delete", 0, 176, 150, 252);
    field(RF_REVERT, FT_BUTTON, "Revert", 0, 260, 150, 336);
    field(RF_INFO, FT_LABEL, 0, 0, 452, 154, 600);
    rform.f = rf;
    rform.n = RF_N;
    rform.changed = rec_changed;
}

static void open_record(int r)
{
    if (!rec_win) {
        rec_win = wm_open(xga ? 32 : 16, xga ? 512 : 284, 608, 180, "Part", WF_TITLE);
        rec_win->key = rec_key;
        rec_win->mouse = rec_mouse;
        rec_win->tick = rec_tick;
        rec_win->close = rec_close;
        rform.win = rec_win;
        rform.focus = RF_DESC;
    } else {
        wm_raise(rec_win);
    }
    rec_load(r);
    rec_draw();
}

static void new_record(void)
{
    open_record(-1);
    form_focus(&rform, RF_CODE);
}

/* ---- the chart ---- */

static int chart_values[NCAT];
static char chart_text[NCAT][16];
static const char *chart_texts[NCAT];

static void chart_draw(void)
{
    Surface *s = &chart_win->s;
    int k, max = 1, total = 0;
    char buf[48];
    for (k = 0; k < NCAT; k++)
        chart_values[k] = 0;
    for (k = 0; k < nparts; k++)
        if (parts[k].used)
            chart_values[parts[k].cat] += parts[k].qty * parts[k].price;
    for (k = 0; k < NCAT; k++) {
        if (chart_values[k] > max)
            max = chart_values[k];
        total += chart_values[k] / 100;
        money(chart_text[k], chart_values[k], 1);
        chart_texts[k] = chart_text[k];
    }
    gfx_fill(s, 0, 0, s->w, 24, th.bg, ROP_COPY);
    sprintf(buf, "Stock value: %d,%03d in all", total / 1000, total % 1000);
    font_draw(s, font_sans, 6, 16, buf, th.text, -1);
    bars_draw(s, 4, 24, s->w - 4, s->h - 4, cat_names, chart_values, chart_texts, NCAT, max);
    wm_damage_all(chart_win);
}

static void chart_update(void)
{
    if (chart_win)
        chart_draw();
}

static void chart_close(Window *w)
{
    chart_win = 0;
}

static void chart_key(Window *w, const Event *e)
{
    if (!fw_modal)
        global_key(e);
}

static void chart_toggle(void)
{
    if (chart_win) {
        wm_close(chart_win);
        return;
    }
    chart_win = wm_open(xga ? 672 : 316, xga ? 512 : 58, 312, xga ? 200 : 196,
                        "Stock by category", WF_TITLE);
    chart_win->close = chart_close;
    chart_win->key = chart_key;
    chart_draw();
}

/* ---- the pieces on their own ----

   Each timed over a few runs, as @perf b.NAME TICKS (a run's average):
   a row's cells (the text, sprintf and all), clearing a strip, putting
   the row's text into it, expanding it into the store, the same text in
   cells, the same row the library's way (font_draw a glyph at a time),
   a whole row (table_row), the rows scrolled in the store by one, the
   rows copied to the screen (what the composition does with them), the
   filter by each method, and the sort by text and by number. */

static unsigned t_bench;

static void b_start(void)
{
    t_bench = video_ticks();
}

static void b_end(const char *name, int n)
{
    printf("@perf b.%s %u\n", name, (video_ticks() - t_bench) / n);
}

static void run_bench(void)
{
    static char texts[16][48];
    Surface *s = &list_win->s;
    int w = tbl.w - TBL_SB_W, y = tbl.y + TBL_HDR_H, n = 4, k, c, x, glyphs = 0, m;
    int fm = filter_mode, sm = sort_mode;
    for (c = 0; c < tbl.ncol; c++) {
        cell(&tbl, 5, c, texts[c]);
        glyphs += strlen(texts[c]);
    }
    printf("@perf b.glyphs %d\n", glyphs);
    b_start();
    for (k = 0; k < n; k++)
        for (c = 0; c < tbl.ncol; c++)
            cell(&tbl, 5, c, texts[c]);
    b_end("cells", n);
    b_start();
    for (k = 0; k < n; k++)
        strip_begin(w);
    b_end("strip_clear", n);
    b_start();
    for (k = 0; k < n; k++)
        for (c = x = 0; c < tbl.ncol; c++) {
            strip_text(x + 4, x + tbl.cols[c].w - 3, texts[c]);
            x += tbl.cols[c].w;
        }
    b_end("strip_text", n);
    b_start();
    for (k = 0; k < n; k++)
        strip_put(s, tbl.x, y, tbl.x & 31, w, th.text, th.bg);
    b_end("strip_put", n);
    b_start();
    for (k = 0; k < n; k++)
        gfx_expand(s, tbl.x, y, &strip, tbl.x & 31, 0, w, STRIP_H, th.text, th.bg, 1);
    b_end("gfx_expand", n);
    b_start();
    for (k = 0; k < n; k++)
        for (c = x = 0; c < tbl.ncol; c++) {
            strip_cells((x + 7) & ~7, texts[c], (tbl.cols[c].w - 4) / 8);
            x += tbl.cols[c].w;
        }
    b_end("strip_cells", n);
    b_start();
    for (k = 0; k < n; k++) {
        gfx_fill(s, tbl.x, y, tbl.x + w, y + TBL_ROW_H, th.bg, ROP_COPY);
        for (c = x = 0; c < tbl.ncol; c++) {
            font_draw(s, font_sans, tbl.x + x + 4, y + STRIP_BASE, texts[c], th.text, -1);
            x += tbl.cols[c].w;
        }
    }
    b_end("font_draw_row", n);
    b_start();
    for (k = 0; k < n; k++)
        gfx_fill(s, tbl.x, y, tbl.x + w, y + TBL_ROW_H, th.bg, ROP_COPY);
    b_end("row_fill", n);
    b_start();
    for (k = 0; k < n; k++)
        table_row(&tbl, 0);
    b_end("table_row", n);
    b_start();
    for (k = 0; k < n; k++)
        gfx_blit(s, tbl.x, y, s, tbl.x, y + TBL_ROW_H, w, (tbl.rows - 1) * TBL_ROW_H, ROP_COPY);
    b_end("store_scroll", n);
    b_start();
    for (k = 0; k < n; k++)
        gfx_blit(&wm.screen, list_win->c.x0 + tbl.x, list_win->c.y0 + y, s, tbl.x, y, w,
                 tbl.rows * TBL_ROW_H, ROP_COPY);
    b_end("screen_rows", n);
    b_start();
    for (k = 0; k < n; k++)
        gfx_blit(&wm.screen, list_win->c.x0 + tbl.x + 3, list_win->c.y0 + y, s, tbl.x, y, w,
                 tbl.rows * TBL_ROW_H, ROP_COPY);
    b_end("screen_rows_shifted", n);
    /* the filter: every method, a word that's in a few records */
    for (m = 0; m < 4; m++) {
        char name[24];
        filter_mode = m;
        data_filter("");
        b_start();
        data_filter("b");
        data_filter("bo");
        data_filter("bol");
        data_filter("bolt");
        sprintf(name, "filter%d_bolt", m);
        b_end(name, 4);
        b_start();
        data_filter("zzzz");
        sprintf(name, "filter%d_scan", m);
        b_end(name, 1);
    }
    filter_mode = fm;
    data_filter("");
    for (m = 0; m < 2; m++) {
        char name[24];
        sort_mode = m;
        b_start();
        data_sort(K_DESC, 0);
        sprintf(name, "sort%d_desc", m);
        b_end(name, 1);
        b_start();
        data_sort(K_QTY, 1);
        sprintf(name, "sort%d_qty", m);
        b_end(name, 1);
    }
    sort_mode = sm;
    data_sort(K_CODE, 0);
}

/* ---- everything ---- */

static void redraw_all(void)
{
    list_draw();
    if (rec_win)
        rec_draw();
    if (chart_win)
        chart_draw();
    wm_damage_screen(0, 0, wm.screen.w, wm.screen.h);
}

int main(void)
{
    unsigned t0;
    wm_init(mode, options);
    op_begin(OP_START);
    t0 = video_ticks();
    xga = wm.screen.w > 640;
    strip_init();
    data_generate(1966);
    sort(K_CODE, 0);
    rec_fields();
    list_open();
    if (xga) {
        chart_toggle();
        open_record(view[0]);
        wm_raise(list_win);
    }
    op_end();
    perf_value("startup_app", video_ticks() - t0);
    if (bench) {
        run_bench();
        redraw_all();
    }
    while (!wm.quit) {
        wm_frame();
        op_frame();
    }
    perf_frames("frame_work");
    op_report();
    printf("@done\n");
    return 0;
}
