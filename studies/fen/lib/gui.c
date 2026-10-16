/* libgui (fen/gui.h): the window system's client side. */

#include <string.h>
#include <fen/sys.h>
#include <fen/gui.h>

static int ws = -1, my_port;
static unsigned batch[1024];
static int nbatch, batch_win;

#define QN 64
static struct ws_event q[QN];
static int qhead, qn;

static struct ws_font font_info[2];
static int font_have[2];

int gui_init(void)
{
    msg_t m;
    int r;
    if (ws > 0)
        return 0;
    ws = name_lookup("wsys");
    if (ws < 0)
        return ws;
    my_port = port_create();
    if (my_port < 0)
        return my_port;
    m.w[0] = WS_HELLO;
    m.w[1] = my_port;
    m.w[2] = GUI_BIT;
    r = ipc_call(ws, &m);
    return r < 0 ? r : 0;
}

int gui_port(void)
{
    return my_port;
}

static int call(int op, int a, int b, int c, int d, int e, int f, int g)
{
    msg_t m;
    m.w[0] = op;
    m.w[1] = a;
    m.w[2] = b;
    m.w[3] = c;
    m.w[4] = d;
    m.w[5] = e;
    m.w[6] = f;
    m.w[7] = g;
    return ipc_call(ws, &m);
}

void gui_flush(void)
{
    if (nbatch && batch_win)
        call(WS_DRAW, batch_win, (int)batch, nbatch, 0, 0, 0, 0);
    nbatch = 0;
}

/* room for a command of n words in win's batch */
static unsigned *cmd(int win, int op, int n)
{
    unsigned *p;
    if (win != batch_win || nbatch + n > (int)(sizeof batch / 4)) {
        gui_flush();
        batch_win = win;
    }
    p = &batch[nbatch];
    nbatch += n;
    p[0] = op << 24 | n;
    return p;
}

int gui_open(int x, int y, int w, int h, const char *title, unsigned bg)
{
    gui_flush();
    return call(WS_OPEN, x, y, w, h, (int)title, strlen(title), bg);
}

void gui_close(int win)
{
    if (win == batch_win)
        nbatch = 0;
    call(WS_CLOSE, win, 0, 0, 0, 0, 0, 0);
}

void gui_title(int win, const char *title)
{
    gui_flush();
    call(WS_TITLE, win, (int)title, strlen(title), 0, 0, 0, 0);
}

void gui_raise(int win)
{
    gui_flush();
    call(WS_RAISE, win, 0, 0, 0, 0, 0, 0);
}

void gui_fill(int win, unsigned c, int x0, int y0, int x1, int y1)
{
    unsigned *p = cmd(win, D_FILL, 6);
    p[1] = c;
    p[2] = x0;
    p[3] = y0;
    p[4] = x1;
    p[5] = y1;
}

void gui_frame(int win, unsigned c, int x0, int y0, int x1, int y1, int t)
{
    unsigned *p = cmd(win, D_FRAME, 7);
    p[1] = c;
    p[2] = x0;
    p[3] = y0;
    p[4] = x1;
    p[5] = y1;
    p[6] = t;
}

void gui_line(int win, unsigned c, int x0, int y0, int x1, int y1)
{
    unsigned *p = cmd(win, D_LINE, 6);
    p[1] = c;
    p[2] = x0;
    p[3] = y0;
    p[4] = x1;
    p[5] = y1;
}

void gui_text(int win, unsigned c, int font, int x, int y, const char *s, int n)
{
    unsigned *p;
    if (n > 255)
        n = 255;
    p = cmd(win, D_TEXT, 6 + (n + 3) / 4);
    p[1] = c;
    p[2] = font;
    p[3] = x;
    p[4] = y;
    p[5] = n;
    memcpy(&p[6], s, n);
}

