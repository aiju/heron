/* The file protocol: what the C library sends to a server for a file, a
 * directory, a pipe or a console. Every server of files speaks it: the
 * file server (srv/fs), the serial console (srv/cons), the terminal
 * (cmd/term). A message is 8 words (fen/abi.h); word 0 of a request is the
 * operation, word 0 of the reply the result. Paths and data stay in the
 * client's memory: the server reads and writes them with ipc_read and
 * ipc_write while the client waits.
 *
 * A descriptor is the server's: a number in a table the server keeps for
 * each process. FS_DUPTO puts one in another process's table, which is how
 * a child inherits its parent's. A server watches for processes ending
 * (exit_watch) and closes what they had open. */

#ifndef FEN_FS_H
#define FEN_FS_H

/* requests: the words after the operation */
#define FS_OPEN 1       /* path, its length, O_ flags, mode -> fd */
#define FS_CLOSE 2      /* fd */
#define FS_READ 3       /* fd, buffer, n -> bytes read, 0 at the end */
#define FS_WRITE 4      /* fd, buffer, n -> bytes written */
#define FS_SEEK 5       /* fd, offset, whence -> the new offset */
#define FS_STAT 6       /* path, its length, struct stat * -> 0 */
#define FS_FSTAT 7      /* fd, struct stat * -> 0 */
#define FS_READDIR 8    /* fd, buffer, n -> bytes of struct dirent */
#define FS_MKDIR 9      /* path, its length -> 0 */
#define FS_UNLINK 10    /* path, its length -> 0 (an empty directory too) */
#define FS_RENAME 11    /* path, its length, new path, its length -> 0 */
#define FS_DUPTO 12     /* fd, pid -> the descriptor in pid's table */
#define FS_PIPE 13      /* -> 0, and the read fd in word 1, the write fd in word 2 */
#define FS_TRUNC 14     /* fd, length -> 0 */
#define FS_IOCTL 15     /* fd, request, argument -> the request's result */
#define FS_SYNC 16      /* -> 0 */
#define FS_STATFS 17    /* struct statfs * -> 0 */
#define FS_WRITE_INLINE 18 /* fd, n (at most 16), then the bytes in words 4-7 */

/* open's flags */
#define O_RDONLY 0
#define O_WRONLY 1
#define O_RDWR 2
#define O_ACCMODE 3
#define O_CREAT 0x40
#define O_EXCL 0x80
#define O_TRUNC 0x200
#define O_APPEND 0x400
#define O_NONBLOCK 0x800
#define O_DIRECTORY 0x10000

/* seek's whence */
#define SEEK_SET 0
#define SEEK_CUR 1
#define SEEK_END 2

/* consoles' ioctls */
#define IO_MODE 1       /* argument: CONS_RAW | CONS_NOECHO, or 0 for cooked -> the old mode */
#define IO_SETFG 2      /* argument: the process group ^C ends */
#define IO_GETSIZE 3    /* -> rows << 16 | columns */
#define IO_ISTTY 4      /* -> 1 for a console */
#define CONS_RAW 1
#define CONS_NOECHO 2

/* files' types, in st_mode's top bits */
#define S_IFMT 0xF000
#define S_IFREG 0x8000
#define S_IFDIR 0x4000
#define S_IFCHR 0x2000
#define S_IFIFO 0x1000
#define S_ISREG(m) (((m) & S_IFMT) == S_IFREG)
#define S_ISDIR(m) (((m) & S_IFMT) == S_IFDIR)
#define S_ISCHR(m) (((m) & S_IFMT) == S_IFCHR)
#define S_ISFIFO(m) (((m) & S_IFMT) == S_IFIFO)

struct stat {
    unsigned st_mode;
    unsigned st_size;
    unsigned st_ino;
    unsigned st_nlink;
    unsigned st_mtime;          /* seconds since 1970 */
    unsigned st_dev;
};

#define NAME_MAX 27
struct dirent {
    unsigned d_ino;
    char d_name[NAME_MAX + 1];
};

struct statfs {
    unsigned f_bsize;
    unsigned f_blocks;
    unsigned f_bfree;
    unsigned f_files;
    unsigned f_ffree;
};

#endif
