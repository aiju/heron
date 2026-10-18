/* The keyboard and the mouse over UART 1 (input.h): the packets parsed in
   the interrupt into a queue of events. Mouse moves with the same buttons
   are merged into the last queued event, so a burst of them doesn't fill
   the queue. */

#include "mini.h"
#include "input.h"

#define QSIZE 64

static Event q[QSIZE];
static volatile int qhead, qtail;   /* the interrupt adds at qtail */
static unsigned char keys[16];      /* a bit a key */
static int mods;
static unsigned char pkt[6];
static int plen, pwant;
volatile int mouse_x, mouse_y, mouse_buttons;

extern void (*rt_uart1_irq)(void);

/* the US keyboard's shifted characters, from ' ' to '~' */
static const char shifted[] =
    " !\"#$%&\"()*+<_>?)!@#$%^&*(::<+>?@ABCDEFGHIJKLMNOPQRSTUVWXYZ{|}^_~ABCDEFGHIJKLMNOPQRSTUVWXYZ{|}~";

static void push(int type, int key, int ch)
{
    int n = (qtail + 1) % QSIZE;
    Event *e;
    if (type == EV_MOUSE && qtail != qhead) {
        e = &q[(qtail + QSIZE - 1) % QSIZE];
        if (e->type == EV_MOUSE && e->buttons == mouse_buttons) {
            e->x = mouse_x;
            e->y = mouse_y;
            return;
        }
    }
    if (n == qhead)
        return;                 /* full: dropped */
    e = &q[qtail];
    e->type = type;
    e->key = key;
    e->ch = ch;
    e->mods = mods;
    e->x = mouse_x;
    e->y = mouse_y;
    e->buttons = mouse_buttons;
    qtail = n;
}

static int translate(int k)
{
    if (k == K_ENTER || k == K_BACKSPACE || k == K_TAB || k == K_ESC)
        return k;
    if (k < ' ' || k > '~')
        return 0;
    if ((mods & M_CTRL) && k >= 'a' && k <= 'z')
        return k - 'a' + 1;
    if (mods & M_SHIFT)
        return shifted[k - ' '];
    return k;
}

static void key(int k, int down)
{
    int m = k == K_SHIFT ? M_SHIFT : k == K_CTRL ? M_CTRL : k == K_ALT ? M_ALT : 0;
    if (down) {
        keys[k >> 3] |= 1 << (k & 7);
        mods |= m;
        push(EV_KEY, k, translate(k));
    } else {
        keys[k >> 3] &= ~(1 << (k & 7));
        mods &= ~m;
        push(EV_KEYUP, k, 0);
    }
}

static void packet(void)
{
    if (pkt[0] == 0x80 || pkt[0] == 0x81) {
        key(pkt[1], pkt[0] == 0x80);
    } else if (pkt[0] == 0x82) {
        mouse_buttons = pkt[1];
        mouse_x = pkt[2] | pkt[3] << 7;
        mouse_y = pkt[4] | pkt[5] << 7;
        push(EV_MOUSE, 0, 0);
    }
}

static void uart1_irq(void)
{
    int c;
    while (UART1(5) & 1) {
        c = UART1(0) & 0xFF;
        if (c & 0x80) {
            pkt[0] = c;
            plen = 1;
            pwant = c == 0x82 ? 6 : c == 0x80 || c == 0x81 ? 2 : 0;
        } else if (plen > 0 && plen < pwant) {
            pkt[plen++] = c;
        } else {
            continue;
        }
        if (plen == pwant) {
            packet();
            plen = 0;
        }
    }
}

void input_init(void)
{
    UART1(3) = 0x03;            /* 8 bits, no parity, 1 stop bit */
    rt_uart1_irq = uart1_irq;
    UART1(1) = 0x01;            /* the receive interrupt */
}

int input_next(Event *e)
{
    if (qhead == qtail)
        return 0;
    *e = q[qhead];
    qhead = (qhead + 1) % QSIZE;
    return 1;
}

int key_down(int k)
{
    return (keys[(k >> 3) & 15] >> (k & 7)) & 1;
}
