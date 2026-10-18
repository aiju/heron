/* A schematic editor on the window manager: a canvas window over a sheet
   with a grid, and a parts window with the tools and the symbols
   (resistor, capacitor, NAND, NOR, inverter, a DIP-14 package, connector,
   LED, ground, supply).

   Select (Esc): a click selects a part or a wire, a drag on a part moves
   the selection with the wires on its pins following (rubber-banded, made
   orthogonal again when it's dropped), a drag elsewhere selects with a
   rectangle. Wire (W): a drag draws a wire, across then down. Net (N): a
   click on a wire lights up its whole net. A part from the parts window
   follows the mouse until a click places it. R rotates, Del deletes, the
   arrows and a drag with the right button pan, - and = zoom.

   The measurement switches: B the overlay's drawing (XOR into the store,
   XOR on the screen, redrawn), V the parts as lines or sprites, G the
   grid, C the placing ghost as the hardware cursor or in XOR. The mode
   and the window manager's options come from pokes (sch_mode, sch_opts);
   bench runs bench.c's measurements instead of the editor. */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "sch.h"
#include "video.h"
#include "perf.h"

int sch_mode = 5, sch_opts = WM_SNAP, band_mode = 0, bench = 0, start_zoom = 0;
int cursor_ghost = 1;           /* the placing ghost as the hardware cursor when it fits */
int ghost_blit;                 /* the moving ghost as one image copied in XOR (V.ghost_blit) */

static Window *canvas, *pal;
Window *sch_canvas;

static int tool = TOOL_SELECT, place_type, place_rot;
static const char *const tool_names[] = {"select", "wire", "net", "place"};

enum { DR_NONE, DR_MOVE, DR_RECT, DR_WIRE, DR_PAN };
static int drag, moving, press_x, press_y, press_ux, press_uy, move_dx, move_dy;
static int buttons_was;

/* the hardware cursor's images: a crosshair, and a part's ghost */
static unsigned *cur_cross, *cur_ghost;
static int ghost_ok, ghost_ox, ghost_oy, ghost_shown, ghost_type = -1, ghost_rot;
static int hover_ux = -9999, hover_uy = -9999;
static char net_text[200];

unsigned ticks_now(void)
{
    return video_ticks();
}

/* ---- the cursor ---- */

static void cpix(unsigned *img, int x, int y, unsigned c)
{
    unsigned *w = &img[2 * y + (x >> 4)];
    int sh = 2 * (x & 15);
    *w = (*w & ~(3u << sh)) | c << sh;
}

static unsigned cget(const unsigned *img, int x, int y)
{
    if (x < 0 || y < 0 || x > 31 || y > 31)
        return 0;
    return img[2 * y + (x >> 4)] >> (2 * (x & 15)) & 3;
}

/* a white edge round the colour-1 pixels, so the cursor shows on black */
static void outline(unsigned *img)
{
    int x, y;
    for (y = 0; y < 32; y++)
        for (x = 0; x < 32; x++)
            if (!cget(img, x, y) && (cget(img, x - 1, y) == 1 || cget(img, x + 1, y) == 1 ||
                                     cget(img, x, y - 1) == 1 || cget(img, x, y + 1) == 1))
                cpix(img, x, y, 2);
}

static void cursors(void)
{
    int k;
    cur_cross = vram_alloc(32 * 8);
    cur_ghost = vram_alloc(32 * 8);
    memset(cur_cross, 0, 32 * 8);
    for (k = 0; k < 31; k++)
        if (k < 13 || k > 17) {
            cpix(cur_cross, k, 15, 1);
            cpix(cur_cross, 15, k, 1);
        }
    outline(cur_cross);
}

/* the ghost of a part as the cursor, if its sprite fits in 32 x 32 */
static int ghost_cursor(int type, int rot)
{
    const Sprite *sp = sym_sprite(type, rot, V.zoom);
    int x, y;
    if (!cursor_ghost || sp->w > 32 || sp->h > 32)
        return 0;
    memset(cur_ghost, 0, 32 * 8);
    for (y = 0; y < sp->h; y++)
        for (x = 0; x < sp->w; x++)
            if (sp->bits[y * sp->pitch + (x >> 5)] >> (x & 31) & 1)
                cpix(cur_ghost, x, y, 3);
    ghost_ox = sp->ox;
    ghost_oy = sp->oy;
    return 1;
}

