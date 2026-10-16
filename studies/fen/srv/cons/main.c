/* cons: the serial console. The I/O card's 16C550 at 115,200 baud, driven
 * by its interrupts with its FIFOs on, a line discipline in front of it,
 * and the file protocol (fen/fs.h) for the processes that have it open:
 * /dev/cons, through the C library's mount table.
 *
 * Cooked, the default: what's typed is echoed and kept until Return; ^H or
 * DEL rubs out, ^U kills the line, ^D ends the input (or sends the line
 * without its newline), ^C ends the foreground process group. Raw: every
 * byte as it comes, nothing echoed. Output gets "\r\n" for "\n". */

#include <stdlib.h>
#include <string.h>
#include <fen/sys.h>
#include <fen/fs.h>
#include <fen/srv.h>

#define UART_PA 0x20000000
#define UART_VA 0x00EFF000
#define UART_IRQ 6
#define UART_BIT 1

#define R(n) (*(volatile unsigned *)(UART_VA + 4 * (n)))
#define RBR R(0)
#define THR R(0)
#define IER R(1)
#define IIR R(2)
#define FCR R(2)
#define LCR R(3)
#define MCR R(4)
#define LSR R(5)
#define DLL R(0)
#define DLM R(1)

#define LSR_DR 0x01
#define LSR_THRE 0x20
#define IER_RX 0x01
#define IER_TX 0x02

static int port;

/* output: a ring the transmitter empties */
#define OUT_SIZE 2048
static unsigned char out[OUT_SIZE];
static unsigned out_rd, out_wr;
static struct srv_req *writers;     /* writes waiting for room */

/* input: the line being typed, and what's ready to read */
#define IN_SIZE 1024
static char line[256];
static int line_len;
static unsigned char in[IN_SIZE];
static unsigned in_rd, in_wr;
static int eof_pending;             /* ^D on an empty line */
static struct srv_req *readers;

static int mode;                    /* CONS_RAW, CONS_NOECHO */
static int fg_pgid;

static void tx_kick(void)
{
    int n = 0;
    while (out_rd != out_wr && (LSR & LSR_THRE) && n < 16) {
        /* the FIFO takes 16 at a time when THRE is set */
        int i;
        for (i = 0; i < 16 && out_rd != out_wr; i++)
            THR = out[out_rd++ % OUT_SIZE];
        n += 16;
    }
    IER = IER_RX | (out_rd != out_wr ? IER_TX : 0);
}

static int out_room(void)
{
    return OUT_SIZE - (out_wr - out_rd);
}

static void put(int c)
{
    if (out_room() > 0)
        out[out_wr++ % OUT_SIZE] = c;
}

static void putout(int c)
{
    if (c == '\n')
        put('\r');
    put(c);
}

/* Copy what fits of a write into the ring: how far it got. */
static int take_write(int rcvid, msg_t *m, unsigned done)
{
    int inl = m->w[0] == FS_WRITE_INLINE;
    unsigned n = inl ? m->w[2] : m->w[3];
    char buf[64];
    while (done < n && out_room() >= 2 * (int)sizeof buf) {
        unsigned k = n - done > sizeof buf ? sizeof buf : n - done, i;
        if (inl)
            memcpy(buf, (char *)&m->w[4] + done, k);
        else if (ipc_read(rcvid, (char *)m->w[2] + done, buf, k) < 0)
            return -EFAULT;
        for (i = 0; i < k; i++)
            putout(buf[i]);
        done += k;
    }
    return done;
}

