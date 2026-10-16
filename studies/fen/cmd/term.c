/* term: a terminal in a window. It runs a shell, and is the file server
 * (fen/fs.h) of the shell's descriptors 0, 1 and 2, and so of everything
 * the shell starts: what they write goes on the screen, what's typed in
 * the window they read.
 *
 * Every descriptor of the terminal is the same one file, handle 1, so it
 * keeps no tables: FS_DUPTO answers 1 and FS_CLOSE does nothing. Cooked
 * input (the default) is the console's line discipline (srv/cons): echo,
 * ^H, ^U, ^D, and ^C ending the foreground process group; raw gives every
 * key as it comes, the arrows as ANSI sequences.
 *
 * Output understands enough of ANSI X3.64 (VT100) for full-screen
 * programs: cursor motion, erasing, scrolling regions, colours and
 * reverse. The screen is kept as cells, and what changed is drawn a row
 * at a time, in runs of cells with the same colours, with scrolling as one
 * D_SCROLL however many lines went by. It's drawn when a program reads
 * (it has said what it had to say), when a key is typed, and otherwise
 * at most every DRAW_US while output comes: scrolling the window costs as
 * much as copying it, so a stream of lines is drawn a few at a time. */

#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <fen/sys.h>
#include <fen/fs.h>
#include <fen/srv.h>
#include <fen/spawn.h>
#include <fen/gui.h>

#define MAXC 132
#define MAXR 60
#define HANDLE 1
#define DRAW_BIT 1              /* the alarm's */
#define DRAW_US 80000

static int port, win, shell_pid;
static int cw, ch, ascent;              /* a cell, from the mono font */
static int cols = 80, rows = 24;

/* ---- the screen ---- */

/* colours as ANSI numbers them: 0-7, and 8-15 bright */
static const unsigned rgb[16] = {
    0x000000, 0xAA0000, 0x00AA00, 0xAA5500, 0x0000AA, 0xAA00AA, 0x00AAAA, 0xAAAAAA,
    0x555555, 0xFF5555, 0x55FF55, 0xFFFF55, 0x5555FF, 0xFF55FF, 0x55FFFF, 0xFFFFFF,
};
#define DEF_FG 0
#define DEF_BG 15
#define ATTR(fg, bg) ((fg) | (bg) << 4)

/* the cells, a row through a pointer, so that scrolling moves pointers */
static char text_rows[MAXR][MAXC];
static unsigned char attr_rows[MAXR][MAXC];
static char *text[MAXR];
static unsigned char *attr[MAXR];
static int dirty0[MAXR], dirty1[MAXR];  /* each row's changed columns, [dirty0, dirty1) */
static int scrolled;                    /* lines scrolled since the last drawing */

static int cx, cy;                      /* the cursor */
static int saved_x, saved_y;
static int cursor_shown = 1, cursor_drawn_x = -1, cursor_drawn_y = -1;
static int fg = DEF_FG, bg = DEF_BG, bold, reverse;
static int top, bottom;                 /* the scrolling region, rows [top, bottom] */
static int wrap_next;                   /* the cursor is past the last column */

static void touch(int y, int x0, int x1)
{
    if (y < 0 || y >= rows)
        return;
    if (x0 < 0)
        x0 = 0;
    if (x1 > cols)
        x1 = cols;
    if (x0 >= x1)
        return;
    if (dirty0[y] >= dirty1[y]) {
        dirty0[y] = x0;
        dirty1[y] = x1;
        return;
    }
    if (x0 < dirty0[y])
        dirty0[y] = x0;
    if (x1 > dirty1[y])
        dirty1[y] = x1;
}

static void touch_all(void)
{
    int y;
    for (y = 0; y < rows; y++) {
        dirty0[y] = 0;
        dirty1[y] = cols;
    }
}

static unsigned cur_attr(void)
{
    int f = fg, b = bg;
    if (bold && f < 8)
        f += 8;
    if (reverse) {
        int t = f;
        f = b;
        b = t;
    }
    return ATTR(f, b);
}

static void clear_cells(int y, int x0, int x1)
{
    int x;
    unsigned a = ATTR(fg, bg);
    for (x = x0; x < x1; x++) {
        text[y][x] = ' ';
        attr[y][x] = a;
    }
    touch(y, x0, x1);
}