/* ---- the selection ---- */

static void select_none(void)
{
    int i;
    for (i = 0; i < sh.nparts; i++)
        if (sh.parts[i].sel) {
            sh.parts[i].sel = 0;
            view_part(&sh.parts[i]);
        }
    for (i = 0; i < sh.nwires; i++)
        if (sh.wires[i].sel) {
            sh.wires[i].sel = 0;
            view_wire(&sh.wires[i]);
        }
}

static void counts(void)
{
    status("%d parts, %d wires, %d dots | zoom %d | %s | redraw %d.%d ms", sh.nparts,
           sh.nwires, sh.njunc, V.zoom, tool_names[tool], V.last_redraw / 50350,
           V.last_redraw / 5035 % 10);
}

/* the next free reference with the symbol's prefix */
static void next_ref(int type, char *buf)
{
    const char *pre = symbols[type].prefix;
    int i, n = 0, l = strlen(pre);
    for (i = 0; i < sh.nparts; i++)
        if (!strncmp(sh.parts[i].ref, pre, l)) {
            int v = atoi(sh.parts[i].ref + l);
            if (v > n)
                n = v;
        }
    sprintf(buf, "%s%d", pre, n + 1);
}

/* redraw the union of rectangles collected */
static Rect acc;
static int acc_n;

static void acc_add(const Rect *r)
{
    if (!acc_n++) {
        acc = *r;
        return;
    }
    if (r->x0 < acc.x0) acc.x0 = r->x0;
    if (r->y0 < acc.y0) acc.y0 = r->y0;
    if (r->x1 > acc.x1) acc.x1 = r->x1;
    if (r->y1 > acc.y1) acc.y1 = r->y1;
}

static void acc_flush(void)
{
    if (acc_n)
        view_region(acc.x0 - 4, acc.y0 - 4, acc.x1 + 4, acc.y1 + 4);
    acc_n = 0;
}

static void rotate_selection(void)
{
    int i;
    Rect r;
    for (i = 0; i < sh.nparts; i++) {
        Part *p = &sh.parts[i];
        if (!p->sel)
            continue;
        part_rect(p, &r);
        acc_add(&r);
        p->rot = (p->rot + 1) & 3;
        p->lgen = 0;
        part_rect(p, &r);
        acc_add(&r);
    }
    junctions();
    acc_flush();
}

static void delete_selection(void)
{
    int i;
    Rect r;
    for (i = sh.nparts - 1; i >= 0; i--)
        if (sh.parts[i].sel) {
            part_rect(&sh.parts[i], &r);
            acc_add(&r);
            part_delete(i);
        }
    for (i = sh.nwires - 1; i >= 0; i--)
        if (sh.wires[i].sel) {
            wire_rect(&sh.wires[i], &r);
            acc_add(&r);
            wire_delete(i);
        }
    junctions();
    acc_flush();
}

/* ---- moving the selection: the parts' pins drag the wires on them ---- */

static unsigned char wire_ends[MAXWIRES];   /* which ends move: 1 the first, 2 the second */

static int pin_moving(int x, int y)
{
    int i, k, n, px, py;
    for (i = 0; i < sh.nparts; i++) {
        const Part *p = &sh.parts[i];
        if (!p->sel)
            continue;
        n = part_pins(p);
        for (k = 0; k < n; k++) {
            part_pin(p, k, &px, &py);
            if (px == x && py == y)
                return 1;
        }
    }
    return 0;
}

