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

#define SPAWN_NEWPGRP 1

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

/* The startup block (fen/abi.h), built here and copied to the child. */
static int startup(int pid, char *const argv[], char *const envp[], const int *fds, int nfds)
{
    static char blk[4096];
    struct start_block *b = (struct start_block *)blk;
    unsigned off = sizeof *b;
    int argc = 0, nenv = 0, i, k;
    char **cargv, **cenv;
    struct fd_desc *cfd;
    int defaults[3] = {0, 1, 2};
    int e;
#define CHILD(p) ((void *)(START_BLOCK + ((char *)(p) - blk)))
    if (!fds) {
        fds = defaults;
        nfds = 3;
    }
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
    k = 0;
    for (i = 0; i < nfds; i++) {
        int port, handle, h;
        if (fds[i] < 0 || __fd_get(fds[i], &port, &handle) < 0)
            continue;
        h = __fd_dupto(fds[i], pid);
        if (h < 0)
            continue;
        cfd[k].fd = i;
        cfd[k].port = port;
        cfd[k].handle = h;
        cfd[k].flags = 0;
        k++;
    }
    b->nfds = k;
    e = vm_alloc(pid, (void *)START_BLOCK, 1, PROT_READ | PROT_WRITE);
    if (e < 0)
        return e;
    return vm_write(pid, (void *)START_BLOCK, blk, off);
}

int spawnx(const char *path, char *const argv[], char *const envp[], const int *fds, int nfds,
           int flags)
{
    struct fx_header h;
    const char *name = strrchr(path, '/');
    int fd, pid, e;
    fd = open(path, O_RDONLY);
    if (fd < 0)
        return -1;
    if (read(fd, &h, sizeof h) != sizeof h || h.magic != FX_MAGIC) {
        close(fd);
        errno = ENOEXEC;
        return -1;
    }
    pid = proc_create(name ? name + 1 : path, 0);
    if (pid < 0) {
        close(fd);
        errno = -pid;
        return -1;
    }
    e = load(pid, fd, &h);
    close(fd);
    if (e >= 0)
        e = startup(pid, argv, envp ? envp : environ, fds, nfds);
    if (e >= 0 && (flags & SPAWN_NEWPGRP))
        e = setpgid(pid, pid);
    if (e >= 0)
        e = thread_create(pid, (void *)h.entry, (void *)STACK_TOP, START_BLOCK);
    if (e < 0) {
        proc_kill(pid, 1);
        proc_wait(pid, 0, 0);
        errno = -e;
        return -1;
    }
    return pid;
}

int spawn(const char *path, char *const argv[], char *const envp[], const int *fds, int nfds)
{
    return spawnx(path, argv, envp, fds, nfds, 0);
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
