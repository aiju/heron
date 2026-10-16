/* wsys: the window system. It owns the video card, the keyboard and the
 * mouse, keeps the windows (gwm.c) and draws for its programs through the
 * graphics study's library, as fen/wsys.h describes.
 *
 * One thread and one loop: requests from programs, and notifications from
 * the PS/2 ports' interrupt and from processes ending. The mouse moves a
 * software cursor (the video card has none; RFC 0016, 9.3), which is taken
 * off while anything draws and put back when the loop has nothing more to
 * do. Dragging a title bar moves a window, its bottom right corner sizes
 * it, its box closes it (the program decides), and a click on the desktop
 * opens a menu of programs to start (/etc/menu). */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <fen/sys.h>
#include <fen/spawn.h>
#include <fen/srv.h>
#include <fen/wsys.h>
#include "wsys.h"
#include "theme.h"

#define DEPTH 3                 /* 8 bits per pixel */
#define PS2_BIT 1

Font fonts[MAXFONTS];
extern const unsigned char font_sans12[], font_mono12[];

static int port;

/* ---- programs and their events ---- */

#define MAXCLIENTS 32
#define QLEN 64

struct client {
    int pid;                    /* 0: a free slot */
    int port;
    unsigned bits;
    struct ws_event q[QLEN];
    int head, n;
    int notified;
};

static struct client clients[MAXCLIENTS];
static int owner[MAXWIN + 1];   /* window -> client index + 1 */

static struct client *client_of(int pid, int make)
{
    int i, free = -1;
    for (i = 0; i < MAXCLIENTS; i++) {
        if (clients[i].pid == pid)
            return &clients[i];
        if (!clients[i].pid && free < 0)
            free = i;
    }
    if (!make || free < 0)
        return 0;
    memset(&clients[free], 0, sizeof clients[free]);
    clients[free].pid = pid;
    return &clients[free];
}

static void post(struct client *c, int type, int win, int a, int b, int cc, int d)
{
    struct ws_event *e;
    if (!c)
        return;
    /* a mouse move replaces one not taken yet */
    if (type == EV_MOUSE && d == MOUSE_MOVE && c->n) {
        e = &c->q[(c->head + c->n - 1) % QLEN];
        if (e->type == EV_MOUSE && e->d == MOUSE_MOVE && e->win == win) {
            e->a = a;
            e->b = b;
            e->c = cc;
            return;
        }
    }
    if (c->n == QLEN) {
        c->head = (c->head + 1) % QLEN;
        c->n--;
    }
    e = &c->q[(c->head + c->n) % QLEN];
    e->type = type;
    e->win = win;
    e->a = a;
    e->b = b;
    e->c = cc;
    e->d = d;
    c->n++;
}

static struct client *win_client(int win)
{
    if (win <= 0 || win > MAXWIN || !owner[win])
        return 0;
    return &clients[owner[win] - 1];
}

/* the updates gwm has, as exposes to the windows' programs */
static void send_updates(void)
{
    Rect r;
    int id;
    while ((id = gwm_next_update(&r)) != 0)
        post(win_client(id), EV_EXPOSE, id, r.x0, r.y0, r.x1, r.y1);
}

static void notify_clients(void)
{
    int i;
    for (i = 0; i < MAXCLIENTS; i++) {
        struct client *c = &clients[i];
        if (c->pid && c->n && !c->notified && c->port) {
            notify(c->port, c->bits);
            c->notified = 1;
        }
    }
}

/* ---- the cursor ---- */

static int mx = SCREEN_W / 2, my = SCREEN_H / 2, buttons;
static int cursor_on;
static unsigned char under[CURSOR_W * CURSOR_H];
static Surface under_s;

void cursor_off(void)
{
    if (!cursor_on)
        return;
    gfx_noclip(&screen);
    gfx_blit(&screen, mx, my, &under_s, 0, 0, CURSOR_W, CURSOR_H, GFX_COPY);
    cursor_on = 0;
}

static void cursor_show(void)
{
    if (cursor_on)
        return;
    gfx_noclip(&screen);
    gfx_blit(&under_s, 0, 0, &screen, mx, my, CURSOR_W, CURSOR_H, GFX_COPY);
    gfx_expand(&screen, mx, my, &cursor_mask, 0, 0, CURSOR_W, CURSOR_H, c_black, 0, 0);
    gfx_expand(&screen, mx, my, &cursor_image, 0, 0, CURSOR_W, CURSOR_H, c_white, 0, 0);
    cursor_on = 1;
}

