/* The keyboard and the mouse: the I/O card's two PS/2 ports
 * (studies/fen/board/src/ps2.rs), their page mapped into the window
 * system and their interrupt (level 3) a notification. At start-up each
 * device is reset and enabled, waiting for its answers; after that every
 * byte comes by interrupt. The keyboard speaks scan code set 2, which is
 * turned into characters with a US layout; the mouse sends 3-byte
 * packets. */

#include <fen/sys.h>
#include <fen/wsys.h>
#include "wsys.h"

#define PS2_PA 0x20002000
#define PS2_VA 0x00A01000
#define KBD_DATA (*(volatile unsigned *)(PS2_VA))
#define KBD_STAT (*(volatile unsigned *)(PS2_VA + 4))
#define MOUSE_DATA (*(volatile unsigned *)(PS2_VA + 0x10))
#define MOUSE_STAT (*(volatile unsigned *)(PS2_VA + 0x14))
#define RX 1
#define IE 4

/* a byte from a port, waiting at most `ms` */
static int get(volatile unsigned *data, volatile unsigned *stat, int ms)
{
    while (!(*stat & RX)) {
        if (ms-- <= 0)
            return -1;
        sleep_us(1000);
    }
    return *data & 0xFF;
}

/* send a command, and wait for its ACK and the bytes after it */
static int command(volatile unsigned *data, volatile unsigned *stat, int cmd, int answers)
{
    int i;
    *data = cmd;
    if (get(data, stat, 50) != 0xFA)
        return -1;
    for (i = 0; i < answers; i++)
        if (get(data, stat, 50) < 0)
            return -1;
    return 0;
}

int input_init(void)
{
    int e = vm_map_phys((void *)PS2_VA, PS2_PA, 1, PROT_READ | PROT_WRITE);
    if (e < 0)
        return e;
    /* the keyboard: reset (ACK, then AA for its self-test) */
    command(&KBD_DATA, &KBD_STAT, 0xFF, 1);
    command(&KBD_DATA, &KBD_STAT, 0xF4, 0);
    /* the mouse: reset (ACK, AA, its id 00), 40 samples a second, on */
    command(&MOUSE_DATA, &MOUSE_STAT, 0xFF, 2);
    command(&MOUSE_DATA, &MOUSE_STAT, 0xF3, 0);
    command(&MOUSE_DATA, &MOUSE_STAT, 40, 0);
    command(&MOUSE_DATA, &MOUSE_STAT, 0xF4, 0);
    KBD_STAT = IE;
    MOUSE_STAT = IE;
    return 0;
}

/* ---- the keyboard ---- */

/* set 2 make codes to characters, unshifted and shifted */
static const char plain[0x80] = {
    [0x1C] = 'a', [0x32] = 'b', [0x21] = 'c', [0x23] = 'd', [0x24] = 'e', [0x2B] = 'f',
    [0x34] = 'g', [0x33] = 'h', [0x43] = 'i', [0x3B] = 'j', [0x42] = 'k', [0x4B] = 'l',
    [0x3A] = 'm', [0x31] = 'n', [0x44] = 'o', [0x4D] = 'p', [0x15] = 'q', [0x2D] = 'r',
    [0x1B] = 's', [0x2C] = 't', [0x3C] = 'u', [0x2A] = 'v', [0x1D] = 'w', [0x22] = 'x',
    [0x35] = 'y', [0x1A] = 'z',
    [0x45] = '0', [0x16] = '1', [0x1E] = '2', [0x26] = '3', [0x25] = '4', [0x2E] = '5',
    [0x36] = '6', [0x3D] = '7', [0x3E] = '8', [0x46] = '9',
    [0x0E] = '`', [0x4E] = '-', [0x55] = '=', [0x54] = '[', [0x5B] = ']', [0x5D] = '\\',
    [0x4C] = ';', [0x52] = '\'', [0x41] = ',', [0x49] = '.', [0x4A] = '/', [0x29] = ' ',
    [0x66] = 8, [0x0D] = 9, [0x5A] = 13, [0x76] = 27, [0x61] = '\\',
};

