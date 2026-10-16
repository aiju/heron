/* fs: the file server. Files and directories on the CF card (fenfs.c),
 * pipes, and the devices in /dev that are just data (null, zero, the
 * kernel's log), all through the file protocol (fen/fs.h).
 *
 * One thread, one loop. A request that can't be answered yet (a read of an
 * empty pipe, a write to a full one) is kept and answered later; while the
 * card works, requests that come in are kept too (wait_irq), and the loop
 * takes the kept ones before new ones. */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <fen/sys.h>
#include <fen/fs.h>
#include <fen/srv.h>
#include "fs.h"

int fs_port;

enum { K_FILE = 1, K_DIR, K_PIPE_R, K_PIPE_W, K_NULL, K_ZERO, K_KLOG };

/* character devices: an inode of type S_IFCHR whose first block slot is
 * its kind */
#define DEV_NULL 1
#define DEV_ZERO 2
#define DEV_KLOG 3

/* requests that came while the server waited for the card */
static struct srv_req *backlog;
static unsigned irq_seen;
static int exits_pending;

void wait_irq(unsigned bit)
{
    msg_t m;
    int pid, rcvid;
    while (!(irq_seen & bit)) {
        rcvid = ipc_recv(fs_port, &m, &pid);
        if (rcvid == 0) {
            irq_seen |= m.w[0];
            if (m.w[0] & SRV_EXIT_BIT)
                exits_pending = 1;
        } else if (rcvid > 0) {
            srv_keep(&backlog, rcvid, pid, &m);
        }
    }
    irq_seen &= ~bit;
}

/* ---- pipes ---- */

#define PIPE_SIZE 4096

struct pipe {
    unsigned char buf[PIPE_SIZE];
    unsigned rd, wr;            /* bytes read and written, ever */
    int readers, writers;
    struct srv_req *rq, *wq;    /* reads and writes waiting */
    struct pipe *next;
};

static struct pipe *pipes;

static int pipe_put(struct pipe *p, int rcvid, msg_t *m, unsigned done, unsigned n)
{
    /* copy from the client into the ring: as much as fits */
    while (done < n && p->wr - p->rd < PIPE_SIZE) {
        unsigned at = p->wr % PIPE_SIZE;
        unsigned k = PIPE_SIZE - at;
        unsigned room = PIPE_SIZE - (p->wr - p->rd);
        int e;
        if (k > room)
            k = room;
        if (k > n - done)
            k = n - done;
        if (m->w[0] == FS_WRITE_INLINE)
            memcpy(p->buf + at, (char *)&m->w[4] + done, k);
        else if ((e = ipc_read(rcvid, (char *)m->w[2] + done, p->buf + at, k)) < 0)
            return e;
        p->wr += k;
        done += k;
    }
    return done;
}

static int pipe_get(struct pipe *p, int rcvid, msg_t *m)
{
    unsigned n = m->w[3], done = 0;
    while (done < n && p->rd != p->wr) {
        unsigned at = p->rd % PIPE_SIZE;
        unsigned k = PIPE_SIZE - at;
        int e;
        if (k > p->wr - p->rd)
            k = p->wr - p->rd;
        if (k > n - done)
            k = n - done;
        if ((e = ipc_write(rcvid, (char *)m->w[2] + done, p->buf + at, k)) < 0)
            return e;
        p->rd += k;
        done += k;
    }
    return done;
}

/* Move what can move: waiting writes into the ring, waiting reads out. */
static void pipe_run(struct pipe *p)
{
    int moved = 1;
    while (moved) {
        moved = 0;
        while (p->wq) {
            struct srv_req *r = p->wq;
            unsigned n = r->m.w[0] == FS_WRITE_INLINE ? r->m.w[2] : r->m.w[3];
            int done;
            if (!p->readers) {
                srv_answer(&p->wq, r, -EPIPE);
                continue;
            }
            done = pipe_put(p, r->rcvid, &r->m, r->done, n);
            if (done < 0) {
                srv_answer(&p->wq, r, done);
                continue;
            }
            if ((unsigned)done != r->done)
                moved = 1;
            r->done = done;
            if ((unsigned)done < n)
                break;
            srv_answer(&p->wq, r, n);
        }
        while (p->rq && (p->rd != p->wr || !p->writers)) {
            struct srv_req *r = p->rq;
            int got = pipe_get(p, r->rcvid, &r->m);
            if (got > 0)
                moved = 1;
            srv_answer(&p->rq, r, got);
        }
    }
}