/* the rows [t, b] up by n (n < 0: down), the new ones blank */
static void scroll_rows(int t, int b, int n)
{
    int y, i, k = n < 0 ? -n : n, whole = t == 0 && b == rows - 1 && n > 0 && scrolled >= 0;
    char *tp[MAXR];
    unsigned char *ap[MAXR];
    if (k > b - t + 1)
        k = b - t + 1;
    for (i = 0; i < k; i++) {
        tp[i] = text[n > 0 ? t + i : b - i];
        ap[i] = attr[n > 0 ? t + i : b - i];
    }
    if (n > 0) {
        for (y = t; y + k <= b; y++) {
            text[y] = text[y + k];
            attr[y] = attr[y + k];
            dirty0[y] = dirty0[y + k];
            dirty1[y] = dirty1[y + k];
        }
    } else {
        for (y = b; y - k >= t; y--) {
            text[y] = text[y - k];
            attr[y] = attr[y - k];
            dirty0[y] = dirty0[y - k];
            dirty1[y] = dirty1[y - k];
        }
    }
    for (i = 0; i < k; i++) {
        y = n > 0 ? b - k + 1 + i : t + i;
        text[y] = tp[i];
        attr[y] = ap[i];
        dirty0[y] = dirty1[y] = 0;
        clear_cells(y, 0, cols);
        /* a blank row the D_SCROLL opens is filled with the background
           already */
        if (whole && bg == DEF_BG)
            dirty0[y] = dirty1[y] = 0;
    }
    /* the whole screen moving is one D_SCROLL later; anything else is
       drawn again */
    if (whole)
        scrolled += k;
    else {
        for (y = t; y <= b; y++)
            touch(y, 0, cols);
        if (t == 0 && b == rows - 1)
            scrolled = -1;          /* (a scroll down: no D_SCROLL for it) */
    }
}

static void line_feed(void)
{
    if (cy == bottom)
        scroll_rows(top, bottom, 1);
    else if (cy < rows - 1)
        cy++;
}

static void put_char(int c)
{
    if (wrap_next) {
        cx = 0;
        line_feed();
        wrap_next = 0;
    }
    text[cy][cx] = c;
    attr[cy][cx] = cur_attr();
    touch(cy, cx, cx + 1);
    if (cx == cols - 1)
        wrap_next = 1;
    else
        cx++;
}

static void reset(void)
{
    int y;
    fg = DEF_FG;
    bg = DEF_BG;
    bold = reverse = 0;
    top = 0;
    bottom = rows - 1;
    cx = cy = 0;
    wrap_next = 0;
    cursor_shown = 1;
    for (y = 0; y < rows; y++)
        clear_cells(y, 0, cols);
}

/* ---- drawing ---- */

/* the cells [x0, x1) of row y: runs of one colour, the blanks at the end
 * of a run as a fill */
static void draw_row(int y, int x0, int x1)
{
    int x = x0;
    while (x < x1) {
        int k = x, e;
        unsigned a = attr[y][x];
        if (cursor_shown && y == cy && x == cx) {
            gui_textbg(win, rgb[a >> 4], rgb[a & 15], FONT_MONO, x * cw, y * ch + ascent,
                       &text[y][x], 1);
            x++;
            continue;
        }
        while (k < x1 && attr[y][k] == a && !(cursor_shown && y == cy && k == cx))
            k++;
        for (e = k; e > x && text[y][e - 1] == ' '; e--)
            ;
        if (e > x)
            gui_textbg(win, rgb[a & 15], rgb[a >> 4], FONT_MONO, x * cw, y * ch + ascent,
                       &text[y][x], e - x);
        if (e < k)
            gui_fill(win, rgb[a >> 4], e * cw, y * ch, k * cw, y * ch + ch);
        x = k;
    }
}

static int armed;               /* output not drawn yet, and an alarm for it */

static void draw(void)
{
    int y, x = cx < cols ? cx : cols - 1;
    if (!win)
        return;
    /* the cursor moves: where it was, and where it is */
    if (cursor_drawn_y >= 0 && (cursor_drawn_x != x || cursor_drawn_y != cy || !cursor_shown))
        touch(cursor_drawn_y - (scrolled > 0 ? scrolled : 0), cursor_drawn_x, cursor_drawn_x + 1);
    if (cursor_shown)
        touch(cy, x, x + 1);
    if (scrolled > 0 && scrolled < rows)
        gui_scroll(win, 0, 0, cols * cw, rows * ch, scrolled * ch);
    else if (scrolled != 0)
        touch_all();
    scrolled = 0;
    {
        int save = cx;
        cx = x;
        for (y = 0; y < rows; y++)
            if (dirty0[y] < dirty1[y]) {
                draw_row(y, dirty0[y], dirty1[y]);
                dirty0[y] = dirty1[y] = 0;
            }
        cx = save;
    }
    cursor_drawn_x = cursor_shown ? x : -1;
    cursor_drawn_y = cursor_shown ? cy : -1;
    gui_flush();
}