/* ---- colours ---- */

static unsigned cache_rgb[16], cache_px[16];
static int cache_next;

static unsigned colour(unsigned c)
{
    int i;
    if (c & WS_PIXEL)
        return c & 0xFF;
    for (i = 0; i < 16; i++)
        if (cache_rgb[i] == c + 1)
            return cache_px[i];
    i = cache_next++ & 15;
    cache_rgb[i] = c + 1;
    cache_px[i] = theme_nearest(DEPTH, (c >> 16) & 0xFF, (c >> 8) & 0xFF, c & 0xFF);
    return cache_px[i];
}

/* ---- drawing ---- */

static unsigned cmds[4096];

static void clip_to(const Rect *r, const Rect *user, int ox, int oy, int has_user)
{
    Rect c = *r;
    if (has_user) {
        Rect u;
        u.x0 = user->x0 + ox;
        u.y0 = user->y0 + oy;
        u.x1 = user->x1 + ox;
        u.y1 = user->y1 + oy;
        if (u.x0 > c.x0) c.x0 = u.x0;
        if (u.y0 > c.y0) c.y0 = u.y0;
        if (u.x1 < c.x1) c.x1 = u.x1;
        if (u.y1 < c.y1) c.y1 = u.y1;
        if (c.x1 < c.x0) c.x1 = c.x0;
        if (c.y1 < c.y0) c.y1 = c.y0;
    }
    gfx_clip_rect(&screen, &c);
}

static void draw_text(Font *f, int x, int y, const char *s, int n, unsigned fg)
{
    char buf[256];
    if (n > 255)
        n = 255;
    memcpy(buf, s, n);
    buf[n] = 0;
    font_draw(&screen, f, x, y, buf, fg, 0);
}

/* One command, through every visible rectangle of the window. */
static void draw_cmd(int win, unsigned *a, int len, Rect *user, int *has_user)
{
    int op = a[0] >> 24, i, n, ox, oy;
    Rect *clips;
    n = gwm_clips(win, &clips, &ox, &oy);
    switch (op) {
    case D_CLIP:
        if (len >= 5) {
            user->x0 = a[1];
            user->y0 = a[2];
            user->x1 = a[3];
            user->y1 = a[4];
            *has_user = 1;
        }
        return;
    case D_NOCLIP:
        *has_user = 0;
        return;
    case D_SCROLL:
        if (len >= 6)
            gwm_scroll(win, a[1], a[2], a[3], a[4], a[5]);
        return;
    }
    if (n)
        cursor_off();
    for (i = 0; i < n; i++) {
        clip_to(&clips[i], user, ox, oy, *has_user);
        switch (op) {
        case D_FILL:
            if (len >= 6)
                gfx_fill(&screen, a[2] + ox, a[3] + oy, a[4] + ox, a[5] + oy, colour(a[1]),
                         GFX_COPY);
            break;
        case D_FRAME:
            if (len >= 7)
                gfx_frame(&screen, a[2] + ox, a[3] + oy, a[4] + ox, a[5] + oy, a[6], colour(a[1]),
                          GFX_COPY);
            break;
        case D_LINE:
            if (len >= 6)
                gfx_line(&screen, a[2] + ox, a[3] + oy, a[4] + ox, a[5] + oy, colour(a[1]),
                         GFX_COPY);
            break;
        case D_TEXT:
            if (len >= 6 && a[2] < MAXFONTS && (int)((a[5] + 3) / 4) <= len - 6)
                draw_text(&fonts[a[2]], a[3] + ox, a[4] + oy, (char *)&a[6], a[5], colour(a[1]));
            break;
        case D_TEXTBG:
            if (len >= 7 && a[3] < MAXFONTS && (int)((a[6] + 3) / 4) <= len - 7) {
                Font *f = &fonts[a[3]];
                int w = font_width(f, "M") * a[6];
                int x = a[4] + ox, y = a[5] + oy;
                /* text as cells: a mono font's whole cells */
                char buf[256];
                int k = a[6] > 255 ? 255 : a[6];
                memcpy(buf, &a[7], k);
                buf[k] = 0;
                w = font_width(f, buf);
                gfx_fill(&screen, x, y - f->ascent, x + w, y + f->descent, colour(a[2]), GFX_COPY);
                font_draw(&screen, f, x, y, buf, colour(a[1]), 0);
            }
            break;
        case D_ELLIPSE:
            if (len >= 7) {
                if (a[6])
                    gfx_fill_ellipse(&screen, a[2] + ox, a[3] + oy, a[4], a[5], colour(a[1]),
                                     GFX_COPY);
                else
                    gfx_ellipse(&screen, a[2] + ox, a[3] + oy, a[4], a[5], colour(a[1]), GFX_COPY);
            }
            break;
        case D_PIXELS:
            if (len >= 5) {
                int w = a[3], h = a[4], pitch = (w + 3) & ~3;
                Surface src;
                if (w > 0 && h > 0 && pitch * h <= (len - 5) * 4) {
                    gfx_init(&src, &a[5], w, h, pitch, DEPTH);
                    gfx_blit(&screen, a[1] + ox, a[2] + oy, &src, 0, 0, w, h, GFX_COPY);
                }
            }
            break;
        case D_POLY:
            if (len >= 3 && (int)a[2] * 2 <= len - 3 && a[2] <= 64) {
                int xy[128], k;
                for (k = 0; k < (int)a[2]; k++) {
                    xy[2 * k] = a[3 + 2 * k] + ox;
                    xy[2 * k + 1] = a[4 + 2 * k] + oy;
                }
                gfx_poly(&screen, xy, a[2], colour(a[1]), GFX_COPY, GFX_NONZERO);
            }
            break;
        }
    }
    gfx_noclip(&screen);
}

