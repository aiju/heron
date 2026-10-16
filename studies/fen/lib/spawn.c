/* Starting programs. There's no fork (report 0020: copying a process costs
 * too much here): spawn reads the executable, makes a process, maps its
 * pages and copies the image in (vm_alloc and vm_write), writes its
 * startup block, gives it the descriptors it inherits (FS_DUPTO at each
 * one's server), and starts its first thread. */

#include <errno.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <fen/sys.h>
#include <fen/spawn.h>

extern char **environ;
int __fd_get(int fd, int *port, int *handle);
int __fd_dupto(int fd, int pid);
const char *__cwd(void);

static int map_range(int pid, unsigned lo, unsigned hi, int prot)
{
    lo &= ~4095;
    hi = (hi + 4095) & ~4095;
    if (hi <= lo)
        return 0;
    return vm_alloc(pid, (void *)lo, (hi - lo) >> 12, prot);
}

/* the image: header, pages, contents */
static int load(int pid, int fd, struct fx_header *h)
{
    static char buf[4096];
    unsigned end = h->base + h->mem_size, done = 0;
    int e;
    if ((e = map_range(pid, h->base, h->text_start, PROT_READ | PROT_WRITE)) < 0 ||
        (e = map_range(pid, h->text_start, h->text_end, PROT_READ | PROT_EXEC)) < 0 ||
        (e = map_range(pid, h->text_end > h->base ? h->text_end : h->base, end,
                       PROT_READ | PROT_WRITE)) < 0)
        return e;
    while (done < h->file_size) {
        unsigned k = h->file_size - done;
        int n;
        if (k > sizeof buf)
            k = sizeof buf;
        n = read(fd, buf, k);
        if (n <= 0)
            return n < 0 ? -errno : -ENOEXEC;
        e = vm_write(pid, (void *)(h->base + done), buf, n);
        if (e < 0)
            return e;
        done += n;
    }
    return 0;
}

/* The startup block (fen/abi.h), built here and copied to the child, with
 * the descriptors it gets as they are in its servers' tables. */
static int startup(int pid, char *const argv[], char *const envp[], const struct fd_desc *d,
                   int nfds)
{
    static char blk[4096];
    struct start_block *b = (struct start_block *)blk;
    unsigned off = sizeof *b;
    int argc = 0, nenv = 0, i;
    char **cargv, **cenv;
    struct fd_desc *cfd;
    int e;
#define CHILD(p) ((void *)(START_BLOCK + ((char *)(p) - blk)))
    while (argv && argv[argc])
        argc++;
    while (envp && envp[nenv])
        nenv++;
    cargv = (char **)(blk + off);
    off += (argc + 1) * sizeof(char *);
    cenv = (char **)(blk + off);
    off += (nenv + 1) * sizeof(char *);
    cfd = (struct fd_desc *)(blk + off);
    off += nfds * sizeof(struct fd_desc);
    if (off > sizeof blk)
        return -E2BIG;
    b->argc = argc;
    b->argv = CHILD(cargv);
    b->envp = CHILD(cenv);
    b->fds = CHILD(cfd);
    b->nfds = nfds;
    if (nfds)
        memcpy(cfd, d, nfds * sizeof *d);
#define STR(dst, s) do { unsigned n_ = strlen(s) + 1; \
        if (off + n_ > sizeof blk) return -E2BIG; \
        memcpy(blk + off, s, n_); dst = CHILD(blk + off); off += n_; } while (0)
    for (i = 0; i < argc; i++)
        STR(cargv[i], argv[i]);
    cargv[argc] = 0;
    for (i = 0; i < nenv; i++)
        STR(cenv[i], envp[i]);
    cenv[nenv] = 0;
    {
        char *p;
        STR(p, __cwd());
        b->cwd = (char *)p - (char *)START_BLOCK;
    }
    e = vm_alloc(pid, (void *)START_BLOCK, 1, PROT_READ | PROT_WRITE);
    if (e < 0)
        return e;
    return vm_write(pid, (void *)START_BLOCK, blk, off);
}

