/* The block cache: NBUF blocks, the least recently used one reused. Writes
 * go to the card at once (write-through), so the card is always up to
 * date and nothing is lost when the machine stops. */

#include <string.h>
#include "fs.h"

#define NBUF 96

static struct buf bufs[NBUF];
static unsigned clock_;
unsigned cache_hits, cache_misses;

struct buf *bread(unsigned blk)
{
    struct buf *b, *lru = 0;
    int i;
    for (i = 0; i < NBUF; i++) {
        b = &bufs[i];
        if (b->valid && b->blk == blk) {
            b->used = ++clock_;
            cache_hits++;
            return b;
        }
        if (!lru || !b->valid || (lru->valid && b->used < lru->used))
            lru = b;
    }
    cache_misses++;
    b = lru;
    if (b->valid && b->dirty)
        bwrite(b);
    b->valid = 0;
    if (ide_read(blk * 2, b->data, 2) < 0)
        return 0;
    b->blk = blk;
    b->valid = 1;
    b->dirty = 0;
    b->used = ++clock_;
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