static void run_writers(void)
{
    while (writers) {
        struct srv_req *r = writers;
        unsigned n = r->m.w[0] == FS_WRITE_INLINE ? r->m.w[2] : r->m.w[3];
        int done = take_write(r->rcvid, &r->m, r->done);
        if (done < 0) {
            srv_answer(&writers, r, done);
            continue;
        }
        r->done = done;
        if ((unsigned)done < n)
            break;
        srv_answer(&writers, r, n);
    }
    tx_kick();
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

static void in_put(int c)
{
    if (in_wr - in_rd < IN_SIZE)
        in[in_wr++ % IN_SIZE] = c;
}

static void echo(int c)
{
    if (!(mode & CONS_NOECHO))
        putout(c);
}

/* a byte typed */
static void typed(int c)
{
    if (mode & CONS_RAW) {
        in_put(c);
        return;
    }
    if (c == '\r')
        c = '\n';
    switch (c) {
    case 3:                         /* ^C */
        echo('^');
        echo('C');
        echo('\n');
        line_len = 0;
        if (fg_pgid > 0)
            proc_kill(-fg_pgid, 128 + 2);
        return;
    case 4:                         /* ^D */
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
        if (line_len > 0) {
            line_len--;
            echo('\b');
            echo(' ');
            echo('\b');
        }
        return;
    case 21:                        /* ^U */
        while (line_len > 0) {
            line_len--;
            echo('\b');
            echo(' ');
            echo('\b');
        }
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

static void interrupt(void)
{
    unsigned lsr;
    while ((lsr = LSR) & LSR_DR)
        typed(RBR & 0xFF);
    (void)IIR;
    run_readers();
    run_writers();
    irq_ack(UART_IRQ);
}

static void gone(int pid)
{
    srv_drop_pid(&readers, pid);
    srv_drop_pid(&writers, pid);
}

static int handle(int rcvid, int pid, msg_t *m)
{
    struct srv_file *f;
    if (m->w[0] == FS_OPEN)
        return srv_open(pid, 1, 0, m->w[3]);
    if (m->w[0] == FS_STAT) {
        struct stat st;
        memset(&st, 0, sizeof st);
        st.st_mode = S_IFCHR | 0666;
        return ipc_write(rcvid, (void *)m->w[3], &st, sizeof st) < 0 ? -EFAULT : 0;
    }
    f = srv_fd(pid, m->w[1]);
    if (!f)
        return -EBADF;
    switch (m->w[0]) {
    case FS_CLOSE:
        return srv_close(pid, m->w[1]);
    case FS_DUPTO:
        return srv_dupto(pid, m->w[1], m->w[2]);
    case FS_READ:
        srv_keep(&readers, rcvid, pid, m);
        run_readers();
        return 1 << 30;
    case FS_WRITE:
    case FS_WRITE_INLINE: {
        unsigned n = m->w[0] == FS_WRITE_INLINE ? m->w[2] : m->w[3];
        int done;
        if (writers) {
            srv_keep(&writers, rcvid, pid, m);
            return 1 << 30;
        }
        done = take_write(rcvid, m, 0);
        tx_kick();
        if (done < 0)
            return done;
        if ((unsigned)done < n) {
            struct srv_req *r = srv_keep(&writers, rcvid, pid, m);
            if (r)
                r->done = done;
            return 1 << 30;
        }
        return n;
    }
    case FS_FSTAT: {
        struct stat st;
        memset(&st, 0, sizeof st);
        st.st_mode = S_IFCHR | 0666;
        return ipc_write(rcvid, (void *)m->w[2], &st, sizeof st) < 0 ? -EFAULT : 0;
    }
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
            return 24 << 16 | 80;
        }
        return -EINVAL;
    case FS_SEEK:
        return -ESPIPE;
    }
    return -ENOSYS;
}

int main(void)
{
    msg_t m;
    int rcvid, pid, r;
    port = port_create();
    if (port < 0)
        return 1;
    if (vm_map_phys((void *)UART_VA, UART_PA, 1, PROT_READ | PROT_WRITE) < 0)
        return 2;
    srv_init(port, 0);
    /* 115,200 baud from 1.8432 MHz, 8 bits, no parity, one stop bit */
    LCR = 0x80;
    DLL = 1;
    DLM = 0;
    LCR = 0x03;
    FCR = 0x07 | 0x80;              /* FIFOs on and cleared; interrupt at 8 bytes */
    MCR = 0x0B;                     /* DTR, RTS, OUT2 */
    IER = IER_RX;
    if (irq_bind(UART_IRQ, port, UART_BIT) < 0)
        return 3;
    name_register("cons", port);
    for (;;) {
        rcvid = srv_recv(port, &m, &pid);
        if (rcvid == 0) {
            if (m.w[0] & SRV_EXIT_BIT)
                srv_exits(gone);
            if (m.w[0] & UART_BIT)
                interrupt();
            continue;
        }
        if (rcvid < 0)
            continue;
        r = handle(rcvid, pid, &m);
        if (r != 1 << 30) {
            m.w[0] = r;
            srv_reply_next(rcvid, &m);
        }
    }
}