static int do_draw(int rcvid, msg_t *m)
{
    int win = m->w[1], words = m->w[3], at = 0, has_user = 0;
    Rect user;
    if (!gwm_exists(win))
        return -EBADF;
    if (words > (int)(sizeof cmds / 4))
        words = sizeof cmds / 4;
    if (ipc_read(rcvid, (void *)m->w[2], cmds, words * 4) < 0)
        return -EFAULT;
    while (at < words) {
        int len = cmds[at] & 0xFFFF;
        if (len <= 0 || at + len > words)
            break;
        draw_cmd(win, &cmds[at], len, &user, &has_user);
        at += len;
    }
    return 0;
}

/* ---- windows ---- */

static int cascade;

static int do_open(int rcvid, int pid, msg_t *m)
{
    char title[64];
    struct client *c = client_of(pid, 1);
    int x = m->w[1], y = m->w[2], w = m->w[3], h = m->w[4], n = m->w[6], id;
    unsigned bg;
    if (!c)
        return -ENOMEM;
    if (n > 63)
        n = 63;
    if (ipc_read(rcvid, (void *)m->w[5], title, n) < 0)
        n = 0;
    title[n] = 0;
    w += 2;
    h += TITLE_H + 3;
    if (w > SCREEN_W)
        w = SCREEN_W;
    if (h > SCREEN_H)
        h = SCREEN_H;
    if (x < 0 || y < 0) {
        x = 24 + 24 * (cascade % 8);
        y = 24 + 20 * (cascade % 8);
        cascade++;
    }
    if (x + w > SCREEN_W)
        x = SCREEN_W - w;
    if (y + h > SCREEN_H)
        y = SCREEN_H - h;
    bg = colour(m->w[7]);
    cursor_off();
    id = gwm_open(x, y, x + w, y + h, title, bg);
    if (!id)
        return -ENFILE;
    owner[id] = c - clients + 1;
    return id;
}

static int mine(int pid, int win)
{
    struct client *c = win_client(win);
    return c && c->pid == pid;
}

static void close_window(int win)
{
    cursor_off();
    gwm_close(win);
    owner[win] = 0;
}

static void client_gone(int pid)
{
    int w;
    struct client *c = client_of(pid, 0);
    if (!c)
        return;
    for (w = 1; w <= MAXWIN; w++)
        if (owner[w] == c - clients + 1)
            close_window(w);
    c->pid = 0;
}

