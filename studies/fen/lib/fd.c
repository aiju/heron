/* Descriptors: what open(), read() and the rest do, over the file protocol
 * (fen/fs.h). A descriptor is a server's port and the server's own number
 * for the file. A path names a server through a small mount table, the
 * longest prefix winning, and what's left of it goes to the server. */

#include <errno.h>
#include <stdarg.h>
#include <string.h>
#include <unistd.h>
#include <dirent.h>
#include <sys/stat.h>
#include <fen/sys.h>
#include <fen/fs.h>

int errno;

struct fdent {
    int port;           /* 0: not open */
    int handle;
    int flags;
};

static struct fdent fdtab[MAX_FDS];
static char cwd[256] = "/";

static struct mount {
    const char *prefix;
    const char *server;
    int port;
} mounts[] = {
    {"/dev/cons", "cons", 0},
    {"/dev/wsys", "wsys", 0},
    {"/", "fs", 0},
};
#define NMOUNTS (sizeof mounts / sizeof mounts[0])

static int ret(int r)
{
    if (r < 0) {
        errno = -r;
        return -1;
    }
    return r;
}

/* the descriptors a program inherits (lib/start.c) */
void __fd_inherit(struct fd_desc *d, int n, const char *dir)
{
    int i;
    for (i = 0; i < n; i++)
        if (d[i].fd >= 0 && d[i].fd < MAX_FDS) {
            fdtab[d[i].fd].port = d[i].port;
            fdtab[d[i].fd].handle = d[i].handle;
            fdtab[d[i].fd].flags = d[i].flags;
        }
    if (dir && dir[0] == '/')
        strlcpy(cwd, dir, sizeof cwd);
}

/* for spawn: what a descriptor is */
int __fd_get(int fd, int *port, int *handle)
{
    if (fd < 0 || fd >= MAX_FDS || !fdtab[fd].port)
        return -EBADF;
    *port = fdtab[fd].port;
    *handle = fdtab[fd].handle;
    return 0;
}

const char *__cwd(void)
{
    return cwd;
}

/* path, made absolute and tidied: no ".", "..", or doubled '/' */
int __abspath(const char *path, char *out, unsigned size)
{
    char tmp[512];
    char *parts[64];
    int n = 0, i;
    char *p;
    unsigned len;
    if (!path || !*path)
        return -ENOENT;
    if (path[0] == '/')
        len = strlcpy(tmp, path, sizeof tmp);
    else {
        len = strlcpy(tmp, cwd, sizeof tmp);
        len = strlcat(tmp, "/", sizeof tmp);
        len = strlcat(tmp, path, sizeof tmp);
    }
    if (len >= sizeof tmp)
        return -ENAMETOOLONG;
    for (p = tmp; *p;) {
        char *start;
        while (*p == '/')
            p++;
        if (!*p)
            break;
        start = p;
        while (*p && *p != '/')
            p++;
        if (*p)
            *p++ = 0;
        if (!strcmp(start, "."))
            continue;
        if (!strcmp(start, "..")) {
            if (n)
                n--;
            continue;
        }
        if (n == 64)
            return -ENAMETOOLONG;
        parts[n++] = start;
    }
    len = 0;
    if (size < 2)
        return -ENAMETOOLONG;
    if (!n) {
        out[0] = '/';
        out[1] = 0;
        return 0;
    }
    for (i = 0; i < n; i++) {
        unsigned k = strlen(parts[i]);
        if (len + k + 2 > size)
            return -ENAMETOOLONG;
        out[len++] = '/';
        memcpy(out + len, parts[i], k);
        len += k;
    }
    out[len] = 0;
    return 0;
}

/* The server for an absolute path, and the rest of the path it gets. */
static int server_for(const char *abs, const char **rest)
{
    unsigned i;
    for (i = 0; i < NMOUNTS; i++) {
        struct mount *m = &mounts[i];
        unsigned k = strlen(m->prefix);
        if (strncmp(abs, m->prefix, k) == 0 &&
            (abs[k] == 0 || abs[k] == '/' || m->prefix[k - 1] == '/')) {
            if (!m->port) {
                int p = name_lookup(m->server);
                if (p < 0)
                    return -ENOENT;
                m->port = p;
            }
            *rest = abs + k - (m->prefix[k - 1] == '/');
            if (!**rest)
                *rest = "/";
            return m->port;
        }
    }
    return -ENOENT;
}