static struct pipe *pipe_new(void)
{
    struct pipe *p = calloc(1, sizeof *p);
    if (p) {
        p->next = pipes;
        pipes = p;
    }
    return p;
}

static void pipe_maybe_free(struct pipe *p)
{
    struct pipe **pp;
    if (p->readers || p->writers)
        return;
    for (pp = &pipes; *pp; pp = &(*pp)->next)
        if (*pp == p) {
            *pp = p->next;
            break;
        }
    free(p);
}

/* ---- open files ---- */

static void release(struct srv_file *f)
{
    struct pipe *p = f->obj;
    switch (f->kind) {
    case K_FILE:
    case K_DIR:
        iput(f->obj);
        break;
    case K_PIPE_R:
        p->readers--;
        pipe_run(p);
        pipe_maybe_free(p);
        break;
    case K_PIPE_W:
        p->writers--;
        pipe_run(p);
        pipe_maybe_free(p);
        break;
    }
}

static void gone(int pid)
{
    struct pipe *p;
    srv_drop_pid(&backlog, pid);
    for (p = pipes; p; p = p->next) {
        srv_drop_pid(&p->rq, pid);
        srv_drop_pid(&p->wq, pid);
    }
}

static void fill_stat(struct inode *ip, struct stat *st)
{
    memset(st, 0, sizeof *st);
    st->st_mode = ip->d.mode;
    st->st_size = ip->d.size;
    st->st_ino = ip->ino;
    st->st_nlink = ip->d.nlink;
    st->st_mtime = ip->d.mtime;
}

struct client {
    int rcvid;
    unsigned buf;
};

static int to_client(void *ctx, unsigned off, void *p, unsigned n)
{
    struct client *c = ctx;
    return ipc_write(c->rcvid, (void *)(c->buf + off), p, n);
}

static int from_client(void *ctx, unsigned off, void *p, unsigned n)
{
    struct client *c = ctx;
    return ipc_read(c->rcvid, (void *)(c->buf + off), p, n);
}

static int from_inline(void *ctx, unsigned off, void *p, unsigned n)
{
    memcpy(p, (char *)ctx + off, n);
    return 0;
}

static int do_open(int rcvid, int pid, msg_t *m)
{
    char path[256], name[FENFS_NAME];
    int err, flags = m->w[3], kind, acc;
    struct inode *ip;
    int e = srv_path(rcvid, m, 1, path, sizeof path);
    if (e < 0)
        return e;
    acc = flags & O_ACCMODE;
    ip = namei(path, &err);
    if (!ip) {
        struct inode *dp;
        if (err != -ENOENT || !(flags & O_CREAT))
            return err;
        dp = nameiparent(path, name, &err);
        if (!dp)
            return err;
        ip = ialloc(S_IFREG | 0644);
        if (!ip) {
            iput(dp);
            return -ENOSPC;
        }
        ip->d.nlink = 1;
        iupdate(ip);
        e = dirlink(dp, name, ip->ino);
        iput(dp);
        if (e < 0) {
            ip->d.nlink = 0;
            iput(ip);
            return e;
        }
    } else if ((flags & O_CREAT) && (flags & O_EXCL)) {
        iput(ip);
        return -EEXIST;
    }
    if (S_ISDIR(ip->d.mode)) {
        if (acc != O_RDONLY) {
            iput(ip);
            return -EISDIR;
        }
        kind = K_DIR;
    } else if (S_ISCHR(ip->d.mode)) {
        unsigned dev = ip->d.direct[0];
        iput(ip);
        kind = dev == DEV_ZERO ? K_ZERO : dev == DEV_KLOG ? K_KLOG : K_NULL;
        return srv_open(pid, kind, 0, flags);
    } else {
        if (flags & O_DIRECTORY) {
            iput(ip);
            return -ENOTDIR;
        }
        kind = K_FILE;
        if ((flags & O_TRUNC) && acc != O_RDONLY)
            itrunc(ip, 0);
    }
    e = srv_open(pid, kind, ip, flags);
    if (e < 0)
        iput(ip);
    return e;
}

