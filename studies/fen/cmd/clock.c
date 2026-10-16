/* clock: the time in a window, on a dial and as text, and the date. It
 * waits on its window system port for both its events and an alarm a
 * second (the kernel's alarm()), so it does nothing in between. */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include <fen/sys.h>
#include <fen/gui.h>

#define W 160
#define H 196
#define CX (W / 2)
#define CY 82
#define R 72
#define TICK_BIT 1

#define FACE 0xFFFFFF
#define INK 0x000000
#define HAND2 0xCC0000

static int win;

/* sin(6 degrees * i) * 1024, a quarter turn */
static const short quarter[16] = {
    0, 107, 213, 316, 416, 512, 602, 685, 761, 828, 887, 935, 974, 1002, 1018, 1024,
};

/* sine and cosine of the i-th sixtieth of a turn, clockwise from 12 */
static int sin60(int i)
{
    i %= 60;
    if (i <= 15) return quarter[i];
    if (i <= 30) return quarter[30 - i];
    if (i <= 45) return -quarter[i - 30];
    return -quarter[60 - i];
}

static int cos60(int i)
{
    return sin60(i + 15);
}

/* the point at radius r (in 1/1024ths of R) and sixtieth i */
static void at(int i, int r, int *x, int *y)
{
    *x = CX + sin60(i) * R / 1024 * r / 1024;
    *y = CY - cos60(i) * R / 1024 * r / 1024;
}

/* a hand: a thin kite from the centre */
static void hand(int i, int len, int width, unsigned colour)
{
    int xy[8], tx, ty;
    at(i, len, &tx, &ty);
    xy[0] = CX + cos60(i) * width / 1024;
    xy[1] = CY + sin60(i) * width / 1024;
    xy[2] = tx;
    xy[3] = ty;
    xy[4] = CX - cos60(i) * width / 1024;
    xy[5] = CY - sin60(i) * width / 1024;
    xy[6] = CX - sin60(i) * width / 1024;
    xy[7] = CY + cos60(i) * width / 1024;
    gui_poly(win, colour, xy, 4);
}

static void dial(void)
{
    int i;
    gui_ellipse(win, FACE, CX, CY, R, R, 1);
    gui_ellipse(win, INK, CX, CY, R, R, 0);
    for (i = 0; i < 60; i++) {
        int x0, y0, x1, y1;
        at(i, i % 5 ? 940 : 860, &x0, &y0);
        at(i, 1000, &x1, &y1);
        gui_line(win, INK, x0, y0, x1, y1);
    }
}

static void draw(int all)
{
    static const char *days[] = {"Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"};
    static const char *months[] = {"Jan", "Feb", "Mar", "Apr", "May", "Jun",
                                   "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"};
    time_t t = time(0);
    struct tm *tm = localtime(&t);
    char buf[32];
    int n;
    if (all)
        gui_fill(win, FACE, 0, 0, W, H);
    dial();
    hand(tm->tm_hour % 12 * 5 + tm->tm_min / 12, 560, 4, INK);
    hand(tm->tm_min, 860, 3, INK);
    {
        int x, y;
        at(tm->tm_sec, 900, &x, &y);
        gui_line(win, HAND2, CX, CY, x, y);
    }
    gui_ellipse(win, INK, CX, CY, 3, 3, 1);
    n = sprintf(buf, "%02d:%02d:%02d", tm->tm_hour, tm->tm_min, tm->tm_sec);
    gui_textbg(win, INK, FACE, FONT_SANS, (W - gui_width(FONT_SANS, buf, n)) / 2, CY + R + 22,
               buf, n);
    n = sprintf(buf, "%s %d %s %d", days[tm->tm_wday], tm->tm_mday, months[tm->tm_mon],
                tm->tm_year + 1900);
    gui_fill(win, FACE, 0, CY + R + 26, W, H);
    gui_textbg(win, INK, FACE, FONT_SANS, (W - gui_width(FONT_SANS, buf, n)) / 2, CY + R + 40,
               buf, n);
    gui_flush();
}

/* the alarm for the next second */
static void arm(int port)
{
    unsigned us = 1000000 - time_us() % 1000000;
    alarm(port, TICK_BIT, us + 1000);
}

int main(void)
{
    struct ws_event e;
    msg_t m;
    int port, rcvid;
    if (gui_init() < 0) {
        fprintf(stderr, "clock: no window system\n");
        return 1;
    }
    port = gui_port();
    win = gui_open(-1, -1, W, H, "Clock", FACE);
    if (win < 0)
        return 1;
    draw(1);
    arm(port);
    for (;;) {
        rcvid = ipc_recv(port, &m, 0);
        if (rcvid > 0) {
            m.w[0] = -ENOSYS;
            ipc_reply(rcvid, &m);
            continue;
        }
        if (rcvid < 0)
            continue;
        if (m.w[0] & GUI_BIT) {
            int expose = 0;
            gui_poll();
            while (gui_event(&e, 0)) {
                if (e.type == EV_CLOSE) {
                    gui_close(win);
                    return 0;
                }
                if (e.type == EV_EXPOSE)
                    expose = 1;
            }
            if (expose)
                draw(1);
        }
        if (m.w[0] & TICK_BIT) {
            draw(0);
            arm(port);
        }
    }
}
