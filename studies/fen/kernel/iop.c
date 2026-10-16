/* The I/O processor (studies/iop, RFC 0027; its rings as RFC 0040, 5),
 * when the board has one: the host says so in boot flag 2. The kernel
 * waits for its cold start to be done, then, through its own ring (client
 * 0, which it polls: it has nothing else to do yet), asks for its
 * completion ring, in a page of its own RAM, and gives the file server a
 * request ring of its own, client 1, in page 1 of the shared RAM, with a
 * window onto all of RAM and its completions' event (SRC_RING + 1) at the
 * CF card's level, slow. The file server asks for its completion ring
 * itself. The layouts are the IOP study's (studies/iop/layout.py). */

#include "kernel.h"

#define SR 0xC0000000u          /* the shared RAM: physical 0x4000_0000 */
#define SR_PA 0x40000000u
#define H(a) (*(volatile u16 *)(a))
#define W(a) (*(volatile u32 *)(a))

#define S_READY 0               /* the status block */
#define S_SECTORS 4
#define STATUS_READY 0x494F
#define RING_HEAD 0             /* a ring: its head, its tail, its entries */
#define RING_TAIL 4
#define RING_ENTRIES 8
#define K_REQ 0x1000            /* the kernel's request ring, 64 requests */
#define K_N 64
#define OP_RING 17
#define OP_WINDOW 18
#define OP_ROUTE 19
#define OP_CMPRING 23
#define SRC_RING 32
#define SLOW 1

#define FS_RING 0x10000         /* client 1's request ring, 64 requests */
#define SETTINGS 0x100          /* where OP_RING's settings go */
#define FS_LEVEL 5              /* RFC 0029's level 5: the board's bit 4, the CF card's */

u32 iop_sectors;
static u32 khead, ktail, kcmp;

/* A request on the kernel's ring, and its completion's status. */
static int kreq(u32 op, u32 a, u32 b, u32 len)
{
    u32 e = SR + K_REQ + RING_ENTRIES + 16 * (khead % K_N), c = (u32)PHYS(kcmp), st;
    W(e) = op;
    W(e + 4) = a;
    W(e + 8) = b;
    W(e + 12) = len;
    H(SR + K_REQ + RING_HEAD) = ++khead;
    W(PHYS(0x74000000)) = 0;    /* doorbell 0 */
    while (H(c + RING_HEAD) == (u16)ktail)
        ;
    st = H(c + RING_ENTRIES + 8 * (ktail % K_N) + 2);
    H(c + RING_TAIL) = ++ktail;
    return st;
}

void iop_init(void)
{
    u32 s = SR + SETTINGS;
    int st;
    if (!(INFO_FLAGS & 2))
        return;
    while (H(SR + S_READY) != STATUS_READY)
        ;
    iop_sectors = H(SR + S_SECTORS) | (u32)H(SR + S_SECTORS + 2) << 16;
    kcmp = page_alloc();
    if (!kcmp)
        panic("no page for the IOP's completions");
    st = kreq(OP_CMPRING, kcmp, 0, K_N);
    W(SR + FS_RING + RING_HEAD) = 0;    /* the file server's head, and its events handled */
    H(s) = FS_RING & 0xFFFF;    /* requests: address, entries */
    H(s + 2) = (SR_PA + FS_RING) >> 16;
    H(s + 4) = 64;
    H(s + 6) = 0;               /* no completion ring yet */
    H(s + 8) = 0;
    H(s + 10) = 0;
    if (!st)
        st = kreq(OP_RING, SR_PA + SETTINGS, 1, 0);
    if (!st)
        st = kreq(OP_WINDOW | 1 << 16, 0, ram_size, 0);
    if (!st)
        st = kreq(OP_ROUTE | SLOW << 16, 0, (SRC_RING + 1) | FS_LEVEL << 16, 0);
    if (st)
        panic("the IOP refused the file server's ring: %d", st);
    kprintf("IOP: %u KB disk\n", iop_sectors / 2);
}