static int do_read(int rcvid, int pid, msg_t *m, struct srv_file *f)
{
    struct client c;
    int n;
    c.rcvid = rcvid;
    c.buf = m->w[2];
    switch (f->kind) {
    case K_FILE:
        n = readi(f->obj, f->off, m->w[3], to_client, &c);
        if (n > 0)
            f->off += n;
        return n;
    case K_PIPE_R: {
        struct pipe *p = f->obj;
        if (p->rd == p->wr && p->writers) {
            srv_keep(&p->rq, rcvid, pid, m);
            return 1 << 30;     /* answered later */
        }
        n = pipe_get(p, rcvid, m);
        pipe_run(p);
        return n;
    }
    case K_NULL:
        return 0;
    case K_ZERO: {
        static char zero[256];
        unsigned done = 0, k;
        while (done < (unsigned)m->w[3]) {
            k = m->w[3] - done > sizeof zero ? sizeof zero : m->w[3] - done;
            if (ipc_write(rcvid, (char *)c.buf + done, zero, k) < 0)
                break;
            done += k;
        }
        return done;
    }
    case K_KLOG: {
        char buf[512];
        int k = klog(buf, m->w[3] < 512 ? m->w[3] : 512, f->off);
        if (k > 0) {
            ipc_write(rcvid, (void *)c.buf, buf, k);
            f->off += k;
        }
        return k;
    }
    case K_DIR:
        return -EISDIR;
    }
    return -EBADF;
}

static int do_write(int rcvid, int pid, msg_t *m, struct srv_file *f)
{
    struct client c;
    int inl = m->w[0] == FS_WRITE_INLINE;
    unsigned n = inl ? m->w[2] : m->w[3];
    int r;
    if ((f->flags & O_ACCMODE) == O_RDONLY && f->kind != K_PIPE_W)
        return -EBADF;
    c.rcvid = rcvid;
    c.buf = m->w[2];
    switch (f->kind) {
    case K_FILE: {
        struct inode *ip = f->obj;
        if (f->flags & O_APPEND)
            f->off = ip->d.size;
        if (inl)
            r = writei(ip, f->off, n, from_inline, &m->w[4]);
        else
            r = writei(ip, f->off, n, from_client, &c);
        if (r > 0)
            f->off += r;
        return r;
    }
    case K_PIPE_W: {
        struct pipe *p = f->obj;
        int done;
        if (!p->readers)
            return -EPIPE;
        done = pipe_put(p, rcvid, m, 0, n);
        if (done < 0)
            return done;
        pipe_run(p);
        if ((unsigned)done < n) {
            struct srv_req *k = srv_keep(&p->wq, rcvid, pid, m);
            if (k)
                k->done = done;
            return 1 << 30;
        }
        return n;
    }
    case K_NULL:
    case K_ZERO:
        return n;
    case K_KLOG: {
        char buf[64];
        unsigned done = 0, k;
        if (inl) {
            kdebug((char *)&m->w[4], n);
            return n;
        }
        while (done < n) {
            k = n - done > sizeof buf ? sizeof buf : n - done;
            if (ipc_read(rcvid, (char *)c.buf + done, buf, k) < 0)
                break;
            kdebug(buf, k);
            done += k;
        }
        return done;
    }
    }
    return -EBADF;
}

/* FS_READDIR: whole entries, the free ones left out */
struct dirsink {
    int rcvid;
    unsigned buf, n, done, consumed;
};

static int dir_sink(void *ctx, unsigned off, void *p, unsigned n)
{
    struct dirsink *s = ctx;
    struct fenfs_dirent *d = p;
    unsigned i;
    for (i = 0; i < n / sizeof *d; i++) {
        if (s->done + sizeof *d > s->n)
            return -1;
        s->consumed += sizeof *d;
        if (!d[i].ino)
            continue;
        if (ipc_write(s->rcvid, (void *)(s->buf + s->done), &d[i], sizeof *d) < 0)
            return -1;
        s->done += sizeof *d;
    }
    return 0;
}

static int do_readdir(int rcvid, msg_t *m, struct srv_file *f)
{
    struct dirsink s;
    struct inode *ip = f->obj;
    if (f->kind != K_DIR)
        return -ENOTDIR;
    s.rcvid = rcvid;
    s.buf = m->w[2];
    s.n = m->w[3];
    s.done = s.consumed = 0;
    readi(ip, f->off, ip->d.size - f->off, dir_sink, &s);
    f->off += s.consumed;
    return s.done;
}

static int do_mkdir(int rcvid, msg_t *m)
{
    char path[256], name[FENFS_NAME];
    struct inode *dp, *ip;
    int err, e = srv_path(rcvid, m, 1, path, sizeof path);
    if (e < 0)
        return e;
    if ((ip = namei(path, &err)) != 0) {
        iput(ip);
        return -EEXIST;
    }
    dp = nameiparent(path, name, &err);
    if (!dp)
        return err;
    ip = ialloc(S_IFDIR | 0755);
    if (!ip) {
        iput(dp);
        return -ENOSPC;
    }
    ip->d.nlink = 2;
    iupdate(ip);
    e = dirlink(ip, ".", ip->ino);
    if (e >= 0)
        e = dirlink(ip, "..", dp->ino);
    if (e >= 0)
        e = dirlink(dp, name, ip->ino);
    if (e >= 0) {
        dp->d.nlink++;
        iupdate(dp);
    } else {
        ip->d.nlink = 0;
    }
    iput(ip);
    iput(dp);
    return e < 0 ? e : 0;
}

