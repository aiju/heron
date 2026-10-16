/* The file system (fen/fenfs.h): inodes, block maps, directories, paths.
 * Inodes in use are kept in memory, counted; an inode with no links and
 * no users is freed when its last user lets go. */

#include <string.h>
#include <time.h>
#include <fen/fs.h>
#include <fen/sys.h>
#include "fs.h"

struct fenfs_super sb;

#define NINODE 64
static struct inode inodes[NINODE];
static unsigned bitmap_hint;

unsigned fs_now(void)
{
    return time(0);
}

int fs_mount(void)
{
    struct buf *b = bread(1);
    if (!b)
        return -EIO;
    memcpy(&sb, b->data, sizeof sb);
    if (sb.magic != FENFS_MAGIC)
        return -EINVAL;
    bitmap_hint = sb.data_start;
    return 0;
}

/* ---- blocks ---- */

static unsigned balloc(void)
{
    unsigned i, n = sb.nblocks;
    for (i = 0; i < n; i++) {
        unsigned blk = bitmap_hint + i;
        struct buf *b;
        unsigned bit;
        if (blk >= n)
            blk -= n - sb.data_start;
        if (blk < sb.data_start)
            continue;
        b = bread(sb.bitmap_start + blk / (BLOCK * 8));
        if (!b)
            return 0;
        bit = blk % (BLOCK * 8);
        if (!(b->data[bit / 8] & (1 << (bit % 8)))) {
            struct buf *z;
            b->data[bit / 8] |= 1 << (bit % 8);
            bdirty(b);
            bitmap_hint = blk + 1;
            z = bread(blk);
            if (!z)
                return 0;
            memset(z->data, 0, BLOCK);
            bdirty(z);
            return blk;
        }
    }
    return 0;
}

static void bfree(unsigned blk)
{
    struct buf *b;
    unsigned bit;
    if (blk < sb.data_start || blk >= sb.nblocks)
        return;
    b = bread(sb.bitmap_start + blk / (BLOCK * 8));
    if (!b)
        return;
    bit = blk % (BLOCK * 8);
    b->data[bit / 8] &= ~(1 << (bit % 8));
    bdirty(b);
    if (blk < bitmap_hint)
        bitmap_hint = blk;
}

int fs_free_blocks(void)
{
    unsigned blk, n = 0;
    for (blk = sb.data_start; blk < sb.nblocks; blk++) {
        struct buf *b = bread(sb.bitmap_start + blk / (BLOCK * 8));
        unsigned bit = blk % (BLOCK * 8);
        if (b && !(b->data[bit / 8] & (1 << (bit % 8))))
            n++;
    }
    return n;
}

/* ---- inodes ---- */

static struct buf *inode_block(unsigned ino, struct fenfs_inode **dp)
{
    struct buf *b = bread(sb.inode_start + ino / FENFS_INODES_PER_BLOCK);
    if (b)
        *dp = (struct fenfs_inode *)b->data + ino % FENFS_INODES_PER_BLOCK;
    return b;
}

struct inode *iget(unsigned ino)
{
    struct inode *ip, *free = 0;
    struct fenfs_inode *d;
    struct buf *b;
    int i;
    if (ino == 0 || ino >= sb.ninodes)
        return 0;
    for (i = 0; i < NINODE; i++) {
        ip = &inodes[i];
        if (ip->refs && ip->ino == ino) {
            ip->refs++;
            return ip;
        }
        if (!ip->refs && !free)
            free = ip;
    }
    if (!free)
        return 0;
    b = inode_block(ino, &d);
    if (!b)
        return 0;
    free->ino = ino;
    free->refs = 1;
    free->d = *d;
    return free;
}

int iupdate(struct inode *ip)
{
    struct fenfs_inode *d;
    struct buf *b = inode_block(ip->ino, &d);
    if (!b)
        return -EIO;
    *d = ip->d;
    bdirty(b);
    return 0;
}

