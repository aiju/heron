/* The kernel's start: memory, the scheduler, the timer, and the first
 * process.
 *
 * The boot image is the kernel at physical 0 and, from the first page
 * after its end, the boot archive: the programs the system needs before
 * it has a file system (init and the file server, at least). The kernel
 * starts the one called "init"; init asks for the others by name
 * (boot_spawn). */

#include "kernel.h"

#define BOOT_MAGIC 0x424E4546   /* "FENB" */

struct boot_entry {
    char name[24];
    u32 offset;                 /* from the archive's start */
    u32 size;
};

struct boot_archive {
    u32 magic;
    u32 count;
    struct boot_entry e[1];
};

static struct boot_archive *archive;
static u32 archive_end;

static struct boot_entry *boot_find(const char *name)
{
    u32 i;
    if (!archive)
        return 0;
    for (i = 0; i < archive->count; i++)
        if (!strcmp(archive->e[i].name, name))
            return &archive->e[i];
    return 0;
}

/* The startup block of a program started from the archive: argc 1, its
 * name, no environment, no descriptors. */
static int boot_block(struct proc *p, const char *name)
{
    struct {
        struct start_block b;
        char *argv[2];
        char *envp[1];
        char str[24];
    } blk;
    int e = vm_alloc(p, START_BLOCK, 1, PROT_READ | PROT_WRITE);
    if (e)
        return e;
    memset(&blk, 0, sizeof blk);
    blk.b.argc = 1;
    blk.b.argv = (char **)(START_BLOCK + ((u32)&blk.argv[0] - (u32)&blk));
    blk.b.envp = (char **)(START_BLOCK + ((u32)&blk.envp[0] - (u32)&blk));
    blk.b.nfds = 0;
    blk.b.fds = 0;
    blk.argv[0] = (char *)(START_BLOCK + ((u32)&blk.str[0] - (u32)&blk));
    blk.b.cwd = (u32)&blk.str[23] - (u32)&blk;      /* "" */
    strlcpy(blk.str, name, 23);
    return copy_to_proc(p, START_BLOCK, &blk, sizeof blk, 1);
}

/* Load an executable (fen/abi.h's format) from the archive into a new
 * process, and start its first thread. */
int boot_spawn(const char *name, int parent, int flags, int prio)
{
    struct boot_entry *be = boot_find(name);
    struct fx_header *h;
    struct proc *p;
    u32 va, end;
    if (!be)
        return -ENOENT;
    h = (struct fx_header *)((char *)archive + be->offset);
    if (h->magic != FX_MAGIC || h->base & (PAGE - 1))
        return -ENOEXEC;
    p = proc_new(name, parent, flags);
    if (!p)
        return -EAGAIN;
    end = (h->base + h->mem_size + PAGE - 1) & ~(PAGE - 1);
    for (va = h->base; va < end; va += PAGE) {
        u32 prot = va >= h->text_start && va < h->text_end ? PROT_READ | PROT_EXEC
                                                            : PROT_READ | PROT_WRITE;
        if (vm_alloc(p, va, 1, prot)) {
            proc_exit(p, 1);
            return -ENOMEM;
        }
    }
    if (copy_to_proc(p, h->base, h + 1, h->file_size, 0) || boot_block(p, name)) {
        proc_exit(p, 1);
        return -ENOMEM;
    }
    if (!thread_new(p, h->entry, STACK_TOP, START_BLOCK, prio)) {
        proc_exit(p, 1);
        return -EAGAIN;
    }
    return p->pid;
}

void kmain(void)
{
    u32 first_free;
    int pid;
    kputs("Fen kernel\n");
    archive = (struct boot_archive *)(((u32)kernel_end + PAGE - 1) & ~(PAGE - 1));
    if (archive->magic != BOOT_MAGIC) {
        kputs("no boot archive\n");
        archive = 0;
        first_free = (u32)kernel_end;
    } else {
        u32 i;
        archive_end = (u32)archive;
        for (i = 0; i < archive->count; i++) {
            u32 e = (u32)archive + archive->e[i].offset + archive->e[i].size;
            if (e > archive_end)
                archive_end = e;
        }
        first_free = archive_end;
    }
    first_free = ((first_free & ~WINDOW) + PAGE - 1) & ~(PAGE - 1);
    mem_init(first_free);
    sched_init();
    ipc_init();
    iop_init();
    kprintf("%u KB of RAM, %u KB free; clock %u Hz\n", ram_size >> 10, pages_free() * 4,
            INFO_CLOCK);
    pid = boot_spawn("init", 0, PROC_IO, 16);
    if (pid < 0)
        panic("can't start init: %d", pid);
    irq_init();
    start_first();
}