/* draw what changed now, or after a while */
static void draw_now(void)
{
    if (armed) {
        alarm(port, DRAW_BIT, 0);
        armed = 0;
    }
    draw();
}

static void draw_later(void)
{
    if (!armed) {
        alarm(port, DRAW_BIT, DRAW_US);
        armed = 1;
    }
}

/* ---- output: the characters and the escape sequences ---- */

enum { S_TEXT, S_ESC, S_CSI };
static int state;
static int par[8], npar, priv;

static int arg(int i, int def)
{
    return i < npar && par[i] > 0 ? par[i] : def;
}

static void clamp_cursor(void)
{
    if (cx < 0) cx = 0;
    if (cx >= cols) cx = cols - 1;
    if (cy < 0) cy = 0;
    if (cy >= rows) cy = rows - 1;
    wrap_next = 0;
}

static void sgr(void)
{
    int i;
    if (npar == 0)
        par[npar++] = 0;
    for (i = 0; i < npar; i++) {
        int p = par[i];
        if (p == 0) {
            fg = DEF_FG;
            bg = DEF_BG;
            bold = reverse = 0;
        } else if (p == 1)
            bold = 1;
        else if (p == 22)
            bold = 0;
        else if (p == 7)
            reverse = 1;
        else if (p == 27)
            reverse = 0;
        else if (p >= 30 && p <= 37)
            fg = p - 30;
        else if (p == 39)
            fg = DEF_FG;
        else if (p >= 40 && p <= 47)
            bg = p - 40;
        else if (p == 49)
            bg = DEF_BG;
        else if (p >= 90 && p <= 97)
            fg = p - 90 + 8;
        else if (p >= 100 && p <= 107)
            bg = p - 100 + 8;
    }
}

static void csi(int c)
{
    int n = arg(0, 1), y;
    switch (c) {
    case 'A': cy -= n; if (cy < top && cy + n >= top) cy = top; clamp_cursor(); break;
    case 'B': cy += n; if (cy > bottom && cy - n <= bottom) cy = bottom; clamp_cursor(); break;
    case 'C': cx += n; clamp_cursor(); break;
    case 'D': cx -= n; clamp_cursor(); break;
    case 'E': cx = 0; cy += n; clamp_cursor(); break;
    case 'F': cx = 0; cy -= n; clamp_cursor(); break;
    case 'G': cx = n - 1; clamp_cursor(); break;
    case 'd': cy = n - 1; clamp_cursor(); break;
    case 'H':
    case 'f':
        cy = arg(0, 1) - 1;
        cx = arg(1, 1) - 1;
        clamp_cursor();
        break;
    case 'J':
        switch (arg(0, 0)) {
        case 0:
            clear_cells(cy, cx, cols);
            for (y = cy + 1; y < rows; y++)
                clear_cells(y, 0, cols);
            break;
        case 1:
            clear_cells(cy, 0, cx + 1);
            for (y = 0; y < cy; y++)
                clear_cells(y, 0, cols);
            break;
        default:
            for (y = 0; y < rows; y++)
                clear_cells(y, 0, cols);
            break;
        }
        break;
    case 'K':
        switch (arg(0, 0)) {
        case 0: clear_cells(cy, cx, cols); break;
        case 1: clear_cells(cy, 0, cx + 1); break;
        default: clear_cells(cy, 0, cols); break;
        }
        break;
    case 'L':
        if (cy >= top && cy <= bottom)
            scroll_rows(cy, bottom, -n);
        break;
    case 'M':
        if (cy >= top && cy <= bottom)
            scroll_rows(cy, bottom, n);
        break;
    case 'S': scroll_rows(top, bottom, n); break;
    case 'T': scroll_rows(top, bottom, -n); break;
    case 'P': {
        int x;
        if (n > cols - cx)
            n = cols - cx;
        for (x = cx; x + n < cols; x++) {
            text[cy][x] = text[cy][x + n];
            attr[cy][x] = attr[cy][x + n];
        }
        clear_cells(cy, cols - n, cols);
        touch(cy, cx, cols);
        break;
    }
    case '@': {
        int x;
        if (n > cols - cx)
            n = cols - cx;
        for (x = cols - 1; x >= cx + n; x--) {
            text[cy][x] = text[cy][x - n];
            attr[cy][x] = attr[cy][x - n];
        }
        clear_cells(cy, cx, cx + n);
        touch(cy, cx, cols);
        break;
    }
    case 'X':
        clear_cells(cy, cx, cx + n < cols ? cx + n : cols);
        break;
    case 'm': sgr(); break;
    case 'r':
        top = arg(0, 1) - 1;
        bottom = arg(1, rows) - 1;
        if (top < 0 || bottom >= rows || top >= bottom) {
            top = 0;
            bottom = rows - 1;
        }
        cx = cy = 0;
        wrap_next = 0;
        break;
    case 's': saved_x = cx; saved_y = cy; break;
    case 'u': cx = saved_x; cy = saved_y; clamp_cursor(); break;
    case 'h':
    case 'l':
        if (priv && arg(0, 0) == 25)
            cursor_shown = c == 'h';
        break;
    }
}