void iput(struct inode *ip)
{
    if (!ip)
        return;
    if (ip->refs == 1 && ip->d.nlink == 0 && ip->d.mode) {
        itrunc(ip, 0);
        ip->d.mode = 0;
        iupdate(ip);
    }
    ip->refs--;
}

struct inode *ialloc(unsigned mode)
{
    unsigned ino;
    for (ino = FENFS_ROOT + 1; ino < sb.ninodes; ino++) {
        struct fenfs_inode *d;
        struct buf *b = inode_block(ino, &d);
        if (!b)
            return 0;
        if (d->mode == 0) {
            memset(d, 0, sizeof *d);
            d->mode = mode;
            d->mtime = fs_now();
            bdirty(b);
            return iget(ino);
        }
    }
    return 0;
}

int fs_free_inodes(void)
{
    unsigned ino, n = 0;
    for (ino = FENFS_ROOT + 1; ino < sb.ninodes; ino++) {
        struct fenfs_inode *d;
        if (inode_block(ino, &d) && d->mode == 0)
            n++;
    }
    return n;
}

/* The disk block of a file's block bn, allocating it (and its indirect
 * blocks) if `alloc`; 0 for a hole or when the disk is full. */
static unsigned bmap(struct inode *ip, unsigned bn, int alloc)
{
    unsigned *slot, blk;
    struct buf *b;
    if (bn < FENFS_NDIRECT) {
        if (!ip->d.direct[bn] && alloc) {
            ip->d.direct[bn] = balloc();
            iupdate(ip);
        }
        return ip->d.direct[bn];
    }
    bn -= FENFS_NDIRECT;
    if (bn < FENFS_PER_BLOCK) {
        if (!ip->d.indirect) {
            if (!alloc || !(ip->d.indirect = balloc()))
                return 0;
            iupdate(ip);
        }
        b = bread(ip->d.indirect);
        if (!b)
            return 0;
        slot = (unsigned *)b->data + bn;
        if (!*slot && alloc) {
            blk = balloc();
            b = bread(ip->d.indirect);
            slot = (unsigned *)b->data + bn;
            *slot = blk;
            bdirty(b);
        }
        return *slot;
    }
    bn -= FENFS_PER_BLOCK;
    if (bn >= FENFS_PER_BLOCK * FENFS_PER_BLOCK)
        return 0;
    if (!ip->d.dindirect) {
        if (!alloc || !(ip->d.dindirect = balloc()))
            return 0;
        iupdate(ip);
    }
    b = bread(ip->d.dindirect);
    if (!b)
        return 0;
    slot = (unsigned *)b->data + bn / FENFS_PER_BLOCK;
    if (!*slot) {
        if (!alloc)
            return 0;
        blk = balloc();
        b = bread(ip->d.dindirect);
        slot = (unsigned *)b->data + bn / FENFS_PER_BLOCK;
        *slot = blk;
        bdirty(b);
        if (!blk)
            return 0;
    }
    blk = *slot;
    b = bread(blk);
    if (!b)
        return 0;
    slot = (unsigned *)b->data + bn % FENFS_PER_BLOCK;
    if (!*slot && alloc) {
        unsigned nb = balloc();
        b = bread(blk);
        slot = (unsigned *)b->data + bn % FENFS_PER_BLOCK;
        *slot = nb;
        bdirty(b);
    }
    return *slot;
}

/* Copy file data out: the sink gets (offset in the read, data, length). */
int readi(struct inode *ip, unsigned off, unsigned n,
          int (*sink)(void *ctx, unsigned off, void *p, unsigned n), void *ctx)
{
    unsigned done = 0;
    static unsigned char zero[BLOCK];
    if (off >= ip->d.size)
        return 0;
    if (n > ip->d.size - off)
        n = ip->d.size - off;
    while (done < n) {
        unsigned bo = (off + done) % BLOCK;
        unsigned k = BLOCK - bo;
        unsigned blk = bmap(ip, (off + done) / BLOCK, 0);
        unsigned char *p = zero;
        int e;
        if (k > n - done)
            k = n - done;
        if (blk) {
            struct buf *b = bread(blk);
            if (!b)
                return done ? (int)done : -EIO;
            p = b->data;
        }
        e = sink(ctx, done, p + bo, k);
        if (e < 0)
            return done ? (int)done : e;
        done += k;
    }
    return done;
}