static void move_begin(void)
{
    int i;
    Rect r;
    for (i = 0; i < sh.nwires; i++) {
        Wire *w = &sh.wires[i];
        int e = w->sel ? 3 : pin_moving(w->x0, w->y0) | pin_moving(w->x1, w->y1) << 1;
        wire_ends[i] = e;
        /* a wire that moves whole is in the ghost; one that stretches is a band */
        w->hide = e == 3 ? 1 : e ? 2 : 0;
        if (e) {
            wire_rect(w, &r);
            acc_add(&r);
        }
    }
    for (i = 0; i < sh.nparts; i++)
        if (sh.parts[i].sel) {
            sh.parts[i].hide = 1;
            part_rect(&sh.parts[i], &r);
            acc_add(&r);
        }
    acc_flush();
    ghost_make(&r);
    moving = 1;
    move_dx = move_dy = 0x7FFF;
}

static void move_update(int dx, int dy)
{
    static OvItem it[MAXOV];
    int i, n = 0, X = ZS(dx), Y = ZS(dy);
    if (dx == move_dx && dy == move_dy)
        return;
    move_dx = dx;
    move_dy = dy;
    it[n].kind = OV_GHOST;
    it[n].x0 = V.ghost_x + X;
    it[n].y0 = V.ghost_y + Y;
    n++;
    for (i = 0; i < sh.nwires && n < MAXOV - 2; i++) {
        Wire *w = &sh.wires[i];
        int fx, fy, mx, my;
        if (w->hide != 2)
            continue;
        /* the fixed end, and the moving one where it is now */
        if (wire_ends[i] == 1) {
            fx = w->x1; fy = w->y1; mx = w->x0; my = w->y0;
        } else {
            fx = w->x0; fy = w->y0; mx = w->x1; my = w->y1;
        }
        n += ov_ell(it + n, PX(fx), PY(fy), PX(mx) + X, PY(my) + Y, w->x0 == w->x1);
    }
    ov_set(it, n);
}

static void move_end(int dx, int dy)
{
    int i, nw = sh.nwires;
    Rect r;
    ov_clear();
    ghost_free();
    moving = 0;
    for (i = 0; i < sh.nparts; i++) {
        Part *p = &sh.parts[i];
        if (!p->hide)
            continue;
        p->x += dx;
        p->y += dy;
        p->hide = 0;
        part_rect(p, &r);
        acc_add(&r);
    }
    for (i = 0; i < nw; i++) {
        Wire *w = &sh.wires[i];
        if (w->hide == 1) {
            w->x0 += dx; w->x1 += dx; w->y0 += dy; w->y1 += dy;
        } else if (w->hide == 2) {
            /* the stretched wire made orthogonal: along its old direction
               from the fixed end, then to the pin */
            int fx, fy, mx, my, down = w->x0 == w->x1, cx, cy;
            if (wire_ends[i] == 1) {
                fx = w->x1; fy = w->y1; mx = w->x0 + dx; my = w->y0 + dy;
            } else {
                fx = w->x0; fy = w->y0; mx = w->x1 + dx; my = w->y1 + dy;
            }
            cx = down ? fx : mx;
            cy = down ? my : fy;
            if (fx == cx && fy == cy) {
                cx = mx;
                cy = my;
            }
            w->x0 = fx < cx ? fx : cx; w->x1 = fx < cx ? cx : fx;
            w->y0 = fy < cy ? fy : cy; w->y1 = fy < cy ? cy : fy;
            if (cx != mx || cy != my)
                wire_add(cx, cy, mx, my);
        }
        w->hide = 0;
    }
    for (i = 0; i < sh.nwires; i++)
        if (i >= nw || wire_ends[i]) {
            wire_rect(&sh.wires[i], &r);
            acc_add(&r);
        }
    junctions();
    acc_flush();
}

/* ---- the canvas's input ---- */

