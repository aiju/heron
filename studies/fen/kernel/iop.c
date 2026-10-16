/* The I/O processor (studies/iop, RFC 0027), when the board has one: the
 * host says so in boot flag 2. The kernel waits for its cold start to be
 * done, then, through its own ring (client 0, which it polls: it has
 * nothing else to do yet), gives the file server a ring of its own,
 * client 1, in page 1 of the shared RAM, with a window onto all of RAM and
 * its completions at the CF card's level. The layouts are the IOP study's
 * (studies/iop/layout.py). */

#include "kernel.h"

#define SR 0xC0000000u          /* the shared RAM: physical 0x4000_0000 */
#define SR_PA 0x40000000u
#define H(a) (*(volatile u16 *)(a))
#define W(a) (*(volatile u32 *)(a))

#define S_READY 0               /* the status block */
#define S_SECTORS 4
#define STATUS_READY 0x494F
#define K_IDX 0x40              /* the kernel's rings */
#define K_REQ 0x1000
#define K_CMP 0x1400
#define K_REQ_MASK (64 * 16 - 1)
#define K_CMP_MASK (64 * 8 - 1)
#define I_REQHEAD 0
#define I_CMPHEAD 4
#define I_CMPTAIL 6
#define OP_RING 17
#define OP_WINDOW 18

#define FS_RING 0x10000         /* client 1's: requests (64) at +0, completions (64) at +0x400, indices at +0x600 */
#define SETTINGS 0x100          /* where OP_RING's settings go */
#define FS_LEVEL 5              /* RFC 0029's level 5: the board's bit 4, the CF card's */

u32 iop_sectors;
static u32 khead, ktail;

/* A request on the kernel's ring, and its completion's status. */
static int kreq(u32 op, u32 a, u32 b, u32 len)
{
    u32 e = SR + K_REQ + khead, st;
    W(e) = op;
    W(e + 4) = a;
    W(e + 8) = b;
    W(e + 12) = len;
    khead = (khead + 16) & K_REQ_MASK;
    H(SR + K_IDX + I_REQHEAD) = khead;
    W(PHYS(0x74000000)) = 0;    /* doorbell 0 */
    while (H(SR + K_IDX + I_CMPHEAD) == ktail)
        ;
    st = H(SR + K_CMP + ktail + 2);
    ktail = (ktail + 8) & K_CMP_MASK;
    H(SR + K_IDX + I_CMPTAIL) = ktail;
    return st;
}

void iop_init(void)
{
    u32 s = SR + SETTINGS, i;
    int st;
    if (!(INFO_FLAGS & 2))
        return;
    while (H(SR + S_READY) != STATUS_READY)
        ;
    iop_sectors = H(SR + S_SECTORS) | (u32)H(SR + S_SECTORS + 2) << 16;
    for (i = 0; i < 8; i += 2)
        H(SR + FS_RING + 0x600 + i) = 0;
    H(s) = FS_RING & 0xFFFF;    /* requests: address, bytes */
    H(s + 2) = (SR_PA + FS_RING) >> 16;
    H(s + 4) = 64 * 16;
    H(s + 6) = (FS_RING + 0x400) & 0xFFFF;      /* completions */
    H(s + 8) = (SR_PA + FS_RING) >> 16;
    H(s + 10) = 64 * 8;
    H(s + 12) = (FS_RING + 0x600) & 0xFFFF;     /* indices */
    H(s + 14) = (SR_PA + FS_RING) >> 16;
    H(s + 16) = FS_LEVEL;       /* level | CPU 0 << 8, not held */
    H(s + 18) = 0;
    st = kreq(OP_RING, SR_PA + SETTINGS, 1, 0);
    if (!st)
        st = kreq(OP_WINDOW | 1 << 16, 0, ram_size, 0);
    if (st)
        panic("the IOP refused the file server's ring: %d", st);
    kprintf("IOP: %u KB disk\n", iop_sectors / 2);
}