/* A request about a path: words 1 and 2 are the path and its length. */
static int path_call(const char *path, int op, int w3, int w4, int *port_out)
{
    char abs[256];
    const char *rest;
    msg_t m;
    int port, e = __abspath(path, abs, sizeof abs);
    if (e < 0)
        return e;
    port = server_for(abs, &rest);
    if (port < 0)
        return port;
    if (port_out)
        *port_out = port;
    m.w[0] = op;
    m.w[1] = (int)rest;
    m.w[2] = strlen(rest);
    m.w[3] = w3;
    m.w[4] = w4;
    return ipc_call(port, &m);
}

static int new_fd(int from)
{
    int i;
    for (i = from; i < MAX_FDS; i++)
        if (!fdtab[i].port)
            return i;
    return -EMFILE;
}

int open(const char *path, int flags, ...)
{
    va_list ap;
    int mode, port, h, fd = new_fd(0);
    va_start(ap, flags);
    mode = va_arg(ap, int);
    va_end(ap);
    if (fd < 0)
        return ret(fd);
    h = path_call(path, FS_OPEN, flags, mode, &port);
    if (h < 0)
        return ret(h);
    fdtab[fd].port = port;
    fdtab[fd].handle = h;
    fdtab[fd].flags = flags;
    return fd;
}

int creat(const char *path, int mode)
{
    return open(path, O_WRONLY | O_CREAT | O_TRUNC, mode);
}

static struct fdent *fd_get(int fd)
{
    if (fd < 0 || fd >= MAX_FDS || !fdtab[fd].port)
        return 0;
    return &fdtab[fd];
}

static int fd_call(int fd, int op, int w2, int w3, int w4)
{
    struct fdent *f = fd_get(fd);
    msg_t m;
    if (!f)
        return -EBADF;
    m.w[0] = op;
    m.w[1] = f->handle;
    m.w[2] = w2;
    m.w[3] = w3;
    m.w[4] = w4;
    return ipc_call(f->port, &m);
}

int close(int fd)
{
    int r = fd_call(fd, FS_CLOSE, 0, 0, 0);
    if (r == -EBADF)
        return ret(r);
    fdtab[fd].port = 0;
    return ret(r < 0 ? r : 0);
}

ssize_t read(int fd, void *buf, size_t n)
{
    return ret(fd_call(fd, FS_READ, (int)buf, n, 0));
}

ssize_t write(int fd, const void *buf, size_t n)
{
    struct fdent *f = fd_get(fd);
    msg_t m;
    if (!f)
        return ret(-EBADF);
    if (n <= 16) {
        /* small writes go in the message: no copy from this process */
        m.w[0] = FS_WRITE_INLINE;
        m.w[1] = f->handle;
        m.w[2] = n;
        memcpy(&m.w[4], buf, n);
        return ret(ipc_call(f->port, &m));
    }
    return ret(fd_call(fd, FS_WRITE, (int)buf, n, 0));
}

off_t lseek(int fd, off_t off, int whence)
{
    return ret(fd_call(fd, FS_SEEK, off, whence, 0));
}

int fstat(int fd, struct stat *st)
{
    return ret(fd_call(fd, FS_FSTAT, (int)st, 0, 0));
}

int ftruncate(int fd, off_t len)
{
    return ret(fd_call(fd, FS_TRUNC, len, 0, 0));
}

int ioctl(int fd, int req, int arg)
{
    return ret(fd_call(fd, FS_IOCTL, req, arg, 0));
}

int isatty(int fd)
{
    return fd_call(fd, FS_IOCTL, IO_ISTTY, 0, 0) == 1;
}

/* A copy of fd in this process's table at the server, in slot `to`. */
static int dup_to(int fd, int to)
{
    struct fdent *f = fd_get(fd);
    int h;
    if (!f)
        return -EBADF;
    h = fd_call(fd, FS_DUPTO, getpid(), 0, 0);
    if (h < 0)
        return h;
    fdtab[to].port = f->port;
    fdtab[to].handle = h;
    fdtab[to].flags = f->flags;
    return to;
}

int dup(int fd)
{
    int to = new_fd(0);
    if (to < 0)
        return ret(to);
    return ret(dup_to(fd, to));
}

int dup2(int fd, int to)
{
    if (to < 0 || to >= MAX_FDS || !fd_get(fd))
        return ret(-EBADF);
    if (fd == to)
        return to;
    if (fdtab[to].port)
        close(to);
    return ret(dup_to(fd, to));
}

/* For spawn: fd in another process's table at its server. */
int __fd_dupto(int fd, int pid)
{
    return fd_call(fd, FS_DUPTO, pid, 0, 0);
}