int writei(struct inode *ip, unsigned off, unsigned n,
           int (*source)(void *ctx, unsigned off, void *p, unsigned n), void *ctx)
{
    unsigned done = 0;
    while (done < n) {
        unsigned bo = (off + done) % BLOCK;
        unsigned k = BLOCK - bo;
        unsigned blk = bmap(ip, (off + done) / BLOCK, 1);
        struct buf *b;
        int e;
        if (k > n - done)
            k = n - done;
        if (!blk) {
            if (!done)
                return -ENOSPC;
            break;
        }
        b = bread(blk);
        if (!b)
            return done ? (int)done : -EIO;
        e = source(ctx, done, b->data + bo, k);
        if (e < 0) {
            if (!done)
                return e;
            break;
        }
        bdirty(b);
        done += k;
    }
    if (done && off + done > ip->d.size)
        ip->d.size = off + done;
    if (done) {
        ip->d.mtime = fs_now();
        iupdate(ip);
    }
    return done;
}

static void free_indirect(unsigned blk, int depth)
{
    struct buf *b;
    unsigned i, list[FENFS_PER_BLOCK];
    if (!blk)
        return;
    b = bread(blk);
    if (b) {
        memcpy(list, b->data, sizeof list);
        for (i = 0; i < FENFS_PER_BLOCK; i++)
            if (list[i]) {
                if (depth > 1)
                    free_indirect(list[i], depth - 1);
                else
                    bfree(list[i]);
            }
    }
    bfree(blk);
}

/* Cut a file to `size` (only to 0, or past its end, which leaves a hole). */
int itrunc(struct inode *ip, unsigned size)
{
    int i;
    if (size >= ip->d.size) {
        ip->d.size = size;
        return iupdate(ip);
    }
    if (size) {
        /* keep the blocks below size; free the rest */
        unsigned first = (size + BLOCK - 1) / BLOCK;
        unsigned bn, last = (ip->d.size + BLOCK - 1) / BLOCK;
        for (bn = first; bn < last && bn < FENFS_NDIRECT; bn++)
            if (ip->d.direct[bn]) {
                bfree(ip->d.direct[bn]);
                ip->d.direct[bn] = 0;
            }
        if (first <= FENFS_NDIRECT) {
            free_indirect(ip->d.indirect, 1);
            free_indirect(ip->d.dindirect, 2);
            ip->d.indirect = ip->d.dindirect = 0;
        }
        ip->d.size = size;
        return iupdate(ip);
    }
    for (i = 0; i < FENFS_NDIRECT; i++)
        if (ip->d.direct[i]) {
            bfree(ip->d.direct[i]);
            ip->d.direct[i] = 0;
        }
    free_indirect(ip->d.indirect, 1);
    free_indirect(ip->d.dindirect, 2);
    ip->d.indirect = ip->d.dindirect = 0;
    ip->d.size = 0;
    ip->d.mtime = fs_now();
    return iupdate(ip);
}

/* ---- directories ---- */

struct find {
    const char *name;
    unsigned ino;
    unsigned at;
    int found;
};

static int find_sink(void *ctx, unsigned off, void *p, unsigned n)
{
    struct find *f = ctx;
    struct fenfs_dirent *d = p;
    unsigned i;
    for (i = 0; i < n / sizeof *d; i++)
        if (d[i].ino && !strncmp(d[i].name, f->name, FENFS_NAME)) {
            f->ino = d[i].ino;
            f->at = off + i * sizeof *d;
            f->found = 1;
            return -1;
        }
    return 0;
}

