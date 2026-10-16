/* The block cache: NBUF blocks, found by a hash of the block number, the
 * least recently used one reused. Writes
 * go to the card at once (write-through), so the card is always up to
 * date and nothing is lost when the machine stops. */

#include <string.h>
#include <fen/sys.h>
#include "fs.h"

#define NBUF 96
#define NHASH 64

static struct buf bufs[NBUF];
#ifdef IOP_DISK
#define CACHE_VA 0x00E00000     /* NBUF blocks, page aligned */
#endif
static struct buf *hash[NHASH];
static struct buf *newest, *oldest;     /* the list by last use */
unsigned cache_hits, cache_misses;

static void unlink_use(struct buf *b)
{
    if (b->newer)
        b->newer->older = b->older;
    else
        newest = b->older;
    if (b->older)
        b->older->newer = b->newer;
    else
        oldest = b->newer;
}

static void make_newest(struct buf *b)
{
    b->newer = 0;
    b->older = newest;
    if (newest)
        newest->newer = b;
    newest = b;
    if (!oldest)
        oldest = b;
}

static void unhash(struct buf *b)
{
    struct buf **pp;
    for (pp = &hash[b->blk % NHASH]; *pp; pp = &(*pp)->hnext)
        if (*pp == b) {
            *pp = b->hnext;
            return;
        }
}

struct buf *bread(unsigned blk)
{
    struct buf *b;
    int i;
    if (!newest) {
#ifdef IOP_DISK
        if (vm_alloc(0, (void *)CACHE_VA, NBUF * BLOCK / 4096, PROT_READ | PROT_WRITE) < 0)
            return 0;
        for (i = 0; i < NBUF; i++)
            bufs[i].data = (unsigned char *)CACHE_VA + i * BLOCK;
#endif
        for (i = 0; i < NBUF; i++)
            make_newest(&bufs[i]);
    }
    for (b = hash[blk % NHASH]; b; b = b->hnext)
        if (b->blk == blk) {
            unlink_use(b);
            make_newest(b);
            cache_hits++;
            return b;
        }
    cache_misses++;
    b = oldest;
    if (b->valid) {
        if (b->dirty)
            bwrite(b);
        unhash(b);
        b->valid = 0;
    }
    unlink_use(b);
    make_newest(b);
    if (ide_read(blk * 2, b->data, 2) < 0)
        return 0;
    b->blk = blk;
    b->valid = 1;
    b->dirty = 0;
    b->hnext = hash[blk % NHASH];
    hash[blk % NHASH] = b;
    return b;
}

int bwrite(struct buf *b)
{
    b->dirty = 0;
    return ide_write(b->blk * 2, b->data, 2);
}

void bdirty(struct buf *b)
{
    bwrite(b);
}

int bsync(void)
{
    int i, e = 0;
    for (i = 0; i < NBUF; i++)
        if (bufs[i].valid && bufs[i].dirty && bwrite(&bufs[i]) < 0)
            e = -EIO;
    return e;
}