static void press(int x, int y, int mods)
{
    int ux = view_ux(x), uy = view_uy(y), sx = snap(ux), sy = snap(uy), i;
    char ref[8];
    if (y >= V.h)
        return;
    switch (tool) {
    case TOOL_PLACE: {
        Part *p;
        ov_clear();
        next_ref(place_type, ref);
        p = part_add(place_type, sx, sy, place_rot, ref, 0);
        if (p) {
            junctions();
            view_part(p);
            status("placed %s at %d, %d", p->ref, sx / GRID, sy / GRID);
        }
        ghost_shown = 0;
        break;
    }
    case TOOL_WIRE:
        drag = DR_WIRE;
        press_ux = sx;
        press_uy = sy;
        break;
    case TOOL_NET: {
        unsigned t0 = ticks_now();
        int n = net_highlight(sx, sy, net_text, sizeof net_text);
        unsigned t1 = ticks_now();
        view_redraw();
        printf("@perf net_find %u\n", t1 - t0);
        printf("@perf net_redraw %u\n", V.last_redraw);
        status("%s", n ? net_text : "no net there");
        break;
    }
    default:
        i = hit_part(ux, uy);
        if (i >= 0) {
            if (!sh.parts[i].sel) {
                if (!(mods & M_SHIFT))
                    select_none();
                sh.parts[i].sel = 1;
                view_part(&sh.parts[i]);
            }
            drag = DR_MOVE;
            moving = 0;
            press_ux = sx;
            press_uy = sy;
            status("%s %s", sh.parts[i].ref, sh.parts[i].val);
        } else if ((i = hit_wire(ux, uy, 1)) >= 0) {
            if (!(mods & M_SHIFT))
                select_none();
            sh.wires[i].sel = 1;
            view_wire(&sh.wires[i]);
            status("wire %d,%d - %d,%d", sh.wires[i].x0 / GRID, sh.wires[i].y0 / GRID,
                   sh.wires[i].x1 / GRID, sh.wires[i].y1 / GRID);
        } else {
            if (!(mods & M_SHIFT))
                select_none();
            drag = DR_RECT;
            press_x = x;
            press_y = y;
        }
        break;
    }
}

static void motion(int x, int y)
{
    OvItem it[4];
    int n;
    switch (drag) {
    case DR_PAN:
        view_pan(press_x - x, press_y - y);
        press_x = x;
        press_y = y;
        break;
    case DR_WIRE:
        n = ov_ell(it, PX(press_ux), PY(press_uy), PX(snap(view_ux(x))), PY(snap(view_uy(y))),
                   0);
        ov_set(it, n);
        break;
    case DR_RECT:
        it[0].kind = OV_FRAME;
        it[0].x0 = press_x < x ? press_x : x;
        it[0].x1 = press_x < x ? x : press_x;
        it[0].y0 = press_y < y ? press_y : y;
        it[0].y1 = press_y < y ? y : press_y;
        ov_set(it, 1);
        break;
    case DR_MOVE: {
        int dx = snap(view_ux(x)) - press_ux, dy = snap(view_uy(y)) - press_uy;
        if (!moving && (dx || dy))
            move_begin();
        if (moving)
            move_update(dx, dy);
        break;
    }
    }
}

static void release(int x, int y)
{
    int i;
    Rect r;
    switch (drag) {
    case DR_WIRE: {
        int ex = snap(view_ux(x)), ey = snap(view_uy(y));
        Wire *a, *b;
        ov_clear();
        /* across, then down */
        a = wire_add(press_ux, press_uy, ex, press_uy);
        b = wire_add(ex, press_uy, ex, ey);
        junctions();
        if (a) {
            wire_rect(a, &r);
            acc_add(&r);
        }
        if (b) {
            wire_rect(b, &r);
            acc_add(&r);
        }
        acc_flush();
        counts();
        break;
    }
    case DR_RECT: {
        int x0 = view_ux(press_x < x ? press_x : x), x1 = view_ux(press_x < x ? x : press_x);
        int y0 = view_uy(press_y < y ? press_y : y), y1 = view_uy(press_y < y ? y : press_y);
        int n = 0;
        ov_clear();
        for (i = 0; i < sh.nparts; i++) {
            Part *p = &sh.parts[i];
            int a, b, c, d;
            part_box(p, &a, &b, &c, &d);
            if (a >= x0 && c <= x1 && b >= y0 && d <= y1 && !p->sel) {
                p->sel = 1;
                part_rect(p, &r);
                acc_add(&r);
                n++;
            }
        }
        for (i = 0; i < sh.nwires; i++) {
            Wire *w = &sh.wires[i];
            if (w->x0 >= x0 && w->x1 <= x1 && w->y0 >= y0 && w->y1 <= y1 && !w->sel) {
                w->sel = 1;
                wire_rect(w, &r);
                acc_add(&r);
                n++;
            }
        }
        acc_flush();
        status("%d selected", n);
        break;
    }
    case DR_MOVE:
        if (moving) {
            move_end(snap(view_ux(x)) - press_ux, snap(view_uy(y)) - press_uy);
            counts();
        }
        break;
    }
    drag = DR_NONE;
}

