/* The system calls that aren't IPC (ipc.c) or interrupts (trap.c). Each
 * is called from its stub (build/fen/gen/ksys.s, from syscalls.py) with
 * the user's r1-r6 as its arguments, and its result goes back in the
 * user's r1. A system call that blocks returns, and its real result is
 * put in the thread's bank when it wakes. */

#include "kernel.h"

/* The process a call is about: 0 is the caller's own, otherwise it must be
 * one of the caller's children. */
static struct proc *target(int pid)
{
    struct proc *p;
    if (pid == 0)
        return current->proc;
    p = proc_get(pid);
    if (!p || (p->parent != current->proc->pid && p != current->proc))
        return 0;
    return p;
}

int sys_exit(int status)
{
    proc_exit(current->proc, status & 0xFF);
    return 0;
}

int sys_yield(void)
{
    need_resched = 1;
    return 0;
}

int sys_sleep(u32 us)
{
    if (us == 0)
        return sys_yield();
    sleep_until(current, now_us() + us);
    return 0;
}

u32 sys_time(void)
{
    return now_us();
}

int sys_kdebug(const char *buf, u32 n)
{
    char tmp[129];
    while (n) {
        u32 k = n > 128 ? 128 : n;
        if (ucopy(tmp, buf, k))
            return -EFAULT;
        tmp[k] = 0;
        kputs(tmp);
        buf += k;
        n -= k;
    }
    return 0;
}

int sys_getpid(void)
{
    return current->proc->pid;
}

int sys_getppid(void)
{
    return current->proc->parent;
}

int sys_gettid(void)
{
    return current->id;
}

static u32 epoch;

u32 sys_sysinfo(int key)
{
    switch (key) {
    case SI_RAM: return ram_size;
    case SI_FREE: return pages_free() * PAGE;
    case SI_CLOCK: return INFO_CLOCK;
    case SI_BOOT: return INFO_FLAGS;
    case SI_TICKS: return ticks;
    case SI_EPOCH:
        if (!epoch)
            epoch = REG(0xA0000300) - now_us() / 1000000;
        return epoch;
    }
    return 0;
}

int sys_proc_create(const char *uname, int flags)
{
    char name[16];
    struct proc *p;
    int n = ustrncpy(name, uname, sizeof name);
    if (n == -ENAMETOOLONG) {
        n = 15;
        name[15] = 0;
    }
    if (n < 0)
        return n;
    if (flags & ~current->proc->flags & PROC_IO)
        return -EPERM;
    p = proc_new(name, current->proc->pid, flags);
    if (!p)
        return -EAGAIN;
    return p->pid;
}

int sys_vm_alloc(int pid, u32 va, u32 n, u32 prot)
{
    struct proc *p = target(pid);
    return p ? vm_alloc(p, va, n, prot) : -ESRCH;
}

int sys_vm_free(int pid, u32 va, u32 n)
{
    struct proc *p = target(pid);
    return p ? vm_free(p, va, n) : -ESRCH;
}

int sys_vm_write(int pid, u32 va, const void *src, u32 n)
{
    struct proc *p = target(pid);
    return p ? copy_to_proc(p, va, src, n, 0) : -ESRCH;
}

int sys_vm_protect(int pid, u32 va, u32 n, u32 prot)
{
    struct proc *p = target(pid);
    return p ? vm_protect(p, va, n, prot) : -ESRCH;
}

int sys_vm_map_phys(u32 va, u32 pa, u32 n, u32 prot)
{
    if (!(current->proc->flags & PROC_IO))
        return -EPERM;
    return vm_map_phys(current->proc, va, pa, n, prot);
}

/* vm_share(pid, va, my_va, n): map n of my pages into a child at va,
 * readable and writable as they are to me. */
int sys_vm_share(int pid, u32 va, u32 my_va, u32 n)
{
    struct proc *p = target(pid);
    u32 prot = PROT_READ;
    if (!p)
        return -ESRCH;
    if (pte_of(current->proc, my_va) & PTE_W)
        prot |= PROT_WRITE;
    return vm_share(current->proc, my_va, p, va, n, prot);
}