static int do_unlink(int rcvid, msg_t *m)
{
    char path[256], name[FENFS_NAME];
    struct inode *dp, *ip;
    int err, e = srv_path(rcvid, m, 1, path, sizeof path);
    if (e < 0)
        return e;
    dp = nameiparent(path, name, &err);
    if (!dp)
        return err;
    ip = dirlookup(dp, name, 0);
    if (!ip) {
        iput(dp);
        return -ENOENT;
    }
    if (S_ISDIR(ip->d.mode)) {
        if (!dirempty(ip)) {
            iput(ip);
            iput(dp);
            return -ENOTEMPTY;
        }
        dp->d.nlink--;
        iupdate(dp);
        ip->d.nlink = 0;
    } else {
        ip->d.nlink--;
    }
    iupdate(ip);
    e = dirunlink(dp, name);
    iput(ip);
    iput(dp);
    return e;
}

static int do_rename(int rcvid, msg_t *m)
{
    char from[256], to[256], fname[FENFS_NAME], tname[FENFS_NAME];
    struct inode *fd, *td, *ip, *old;
    int err, e;
    if ((e = srv_path(rcvid, m, 1, from, sizeof from)) < 0 ||
        (e = srv_path(rcvid, m, 3, to, sizeof to)) < 0)
        return e;
    if (!strcmp(from, to))
        return 0;
    fd = nameiparent(from, fname, &err);
    if (!fd)
        return err;
    ip = dirlookup(fd, fname, 0);
    if (!ip) {
        iput(fd);
        return -ENOENT;
    }
    td = nameiparent(to, tname, &err);
    if (!td) {
        iput(ip);
        iput(fd);
        return err;
    }
    old = dirlookup(td, tname, 0);
    if (old) {
        if (S_ISDIR(old->d.mode)) {
            iput(old);
            e = -EISDIR;
            goto out;
        }
        old->d.nlink--;
        iupdate(old);
        dirunlink(td, tname);
        iput(old);
    }
    e = dirlink(td, tname, ip->ino);
    if (e >= 0)
        e = dirunlink(fd, fname);
    if (e >= 0 && S_ISDIR(ip->d.mode) && fd != td) {
        /* its .. moves */
        dirunlink(ip, "..");
        dirlink(ip, "..", td->ino);
        fd->d.nlink--;
        td->d.nlink++;
        iupdate(fd);
        iupdate(td);
    }
out:
    iput(ip);
    iput(td);
    iput(fd);
    return e < 0 ? e : 0;
}

static int do_stat(int rcvid, msg_t *m)
{
    char path[256];
    struct stat st;
    struct inode *ip;
    int err, e = srv_path(rcvid, m, 1, path, sizeof path);
    if (e < 0)
        return e;
    ip = namei(path, &err);
    if (!ip)
        return err;
    fill_stat(ip, &st);
    iput(ip);
    e = ipc_write(rcvid, (void *)m->w[3], &st, sizeof st);
    return e < 0 ? e : 0;
}

static int do_fstat(int rcvid, msg_t *m, struct srv_file *f)
{
    struct stat st;
    int e;
    memset(&st, 0, sizeof st);
    if (f->kind == K_FILE || f->kind == K_DIR)
        fill_stat(f->obj, &st);
    else if (f->kind == K_PIPE_R || f->kind == K_PIPE_W) {
        struct pipe *p = f->obj;
        st.st_mode = S_IFIFO | 0600;
        st.st_size = p->wr - p->rd;
    } else
        st.st_mode = S_IFCHR | 0666;
    e = ipc_write(rcvid, (void *)m->w[2], &st, sizeof st);
    return e < 0 ? e : 0;
}

static int do_pipe(int pid, msg_t *m)
{
    struct pipe *p = pipe_new();
    int a, b;
    if (!p)
        return -ENOMEM;
    a = srv_open(pid, K_PIPE_R, p, O_RDONLY);
    if (a < 0) {
        pipe_maybe_free(p);
        return a;
    }
    p->readers = 1;
    b = srv_open(pid, K_PIPE_W, p, O_WRONLY);
    if (b < 0) {
        srv_close(pid, a);
        return b;
    }
    p->writers = 1;
    m->w[1] = a;
    m->w[2] = b;
    return 0;
}