static int handle(int rcvid, int pid, msg_t *m)
{
    struct client *c;
    switch (m->w[0]) {
    case WS_HELLO:
        c = client_of(pid, 1);
        if (!c)
            return -ENOMEM;
        c->port = m->w[1];
        c->bits = m->w[2];
        return 0;
    case WS_OPEN:
        return do_open(rcvid, pid, m);
    case WS_CLOSE:
        if (!mine(pid, m->w[1]))
            return -EBADF;
        close_window(m->w[1]);
        return 0;
    case WS_TITLE: {
        char title[64];
        int n = m->w[3] > 63 ? 63 : m->w[3];
        if (!mine(pid, m->w[1]))
            return -EBADF;
        if (ipc_read(rcvid, (void *)m->w[2], title, n) < 0)
            return -EFAULT;
        title[n] = 0;
        cursor_off();
        gwm_set_title(m->w[1], title);
        return 0;
    }
    case WS_DRAW:
        if (!mine(pid, m->w[1]))
            return -EBADF;
        return do_draw(rcvid, m);
    case WS_EVENTS: {
        int k = 0, max = m->w[2];
        c = client_of(pid, 0);
        if (!c)
            return 0;
        while (c->n && k < max) {
            if (ipc_write(rcvid, (struct ws_event *)m->w[1] + k, &c->q[c->head],
                          sizeof(struct ws_event)) < 0)
                break;
            c->head = (c->head + 1) % QLEN;
            c->n--;
            k++;
        }
        c->notified = 0;
        return k;
    }
    case WS_INFO:
        m->w[1] = SCREEN_W;
        m->w[2] = SCREEN_H;
        m->w[3] = DEPTH;
        return 0;
    case WS_FONT: {
        struct ws_font wf;
        Font *f;
        int i;
        if (m->w[1] < 0 || m->w[1] >= MAXFONTS)
            return -EINVAL;
        f = &fonts[m->w[1]];
        wf.ascent = f->ascent;
        wf.descent = f->descent;
        wf.height = f->height;
        wf.first = f->first;
        wf.count = f->count;
        for (i = 0; i < 96; i++) {
            char s[2];
            s[0] = 32 + i;
            s[1] = 0;
            wf.adv[i] = font_width(f, s);
        }
        return ipc_write(rcvid, (void *)m->w[2], &wf, sizeof wf) < 0 ? -EFAULT : 0;
    }
    case WS_RESIZE:
        if (!mine(pid, m->w[1]))
            return -EBADF;
        cursor_off();
        gwm_resize(m->w[1], m->w[2], m->w[3]);
        return 0;
    case WS_RAISE:
        if (!mine(pid, m->w[1]))
            return -EBADF;
        cursor_off();
        gwm_raise(m->w[1]);
        return 0;
    }
    return -ENOSYS;
}

/* ---- the desktop's menu ---- */

#define MAXITEMS 16
static char item_label[MAXITEMS][24];
static char item_cmd[MAXITEMS][64];
static int nitems;
static Rect menu;
static int menu_open, menu_sel = -1;
#define ITEM_H 18

static void load_menu(void)
{
    FILE *f = fopen("/etc/menu", "r");
    char line[96];
    nitems = 0;
    if (!f) {
        strcpy(item_label[0], "Terminal");
        strcpy(item_cmd[0], "/bin/term");
        nitems = 1;
        return;
    }
    while (nitems < MAXITEMS && fgets(line, sizeof line, f)) {
        char *colon = strchr(line, ':'), *cmd;
        int k;
        if (line[0] == '#' || !colon)
            continue;
        *colon = 0;
        cmd = colon + 1;
        while (*cmd == ' ')
            cmd++;
        k = strlen(cmd);
        while (k && (cmd[k - 1] == '\n' || cmd[k - 1] == ' '))
            cmd[--k] = 0;
        strlcpy(item_label[nitems], line, sizeof item_label[0]);
        strlcpy(item_cmd[nitems], cmd, sizeof item_cmd[0]);
        nitems++;
    }
    fclose(f);
}

static Surface save_s;

static void draw_menu_item(int i)
{
    Font *ui = &fonts[0];
    int y = menu.y0 + 2 + i * ITEM_H;
    unsigned bg = i == menu_sel ? c_title : c_window, fg = i == menu_sel ? c_title_text : c_text;
    gfx_fill(&screen, menu.x0 + 1, y, menu.x1 - 1, y + ITEM_H, bg, GFX_COPY);
    font_draw(&screen, ui, menu.x0 + 10, y + 13, item_label[i], fg, 0);
}

