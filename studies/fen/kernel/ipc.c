/* Messages between threads: ports, calls, receives and replies,
 * notifications, and copies to and from a client's memory.
 *
 * A message is 8 words in r0-r7. ipc_call leaves it in the caller's bank
 * and blocks the caller; when a thread of the port's owner receives it,
 * BCOPY copies r0-r7 from the caller's bank into the receiver's, and the
 * receiver gets a rcvid for the caller (its thread id and the bank's
 * generation) in r8 and its pid in r9. The caller then waits until a thread of that process replies, with
 * the reply copied back the same way. Nothing is buffered in the kernel:
 * a message waits in its sender's registers. A server may receive others
 * before it replies (a deferred reply), and reads and writes a waiting
 * client's memory with ipc_read and ipc_write, which the kernel copies
 * through the window after looking the client's pages up in the map.
 *
 * Notifications are bits on a port: notify ORs them in, and a receive
 * takes them all as a message with rcvid 0 and the bits in r0. Interrupts
 * reach their user-level drivers that way (trap.c), and so does news of a
 * process ending, for servers that keep something per client. */

#include "kernel.h"

struct port ports[MAX_PORTS];

static struct {
    char name[16];
    int port;
} names[MAX_NAMES];

#define WATCHERS 16
static struct {
    int port;
    u32 bits;
} watchers[WATCHERS];

#define EXIT_LOG 64
static struct exit_entry exit_log[EXIT_LOG];
static u32 exit_seq;

void ipc_init(void)
{
    int i;
    for (i = 0; i < MAX_PORTS; i++)
        ports[i].id = i;
}

static struct port *port_get(int id)
{
    if (id <= 0 || id >= MAX_PORTS || !ports[id].owner)
        return 0;
    return &ports[id];
}

/* Wake a thread that waited at the front of its priority's queue: it's the
 * one the message is for, so it should run before others of its level. */
static void ready_front(struct thread *t)
{
    ready(t);
    runq_to_front(t);
}

/* The message in c's bank to s, which was waiting in a receive. */
static void deliver(struct thread *s, struct thread *c)
{
    bank_msg(s->id, c->id, RCVID(c), c->proc->pid);
    c->state = T_REPLY;
    c->peer = s;
    c->port = 0;
    c->peer_pid = s->proc->pid;
}

/* A notification to t, waiting in a receive (or about to return from one). */
static void deliver_bits(struct thread *t, struct port *p)
{
    ureg_set(t->id, 0, p->pending);
    ureg_set(t->id, 8, 0);
    ureg_set(t->id, 9, 0);
    p->pending = 0;
}

/* Wake t, blocked on a port or for a reply, with an error in r0 (and r8,
 * for a receiver). */
static void fail(struct thread *t, int err)
{
    ureg_set(t->id, 0, err);
    ureg_set(t->id, 8, err);
    t->port = 0;
    t->peer = 0;
    ready(t);
}

int sys_port_create(void)
{
    int i;
    for (i = 1; i < MAX_PORTS; i++) {
        struct port *p = &ports[i];
        if (!p->owner) {
            p->owner = current->proc->pid;
            p->pending = 0;
            p->senders = p->receivers = 0;
            return i;
        }
    }
    return -ENFILE;
}

/* alarms: a notification at a time, one for a port */
#define ALARMS 32
static struct {
    int port;
    u32 bits, at;
} alarms[ALARMS];
static int nalarms;

static void alarm_cancel(int id)
{
    int i;
    for (i = 0; i < nalarms; i++)
        if (alarms[i].port == id) {
            alarms[i] = alarms[--nalarms];
            return;
        }
}

int sys_alarm(int id, u32 bits, u32 us)
{
    struct port *p = port_get(id);
    if (!p || p->owner != current->proc->pid)
        return -EINVAL;
    alarm_cancel(id);
    if (!us)
        return 0;
    if (nalarms == ALARMS)
        return -ENFILE;
    alarms[nalarms].port = id;
    alarms[nalarms].bits = bits;
    alarms[nalarms].at = now_us() + us;
    nalarms++;
    return 0;
}

/* from the timer's tick: the alarms that are due */
void ring_alarms(void)
{
    u32 now;
    int i = 0;
    if (!nalarms)
        return;
    now = now_us();
    while (i < nalarms) {
        if ((int)(alarms[i].at - now) <= 0) {
            int id = alarms[i].port;
            u32 bits = alarms[i].bits;
            alarms[i] = alarms[--nalarms];
            notify_port(id, bits);
        } else {
            i++;
        }
    }
}

