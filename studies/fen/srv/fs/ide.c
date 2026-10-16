/* The CompactFlash card in True IDE mode, from user space: its page of
 * registers mapped into the file server (vm_map_phys), its interrupt a
 * notification (irq_bind), LBA addressing and PIO transfers of 16 bits.
 * Waiting for the card is waiting for its interrupt (main.c's wait_irq),
 * so the file server can't busy itself with anything else meanwhile; what
 * comes in is kept for afterwards. */

#include <fen/sys.h>
#include "fs.h"

#define IDE_PA 0x20001000       /* the I/O card's CF page (studies/fen/board) */
#define IDE_VA 0x00EFF000
#define IDE_IRQ 4

#define R(n) (*(volatile unsigned *)(IDE_VA + 4 * (n)))
#define DATA ((volatile unsigned short *)IDE_VA)
#define R_ERROR R(1)
#define R_COUNT R(2)
#define R_LBA0 R(3)
#define R_LBA1 R(4)
#define R_LBA2 R(5)
#define R_HEAD R(6)
#define R_STATUS R(7)
#define R_CMD R(7)
#define R_ALT R(8 + 6)          /* CS1: alternate status, and device control */

#define BSY 0x80
#define DRDY 0x40
#define DRQ 0x08
#define ERR 0x01

void ide_in(volatile unsigned short *reg, void *buf, unsigned words);
void ide_out(volatile unsigned short *reg, const void *buf, unsigned words);

unsigned ide_sectors;

static int wait_ready(void)
{
    int n = 0;
    while (R_ALT & BSY)
        if (++n > 1000000)
            return -EIO;
    return 0;
}

/* the card's interrupt: wait for it, then read the status, which clears it */
static int wait_card(void)
{
    unsigned st;
    wait_irq(IDE_BIT);
    st = R_STATUS & 0xFF;
    irq_ack(IDE_IRQ);
    if (st & ERR)
        return -EIO;
    return st;
}

static void command(unsigned lba, int sectors, int cmd)
{
    R_COUNT = sectors;
    R_LBA0 = lba;
    R_LBA1 = lba >> 8;
    R_LBA2 = lba >> 16;
    R_HEAD = 0xE0 | ((lba >> 24) & 15);
    R_CMD = cmd;
}

int ide_init(void)
{
    static unsigned short id[256];
    int e, port;
    extern int fs_port;
    port = fs_port;
    e = vm_map_phys((void *)IDE_VA, IDE_PA, 1, PROT_READ | PROT_WRITE);
    if (e < 0)
        return e;
    e = irq_bind(IDE_IRQ, port, IDE_BIT);
    if (e < 0)
        return e;
    R_ALT = 0;                  /* nIEN clear: interrupts on */
    if (wait_ready() < 0)
        return -EIO;
    R_HEAD = 0xE0;
    R_CMD = 0xEC;               /* IDENTIFY DEVICE */
    if ((e = wait_card()) < 0)
        return e;
    ide_in(DATA, id, 128);
    ide_sectors = id[60] | (unsigned)id[61] << 16;
    return 0;
}

int ide_read(unsigned lba, void *buf, int sectors)
{
    unsigned char *p = buf;
    int e;
    if (wait_ready() < 0)
        return -EIO;
    command(lba, sectors, 0x20);    /* READ SECTORS */
    while (sectors--) {
        if ((e = wait_card()) < 0)
            return e;
        ide_in(DATA, p, 128);
        p += 512;
    }
    return 0;
}

int ide_write(unsigned lba, const void *buf, int sectors)
{
    const unsigned char *p = buf;
    int e;
    if (wait_ready() < 0)
        return -EIO;
    command(lba, sectors, 0x30);    /* WRITE SECTORS: no interrupt before the first */
    while (!(R_ALT & DRQ))
        if (R_ALT & ERR)
            return -EIO;
    while (sectors--) {
        ide_out(DATA, p, 128);
        p += 512;
        if ((e = wait_card()) < 0)
            return e;
    }
    return 0;
}