static void canvas_mouse(Window *w, const Event *e, int x, int y)
{
    int pressed = e->buttons & ~buttons_was, released = buttons_was & ~e->buttons;
    (void)w;
    buttons_was = e->buttons;
    if (pressed & 2) {
        drag = DR_PAN;
        press_x = x;
        press_y = y;
        return;
    }
    if (pressed & 1) {
        press(x, y, e->mods);
        return;
    }
    if (drag != DR_NONE)
        motion(x, y);
    if (released)
        release(x, y);
}

/* ---- tools and keys ---- */

static void pal_draw(void);

static void set_tool(int t)
{
    if (drag != DR_NONE)
        return;
    if (tool == TOOL_PLACE)
        ov_clear();
    tool = t;
    ghost_shown = 0;
    ghost_type = -1;
    pal_draw();
    counts();
}

void sch_key(Window *w, const Event *e)
{
    int step = ZS(4 * GRID);
    (void)w;
    if (e->type != EV_KEY)
        return;
    switch (e->key) {
    case K_ESC:
        if (tool == TOOL_NET) {
            net_clear();
            view_redraw();
        }
        set_tool(TOOL_SELECT);
        break;
    case 'w': set_tool(TOOL_WIRE); break;
    case 'n': set_tool(TOOL_NET); break;
    case 's': set_tool(TOOL_SELECT); break;
    case 'r':
        if (tool == TOOL_PLACE) {
            place_rot = (place_rot + 1) & 3;
            ghost_type = -1;
        } else {
            rotate_selection();
        }
        break;
    case K_DEL:
    case K_BACKSPACE:
        delete_selection();
        counts();
        break;
    case K_LEFT: view_pan(-step, 0); break;
    case K_RIGHT: view_pan(step, 0); break;
    case K_UP: view_pan(0, -step); break;
    case K_DOWN: view_pan(0, step); break;
    case '-':
        view_zoom(V.zoom - 1, V.w / 2, V.h / 2);
        ghost_type = -1;
        counts();
        break;
    case '=':
        view_zoom(V.zoom + 1, V.w / 2, V.h / 2);
        ghost_type = -1;
        counts();
        break;
    case 'b':
        V.band = (V.band + 1) % 3;
        status("overlay: %s", V.band == BAND_STORE ? "XOR in the store"
                              : V.band == BAND_SCREEN ? "XOR on the screen" : "redrawn");
        break;
    case 'v':
        V.vector ^= 1;
        view_redraw();
        counts();
        break;
    case 'g':
        V.grid_on ^= 1;
        view_redraw();
        counts();
        break;
    case 'c':
        cursor_ghost ^= 1;
        ghost_type = -1;
        break;
    case 'f':
        if (drag == DR_NONE && !V.sheet) {
            if (tool == TOOL_PLACE)
                set_tool(TOOL_SELECT);
            sheet_view();
            counts();
        }
        break;
    }
}

/* every frame: the cursor's shape, the placing ghost, the overlay's
   return, the status line */