static const char shifted[0x80] = {
    [0x1C] = 'A', [0x32] = 'B', [0x21] = 'C', [0x23] = 'D', [0x24] = 'E', [0x2B] = 'F',
    [0x34] = 'G', [0x33] = 'H', [0x43] = 'I', [0x3B] = 'J', [0x42] = 'K', [0x4B] = 'L',
    [0x3A] = 'M', [0x31] = 'N', [0x44] = 'O', [0x4D] = 'P', [0x15] = 'Q', [0x2D] = 'R',
    [0x1B] = 'S', [0x2C] = 'T', [0x3C] = 'U', [0x2A] = 'V', [0x1D] = 'W', [0x22] = 'X',
    [0x35] = 'Y', [0x1A] = 'Z',
    [0x45] = ')', [0x16] = '!', [0x1E] = '@', [0x26] = '#', [0x25] = '$', [0x2E] = '%',
    [0x36] = '^', [0x3D] = '&', [0x3E] = '*', [0x46] = '(',
    [0x0E] = '~', [0x4E] = '_', [0x55] = '+', [0x54] = '{', [0x5B] = '}', [0x5D] = '|',
    [0x4C] = ':', [0x52] = '"', [0x41] = '<', [0x49] = '>', [0x4A] = '?', [0x29] = ' ',
    [0x66] = 8, [0x0D] = 9, [0x5A] = 13, [0x76] = 27, [0x61] = '|',
};

static const unsigned char fkeys[12] = {
    0x05, 0x06, 0x04, 0x0C, 0x03, 0x0B, 0x83, 0x0A, 0x01, 0x09, 0x78, 0x07,
};

static int mods, caps, ext, brk;

static void kbd_byte(int b, void (*key)(int, int, int))
{
    int code = 0, down, i;
    if (b == 0xE0) {
        ext = 1;
        return;
    }
    if (b == 0xF0) {
        brk = 1;
        return;
    }
    if (b == 0xFA || b == 0xAA || b == 0xFE)
        return;
    down = !brk;
    brk = 0;
    if (ext) {
        ext = 0;
        switch (b) {
        case 0x75: code = KEY_UP; break;
        case 0x72: code = KEY_DOWN; break;
        case 0x6B: code = KEY_LEFT; break;
        case 0x74: code = KEY_RIGHT; break;
        case 0x6C: code = KEY_HOME; break;
        case 0x69: code = KEY_END; break;
        case 0x7D: code = KEY_PGUP; break;
        case 0x7A: code = KEY_PGDN; break;
        case 0x70: code = KEY_INS; break;
        case 0x71: code = KEY_DEL; break;
        case 0x5A: code = 13; break;
        case 0x4A: code = '/'; break;
        case 0x14: mods = down ? mods | MOD_CTRL : mods & ~MOD_CTRL; return;
        case 0x11: mods = down ? mods | MOD_ALT : mods & ~MOD_ALT; return;
        case 0x1F:
        case 0x27: mods = down ? mods | MOD_META : mods & ~MOD_META; return;
        default: return;
        }
        key(code, mods, down);
        return;
    }
    switch (b) {
    case 0x12:
    case 0x59: mods = down ? mods | MOD_SHIFT : mods & ~MOD_SHIFT; return;
    case 0x14: mods = down ? mods | MOD_CTRL : mods & ~MOD_CTRL; return;
    case 0x11: mods = down ? mods | MOD_ALT : mods & ~MOD_ALT; return;
    case 0x58:
        if (down)
            caps = !caps;
        return;
    }
    for (i = 0; i < 12; i++)
        if (b == fkeys[i]) {
            key(KEY_F1 + i, mods, down);
            return;
        }
    if (b >= 0x80)
        return;
    {
        int shift = (mods & MOD_SHIFT) != 0;
        if (caps && plain[b] >= 'a' && plain[b] <= 'z')
            shift = !shift;
        code = shift ? shifted[b] : plain[b];
    }
    if (code)
        key(code, mods, down);
}

/* ---- the mouse ---- */

static unsigned char pkt[3];
static int npkt;

static void mouse_byte(int b, void (*mouse)(int, int, int))
{
    if (npkt == 0 && !(b & 8))
        return;                 /* out of step: wait for a first byte */
    pkt[npkt++] = b;
    if (npkt < 3)
        return;
    npkt = 0;
    {
        int dx = pkt[1] - ((pkt[0] << 4) & 0x100);
        int dy = pkt[2] - ((pkt[0] << 3) & 0x100);
        mouse(dx, -dy, pkt[0] & 7);
    }
}

void input_poll(void (*key)(int code, int mods, int down),
                void (*mouse)(int dx, int dy, int buttons))
{
    int again = 1;
    while (again) {
        again = 0;
        if (KBD_STAT & RX) {
            kbd_byte(KBD_DATA & 0xFF, key);
            again = 1;
        }
        if (MOUSE_STAT & RX) {
            mouse_byte(MOUSE_DATA & 0xFF, mouse);
            again = 1;
        }
    }
    irq_ack(3);
}