void gui_textbg(int win, unsigned fg, unsigned bg, int font, int x, int y, const char *s, int n)
{
    unsigned *p;
    if (n > 255)
        n = 255;
    p = cmd(win, D_TEXTBG, 7 + (n + 3) / 4);
    p[1] = fg;
    p[2] = bg;
    p[3] = font;
    p[4] = x;
    p[5] = y;
    p[6] = n;
    memcpy(&p[7], s, n);
}

void gui_ellipse(int win, unsigned c, int xc, int yc, int a, int b, int filled)
{
    unsigned *p = cmd(win, D_ELLIPSE, 7);
    p[1] = c;
    p[2] = xc;
    p[3] = yc;
    p[4] = a;
    p[5] = b;
    p[6] = filled;
}

void gui_poly(int win, unsigned c, const int *xy, int n)
{
    unsigned *p;
    if (n > 64)
        n = 64;
    p = cmd(win, D_POLY, 3 + 2 * n);
    p[1] = c;
    p[2] = n;
    memcpy(&p[3], xy, 8 * n);
}

void gui_pixels(int win, int x, int y, int w, int h, const unsigned char *px)
{
    int pitch = (w + 3) & ~3, words = (pitch * h + 3) / 4, row;
    unsigned *p;
    if (5 + words > (int)(sizeof batch / 4))
        return;
    p = cmd(win, D_PIXELS, 5 + words);
    p[1] = x;
    p[2] = y;
    p[3] = w;
    p[4] = h;
    for (row = 0; row < h; row++)
        memcpy((char *)&p[5] + row * pitch, px + row * w, w);
}

void gui_scroll(int win, int x0, int y0, int x1, int y1, int dy)
{
    unsigned *p = cmd(win, D_SCROLL, 6);
    p[1] = x0;
    p[2] = y0;
    p[3] = x1;
    p[4] = y1;
    p[5] = dy;
}

void gui_clip(int win, int x0, int y0, int x1, int y1)
{
    unsigned *p = cmd(win, D_CLIP, 5);
    p[1] = x0;
    p[2] = y0;
    p[3] = x1;
    p[4] = y1;
}

void gui_noclip(int win)
{
    cmd(win, D_NOCLIP, 1);
}

void gui_poll(void)
{
    struct ws_event buf[16];
    int n, i;
    do {
        if (qn > QN - 16)
            return;
        n = call(WS_EVENTS, (int)buf, 16, 0, 0, 0, 0, 0);
        for (i = 0; i < n; i++) {
            q[(qhead + qn) % QN] = buf[i];
            qn++;
        }
    } while (n == 16);
}

int gui_event(struct ws_event *e, int wait)
{
    msg_t m;
    while (!qn) {
        gui_flush();
        gui_poll();
        if (qn || !wait)
            break;
        /* wait for wsys to say there are some */
        while (ipc_recv(my_port, &m, 0) != 0)
            ;
    }
    if (!qn)
        return 0;
    *e = q[qhead];
    qhead = (qhead + 1) % QN;
    qn--;
    return 1;
}

struct ws_font *gui_font(int font)
{
    msg_t m;
    if (font < 0 || font > 1)
        font = 0;
    if (!font_have[font]) {
        m.w[0] = WS_FONT;
        m.w[1] = font;
        m.w[2] = (int)&font_info[font];
        if (ipc_call(ws, &m) == 0)
            font_have[font] = 1;
    }
    return &font_info[font];
}

int gui_width(int font, const char *s, int n)
{
    struct ws_font *f = gui_font(font);
    int w = 0, i;
    for (i = 0; i < n; i++) {
        int c = (unsigned char)s[i];
        if (c >= 32 && c < 128)
            w += f->adv[c - 32];
    }
    return w;
}

int gui_screen(int *w, int *h)
{
    msg_t m;
    int r;
    m.w[0] = WS_INFO;
    r = ipc_call(ws, &m);
    if (w)
        *w = m.w[1];
    if (h)
        *h = m.w[2];
    return r;
}