static void output(int c)
{
    c &= 0xFF;
    switch (state) {
    case S_ESC:
        state = S_TEXT;
        switch (c) {
        case '[':
            state = S_CSI;
            npar = 0;
            priv = 0;
            par[0] = 0;
            return;
        case '7': saved_x = cx; saved_y = cy; return;
        case '8': cx = saved_x; cy = saved_y; clamp_cursor(); return;
        case 'c': reset(); return;
        case 'D': line_feed(); return;
        case 'M':
            if (cy == top)
                scroll_rows(top, bottom, -1);
            else if (cy > 0)
                cy--;
            return;
        }
        return;
    case S_CSI:
        if (c >= '0' && c <= '9') {
            if (npar == 0)
                npar = 1;
            par[npar - 1] = par[npar - 1] * 10 + c - '0';
            return;
        }
        if (c == ';') {
            if (npar == 0)
                npar = 1;
            if (npar < 8)
                par[npar++] = 0;
            return;
        }
        if (c == '?') {
            priv = 1;
            return;
        }
        state = S_TEXT;
        csi(c);
        return;
    }
    switch (c) {
    case 27:
        state = S_ESC;
        return;
    case '\n':                      /* as "\r\n", like the console */
        cx = 0;
        wrap_next = 0;
        line_feed();
        return;
    case '\r':
        cx = 0;
        wrap_next = 0;
        return;
    case '\b':
        if (cx > 0)
            cx--;
        wrap_next = 0;
        return;
    case '\t':
        do
            put_char(' ');
        while (cx % 8 && !wrap_next);
        return;
    case 7:
        return;
    }
    if (c >= 32)
        put_char(c);
}

/* ---- input: the line discipline ---- */

static int mode;                    /* CONS_RAW, CONS_NOECHO */
static int fg_pgid;
static char line[256];
static int line_len;
#define IN_SIZE 1024
static unsigned char in[IN_SIZE];
static unsigned in_rd, in_wr;
static int eof_pending;
static struct srv_req *readers;

static void in_put(int c)
{
    if (in_wr - in_rd < IN_SIZE)
        in[in_wr++ % IN_SIZE] = c;
}

static void in_str(const char *s)
{
    while (*s)
        in_put(*s++);
}

static void echo(int c)
{
    if (!(mode & CONS_NOECHO))
        output(c);
}

static void rubout(void)
{
    line_len--;
    echo('\b');
    echo(' ');
    echo('\b');
}

static void typed(int c)
{
    if (mode & CONS_RAW) {
        in_put(c);
        return;
    }
    if (c == '\r')
        c = '\n';
    switch (c) {
    case 3:
        echo('^');
        echo('C');
        echo('\n');
        line_len = 0;
        if (fg_pgid > 0)
            proc_kill(-fg_pgid, 128 + 2);
        return;
    case 4:
        if (line_len == 0)
            eof_pending = 1;
        else {
            int i;
            for (i = 0; i < line_len; i++)
                in_put(line[i]);
            line_len = 0;
        }
        return;
    case 8:
    case 127:
        if (line_len > 0)
            rubout();
        return;
    case 21:
        while (line_len > 0)
            rubout();
        return;
    case 23:                        /* ^W: the last word */
        while (line_len > 0 && line[line_len - 1] == ' ')
            rubout();
        while (line_len > 0 && line[line_len - 1] != ' ')
            rubout();
        return;
    case '\n': {
        int i;
        echo('\n');
        for (i = 0; i < line_len; i++)
            in_put(line[i]);
        in_put('\n');
        line_len = 0;
        return;
    }
    }
    if (c < 32 && c != '\t')
        return;
    if (line_len < (int)sizeof line - 1) {
        line[line_len++] = c;
        echo(c);
    }
}