/* The descriptors for a child: fds[i] is ours that becomes its i. */
static int inherit(int pid, const int *fds, int nfds, struct fd_desc *d)
{
    static const int defaults[3] = {0, 1, 2};
    int i, k = 0;
    if (!fds) {
        fds = defaults;
        nfds = 3;
    }
    for (i = 0; i < nfds && k < MAX_FDS; i++) {
        int port, handle, h;
        if (fds[i] < 0 || __fd_get(fds[i], &port, &handle) < 0)
            continue;
        h = __fd_dupto(fds[i], pid);
        if (h < 0)
            continue;
        d[k].fd = i;
        d[k].port = port;
        d[k].handle = h;
        d[k].flags = 0;
        k++;
    }
    return k;
}

/* Make the process and load the program; 0 for the caller to start, or
 * an error. */
static int create(const char *path, struct fx_header *h, int flags)
{
    const char *name = strrchr(path, '/');
    int fd, pid, e;
    fd = open(path, O_RDONLY);
    if (fd < 0)
        return -errno;
    if (read(fd, h, sizeof *h) != sizeof *h || h->magic != FX_MAGIC) {
        close(fd);
        return -ENOEXEC;
    }
    pid = proc_create(name ? name + 1 : path, flags & SPAWN_IO ? PROC_IO : 0);
    if (pid < 0) {
        close(fd);
        return pid;
    }
    e = load(pid, fd, h);
    close(fd);
    if (e < 0) {
        proc_kill(pid, 1);
        proc_wait(pid, 0, 0);
        return e;
    }
    return pid;
}

static int finish(int pid, struct fx_header *h, char *const argv[], char *const envp[],
                  const struct fd_desc *d, int n, int flags, int pgid)
{
    int e = startup(pid, argv, envp ? envp : environ, d, n);
    if (e >= 0 && (flags & SPAWN_PGID))
        e = setpgid(pid, pgid ? pgid : pid);
    if (e >= 0)
        e = thread_create(pid, (void *)h->entry, (void *)STACK_TOP, START_BLOCK);
    if (e < 0) {
        proc_kill(pid, 1);
        proc_wait(pid, 0, 0);
        errno = -e;
        return -1;
    }
    return pid;
}

int spawnx(const char *path, char *const argv[], char *const envp[], const int *fds, int nfds,
           int flags, int pgid)
{
    struct fx_header h;
    struct fd_desc d[MAX_FDS];
    int pid = create(path, &h, flags), n;
    if (pid < 0) {
        errno = -pid;
        return -1;
    }
    n = inherit(pid, fds, nfds, d);
    return finish(pid, &h, argv, envp, d, n, flags, pgid);
}

int spawnd(const char *path, char *const argv[], char *const envp[], const struct fd_desc *d,
           int n, int flags, int pgid)
{
    struct fx_header h;
    int pid = create(path, &h, flags);
    if (pid < 0) {
        errno = -pid;
        return -1;
    }
    return finish(pid, &h, argv, envp, d, n, flags, pgid);
}

int spawn(const char *path, char *const argv[], char *const envp[], const int *fds, int nfds)
{
    return spawnx(path, argv, envp, fds, nfds, 0, 0);
}

/* the program for `file`: itself if it has a '/', else the first match in
 * $PATH's directories (or /bin) */
int __find_program(const char *file, char *out, unsigned size)
{
    const char *path;
    struct stat st;
    if (strchr(file, '/')) {
        strlcpy(out, file, size);
        return 0;
    }
    path = getenv("PATH");
    if (!path)
        path = "/bin";
    while (*path) {
        const char *colon = strchr(path, ':');
        unsigned k = colon ? (unsigned)(colon - path) : strlen(path);
        if (k + strlen(file) + 2 <= size) {
            memcpy(out, path, k);
            out[k] = '/';
            strcpy(out + k + 1, file);
            if (stat(out, &st) == 0 && S_ISREG(st.st_mode))
                return 0;
        }
        path += k;
        if (*path == ':')
            path++;
    }
    errno = ENOENT;
    return -1;
}

int spawnp(const char *file, char *const argv[], char *const envp[], const int *fds, int nfds)
{
    char path[256];
    if (__find_program(file, path, sizeof path) < 0)
        return -1;
    return spawn(path, argv, envp, fds, nfds);
}

int waitpid(int pid, int *status, int options)
{
    int r = proc_wait(pid > 0 ? pid : 0, options, status);
    if (r < 0) {
        errno = -r;
        return -1;
    }
    return r;
}

int wait(int *status)
{
    return waitpid(-1, status, 0);
}

int kill(int pid, int status)
{
    int r = proc_kill(pid, status);
    if (r < 0) {
        errno = -r;
        return -1;
    }
    return 0;
}