static void canvas_tick(Window *w)
{
    int mx = mouse_x - w->c.x0, my = mouse_y - w->c.y0, inside;
    Window *o;
    inside = mx >= 0 && my >= 0 && mx < V.w && my < V.h;
    for (o = w->above; o && inside; o = o->above)
        if (mouse_x >= o->r.x0 && mouse_x < o->r.x1 && mouse_y >= o->r.y0 && mouse_y < o->r.y1)
            inside = 0;
    if (inside) {
        int ux = snap(view_ux(mx)), uy = snap(view_uy(my));
        if (tool == TOOL_PLACE) {
            int X = PX(ux), Y = PY(uy);
            if (ghost_type != place_type || ghost_rot != place_rot) {
                ov_clear();
                ghost_type = place_type;
                ghost_rot = place_rot;
                ghost_ok = ghost_cursor(place_type, place_rot);
                if (!ghost_ok) {
                    const Sprite *sp = sym_sprite(place_type, place_rot, V.zoom);
                    ghost_ox = sp->ox;
                    ghost_oy = sp->oy;
                }
                ghost_shown = 0;
            }
            if (ghost_ok) {
                /* the hotspot moved so the ghost sits on the grid point */
                wm_cursor(cur_ghost, mouse_x - (w->c.x0 + X - ghost_ox),
                          mouse_y - (w->c.y0 + Y - ghost_oy));
            } else {
                wm_cursor(cur_cross, 15, 15);
                if (!ghost_shown || ux != hover_ux || uy != hover_uy) {
                    OvItem it;
                    it.kind = OV_SPRITE;
                    it.x0 = X - ghost_ox;
                    it.y0 = Y - ghost_oy;
                    it.x1 = place_type;
                    it.y1 = place_rot;
                    ov_set(&it, 1);
                    ghost_shown = 1;
                }
            }
        } else {
            wm_cursor(tool == TOOL_SELECT ? 0 : cur_cross, tool == TOOL_SELECT ? 0 : 15,
                      tool == TOOL_SELECT ? 0 : 15);
        }
        if ((ux != hover_ux || uy != hover_uy) && (drag != DR_NONE || tool == TOOL_PLACE))
            status("%s  x %d  y %d", tool_names[tool], ux / GRID, uy / GRID);
        hover_ux = ux;
        hover_uy = uy;
    } else {
        wm_cursor(0, 0, 0);
        if (tool == TOOL_PLACE && ghost_shown && !ghost_ok) {
            ov_clear();
            ghost_shown = 0;
        }
    }
    ov_tick();
    status_draw();
}

/* ---- the parts window ---- */

static Sprite icons[T_N];
static int pal_w, cell_w;
#define CELL_H 52
#define TOOLS_H 52

static const char *const buttons[6] = {"Select", "Wire", "Net", "-", "+", "Grid"};
/* in the narrower window at 640 pixels */
static const char *const short_names[T_N] = {"Res", "Cap", "NAND", "NOR", "Inv", "DIP-14",
                                             "Conn", "LED", "GND", "Supply"};

static void pal_draw(void)
{
    Surface *s = &pal->s;
    int k, bw = (pal_w - 8) / 3;
    ui_panel(s, 0, 0, s->w, s->h, 0);
    for (k = 0; k < 6; k++) {
        int x = 4 + (k % 3) * bw, y = 4 + (k / 3) * 24;
        ui_button(s, x, y, x + bw - 2, y + 22, k == 0 && cell_w < 60 ? "Sel" : buttons[k],
                  (k < 3 && tool == k) || (k == 5 && V.grid_on));
    }
    for (k = 0; k < T_N; k++) {
        int x = 2 + (k % 2) * cell_w, y = TOOLS_H + 4 + (k / 2) * CELL_H;
        const Sprite *sp = &icons[k];
        Bitmap bm;
        int on = tool == TOOL_PLACE && place_type == k;
        gfx_fill(s, x + 1, y + 1, x + cell_w - 1, y + CELL_H - 1, on ? th.sel_bg : th.bg,
                 ROP_COPY);
        gfx_frame(s, x, y, x + cell_w, y + CELL_H, 1, th.dark, ROP_COPY);
        bm.bits = sp->bits;
        bm.pitch = sp->pitch;
        gfx_expand(s, x + (cell_w - sp->w) / 2, y + 2 + (34 - sp->h) / 2, &bm, 0, 0, sp->w,
                   sp->h, on ? th.sel_fg : th.text, 0, 0);
        const char *name = cell_w < 60 ? short_names[k] : symbols[k].name;
        text_draw(s, x + (cell_w - text_width(name, 1)) / 2, y + 36, name, 1,
                  on ? th.sel_fg : th.text);
    }
    wm_damage(pal, 0, 0, s->w, s->h);
}