static void port_destroy(struct port *p)
{
    int i;
    while (p->senders) {
        struct thread *t = p->senders;
        q_remove(&p->senders, t);
        fail(t, -EPIPE);
    }
    while (p->receivers) {
        struct thread *t = p->receivers;
        q_remove(&p->receivers, t);
        fail(t, -EPIPE);
    }
    for (i = 0; i < MAX_NAMES; i++)
        if (names[i].port == p->id)
            names[i].port = 0;
    for (i = 0; i < WATCHERS; i++)
        if (watchers[i].port == p->id)
            watchers[i].port = 0;
    irq_port_gone(p->id);
    alarm_cancel(p->id);
    p->owner = 0;
    p->pending = 0;
}

int sys_port_destroy(int id)
{
    struct port *p = port_get(id);
    if (!p || p->owner != current->proc->pid)
        return -EINVAL;
    port_destroy(p);
    return 0;
}

/* ipc_call: port in r8, the message in r0-r7; the reply in r0-r7. */
void sys_ipc_call(void)
{
    struct thread *t = current;
    struct port *p = port_get(ureg_get(t->id, 8));
    struct thread *s;
    if (!p) {
        ureg_set(t->id, 0, -EINVAL);
        return;
    }
    s = p->receivers;
    if (s) {
        q_remove(&p->receivers, s);
        s->port = 0;
        deliver(s, t);
        if (may_switch_to(s)) {
            /* the client waits, the server runs: straight there */
            switch_to(s);
            return;
        }
        block(t, T_REPLY);
        ready_front(s);
    } else {
        t->port = p;
        block(t, T_SEND);
        q_append(&p->senders, t);
    }
}

/* t receives on p: a notification, a waiting caller's message, or it
 * blocks. */
static void receive(struct thread *t, struct port *p)
{
    struct thread *c;
    if (p->pending) {
        deliver_bits(t, p);
        return;
    }
    c = p->senders;
    if (c) {
        q_remove(&p->senders, c);
        deliver(t, c);
        return;
    }
    t->port = p;
    block(t, T_RECV);
    q_append(&p->receivers, t);
}

/* The reply in t's bank to the client rcvid names: the client, not yet
 * ready, or 0 if there's none waiting for t's process. */
static struct thread *reply_copy(struct thread *t, int rcvid)
{
    struct thread *c = rcvid_thread(rcvid);
    if (!c || c->state != T_REPLY || c->peer_pid != t->proc->pid)
        return 0;
    bank_copy(c->id, t->id);
    c->peer = 0;
    c->peer_pid = 0;
    return c;
}

static int reply(struct thread *t, int rcvid)
{
    struct thread *c = reply_copy(t, rcvid);
    if (!c)
        return -ESRCH;
    ready_front(c);
    return 0;
}

/* ipc_recv: port in r8; the message in r0-r7, rcvid in r8, pid in r9. */
void sys_ipc_recv(void)
{
    struct thread *t = current;
    struct port *p = port_get(ureg_get(t->id, 8));
    if (!p || p->owner != t->proc->pid) {
        ureg_set(t->id, 8, -EINVAL);
        return;
    }
    receive(t, p);
}

/* ipc_reply: rcvid in r8, the reply in r0-r7; the result in r8. */
void sys_ipc_reply(void)
{
    struct thread *t = current;
    ureg_set(t->id, 8, reply(t, ureg_get(t->id, 8)));
}

/* ipc_reply_recv: reply to r8 (if it's > 0), then receive on r9's port. A
 * reply to a client that has gone is forgotten. */
void sys_ipc_reply_recv(void)
{
    struct thread *t = current, *c = 0;
    int rcvid = ureg_get(t->id, 8);
    struct port *p = port_get(ureg_get(t->id, 9));
    if (rcvid > 0)
        c = reply_copy(t, rcvid);
    if (!p || p->owner != t->proc->pid) {
        if (c)
            ready_front(c);
        ureg_set(t->id, 8, -EINVAL);
        return;
    }
    if (c && !p->pending && !p->senders && may_switch_to(c)) {
        /* the server waits, the client runs: straight there */
        t->port = p;
        block(t, T_RECV);
        q_append(&p->receivers, t);
        switch_to(c);
        return;
    }
    if (c)
        ready_front(c);
    receive(t, p);
}

/* The client a server is answering: waiting for this process's reply. */
static struct thread *client(int rcvid)
{
    struct thread *c = rcvid_thread(rcvid);
    if (!c || c->state != T_REPLY || c->peer_pid != current->proc->pid)
        return 0;
    return c;
}

int sys_ipc_read(int rcvid, u32 from, void *buf, u32 n)
{
    struct thread *c = client(rcvid);
    int e;
    if (!c)
        return -ESRCH;
    e = copy_from_proc(c->proc, from, buf, n);
    return e ? e : (int)n;
}

int sys_ipc_write(int rcvid, u32 to, const void *buf, u32 n)
{
    struct thread *c = client(rcvid);
    int e;
    if (!c)
        return -ESRCH;
    e = copy_to_proc(c->proc, to, buf, n, 1);
    return e ? e : (int)n;
}

