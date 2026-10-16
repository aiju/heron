/* Exceptions and interrupts.
 *
 * A user thread's exceptions end its process, except page faults in its
 * stack region, which map a zero page and run the instruction again. The
 * timer is the kernel's: it ticks at 100 Hz, rearming the compare
 * register each time. Every other level is a user-level driver's: the
 * kernel masks the level (the board's interrupt mask) and notifies the
 * driver's port, and the driver unmasks it with irq_ack once it has
 * quietened the device. */

#include "kernel.h"

static int irq_port[8];
static u32 irq_bits[8];
static u32 next_tick;

void irq_init(void)
{
    next_tick = now_us() + TICK_US;
    TIMER_COMPARE = next_tick;
    IRQ_MASK = 1 << IRQ_TIMER;
}

static void tick(void)
{
    u32 now = now_us();
    next_tick += TICK_US;
    if ((int)(next_tick - now) <= 0)
        next_tick = now + TICK_US;
    TIMER_COMPARE = next_tick;          /* clears FIRED, and arms */
    timer_tick();
}

void interrupt(int level)
{
    if (level == IRQ_TIMER) {
        tick();
        return;
    }
    IRQ_MASK = IRQ_MASK & ~(1u << level);
    if (irq_port[level])
        notify_port(irq_port[level], irq_bits[level]);
}

int sys_irq_bind(int level, int port, u32 bits)
{
    if (!(current->proc->flags & PROC_IO))
        return -EPERM;
    if (level < 0 || level > 7 || level == IRQ_TIMER)
        return -EINVAL;
    irq_port[level] = port;
    irq_bits[level] = bits;
    IRQ_MASK = IRQ_MASK | (1u << level);
    return 0;
}

int sys_irq_ack(int level)
{
    if (!(current->proc->flags & PROC_IO))
        return -EPERM;
    if (level < 0 || level > 7 || level == IRQ_TIMER || !irq_port[level])
        return -EINVAL;
    IRQ_MASK = IRQ_MASK | (1u << level);
    return 0;
}

void irq_port_gone(int port)
{
    int l;
    for (l = 0; l < 8; l++)
        if (irq_port[l] == port) {
            irq_port[l] = 0;
            IRQ_MASK = IRQ_MASK & ~(1u << l);
        }
}

static const char *what(int vector)
{
    switch (vector) {
    case 0x04: return "non-maskable interrupt";
    case 0x08: return "illegal instruction";
    case 0x0C: return "bus error";
    case 0x10: return "divide error";
    case 0x14: return "address error";
    case 0x18: return "tag trap";
    case 0x1C: return "privilege violation";
    case 0x20: return "page fault";
    case 0x24: return "trace";
    }
    return "exception";
}

/* the exit status, as a shell shows it: 128 + the Unix signal */
static int status_of(int vector)
{
    switch (vector) {
    case 0x08: return 128 + 4;      /* SIGILL */
    case 0x0C: return 128 + 7;      /* SIGBUS */
    case 0x10: return 128 + 8;      /* SIGFPE */
    case 0x14: return 128 + 7;
    case 0x24: return 128 + 5;      /* SIGTRAP */
    }
    return 128 + 11;                /* SIGSEGV */
}

/* A page that may grow the stack: map it, if it's in the stack's region. */
static int grow_stack(struct proc *p, u32 va, u32 fsr)
{
    return (fsr & 1) && va < STACK_TOP && va >= STACK_TOP - STACK_MAX &&
           vm_alloc(p, va & ~(PAGE - 1), 1, PROT_READ | PROT_WRITE) == 0;
}

/* A page fault in the kernel's copy of user memory (entry.s): 1 if it was
 * the stack growing, and the copy can go on. */
int copy_fault(void)
{
    if (!current)
        return 0;
    return grow_stack(current->proc, get_far(), get_fsr());
}

/* An exception from user mode. */
void exception(int vector)
{
    struct thread *t = current;
    struct proc *p = t->proc;
    struct frame *f = (struct frame *)(kstack_top - 8);
    if (vector == 0x20) {
        u32 va = get_far();
        u32 fsr = get_fsr();
        if (grow_stack(p, va, fsr))
            return;
        kprintf("%s[%d]: page fault at %x (fsr %x), pc %x\n", p->name, p->pid, va, fsr, f->pc);
    } else if (vector == 0x14 || vector == 0x0C) {
        kprintf("%s[%d]: %s at %x, pc %x\n", p->name, p->pid, what(vector), get_far(), f->pc);
    } else {
        kprintf("%s[%d]: %s, pc %x\n", p->name, p->pid, what(vector), f->pc);
    }
    proc_exit(p, status_of(vector));
}

void kernel_fault(int vector, struct frame *f)
{
    panic("%s in the kernel at pc %x (sr %x, far %x, fsr %x)", what(vector), f->pc, f->sr,
          get_far(), get_fsr());
}
