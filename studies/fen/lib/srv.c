/* The servers' library (fen/srv.h): descriptor tables per process, the
 * exit log, kept requests. */

#include <stdlib.h>
#include <string.h>
#include <fen/sys.h>
#include <fen/srv.h>

#define PIDS 128

static struct srv_file *table[PIDS][MAX_FDS];
static void (*release_fn)(struct srv_file *f);
static unsigned exit_seq;

void srv_init(int port, void (*release)(struct srv_file *f))
{
    struct exit_entry e[16];
    int n;
    release_fn = release;
    exit_watch(port, SRV_EXIT_BIT);
    /* start from the log's end: what ended before doesn't concern us */
    while ((n = exit_log(exit_seq, e, 16)) > 0)
        exit_seq = e[n - 1].seq;
}

struct srv_file *srv_fd(int pid, int fd)
{
    if (pid <= 0 || pid >= PIDS || fd < 0 || fd >= MAX_FDS)
        return 0;
    return table[pid][fd];
}

static int slot(int pid, struct srv_file *f)
{
    int i;
    if (pid <= 0 || pid >= PIDS)
        return -ESRCH;
    for (i = 0; i < MAX_FDS; i++)
        if (!table[pid][i]) {
            table[pid][i] = f;
            f->refs++;
            return i;
        }
    return -EMFILE;
}

int srv_open(int pid, int kind, void *obj, int flags)
{
    struct srv_file *f = malloc(sizeof *f);
    int fd;
    if (!f)
        return -ENOMEM;
    f->refs = 0;
    f->flags = flags;
    f->off = 0;
    f->kind = kind;
    f->obj = obj;
    fd = slot(pid, f);
    if (fd < 0)
        free(f);
    return fd;
}

int srv_dupto(int pid, int fd, int topid)
{
    struct srv_file *f = srv_fd(pid, fd);
    if (!f)
        return -EBADF;
    return slot(topid, f);
}

int srv_close(int pid, int fd)
{
    struct srv_file *f = srv_fd(pid, fd);
    if (!f)
        return -EBADF;
    table[pid][fd] = 0;
    if (--f->refs == 0) {
        if (release_fn)
            release_fn(f);
        free(f);
    }
    return 0;
}

static void close_all(int pid)
{
    int i;
    for (i = 0; i < MAX_FDS; i++)
        if (table[pid][i])
            srv_close(pid, i);
}

void srv_exits(void (*gone)(int pid))
{
    struct exit_entry e[16];
    int n, i;
    while ((n = exit_log(exit_seq, e, 16)) > 0) {
        for (i = 0; i < n; i++) {
            if (e[i].pid == 0) {
                /* some were lost: check every table we have */
                int p;
                struct proc_info pi[PIDS];
                int live[PIDS];
                int k = proc_list(pi, PIDS), j;
                memset(live, 0, sizeof live);
                for (j = 0; j < k; j++)
                    if (pi[j].state == 1)
                        live[pi[j].pid] = 1;
                for (p = 1; p < PIDS; p++)
                    if (!live[p]) {
                        close_all(p);
                        if (gone)
                            gone(p);
                    }
            } else if (e[i].pid > 0 && e[i].pid < PIDS) {
                close_all(e[i].pid);
                if (gone)
                    gone(e[i].pid);
            }
            exit_seq = e[i].seq;
        }
    }
}

struct srv_req *srv_keep(struct srv_req **list, int rcvid, int pid, msg_t *m)
{
    struct srv_req *r = malloc(sizeof *r), **pp;
    if (!r)
        return 0;
    r->rcvid = rcvid;
    r->pid = pid;
    r->m = *m;
    r->done = 0;
    r->next = 0;
    for (pp = list; *pp; pp = &(*pp)->next)
        ;
    *pp = r;
    return r;
}

void srv_answer(struct srv_req **list, struct srv_req *r, int status)
{
    struct srv_req **pp;
    for (pp = list; *pp; pp = &(*pp)->next)
        if (*pp == r) {
            *pp = r->next;
            break;
        }
    srv_reply(r->rcvid, status);
    free(r);
}

void srv_drop_pid(struct srv_req **list, int pid)
{
    struct srv_req **pp = list;
    while (*pp) {
        struct srv_req *r = *pp;
        if (r->pid == pid) {
            *pp = r->next;
            free(r);
        } else {
            pp = &r->next;
        }
    }
}

static int next_rcvid;
static msg_t next_msg;

void srv_reply_next(int rcvid, const msg_t *reply)
{
    if (next_rcvid > 0)
        ipc_reply(next_rcvid, &next_msg);
    next_rcvid = rcvid;
    next_msg = *reply;
}

int srv_recv(int port, msg_t *m, int *pid)
{
    int rcvid = next_rcvid;
    if (rcvid <= 0)
        return ipc_recv(port, m, pid);
    next_rcvid = 0;
    *m = next_msg;
    return ipc_reply_recv(rcvid, m, port, pid);
}

int srv_reply(int rcvid, int status)
{
    msg_t m;
    memset(&m, 0, sizeof m);
    m.w[0] = status;
    return ipc_reply(rcvid, &m);
}

int srv_path(int rcvid, msg_t *m, int which, char *buf, unsigned size)
{
    unsigned n = m->w[which + 1];
    int r;
    if (n >= size)
        return -ENAMETOOLONG;
    r = ipc_read(rcvid, (void *)m->w[which], buf, n);
    if (r < 0)
        return r;
    buf[n] = 0;
    if (strlen(buf) != n)
        return -EINVAL;
    return n;
}
