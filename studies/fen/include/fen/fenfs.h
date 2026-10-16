/* Fen's file system on disk: small and Unix-shaped. mkfs.py writes the
 * same format on the host.
 *
 *   block 0              unused (room for a boot block)
 *   block 1              the superblock
 *   bitmap_start ...     a bit per block, 1 = in use
 *   inode_start ...      the inodes, 16 to a block
 *   data_start ...       everything else
 *
 * Blocks are 1 KB, two sectors. An inode has 11 direct blocks, an indirect
 * block and a double indirect one, so a file can be 64 MB. A directory is
 * a file of 32-byte entries, an inode number and a name of up to 27
 * characters; inode 0 marks a free entry. The root is inode 1. */

#ifndef FEN_FENFS_H
#define FEN_FENFS_H

#define FENFS_MAGIC 0x464E4546  /* "FENF" */
#define FENFS_BLOCK 1024
#define FENFS_ROOT 1
#define FENFS_NDIRECT 11
#define FENFS_PER_BLOCK (FENFS_BLOCK / 4)
#define FENFS_INODES_PER_BLOCK (FENFS_BLOCK / 64)
#define FENFS_NAME 28

struct fenfs_super {
    unsigned magic;
    unsigned version;
    unsigned nblocks;
    unsigned ninodes;
    unsigned bitmap_start;
    unsigned bitmap_blocks;
    unsigned inode_start;
    unsigned inode_blocks;
    unsigned data_start;
    unsigned made;              /* when mkfs made it, seconds since 1970 */
};

struct fenfs_inode {
    unsigned short mode;        /* S_IF* | permissions; 0 is a free inode */
    unsigned short nlink;
    unsigned size;
    unsigned mtime;
    unsigned direct[FENFS_NDIRECT];
    unsigned indirect;
    unsigned dindirect;
};

struct fenfs_dirent {
    unsigned ino;
    char name[FENFS_NAME];
};

#endif
