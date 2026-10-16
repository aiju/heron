/* What the Fen kernel and user programs agree on: error numbers, page
 * protections, the executable format, how a program starts, and the
 * message conventions. The system calls themselves are in fen/sys.h. */

#ifndef FEN_ABI_H
#define FEN_ABI_H

/* errors: system calls return them negated */
#define EPERM 1
#define ENOENT 2
#define ESRCH 3
#define EINTR 4
#define EIO 5
#define E2BIG 7
#define ENOEXEC 8
#define EBADF 9
#define ECHILD 10
#define EAGAIN 11
#define ENOMEM 12
#define EACCES 13
#define EFAULT 14
#define EBUSY 16
#define EEXIST 17
#define EXDEV 18
#define ENODEV 19
#define ENOTDIR 20
#define EISDIR 21
#define EINVAL 22
#define ENFILE 23
#define EMFILE 24
#define ENOTTY 25
#define EFBIG 27
#define ENOSPC 28
#define ESPIPE 29
#define EROFS 30
#define EPIPE 32
#define ERANGE 34
#define ENAMETOOLONG 36
#define ENOSYS 38
#define ENOTEMPTY 39
#define ENOTSUP 95

/* vm_alloc and friends: what a page allows */
#define PROT_READ 1
#define PROT_WRITE 2
#define PROT_EXEC 4

/* proc_create's flags: what the new process may do */
#define PROC_IO 1           /* map physical pages, take interrupts */
#define PROC_SPAWN 2        /* (every process may create children) */

/* sysinfo's keys */
#define SI_RAM 0            /* bytes of RAM */
#define SI_FREE 1           /* bytes free */
#define SI_CLOCK 2          /* the CPU's clock in Hz */
#define SI_BOOT 3           /* the boot flags the host set */
#define SI_TICKS 4          /* timer ticks since boot */
#define SI_EPOCH 5          /* seconds since 1970 at boot */
#define SI_CYCLES 6         /* reserved */

#define BOOT_SERIAL 1       /* boot flag: no window system, a shell on the UART */

/* the user address space */
#define USER_BASE 0x1000        /* programs are linked here */
#define USER_TOP 0x01000000
#define STACK_TOP 0x00FF0000    /* the main thread's stack, which grows on demand */
#define STACK_MAX 0x00100000
#define START_BLOCK 0x00FF0000  /* the startup block: one page */
#define MMAP_BASE 0x00800000    /* thread stacks, shared memory: libc's to place */
#define MMAP_TOP 0x00F00000

/* the executable format: a header, then the image from `base` */
#define FX_MAGIC 0x584E4546     /* "FENX" */
struct fx_header {
    unsigned magic;
    unsigned entry;
    unsigned base;              /* the image's address */
    unsigned file_size;         /* bytes of image in the file */
    unsigned mem_size;          /* bytes of memory, the image and its bss */
    unsigned text_start;        /* pages in [text_start, text_end) are R X, */
    unsigned text_end;          /* the rest R W */
    unsigned stack;             /* bytes of stack it wants, or 0 */
};

/* A program starts with r1 pointing at its startup block, at START_BLOCK:
 * argc, then argv's and envp's pointers (each list ends with 0), then the
 * descriptors it inherits, then the strings. */
#define MAX_FDS 32
struct fd_desc {
    int fd;
    int port;                   /* the server */
    int handle;                 /* the server's own number for it */
    int flags;
};

struct start_block {
    int argc;
    char **argv;
    char **envp;
    int nfds;
    struct fd_desc *fds;
    int cwd;                    /* offset of the working directory's string */
};

/* Messages are 8 words, in r0-r7. A request's word 0 is its operation; a
 * reply's word 0 is a status: >= 0 a result, < 0 an error. A
 * notification arrives with rcvid 0, its bits in word 0. */
#define MSG_WORDS 8
typedef struct {
    int w[MSG_WORDS];
} msg_t;

/* the kernel's process list entry (proc_list) */
struct proc_info {
    int pid;
    int parent;
    int state;                  /* 1 running, 2 a zombie */
    int threads;
    int pages;
    unsigned ticks;             /* CPU time in timer ticks */
    char name[16];
};

/* exit_log's entries */
struct exit_entry {
    unsigned seq;
    int pid;
};

#endif
