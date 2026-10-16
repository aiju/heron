/* Processes, threads and the scheduler.
 *
 * A thread's id is its register bank, 1-255; a process's id is its page
 * map context, 1-127. The scheduler runs the highest-priority ready thread
 * (32 levels, found with CLZ in a bitmap of the levels that have one),
 * round robin within a level with a time slice of SLICE_TICKS. Switching
 * is rewriting the trap frame at the top of the kernel stack and setting
 * bank and ctx: the threads' registers stay in their banks. */

#include "kernel.h"

struct thread threads[MAX_THREADS];
struct proc procs[MAX_PROCS];
struct thread *current;
int need_resched;
u32 ticks;

static struct thread *runq[NPRIO];      /* circular lists, the head runs next */
u32 ready_bits;                         /* the levels that have one (fastipc.s reads it) */
static struct thread *sleepers;         /* by wake time */

#define KFRAME ((struct frame *)(kstack_top - 8))

void sched_init(void)
{
    int i;
    for (i = 0; i < MAX_THREADS; i++)
        threads[i].id = i;
    for (i = 0; i < MAX_PROCS; i++)
        procs[i].pid = i;
}

void q_append(struct thread **q, struct thread *t)
{
    if (!*q) {
        t->next = t->prev = t;
        *q = t;
        return;
    }
    t->prev = (*q)->prev;
    t->next = *q;
    (*q)->prev->next = t;
    (*q)->prev = t;
}

void q_remove(struct thread **q, struct thread *t)
{
    if (t->next == t)
        *q = 0;
    else {
        t->prev->next = t->next;
        t->next->prev = t->prev;
        if (*q == t)
            *q = t->next;
    }
    t->next = t->prev = 0;
}

/* A thread that wakes runs before one of its own level that was running:
 * threads that wait for something (input, a reply, the time) get it at
 * once, and the ones that compute run when they're all waiting. */
void ready(struct thread *t)
{
    t->state = T_READY;
    q_append(&runq[t->prio], t);
    ready_bits |= 1u << t->prio;
    if (!current || t->prio >= current->prio)
        need_resched = 1;
}

/* A thread just made ready runs first among its level. */
void runq_to_front(struct thread *t)
{
    runq[t->prio] = t;
}

void unready(struct thread *t)
{
    q_remove(&runq[t->prio], t);
    if (!runq[t->prio])
        ready_bits &= ~(1u << t->prio);
}

/* Take a thread out of whatever it's in, and give it a new state. */
void block(struct thread *t, enum tstate st)
{
    if (t->state == T_READY)
        unready(t);
    t->state = st;
    if (t == current)
        need_resched = 1;
}

static struct thread *pick(void)
{
    struct thread *t;
    int prio;
    if (!ready_bits)
        return 0;
    prio = 31 - clz(ready_bits);
    t = runq[prio];
    unready(t);
    return t;
}

/* Could t run now instead of the current thread, which is blocking? If no
 * ready thread is above it, the scheduler would choose it anyway. */
int may_switch_to(struct thread *t)
{
    return !ready_bits || t->prio >= 31 - clz(ready_bits);
}

/* Run t, which is in no queue, instead of the current thread, which has
 * just blocked: the IPC's direct switch, past the run queue. */
void switch_to(struct thread *t)
{
    struct frame *f = KFRAME;
    struct thread *c = current;
    c->pc = f->pc;
    c->sr = f->sr;
    t->state = T_RUNNING;
    if (t->slice <= 0)
        t->slice = SLICE_TICKS;
    current = t;
    need_resched = 0;
    f->pc = t->pc;
    f->sr = t->sr;
    set_bank(t->id);
    if (t->proc != c->proc)
        set_ctx(t->proc->pid);
}

/* From kexit: save the current thread's frame, choose the next, and put
 * its frame there instead. With nothing to run, wait for an interrupt. */
void schedule(void)
{
    struct frame *f = KFRAME;
    struct thread *t = current;
    struct thread *next;
    need_resched = 0;
    if (t) {
        t->pc = f->pc;
        t->sr = f->sr;
        if (t->state == T_RUNNING) {
            if (!ready_bits || 31 - clz(ready_bits) < t->prio) {
                /* nothing better: carry on */
                return;
            }
            ready(t);
        }
    }
    current = 0;
    while (!(next = pick())) {
        set_ctx(0);
        idle_wait();
    }
    next->state = T_RUNNING;
    if (next->slice <= 0)
        next->slice = SLICE_TICKS;
    current = next;
    need_resched = 0;
    f->pc = next->pc;
    f->sr = next->sr;
    set_bank(next->id);
    set_ctx(next->proc->pid);
}

struct proc *proc_get(int pid)
{
    if (pid <= 0 || pid >= MAX_PROCS || procs[pid].state != P_LIVE)
        return 0;
    return &procs[pid];
}

struct thread *thread_get(int tid)
{
    if (tid <= 0 || tid >= MAX_THREADS || threads[tid].state == T_FREE)
        return 0;
    return &threads[tid];
}

/* Whether process pid is `of` or descends from it. */
int is_descendant(int pid, int of)
{
    int depth = 0;
    while (pid > 0 && pid < MAX_PROCS && depth++ < MAX_PROCS) {
        if (pid == of)
            return 1;
        if (procs[pid].state == P_FREE)
            return 0;
        pid = procs[pid].parent;
    }
    return 0;
}

