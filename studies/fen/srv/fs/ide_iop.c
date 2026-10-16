/* The disk through the I/O processor (studies/iop, RFC 0027, 7; RFC
 * 0040, 5): the file server's request ring, client 1's, which the kernel
 * set up in page 1 of the shared RAM (kernel/iop.c), mapped here with the
 * doorbells' page and the IOP's status block; its completion ring, in a
 * page of its own that it asks the IOP for. Its completions' event is the
 * CF card's level, which the IOP raises in the board's interrupt request
 * register (RFC 0037, 8), and which this clears there, mapped too, then
 * says it has handled the event (the completion ring's count of them
 * copied to the request ring's), before it looks.
 * A read or a write is a request for each piece of the buffer that's
 * contiguous in physical memory (vm_phys), the IOP moving the sectors
 * straight between the card and RAM, and waits for its completion. A
 * sector that would cross a page goes through a page of its own. */

#include <string.h>
#include <fen/sys.h>
#include "fs.h"

#define RING_PA 0x40010000
#define BELL_PA 0x74000000
#define STATUS_PA 0x40000000
#define IREQ_PA 0x70002000      /* +0 set, +4 clear, +8 read */
#define RING_VA 0x00EF0000
#define BELL_VA 0x00EF1000
#define STATUS_VA 0x00EF2000
#define BOUNCE_VA 0x00EF3000
#define IREQ_VA 0x00EF4000
#define CMP 0x00EF5000
#define IDE_IRQ 4

#define H(a) (*(volatile unsigned short *)(a))
#define W(a) (*(volatile unsigned *)(a))
#define REQ RING_VA
#define RING_HEAD 0             /* a ring: its head, events for its completions, */
#define RING_EVENTS 2           /* its tail, its entries (64 in each of ours) */
#define RING_TAIL 4
#define RING_ENTRIES 8
#define N 64
#define S_SECTORS 4
#define OP_READ 4
#define OP_WRITE 5
#define OP_CMPRING 23
#define PAGE 4096

unsigned ide_sectors;
static unsigned head, tail, tag;
static unsigned bounce_pa;

static int request(unsigned op, unsigned pa, unsigned lba, unsigned bytes);

int ide_init(void)
{
    extern int fs_port;
    int e;
    if ((e = vm_map_phys((void *)RING_VA, RING_PA, 1, PROT_READ | PROT_WRITE)) < 0 ||
        (e = vm_map_phys((void *)BELL_VA, BELL_PA, 1, PROT_READ | PROT_WRITE)) < 0 ||
        (e = vm_map_phys((void *)STATUS_VA, STATUS_PA, 1, PROT_READ)) < 0 ||
        (e = vm_map_phys((void *)IREQ_VA, IREQ_PA, 1, PROT_READ | PROT_WRITE)) < 0 ||
        (e = vm_alloc(0, (void *)BOUNCE_VA, 1, PROT_READ | PROT_WRITE)) < 0 ||
        (e = vm_alloc(0, (void *)CMP, 1, PROT_READ | PROT_WRITE)) < 0)
        return e;
    W(BOUNCE_VA) = 0;           /* there, so that they have pages */
    W(CMP) = 0;
    bounce_pa = vm_phys((void *)BOUNCE_VA);
    e = irq_bind(IDE_IRQ, fs_port, IDE_BIT);
    if (e < 0)
        return e;
    if ((e = request(OP_CMPRING, vm_phys((void *)CMP), 0, N)) < 0)
        return e;
    ide_sectors = H(STATUS_VA + S_SECTORS) | (unsigned)H(STATUS_VA + S_SECTORS + 2) << 16;
    return ide_sectors ? 0 : -EIO;
}

/* One request, and its completion: 0, or -EIO. */
static int request(unsigned op, unsigned pa, unsigned lba, unsigned bytes)
{
    unsigned e = REQ + RING_ENTRIES + 16 * (head % N), t = ++tag & 0xFFFF;
    W(e) = op;
    W(e + 4) = pa;
    W(e + 8) = lba;
    W(e + 12) = bytes | t << 16;
    H(REQ + RING_HEAD) = ++head;
    W(BELL_VA + 4) = 0;         /* doorbell 1 */
    for (;;) {
        while (H(CMP + RING_HEAD) != (tail & 0xFFFF)) {
            unsigned c = CMP + RING_ENTRIES + 8 * (tail % N), ct = H(c), st = H(c + 2);
            H(CMP + RING_TAIL) = ++tail;
            if (ct == t)
                return st ? -EIO : 0;
        }
        wait_irq(IDE_BIT);
        W(IREQ_VA + 4) = 1 << IDE_IRQ;  /* cleared, */
        H(REQ + RING_EVENTS) = H(CMP + RING_EVENTS);    /* the event handled, */
        irq_ack(IDE_IRQ);               /* and from now on raising it again: a completion */
    }
}

/* The sectors at buf: as many as are contiguous in physical memory from
 * it, or one through the bounce page. */
static int transfer(unsigned op, unsigned lba, unsigned char *buf, int sectors, int *done)
{
    unsigned va = (unsigned)buf, room = PAGE - (va & (PAGE - 1));
    int n = room / 512, pa, e;
    if (n == 0) {
        if (op == OP_WRITE)
            memcpy((void *)BOUNCE_VA, buf, 512);
        e = request(op, bounce_pa, lba, 512);
        if (!e && op == OP_READ)
            memcpy(buf, (void *)BOUNCE_VA, 512);
        *done = 1;
        return e;
    }
    if (n > sectors)
        n = sectors;
    pa = vm_phys(buf);
    if (pa < 0)
        return -EIO;
    *done = n;
    return request(op, pa, lba, n * 512);
}

static int io(unsigned op, unsigned lba, unsigned char *p, int sectors)
{
    int n, e;
    while (sectors > 0) {
        if ((e = transfer(op, lba, p, sectors, &n)) < 0)
            return e;
        lba += n;
        p += n * 512;
        sectors -= n;
    }
    return 0;
}

int ide_read(unsigned lba, void *buf, int sectors)
{
    return io(OP_READ, lba, buf, sectors);
}

int ide_write(unsigned lba, const void *buf, int sectors)
{
    return io(OP_WRITE, lba, (unsigned char *)buf, sectors);
}