static void open_menu(int x, int y)
{
    int w = 0, i;
    load_menu();
    for (i = 0; i < nitems; i++) {
        int k = font_width(&fonts[0], item_label[i]);
        if (k > w)
            w = k;
    }
    menu.x0 = x;
    menu.y0 = y;
    menu.x1 = x + w + 24;
    menu.y1 = y + nitems * ITEM_H + 4;
    if (menu.x1 > SCREEN_W) {
        menu.x0 -= menu.x1 - SCREEN_W;
        menu.x1 = SCREEN_W;
    }
    if (menu.y1 > SCREEN_H) {
        menu.y0 -= menu.y1 - SCREEN_H;
        menu.y1 = SCREEN_H;
    }
    cursor_off();
    gfx_init(&save_s, SAVE_UNDER, SCREEN_W, SCREEN_H, STRIDE, DEPTH);
    gfx_blit(&save_s, 0, 0, &screen, menu.x0, menu.y0, menu.x1 - menu.x0, menu.y1 - menu.y0,
             GFX_COPY);
    gfx_fill(&screen, menu.x0, menu.y0, menu.x1, menu.y1, c_window, GFX_COPY);
    gfx_frame(&screen, menu.x0, menu.y0, menu.x1, menu.y1, 1, c_frame, GFX_COPY);
    menu_sel = -1;
    for (i = 0; i < nitems; i++)
        draw_menu_item(i);
    menu_open = 1;
}

static void track_menu(void)
{
    int sel = -1;
    if (mx >= menu.x0 && mx < menu.x1 && my >= menu.y0 + 2 && my < menu.y1 - 2)
        sel = (my - menu.y0 - 2) / ITEM_H;
    if (sel >= nitems)
        sel = -1;
    if (sel != menu_sel) {
        int old = menu_sel;
        cursor_off();
        menu_sel = sel;
        if (old >= 0)
            draw_menu_item(old);
        if (sel >= 0)
            draw_menu_item(sel);
    }
}

static void run_command(const char *cmd)
{
    char buf[64], *argv[8];
    int argc = 0;
    char *p;
    char *env[] = {"PATH=/bin", "HOME=/home", "USER=fen", 0};
    strlcpy(buf, cmd, sizeof buf);
    for (p = strtok(buf, " "); p && argc < 7; p = strtok(0, " "))
        argv[argc++] = p;
    argv[argc] = 0;
    if (argc)
        spawn(argv[0], argv, env, 0, 0);
}

static void close_menu(void)
{
    cursor_off();
    gfx_blit(&screen, menu.x0, menu.y0, &save_s, 0, 0, menu.x1 - menu.x0, menu.y1 - menu.y0,
             GFX_COPY);
    menu_open = 0;
    if (menu_sel >= 0)
        run_command(item_cmd[menu_sel]);
}

/* ---- the mouse and the keyboard ---- */

enum { IDLE, DRAG, GROW, PRESS, MENU };
static int mode = IDLE, drag_win, drag_dx, drag_dy, grab_win;
static Rect outline;

static void key(int code, int mods, int down)
{
    int top = gwm_top();
    if (top)
        post(win_client(top), EV_KEY, top, code, mods, down, 0);
}

static void mouse_event(int win, int what)
{
    Rect c;
    gwm_content(win, &c);
    post(win_client(win), EV_MOUSE, win, mx - c.x0, my - c.y0, buttons, what);
}

