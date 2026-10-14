/* The ready queue, as a C nucleus would have it: N rounds of putting a
   thread at the back of its queue and taking the first of the highest
   priority, through sched.c (C) or sched_v1b.s (hand-written). */

struct tcb {
    struct tcb *next;
    int state, ctx, ctxb, bank, prio;
};

void enqueue(struct tcb *t);
struct tcb *dequeue(void);

static struct tcb a, b;

int main(void)
{
    int i;
    a.prio = 8;
    b.prio = 8;
    enqueue(&a);
    for (i = 0; i < N; i++) {
        enqueue(i & 1 ? &a : &b);
        dequeue();
    }
    return 0;
}
