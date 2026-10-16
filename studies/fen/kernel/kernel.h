/* The Fen kernel: a small message-passing kernel for draft 2 in system
 * mode (reports/0029-rfc-draft-2-system.md). It runs in supervisor mode in
 * bank 0, in the window: its addresses are its physical addresses with bit
 * 31 set. Every thread has a register bank of its own (its number is the
 * thread's id), and every process a context of the page map (its number is
 * the process's id). The kernel runs with interrupts off, on one stack;
 * see entry.s for how it's entered and left. */

#ifndef KERNEL_H
#define KERNEL_H

#include <fen/abi.h>

typedef unsigned u32;
typedef unsigned short u16;
typedef unsigned char u8;

#define WINDOW 0x80000000u
#define PAGE 4096
#define PAGE_SHIFT 12
/* a physical address through the window */
#define PHYS(pa) ((void *)((u32)(pa) | WINDOW))

/* the board (studies/fen/board/src/lib.rs) */
#define TIMER_BASE 0x8F000000u
#define INFO_BASE 0x8F001000u
#define IMASK_BASE 0x8F002000u
#define REG(a) (*(volatile u32 *)(a))
#define TIMER_COUNT REG(TIMER_BASE)
#define TIMER_COMPARE REG(TIMER_BASE + 4)
#define TIMER_CTRL REG(TIMER_BASE + 8)
#define INFO_RAM REG(INFO_BASE)
#define INFO_CLOCK REG(INFO_BASE + 4)
#define INFO_DEBUG REG(INFO_BASE + 8)
#define INFO_FLAGS REG(INFO_BASE + 12)
/* the simulator's trace port (not hardware): TRACE_START | bank when a
 * thread starts in a bank, TRACE_END | bank when it ends */
#define INFO_TRACE REG(INFO_BASE + 4)
#define TRACE_START 0x01000000u
#define TRACE_END 0x02000000u
/* the interrupt mask: level L (1-8, RFC 0029, 7) is bit L - 1 */
#define IRQ_PENDING REG(IMASK_BASE)
#define IRQ_MASK REG(IMASK_BASE + 4)
#define LEVEL_BIT(l) (1u << ((l) - 1))
#define IRQ_TIMER 7

/* the page map's entries (RFC 0029, 3) */
#define PTE_V 1
#define PTE_W 2
#define PTE_X 4
#define PAGES_PER_CTX 4096

#define MAX_PROCS 128           /* a context each: pid 1-127 */
#define MAX_THREADS 256         /* a bank each: tid 1-255 */
#define MAX_PORTS 256
#define MAX_NAMES 32
#define NPRIO 32
#define TICK_US 10000           /* the timer ticks at 100 Hz */
#define SLICE_TICKS 5           /* a thread's time slice, in ticks */

/* the saved status register's bits */
#define SR_S 0x80000000u
#define SR_I 0x40000000u

/* the trap frame, as an exception leaves it on bank 0's stack */
struct frame {
    u32 sr;
    u32 pc;
};

enum tstate {
    T_FREE,
    T_READY,
    T_RUNNING,
    T_SEND,         /* in ipc_call, waiting for the server to receive */
    T_REPLY,        /* in ipc_call, received, waiting for the reply */
    T_RECV,         /* in ipc_recv, waiting for a message */
    T_SLEEP,
    T_WAIT,         /* in proc_wait */
};

struct proc;
struct port;

struct thread {
    int id;                     /* also its register bank */
    enum tstate state;
    int prio;
    int slice;
    struct proc *proc;
    u32 pc, sr;                 /* where it resumes */
    struct thread *next, *prev; /* the ready queue, or a port's queue */
    struct thread *pnext;       /* the process's threads */
    struct port *port;          /* the port it's sending to or receiving on */
    struct thread *peer;        /* T_REPLY: the server that received */
    u32 wake_at;                /* T_SLEEP: the time, in µs */
    int wait_pid;               /* T_WAIT: the child, or 0 for any */
    int peer_pid;               /* T_REPLY: the process that owes it a reply */
    u32 cycles;                 /* run time, in timer ticks */
    u32 gen;                    /* how many threads have had this bank: part of a rcvid */
    int rcvid;                  /* its rcvid, from its id and gen */
};

/* A rcvid names a thread waiting for a reply: its id and generation, so a
 * stale one can't reach a new thread in the same bank. A thread keeps its
 * own, made when it starts. */
#define MAKE_RCVID(t) ((int)((((t)->gen & 0x7FFFFF) << 8) | (t)->id))
#define RCVID(t) ((t)->rcvid)

enum pstate { P_FREE, P_LIVE, P_ZOMBIE };