static void mouse(int dx, int dy, int b)
{
    int old = buttons, part, win;
    cursor_off();
    mx += dx;
    my += dy;
    if (mx < 0) mx = 0;
    if (my < 0) my = 0;
    if (mx > SCREEN_W - 1) mx = SCREEN_W - 1;
    if (my > SCREEN_H - 1) my = SCREEN_H - 1;
    buttons = b;
    switch (mode) {
    case DRAG:
    case GROW:
        gwm_outline(&outline);
        if (mode == DRAG) {
            int w = outline.x1 - outline.x0, h = outline.y1 - outline.y0;
            outline.x0 = (mx - drag_dx) & ~3;  /* where gwm will put it */
            outline.y0 = my - drag_dy;
            outline.x1 = outline.x0 + w;
            outline.y1 = outline.y0 + h;
        } else {
            outline.x1 = mx + 1 > outline.x0 + 80 ? mx + 1 : outline.x0 + 80;
            outline.y1 = my + 1 > outline.y0 + 40 ? my + 1 : outline.y0 + 40;
        }
        if (!(b & 1)) {
            if (mode == DRAG)
                gwm_move(drag_win, outline.x0, outline.y0);
            else {
                int w = outline.x1 - outline.x0 - 2, h = outline.y1 - outline.y0 - TITLE_H - 3;
                gwm_resize(drag_win, w, h);
                post(win_client(drag_win), EV_RESIZE, drag_win, w, h, 0, 0);
            }
            mode = IDLE;
        } else
            gwm_outline(&outline);
        return;
    case MENU:
        track_menu();
        if (!(b & 1)) {
            close_menu();
            mode = IDLE;
        }
        return;
    case PRESS:
        if (gwm_exists(grab_win))
            mouse_event(grab_win, b & 7 ? MOUSE_MOVE : MOUSE_UP);
        if (!(b & 7))
            mode = IDLE;
        return;
    }
    /* IDLE */
    win = gwm_hit(mx, my, &part);
    if ((b & ~old) & 7) {
        if (!win) {
            open_menu(mx, my);
            mode = MENU;
            return;
        }
        if (win != gwm_top())
            gwm_raise(win);
        if (part == PART_TITLE && (b & 1)) {
            gwm_frame(win, &outline);
            drag_win = win;
            drag_dx = mx - outline.x0;
            drag_dy = my - outline.y0;
            mode = DRAG;
            gwm_outline(&outline);
            return;
        }
        if (part == PART_GROW && (b & 1)) {
            gwm_frame(win, &outline);
            drag_win = win;
            mode = GROW;
            gwm_outline(&outline);
            return;
        }
        if (part == PART_CLOSE) {
            post(win_client(win), EV_CLOSE, win, 0, 0, 0, 0);
            return;
        }
        if (part == PART_CONTENT) {
            grab_win = win;
            mode = PRESS;
            mouse_event(win, MOUSE_DOWN);
        }
        return;
    }
    if (win && part == PART_CONTENT)
        mouse_event(win, MOUSE_MOVE);
}

/* ---- the video card ---- */

static void video_init(void)
{
    int c, r, g, b;
    vm_map_phys(VRAM, VRAM_PA, VRAM_PAGES, PROT_READ | PROT_WRITE);
    vm_map_phys((void *)VIDEO_REGS, VIDEO_REGS_PA, 1, PROT_READ | PROT_WRITE);
    VIDEO_REGS[3] = 0;                  /* palette index */
    for (c = 0; c < 256; c++) {
        theme_rgb(DEPTH, c, &r, &g, &b);
        VIDEO_REGS[4] = r << 16 | g << 8 | b;
    }
    VIDEO_REGS[2] = 0;                  /* start */
    VIDEO_REGS[1] = DEPTH | 8;          /* 8 bits per pixel, on */
}

int main(void)
{
    msg_t m;
    int rcvid, pid, r;
    port = port_create();
    if (port < 0)
        return 1;
    set_priority(0, 20);
    srv_init(port, 0);
    video_init();
    gfx_tables();
    theme_init(DEPTH);
    font_bitmap(&fonts[0], font_sans12);
    font_bitmap(&fonts[1], font_mono12);
    gfx_init(&under_s, under, CURSOR_W, CURSOR_H, CURSOR_W, DEPTH);
    gwm_init(DEPTH);
    if (input_init() < 0)
        kdebug("wsys: no keyboard or mouse\n", 27);
    irq_bind(3, port, PS2_BIT);
    name_register("wsys", port);
    run_command("/bin/term");
    for (;;) {
        send_updates();
        notify_clients();
        if (!cursor_on && mode != DRAG && mode != GROW)
            cursor_show();
        rcvid = srv_recv(port, &m, &pid);
        if (rcvid == 0) {
            if (m.w[0] & SRV_EXIT_BIT)
                srv_exits(client_gone);
            if (m.w[0] & PS2_BIT)
                input_poll(key, mouse);
            continue;
        }
        if (rcvid < 0)
            continue;
        r = handle(rcvid, pid, &m);
        m.w[0] = r;
        srv_reply_next(rcvid, &m);
    }
}