int pipe(int fds[2])
{
    msg_t m;
    int port = name_lookup("fs");
    int a, b, r;
    if (port < 0)
        return ret(port);
    a = new_fd(0);
    if (a < 0)
        return ret(a);
    fdtab[a].port = -1;     /* taken while we find the second */
    b = new_fd(0);
    fdtab[a].port = 0;
    if (b < 0)
        return ret(b);
    m.w[0] = FS_PIPE;
    r = ipc_call(port, &m);
    if (r < 0)
        return ret(r);
    fdtab[a].port = port;
    fdtab[a].handle = m.w[1];
    fdtab[a].flags = O_RDONLY;
    fdtab[b].port = port;
    fdtab[b].handle = m.w[2];
    fdtab[b].flags = O_WRONLY;
    fds[0] = a;
    fds[1] = b;
    return 0;
}

int stat(const char *path, struct stat *st)
{
    return ret(path_call(path, FS_STAT, (int)st, 0, 0));
}

int mkdir(const char *path, int mode)
{
    return ret(path_call(path, FS_MKDIR, mode, 0, 0));
}

int unlink(const char *path)
{
    return ret(path_call(path, FS_UNLINK, 0, 0, 0));
}

int rmdir(const char *path)
{
    struct stat st;
    if (stat(path, &st) < 0)
        return -1;
    if (!S_ISDIR(st.st_mode))
        return ret(-ENOTDIR);
    return unlink(path);
}

int remove(const char *path)
{
    return unlink(path);
}

int rename(const char *from, const char *to)
{
    char a[256], b[256];
    const char *ra, *rb;
    msg_t m;
    int pa, pb, e;
    if ((e = __abspath(from, a, sizeof a)) < 0 || (e = __abspath(to, b, sizeof b)) < 0)
        return ret(e);
    pa = server_for(a, &ra);
    pb = server_for(b, &rb);
    if (pa < 0)
        return ret(pa);
    if (pa != pb)
        return ret(-EXDEV);
    m.w[0] = FS_RENAME;
    m.w[1] = (int)ra;
    m.w[2] = strlen(ra);
    m.w[3] = (int)rb;
    m.w[4] = strlen(rb);
    return ret(ipc_call(pa, &m));
}

int truncate(const char *path, off_t len)
{
    int fd = open(path, O_WRONLY), r;
    if (fd < 0)
        return -1;
    r = ftruncate(fd, len);
    close(fd);
    return r;
}

int statfs(const char *path, struct statfs *st)
{
    char abs[256];
    const char *rest;
    msg_t m;
    int port, e = __abspath(path, abs, sizeof abs);
    if (e < 0)
        return ret(e);
    port = server_for(abs, &rest);
    if (port < 0)
        return ret(port);
    m.w[0] = FS_STATFS;
    m.w[1] = (int)st;
    return ret(ipc_call(port, &m));
}

int sync(void)
{
    msg_t m;
    int port = name_lookup("fs");
    if (port < 0)
        return ret(port);
    m.w[0] = FS_SYNC;
    return ret(ipc_call(port, &m));
}

int chdir(const char *path)
{
    char abs[256];
    struct stat st;
    int e = __abspath(path, abs, sizeof abs);
    if (e < 0)
        return ret(e);
    if (stat(abs, &st) < 0)
        return -1;
    if (!S_ISDIR(st.st_mode))
        return ret(-ENOTDIR);
    strlcpy(cwd, abs, sizeof cwd);
    return 0;
}

char *getcwd(char *buf, size_t size)
{
    if (strlen(cwd) + 1 > size) {
        errno = ERANGE;
        return 0;
    }
    strcpy(buf, cwd);
    return buf;
}

DIR *opendir(const char *path)
{
    extern void *malloc(size_t);
    DIR *d;
    int fd = open(path, O_RDONLY | O_DIRECTORY);
    if (fd < 0)
        return 0;
    d = malloc(sizeof *d);
    if (!d) {
        close(fd);
        errno = ENOMEM;
        return 0;
    }
    d->fd = fd;
    d->pos = d->len = 0;
    return d;
}

struct dirent *readdir(DIR *d)
{
    if (d->pos >= d->len) {
        int n = fd_call(d->fd, FS_READDIR, (int)d->buf, sizeof d->buf, 0);
        if (n <= 0)
            return 0;
        d->len = n / sizeof(struct dirent);
        d->pos = 0;
    }
    return &d->buf[d->pos++];
}

int closedir(DIR *d)
{
    extern void free(void *);
    int r = close(d->fd);
    free(d);
    return r;
}