static void pal_mouse(Window *w, const Event *e, int x, int y)
{
    static int was;
    int pressed = e->buttons & ~was & 1, k, bw = (pal_w - 8) / 3;
    (void)w;
    was = e->buttons;
    if (!pressed)
        return;
    if (y < TOOLS_H) {
        k = (x - 4) / bw + 3 * ((y - 4) / 24);
        if (k == 0 || k == 1 || k == 2)
            set_tool(k);
        else if (k == 3 || k == 4) {
            view_zoom(V.zoom + (k == 3 ? -1 : 1), V.w / 2, V.h / 2);
            ghost_type = -1;
            counts();
        } else if (k == 5) {
            V.grid_on ^= 1;
            view_redraw();
            pal_draw();
        }
        return;
    }
    k = (x - 2) / cell_w + 2 * ((y - TOOLS_H - 4) / CELL_H);
    if (k >= 0 && k < T_N && x >= 2 && x < 2 + 2 * cell_w) {
        set_tool(TOOL_PLACE);
        place_type = k;
        place_rot = 0;
        ghost_type = -1;
        pal_draw();
        status("place a %s: click on the sheet, R rotates, Esc stops", symbols[k].name);
    }
}

/* ---- for bench.c and the sheet view ---- */

void sch_canvas_event(const Event *e, int x, int y)
{
    canvas_mouse(canvas, e, x, y);
}

const unsigned *sch_cursor(int *hx, int *hy)
{
    *hx = *hy = tool == TOOL_SELECT ? 0 : 15;
    return tool == TOOL_SELECT ? 0 : cur_cross;
}

void sch_tool(int t, int type)
{
    set_tool(t);
    place_type = type;
    place_rot = 0;
}

void sch_mouse(int buttons, int x, int y)
{
    Event e;
    memset(&e, 0, sizeof e);
    e.type = EV_MOUSE;
    e.buttons = buttons;
    e.x = x + canvas->c.x0;
    e.y = y + canvas->c.y0;
    canvas_mouse(canvas, &e, x, y);
}

/* ---- set-up ---- */

static void icons_make(void)
{
    int k;
    for (k = 0; k < T_N; k++) {
        /* at 2 if it fits the cell, else 1 */
        sprite_make(&icons[k], k, 0, 2);
        if (icons[k].w > cell_w - 4 || icons[k].h > 34) {
            free(icons[k].bits);
            sprite_make(&icons[k], k, 0, 1);
        }
    }
}

int main(void)
{
    int big = 0, cx, cy, cw, ch;
    wm_init(sch_mode, sch_opts);
    symbols_init();
    big = vid.w >= 1024;
    pal_w = big ? 124 : 104;
    cell_w = (pal_w - 4) / 2;
    pal = wm_open(4, 22, pal_w, TOOLS_H + 8 + CELL_H * 5, "Parts", WF_TITLE | WF_FIXED);
    pal->mouse = pal_mouse;
    pal->key = sch_key;
    /* the canvas's content on a 32-pixel boundary: a word in every mode, so
       the compositor's copies are never shifted */
    cx = big ? 160 : 128;
    cy = 22;
    cw = vid.w - cx - 4;
    ch = vid.h - cy - 3;
    canvas = wm_open(cx, cy, cw, ch, "Schematic: blinker.sch", WF_TITLE | WF_FIXED);
    canvas->mouse = canvas_mouse;
    canvas->key = sch_key;
    canvas->tick = canvas_tick;
    sch_canvas = canvas;
    view_init(canvas, start_zoom ? start_zoom : big ? 3 : 2);
    V.band = band_mode;
    V.ghost_blit = ghost_blit;
    cursors();
    icons_make();
    pal_draw();
    example(0, 0, 1);
    junctions();
    if (bench) {
        bench_run();
        printf("@done\n");
        return 0;
    }
    view_redraw();
    counts();
    perf_value("first_redraw", V.last_redraw);
    perf_value("sprites", sprite_ticks);
    wm_run();
    perf_frames("frame_work");
    printf("@done\n");
    return 0;
}