static void run_readers(void)
{
    while (readers && (in_rd != in_wr || eof_pending)) {
        struct srv_req *r = readers;
        unsigned n = r->m.w[3], k = 0;
        unsigned char buf[256];
        if (in_rd == in_wr) {
            eof_pending = 0;
            srv_answer(&readers, r, 0);
            continue;
        }
        while (k < n && k < sizeof buf && in_rd != in_wr) {
            unsigned char c = in[in_rd++ % IN_SIZE];
            buf[k++] = c;
            if (c == '\n' && !(mode & CONS_RAW))
                break;
        }
        if (ipc_write(r->rcvid, (void *)r->m.w[2], buf, k) < 0)
            k = -EFAULT;
        srv_answer(&readers, r, k);
    }
}

static void key(int code, int mods)
{
    if (code < 0x100) {
        if ((mods & MOD_CTRL) && ((code >= '@' && code <= '_') || (code >= 'a' && code <= 'z')))
            code &= 0x1F;
        typed(code);
        return;
    }
    if (!(mode & CONS_RAW))
        return;
    switch (code) {
    case KEY_UP: in_str("\033[A"); break;
    case KEY_DOWN: in_str("\033[B"); break;
    case KEY_RIGHT: in_str("\033[C"); break;
    case KEY_LEFT: in_str("\033[D"); break;
    case KEY_HOME: in_str("\033[H"); break;
    case KEY_END: in_str("\033[F"); break;
    case KEY_PGUP: in_str("\033[5~"); break;
    case KEY_PGDN: in_str("\033[6~"); break;
    case KEY_INS: in_str("\033[2~"); break;
    case KEY_DEL: in_str("\033[3~"); break;
    }
}

/* ---- the window ---- */

static void resize(int w, int h)
{
    int nc = w / cw, nr = h / ch, y;
    if (nc < 10) nc = 10;
    if (nr < 3) nr = 3;
    if (nc > MAXC) nc = MAXC;
    if (nr > MAXR) nr = MAXR;
    if (nc == cols && nr == rows)
        return;
    /* keep the cursor's row on the screen */
    if (cy >= nr) {
        int k = cy - nr + 1, i;
        char *tp[MAXR];
        unsigned char *ap[MAXR];
        for (i = 0; i < MAXR; i++) {
            tp[i] = text[(i + k) % MAXR];
            ap[i] = attr[(i + k) % MAXR];
        }
        for (i = 0; i < MAXR; i++) {
            text[i] = tp[i];
            attr[i] = ap[i];
        }
        cy -= k;
    }
    for (y = 0; y < nr; y++) {
        int x0 = y < rows ? cols : 0, x;
        for (x = x0; x < nc; x++) {
            text[y][x] = ' ';
            attr[y][x] = ATTR(DEF_FG, DEF_BG);
        }
    }
    cols = nc;
    rows = nr;
    top = 0;
    bottom = rows - 1;
    clamp_cursor();
    scrolled = 0;
    cursor_drawn_y = -1;
    touch_all();
}

static void quit(void)
{
    if (shell_pid > 0)
        proc_kill(-shell_pid, 128 + 1);
    if (fg_pgid > 0 && fg_pgid != shell_pid)
        proc_kill(-fg_pgid, 128 + 1);
    if (win)
        gui_close(win);
    exit(0);
}

/* the window's events: whether to draw now (a key was typed) */
static int events(void)
{
    struct ws_event e;
    int y, now = 0;
    while (gui_event(&e, 0)) {
        switch (e.type) {
        case EV_KEY:
            if (e.c)
                key(e.a, e.b);
            now = 1;
            break;
        case EV_EXPOSE:
            for (y = e.b / ch; y < rows && y * ch < e.d; y++)
                touch(y, e.a / cw, (e.c + cw - 1) / cw);
            if (cursor_drawn_y >= e.b / ch && cursor_drawn_y * ch < e.d)
                cursor_drawn_y = -1;
            break;
        case EV_RESIZE:
            resize(e.a, e.b);
            now = 1;
            break;
        case EV_CLOSE:
            quit();
            break;
        }
    }
    run_readers();
    return now;
}