struct thread *rcvid_thread(int rcvid)
{
    struct thread *t;
    if (rcvid <= 0)
        return 0;
    t = &threads[rcvid & 0xFF];
    if (t->state == T_FREE || RCVID(t) != rcvid)
        return 0;
    return t;
}

struct proc *proc_new(const char *name, int parent, int flags)
{
    int i;
    for (i = 1; i < MAX_PROCS; i++) {
        struct proc *p = &procs[i];
        if (p->state == P_FREE) {
            p->state = P_LIVE;
            p->parent = parent;
            p->flags = flags;
            p->pgid = parent ? procs[parent].pgid : i;
            p->status = 0;
            p->threads = 0;
            p->nthreads = 0;
            p->pages = 0;
            strlcpy(p->name, name, sizeof p->name);
            return p;
        }
    }
    return 0;
}

struct thread *thread_new(struct proc *p, u32 pc, u32 sp, u32 arg, int prio)
{
    int i, r;
    for (i = 1; i < MAX_THREADS; i++) {
        struct thread *t = &threads[i];
        if (t->state == T_FREE) {
            t->proc = p;
            t->gen++;
            t->rcvid = MAKE_RCVID(t);
            t->prio = prio;
            t->slice = SLICE_TICKS;
            t->pc = pc;
            t->sr = 0;          /* user mode, interrupts on below */
            t->sr |= SR_I;
            t->port = 0;
            t->peer = 0;
            t->cycles = 0;
            t->pnext = p->threads;
            p->threads = t;
            p->nthreads++;
            for (r = 0; r < 16; r++)
                ureg_set(t->id, r, 0);
            ureg_set(t->id, 1, arg);
            ureg_set(t->id, 15, sp);
            ready(t);
            return t;
        }
    }
    return 0;
}

/* Take a thread out of the system: out of the queues and IPC, its bank
 * free for another. */
void thread_kill(struct thread *t)
{
    struct proc *p = t->proc;
    struct thread **pp;
    if (t->state == T_FREE)
        return;
    if (t->state == T_READY)
        unready(t);
    if (t->state == T_SLEEP) {
        for (pp = &sleepers; *pp; pp = &(*pp)->next)
            if (*pp == t) {
                *pp = t->next;
                break;
            }
    }
    ipc_thread_gone(t);
    for (pp = &p->threads; *pp; pp = &(*pp)->pnext)
        if (*pp == t) {
            *pp = t->pnext;
            break;
        }
    p->nthreads--;
    t->state = T_FREE;
    if (t == current) {
        current = 0;
        need_resched = 1;
    }
}

static void reap(struct proc *p)
{
    p->state = P_FREE;
}

/* A parent waiting for this child, or for any: the child's pid in r1 and
 * its status in r2. */
static int wake_waiter(struct proc *child)
{
    int i;
    for (i = 1; i < MAX_THREADS; i++) {
        struct thread *t = &threads[i];
        if (t->state == T_WAIT && t->proc->pid == child->parent &&
            (t->wait_pid == 0 || t->wait_pid == child->pid)) {
            ureg_set(t->id, 1, child->pid);
            ureg_set(t->id, 2, child->status);
            ready(t);
            return 1;
        }
    }
    return 0;
}

void proc_exit(struct proc *p, int status)
{
    int i;
    if (p->state != P_LIVE)
        return;
    while (p->threads)
        thread_kill(p->threads);
    ipc_proc_gone(p);
    vm_destroy(p);
    p->status = status;
    p->state = P_ZOMBIE;
    /* its children have no one to wait for them */
    for (i = 1; i < MAX_PROCS; i++) {
        if (procs[i].parent == p->pid) {
            procs[i].parent = 0;
            if (procs[i].state == P_ZOMBIE)
                reap(&procs[i]);
        }
    }
    exit_notify(p->pid);
    if (!p->parent || !proc_get(p->parent))
        reap(p);
    else if (wake_waiter(p))
        reap(p);
}

/* proc_wait(pid): a zombie child now, or block until one exits (or with
 * nohang, 0). */
int proc_wait(int pid, int nohang)
{
    int i;
    struct proc *me = current->proc;
    int any = 0;
    for (i = 1; i < MAX_PROCS; i++) {
        struct proc *c = &procs[i];
        if (c->state == P_FREE || c->parent != me->pid || (pid && c->pid != pid))
            continue;
        any = 1;
        if (c->state == P_ZOMBIE) {
            ureg_set(current->id, 2, c->status);
            reap(c);
            return i;
        }
    }
    if (!any)
        return -ECHILD;
    if (nohang)
        return 0;
    current->wait_pid = pid;
    block(current, T_WAIT);
    return 0;
}

u32 now_us(void)
{
    return TIMER_COUNT;
}

void sleep_until(struct thread *t, u32 when)
{
    struct thread **pp = &sleepers;
    block(t, T_SLEEP);
    t->wake_at = when;
    while (*pp && (int)((*pp)->wake_at - when) <= 0)
        pp = &(*pp)->next;
    t->next = *pp;
    *pp = t;
}

void wake_sleepers(void)
{
    u32 now = now_us();
    while (sleepers && (int)(sleepers->wake_at - now) <= 0) {
        struct thread *t = sleepers;
        sleepers = t->next;
        t->next = 0;
        ready(t);
    }
}

void timer_tick(u32 n)
{
    ticks += n;
    wake_sleepers();
    ring_alarms();
    if (current) {
        current->cycles++;
        if (--current->slice <= 0) {
            current->slice = SLICE_TICKS;
            if (ready_bits && 31 - clz(ready_bits) >= current->prio)
                need_resched = 1;
        }
    }
}