struct inode *dirlookup(struct inode *dp, const char *name, unsigned *off)
{
    struct find f;
    f.name = name;
    f.found = 0;
    readi(dp, 0, dp->d.size, find_sink, &f);
    if (!f.found)
        return 0;
    if (off)
        *off = f.at;
    return iget(f.ino);
}

static int free_sink(void *ctx, unsigned off, void *p, unsigned n)
{
    struct find *f = ctx;
    struct fenfs_dirent *d = p;
    unsigned i;
    for (i = 0; i < n / sizeof *d; i++)
        if (!d[i].ino) {
            f->at = off + i * sizeof *d;
            f->found = 1;
            return -1;
        }
    return 0;
}

static int copy_source(void *ctx, unsigned off, void *p, unsigned n)
{
    memcpy(p, (char *)ctx + off, n);
    return 0;
}

int dirlink(struct inode *dp, const char *name, unsigned ino)
{
    struct fenfs_dirent d;
    struct find f;
    if (strlen(name) >= FENFS_NAME)
        return -ENAMETOOLONG;
    f.found = 0;
    readi(dp, 0, dp->d.size, free_sink, &f);
    if (!f.found)
        f.at = dp->d.size;
    memset(&d, 0, sizeof d);
    d.ino = ino;
    strncpy(d.name, name, FENFS_NAME - 1);
    if (writei(dp, f.at, sizeof d, copy_source, &d) != sizeof d)
        return -ENOSPC;
    return 0;
}

int dirunlink(struct inode *dp, const char *name)
{
    struct fenfs_dirent d;
    unsigned off;
    struct inode *ip = dirlookup(dp, name, &off);
    if (!ip)
        return -ENOENT;
    iput(ip);
    memset(&d, 0, sizeof d);
    if (writei(dp, off, sizeof d, copy_source, &d) != sizeof d)
        return -EIO;
    return 0;
}

static int empty_sink(void *ctx, unsigned off, void *p, unsigned n)
{
    struct fenfs_dirent *d = p;
    unsigned i;
    for (i = 0; i < n / sizeof *d; i++)
        if (d[i].ino && strcmp(d[i].name, ".") && strcmp(d[i].name, "..")) {
            *(int *)ctx = 0;
            return -1;
        }
    return 0;
}

int dirempty(struct inode *dp)
{
    int empty = 1;
    readi(dp, 0, dp->d.size, empty_sink, &empty);
    return empty;
}

/* ---- paths: absolute, tidied by the C library ---- */

static const char *element(const char *p, char *name)
{
    int n = 0;
    while (*p == '/')
        p++;
    if (!*p)
        return 0;
    while (*p && *p != '/') {
        if (n < FENFS_NAME - 1)
            name[n++] = *p;
        p++;
    }
    name[n] = 0;
    return p;
}

static struct inode *walk(const char *path, int parent, char *last, int *err)
{
    struct inode *ip = iget(FENFS_ROOT), *next;
    char name[FENFS_NAME];
    const char *p = path;
    *err = 0;
    while ((p = element(p, name)) != 0) {
        if (!S_ISDIR(ip->d.mode)) {
            iput(ip);
            *err = -ENOTDIR;
            return 0;
        }
        if (parent && !element(p, last)) {
            strcpy(last, name);
            return ip;
        }
        next = dirlookup(ip, name, 0);
        iput(ip);
        if (!next) {
            *err = -ENOENT;
            return 0;
        }
        ip = next;
    }
    if (parent) {
        /* the root has no parent */
        iput(ip);
        *err = -EINVAL;
        return 0;
    }
    return ip;
}

struct inode *namei(const char *path, int *err)
{
    return walk(path, 0, 0, err);
}

struct inode *nameiparent(const char *path, char *name, int *err)
{
    return walk(path, 1, name, err);
}
