/* The file server's parts: the CF card's driver (ide.c), the block cache
 * (cache.c), the file system (fenfs.c), and the protocol (main.c). */

#ifndef FS_H
#define FS_H

#include <fen/abi.h>
#include <fen/fenfs.h>
#include <fen/srv.h>

#define BLOCK FENFS_BLOCK

/* ide.c */
int ide_init(void);
int ide_read(unsigned lba, void *buf, int sectors);
int ide_write(unsigned lba, const void *buf, int sectors);
extern unsigned ide_sectors;

/* main.c: wait for an interrupt, keeping requests that come meanwhile */
void wait_irq(unsigned bit);
#define IDE_BIT 1

/* cache.c */
struct buf {
    unsigned blk;
    int valid;
    int dirty;
    unsigned used;              /* for LRU */
    unsigned char data[BLOCK];
};
struct buf *bread(unsigned blk);        /* 0 on an I/O error */
int bwrite(struct buf *b);
void bdirty(struct buf *b);
int bsync(void);
extern unsigned cache_hits, cache_misses;

/* fenfs.c: inodes in memory */
struct inode {
    unsigned ino;
    int refs;
    struct fenfs_inode d;
};

int fs_mount(void);
extern struct fenfs_super sb;
struct inode *iget(unsigned ino);
void iput(struct inode *ip);
int iupdate(struct inode *ip);
struct inode *ialloc(unsigned mode);
int readi(struct inode *ip, unsigned off, unsigned n, int (*sink)(void *ctx, unsigned off, void *p, unsigned n), void *ctx);
int writei(struct inode *ip, unsigned off, unsigned n, int (*source)(void *ctx, unsigned off, void *p, unsigned n), void *ctx);
int itrunc(struct inode *ip, unsigned size);
struct inode *namei(const char *path, int *err);
struct inode *nameiparent(const char *path, char *name, int *err);
struct inode *dirlookup(struct inode *dp, const char *name, unsigned *off);
int dirlink(struct inode *dp, const char *name, unsigned ino);
int dirunlink(struct inode *dp, const char *name);
int dirempty(struct inode *dp);
unsigned fs_now(void);
int fs_free_blocks(void);
int fs_free_inodes(void);

#endif