int sys_thread_create(int pid, u32 pc, u32 sp, u32 arg)
{
    struct proc *p = target(pid);
    struct thread *t;
    if (!p)
        return -ESRCH;
    t = thread_new(p, pc, sp, arg, current->prio);
    return t ? t->id : -EAGAIN;
}

int sys_thread_exit(void)
{
    struct proc *p = current->proc;
    if (p->nthreads <= 1)
        proc_exit(p, 0);
    else
        thread_kill(current);
    return 0;
}

int sys_set_priority(int tid, int prio)
{
    struct thread *t = tid ? thread_get(tid) : current;
    if (!t || prio < 1 || prio >= NPRIO)
        return -EINVAL;
    if (t->proc != current->proc && t->proc->parent != current->proc->pid &&
        current->proc->pid != 1)
        return -EPERM;
    if (t->state == T_READY) {
        unready(t);
        t->prio = prio;
        ready(t);
    } else {
        t->prio = prio;
    }
    if (t == current)
        need_resched = 1;
    return 0;
}

int sys_proc_wait(int pid)
{
    return proc_wait(pid);
}

static int may_kill(struct proc *p)
{
    int me = current->proc->pid;
    return me == 1 || is_descendant(p->pid, me);
}

/* proc_kill(pid, status): end a process, or with pid < 0 every process
 * of group -pid, that the caller may: its own descendants (init may end
 * any). */
int sys_proc_kill(int pid, int status)
{
    int i, n = 0;
    if (pid > 0) {
        struct proc *p = proc_get(pid);
        if (!p)
            return -ESRCH;
        if (!may_kill(p))
            return -EPERM;
        proc_exit(p, status & 0xFF);
        return 1;
    }
    for (i = 1; i < MAX_PROCS; i++) {
        struct proc *p = &procs[i];
        if (p->state == P_LIVE && p->pgid == -pid && may_kill(p)) {
            proc_exit(p, status & 0xFF);
            n++;
        }
    }
    return n ? n : -ESRCH;
}

int sys_setpgid(int pid, int pgid)
{
    struct proc *p = target(pid);
    if (!p)
        return -ESRCH;
    p->pgid = pgid ? pgid : p->pid;
    return 0;
}

int sys_getpgid(int pid)
{
    struct proc *p = pid ? proc_get(pid) : current->proc;
    return p ? p->pgid : -ESRCH;
}

int sys_proc_list(struct proc_info *buf, int n)
{
    int i, k = 0;
    struct thread *t;
    for (i = 1; i < MAX_PROCS && k < n; i++) {
        struct proc *p = &procs[i];
        struct proc_info e;
        if (p->state == P_FREE)
            continue;
        e.pid = p->pid;
        e.parent = p->parent;
        e.state = p->state == P_LIVE ? 1 : 2;
        e.threads = p->nthreads;
        e.pages = p->pages;
        e.ticks = 0;
        for (t = p->threads; t; t = t->pnext)
            e.ticks += t->cycles;
        memcpy(e.name, p->name, sizeof e.name);
        if (ucopy(&buf[k], &e, sizeof e))
            return -EFAULT;
        k++;
    }
    return k;
}

int sys_klog(char *buf, u32 n, u32 from)
{
    char tmp[256];
    u32 done = 0;
    while (done < n) {
        u32 k = n - done > sizeof tmp ? sizeof tmp : n - done;
        int got = klog_read(tmp, k, from + done);
        if (got <= 0)
            break;
        if (ucopy(buf + done, tmp, got))
            return -EFAULT;
        done += got;
    }
    return done;
}

int sys_boot_spawn(const char *uname, int flags)
{
    char name[24];
    int n = ustrncpy(name, uname, sizeof name);
    if (n < 0)
        return n;
    if (current->proc->pid != 1)
        return -EPERM;
    return boot_spawn(name, current->proc->pid, flags, current->prio);
}