struct proc {
    int pid;                    /* also its context */
    enum pstate state;
    int parent;
    int flags;                  /* PROC_IO, PROC_SPAWN */
    int pgid;                   /* its process group */
    int status;                 /* the exit status, for a zombie */
    char name[16];
    struct thread *threads;
    int nthreads;
    u32 pages;                  /* pages mapped */
    u32 low_top;                /* pages below this may be mapped (the image and heap) */
};

struct port {
    int id;
    int owner;                  /* the pid, or 0 for a free port */
    u32 pending;                /* notification bits not yet received */
    struct thread *senders;     /* T_SEND threads, a circular list */
    struct thread *receivers;   /* T_RECV threads */
};

/* globals */
extern struct thread *current;
extern int need_resched;
extern struct thread threads[MAX_THREADS];
extern struct proc procs[MAX_PROCS];
extern struct port ports[MAX_PORTS];
extern u32 ticks;
extern u32 ready_bits;
extern u32 ram_size;

/* entry.s */
void idle_wait(void);
u32 map_get(u32 index);
void map_set(u32 index, u32 entry);
void map_clear(u32 first, u32 n);
void set_bank(u32 bank);
u32 get_bank(void);
void set_ctx(u32 ctx);
u32 get_ctx(void);
u32 get_sr(void);
void ureg_set(u32 bank, int n, u32 v);
u32 ureg_get(u32 bank, int n);
void bank_copy(u32 to, u32 from);
void bank_copy_ur(u32 to, u32 from);
void bank_msg(u32 to, u32 from, u32 r8, u32 r9);
void bank_msg_ur(u32 to, u32 from, u32 r8, u32 r9);
#ifdef COPY_UR
#define bank_copy bank_copy_ur  /* to measure what BCOPY saves */
#define bank_msg bank_msg_ur
#endif
void page_zero(void *p);
int ucopy(void *dst, const void *src, u32 n);
int ustrncpy(char *dst, const char *src, u32 n);
int clz(u32 x);
void halt(void);
void start_first(void);
extern char kernel_end[] __asm__("__end");
extern char kstack_top[] __asm__("kstack_top");

/* klib.c */
void *memset(void *p, int c, unsigned n);
void *memcpy(void *d, const void *s, unsigned n);
int strcmp(const char *a, const char *b);
int strncmp(const char *a, const char *b, unsigned n);
unsigned strlen(const char *s);
void strlcpy(char *d, const char *s, unsigned n);
void kputs(const char *s);
void kprintf(const char *fmt, ...);
void panic(const char *fmt, ...);
int klog_read(char *buf, unsigned n, unsigned from);

/* mem.c */
void mem_init(u32 first_free);
u32 page_alloc(void);           /* a zeroed physical page, or 0 */
void page_ref(u32 pa);
void page_free(u32 pa);
u32 pages_free(void);
u32 pte_of(struct proc *p, u32 va);
void pte_set(struct proc *p, u32 va, u32 pte);
int vm_alloc(struct proc *p, u32 va, u32 n, u32 prot);
int vm_free(struct proc *p, u32 va, u32 n);
int vm_protect(struct proc *p, u32 va, u32 n, u32 prot);
int vm_map_phys(struct proc *p, u32 va, u32 pa, u32 n, u32 prot);
int vm_share(struct proc *from, u32 from_va, struct proc *to, u32 to_va, u32 n, u32 prot);
void vm_destroy(struct proc *p);
int copy_to_proc(struct proc *p, u32 va, const void *src, u32 n, int need_w);
int copy_from_proc(struct proc *p, u32 va, void *dst, u32 n);

/* proc.c */
void sched_init(void);
void q_append(struct thread **q, struct thread *t);
void q_remove(struct thread **q, struct thread *t);
void runq_to_front(struct thread *t);
void sleep_until(struct thread *t, u32 when);
int proc_wait(int pid, int nohang);
int is_descendant(int pid, int of);
void ready(struct thread *t);
void unready(struct thread *t);
void block(struct thread *t, enum tstate st);
void schedule(void);
int may_switch_to(struct thread *t);
void switch_to(struct thread *t);
struct proc *proc_new(const char *name, int parent, int flags);
struct thread *thread_new(struct proc *p, u32 pc, u32 sp, u32 arg, int prio);
void thread_kill(struct thread *t);
void proc_exit(struct proc *p, int status);
struct proc *proc_get(int pid);
struct thread *thread_get(int tid);
struct thread *rcvid_thread(int rcvid);
void timer_tick(u32 n);
void wake_sleepers(void);
u32 now_us(void);

/* ipc.c */
void ipc_init(void);
void ipc_thread_gone(struct thread *t);
void ipc_proc_gone(struct proc *p);
int notify_port(int port, u32 bits);
void ring_alarms(void);
void exit_notify(int pid);

/* trap.c */
void irq_init(void);
void irq_port_gone(int port);
u32 get_far(void);
u32 get_fsr(void);

/* main.c */
int boot_spawn(const char *name, int parent, int flags, int prio);

#endif