/* a pipe's ends count open files, not descriptors, so a copy changes
 * nothing there */
static int do_dupto(int pid, msg_t *m)
{
    return srv_dupto(pid, m->w[1], m->w[2]);
}

static int do_seek(msg_t *m, struct srv_file *f)
{
    int off = m->w[2];
    if (f->kind != K_FILE && f->kind != K_DIR)
        return -ESPIPE;
    switch (m->w[3]) {
    case SEEK_SET: break;
    case SEEK_CUR: off += f->off; break;
    case SEEK_END: off += ((struct inode *)f->obj)->d.size; break;
    default: return -EINVAL;
    }
    if (off < 0)
        return -EINVAL;
    f->off = off;
    return off;
}

static int do_statfs(int rcvid, msg_t *m)
{
    struct statfs st;
    int e;
    st.f_bsize = BLOCK;
    st.f_blocks = sb.nblocks - sb.data_start;
    st.f_bfree = fs_free_blocks();
    st.f_files = sb.ninodes - 2;
    st.f_ffree = fs_free_inodes();
    e = ipc_write(rcvid, (void *)m->w[1], &st, sizeof st);
    return e < 0 ? e : 0;
}

/* One request: its answer, or 1 << 30 if it was kept for later. Some
 * replies carry more than word 0 (FS_PIPE), so the handler fills m. */
static int handle(int rcvid, int pid, msg_t *m)
{
    struct srv_file *f = 0;
    int op = m->w[0];
    switch (op) {
    case FS_OPEN: return do_open(rcvid, pid, m);
    case FS_STAT: return do_stat(rcvid, m);
    case FS_MKDIR: return do_mkdir(rcvid, m);
    case FS_UNLINK: return do_unlink(rcvid, m);
    case FS_RENAME: return do_rename(rcvid, m);
    case FS_PIPE: return do_pipe(pid, m);
    case FS_SYNC: return bsync();
    case FS_STATFS: return do_statfs(rcvid, m);
    }
    f = srv_fd(pid, m->w[1]);
    if (!f)
        return -EBADF;
    switch (op) {
    case FS_CLOSE: return srv_close(pid, m->w[1]);
    case FS_READ: return do_read(rcvid, pid, m, f);
    case FS_WRITE:
    case FS_WRITE_INLINE: return do_write(rcvid, pid, m, f);
    case FS_SEEK: return do_seek(m, f);
    case FS_FSTAT: return do_fstat(rcvid, m, f);
    case FS_READDIR: return do_readdir(rcvid, m, f);
    case FS_DUPTO: return do_dupto(pid, m);
    case FS_TRUNC:
        if (f->kind != K_FILE)
            return -EINVAL;
        return itrunc(f->obj, m->w[2]);
    case FS_IOCTL:
        return m->w[2] == IO_ISTTY ? 0 : -ENOTTY;
    }
    return -ENOSYS;
}

static void serve(int rcvid, int pid, msg_t *m)
{
    int r = handle(rcvid, pid, m);
    if (r == 1 << 30)
        return;
    m->w[0] = r;
    ipc_reply(rcvid, m);
}

static void say(const char *s)
{
    kdebug(s, strlen(s));
}

int main(void)
{
    msg_t m;
    int pid, rcvid, e;
    char buf[80];
    fs_port = port_create();
    if (fs_port < 0)
        return 1;
    srv_init(fs_port, release);
    e = ide_init();
    if (e < 0) {
        say("fs: no CF card\n");
        return 1;
    }
    e = fs_mount();
    if (e < 0) {
        say("fs: no file system on the card\n");
        return 1;
    }
    snprintf(buf, sizeof buf, "fs: %u KB card, %u blocks, %u inodes\n", ide_sectors / 2,
             sb.nblocks, sb.ninodes);
    say(buf);
    name_register("fs", fs_port);
    for (;;) {
        if (exits_pending) {
            exits_pending = 0;
            srv_exits(gone);
            continue;
        }
        if (backlog) {
            struct srv_req *r = backlog;
            backlog = r->next;
            serve(r->rcvid, r->pid, &r->m);
            free(r);
            continue;
        }
        rcvid = ipc_recv(fs_port, &m, &pid);
        if (rcvid == 0) {
            if (m.w[0] & SRV_EXIT_BIT)
                srv_exits(gone);
            irq_seen |= m.w[0] & ~SRV_EXIT_BIT;
            continue;
        }
        if (rcvid < 0)
            continue;
        serve(rcvid, pid, &m);
    }
}
