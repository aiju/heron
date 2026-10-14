/* The nucleus's ready queues in C: 32 queues, a bit per non-empty queue,
   the highest priority found with CLZ (an assembly helper: C has no way
   to say it). */

struct tcb {
    struct tcb *next;
    int state, ctx, ctxb, bank, prio;
};

unsigned clz(unsigned x) __asm__("k_clz");

static struct tcb *head[32], *tail[32];
static unsigned bits;

void enqueue(struct tcb *t)
{
    int q = t->prio;
    t->next = 0;
    if (tail[q]) {
        tail[q]->next = t;
        tail[q] = t;
    } else {
        head[q] = tail[q] = t;
        bits |= 0x80000000u >> q;
    }
}

struct tcb *dequeue(void)
{
    struct tcb *t;
    int q;
    if (!bits)
        return 0;
    q = clz(bits);
    t = head[q];
    head[q] = t->next;
    if (!head[q]) {
        tail[q] = 0;
        bits &= ~(0x80000000u >> q);
    }
    return t;
}