/* ipc_map(rcvid, client_va, my_va, n): map n pages of a waiting client's
 * memory into this process, readable and writable as they are to the
 * client: memory it shares by asking. */
int sys_ipc_map(int rcvid, u32 cva, u32 va, u32 n)
{
    struct thread *c = client(rcvid);
    u32 i;
    if (!c)
        return -ESRCH;
    for (i = 0; i < n; i++) {
        u32 pte = pte_of(c->proc, cva + i * PAGE);
        if (!(pte & PTE_V))
            return -EFAULT;
    }
    {
        u32 prot = PROT_READ;
        if (pte_of(c->proc, cva) & PTE_W)
            prot |= PROT_WRITE;
        return vm_share(c->proc, cva, current->proc, va, n, prot);
    }
}

int notify_port(int id, u32 bits)
{
    struct port *p = port_get(id);
    struct thread *t;
    if (!p)
        return -EINVAL;
    p->pending |= bits;
    t = p->receivers;
    if (t) {
        q_remove(&p->receivers, t);
        t->port = 0;
        deliver_bits(t, p);
        ready_front(t);
    }
    return 0;
}

int sys_notify(int id, u32 bits)
{
    return notify_port(id, bits);
}

int sys_name_register(const char *uname, int id)
{
    char name[16];
    int i, free = -1;
    struct port *p = port_get(id);
    int n = ustrncpy(name, uname, sizeof name);
    if (n < 0)
        return n;
    if (!p || p->owner != current->proc->pid)
        return -EINVAL;
    for (i = 0; i < MAX_NAMES; i++) {
        if (names[i].port && !strcmp(names[i].name, name)) {
            names[i].port = id;
            return 0;
        }
        if (!names[i].port && free < 0)
            free = i;
    }
    if (free < 0)
        return -ENFILE;
    strlcpy(names[free].name, name, sizeof names[free].name);
    names[free].port = id;
    return 0;
}

int sys_name_lookup(const char *uname)
{
    char name[16];
    int i;
    int n = ustrncpy(name, uname, sizeof name);
    if (n < 0)
        return n;
    for (i = 0; i < MAX_NAMES; i++)
        if (names[i].port && !strcmp(names[i].name, name))
            return names[i].port;
    return -ENOENT;
}

/* exit_watch(port, bits): notify the port with bits whenever a process
 * ends; exit_log tells which. */
int sys_exit_watch(int id, u32 bits)
{
    int i;
    struct port *p = port_get(id);
    if (!p || p->owner != current->proc->pid)
        return -EINVAL;
    for (i = 0; i < WATCHERS; i++)
        if (!watchers[i].port) {
            watchers[i].port = id;
            watchers[i].bits = bits;
            return 0;
        }
    return -ENFILE;
}

void exit_notify(int pid)
{
    int i;
    exit_seq++;
    exit_log[exit_seq % EXIT_LOG].seq = exit_seq;
    exit_log[exit_seq % EXIT_LOG].pid = pid;
    for (i = 0; i < WATCHERS; i++)
        if (watchers[i].port)
            notify_port(watchers[i].port, watchers[i].bits);
}

/* exit_log(seq, buf, n): the entries after seq, oldest first, at most n;
 * how many. If the log has moved on more than it holds, the first entry
 * returned has pid 0: some were lost. */
int sys_exit_log(u32 seq, struct exit_entry *buf, int n)
{
    struct exit_entry e;
    int k = 0;
    if (exit_seq - seq > EXIT_LOG) {
        e.seq = exit_seq - EXIT_LOG;
        e.pid = 0;
        if (ucopy(buf, &e, sizeof e))
            return -EFAULT;
        k = 1;
        seq = exit_seq - EXIT_LOG;
    }
    while (k < n && seq != exit_seq) {
        seq++;
        e = exit_log[seq % EXIT_LOG];
        if (ucopy(&buf[k], &e, sizeof e))
            return -EFAULT;
        k++;
    }
    return k;
}

void ipc_thread_gone(struct thread *t)
{
    if (t->state == T_SEND && t->port)
        q_remove(&t->port->senders, t);
    if (t->state == T_RECV && t->port)
        q_remove(&t->port->receivers, t);
    t->port = 0;
}

void ipc_proc_gone(struct proc *p)
{
    int i;
    for (i = 1; i < MAX_PORTS; i++)
        if (ports[i].owner == p->pid)
            port_destroy(&ports[i]);
    /* its clients waiting for replies get an error */
    for (i = 1; i < MAX_THREADS; i++) {
        struct thread *t = &threads[i];
        if (t->state == T_REPLY && t->peer_pid == p->pid)
            fail(t, -EPIPE);
    }
}