static void gone(int pid)
{
    int st;
    srv_drop_pid(&readers, pid);
    if (pid == shell_pid) {
        waitpid(pid, &st, WNOHANG);
        shell_pid = 0;
        quit();
    }
}

/* ---- the file protocol ---- */

static int write_out(int rcvid, msg_t *m)
{
    int inl = m->w[0] == FS_WRITE_INLINE;
    unsigned n = inl ? m->w[2] : m->w[3], done = 0, i;
    char buf[256];
    while (done < n) {
        unsigned k = n - done > sizeof buf ? sizeof buf : n - done;
        if (inl)
            memcpy(buf, (char *)&m->w[4] + done, k);
        else if (ipc_read(rcvid, (char *)m->w[2] + done, buf, k) < 0)
            return -EFAULT;
        for (i = 0; i < k; i++)
            output(buf[i]);
        done += k;
    }
    return n;
}

static int handle(int rcvid, int pid, msg_t *m)
{
    struct stat st;
    switch (m->w[0]) {
    case FS_OPEN:
        return HANDLE;
    case FS_CLOSE:
        return 0;
    case FS_DUPTO:
        return HANDLE;
    case FS_READ:
        srv_keep(&readers, rcvid, pid, m);
        run_readers();
        draw_now();
        return 1 << 30;
    case FS_WRITE:
    case FS_WRITE_INLINE:
        draw_later();
        return write_out(rcvid, m);
    case FS_STAT:
    case FS_FSTAT:
        memset(&st, 0, sizeof st);
        st.st_mode = S_IFCHR | 0666;
        return ipc_write(rcvid, (void *)m->w[m->w[0] == FS_STAT ? 3 : 2], &st, sizeof st) < 0
                   ? -EFAULT : 0;
    case FS_IOCTL:
        switch (m->w[2]) {
        case IO_ISTTY:
            return 1;
        case IO_MODE: {
            int old = mode;
            mode = m->w[3];
            return old;
        }
        case IO_SETFG:
            fg_pgid = m->w[3];
            return 0;
        case IO_GETSIZE:
            return rows << 16 | cols;
        }
        return -EINVAL;
    case FS_SEEK:
        return -ESPIPE;
    }
    return -ENOSYS;
}

int main(int argc, char **argv)
{
    static char *sh_argv[] = {"sh", "-l", 0};
    struct fd_desc d[3];
    struct ws_font *f;
    msg_t m;
    int rcvid, pid, r, i;
    if (gui_init() < 0)
        return 1;
    port = gui_port();
    f = gui_font(FONT_MONO);
    cw = f->adv[0];
    ch = f->ascent + f->descent;
    ascent = f->ascent;
    if (cw <= 0 || ch <= 0)
        return 1;
    win = gui_open(-1, -1, cols * cw, rows * ch, argc > 1 ? argv[1] : "Terminal", rgb[DEF_BG]);
    if (win < 0)
        return 1;
    srv_init(port, 0);
    for (i = 0; i < MAXR; i++) {
        text[i] = text_rows[i];
        attr[i] = attr_rows[i];
    }
    reset();
    for (i = 0; i < 3; i++) {
        d[i].fd = i;
        d[i].port = port;
        d[i].handle = HANDLE;
        d[i].flags = O_RDWR;
    }
    shell_pid = spawnd("/bin/sh", sh_argv, environ, d, 3, SPAWN_PGID, 0);
    if (shell_pid < 0) {
        const char *s = "term: can't start /bin/sh\n";
        while (*s)
            output(*s++);
    }
    draw();
    for (;;) {
        rcvid = ipc_recv(port, &m, &pid);
        if (rcvid == 0) {
            if (m.w[0] & SRV_EXIT_BIT)
                srv_exits(gone);
            if (m.w[0] & GUI_BIT) {
                gui_poll();
                if (events())
                    draw_now();
                else
                    draw_later();
            }
            if (m.w[0] & DRAW_BIT) {
                armed = 0;
                draw();
            }
            continue;
        }
        if (rcvid < 0)
            continue;
        r = handle(rcvid, pid, &m);
        if (r != 1 << 30) {
            m.w[0] = r;
            ipc_reply(rcvid, &m);
        }
    }
}
