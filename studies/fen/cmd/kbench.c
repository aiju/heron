/* kbench: the kernel's hot paths, and a few of the servers', timed in the
 * machine with the board's microsecond clock. Each line is an operation:
 * what one takes, in nanoseconds and in cycles at the CPU's clock (the
 * timer's tick, 100 times a second, is in them), or for the ones that
 * move data, kilobytes a second. bench.py reads the lines that start with
 * "bench ".
 *
 * kbench serve: the server for the IPC between processes, under the name
 * "kbench"; kbench sink: what reads the pipe. */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <fcntl.h>
#include <fen/sys.h>
#include <fen/spawn.h>

static unsigned mhz;

static void result(const char *name, const char *what, unsigned us, int n)
{
    unsigned ns = us * 1000u / n;
    printf("bench %s %u %u  %s\n", name, ns, us * mhz / n, what);
}

static void rate(const char *name, const char *what, unsigned us, unsigned bytes)
{
    unsigned kbs = us ? (unsigned)(bytes / 1024 * 1000u / (us / 1000u ? us / 1000u : 1)) : 0;
    printf("bench %s %u -  %s\n", name, kbs, what);
}

/* ---- servers ---- */

static void serve(int port)
{
    msg_t m;
    int rcvid = ipc_recv(port, &m, 0);
    for (;;) {
        if (rcvid > 0 && m.w[0] == 1) {
            m.w[0] = 0;
            ipc_reply(rcvid, &m);
            exit(0);
        }
        rcvid = ipc_reply_recv(rcvid, &m, port, 0);
    }
}

static void thread_main(unsigned port)
{
    serve(port);
}

/* ---- the measurements ---- */

#define N 2000

static void null_syscall(void)
{
    unsigned t = time_us();
    int i;
    for (i = 0; i < N; i++)
        getpid();
    result("syscall", "getpid(), a system call that does nothing", time_us() - t, N);
}

static void round_trips(const char *name, const char *what, int port)
{
    msg_t m;
    unsigned t;
    int i;
    memset(&m, 0, sizeof m);
    m.w[0] = 2;
    ipc_call(port, &m);         /* (the first, which may fault pages in) */
    t = time_us();
    for (i = 0; i < N; i++) {
        m.w[0] = 2;
        ipc_call(port, &m);
    }
    result(name, what, time_us() - t, N);
}

static void ipc_thread(void)
{
    int port = port_create();
    char *stack = malloc(4096);
    thread_create(getpid(), (void *)thread_main, stack + 4096, port);
    round_trips("ipc_thread", "ipc_call() to a thread of the same process, and its reply",
                port);
}

static void ipc_process(void)
{
    char *argv[] = {"kbench", "serve", 0};
    msg_t m;
    int pid = spawn("/bin/kbench", argv, 0, 0, 0), port = -1, st, k;
    for (k = 0; k < 1000 && port < 0; k++) {
        port = name_lookup("kbench");
        if (port < 0)
            sleep_us(1000);
    }
    if (port < 0) {
        printf("kbench: no server\n");
        return;
    }
    round_trips("ipc_process", "ipc_call() to another process, and its reply", port);
    m.w[0] = 1;
    ipc_call(port, &m);
    waitpid(pid, &st, 0);
}

static void notify_self(void)
{
    int port = port_create(), i;
    msg_t m;
    unsigned t = time_us();
    for (i = 0; i < N; i++) {
        notify(port, 1);
        ipc_recv(port, &m, 0);
    }
    result("notify", "notify() a port of one's own, and ipc_recv() it", time_us() - t, N);
    port_destroy(port);
}

static void pages(void)
{
    char *va = (char *)0x00900000;
    unsigned t = time_us();
    int i;
    for (i = 0; i < N / 10; i++) {
        vm_alloc(0, va, 1, PROT_READ | PROT_WRITE);
        vm_free(0, va, 1);
    }
    result("page", "vm_alloc() and vm_free() a page (which is zeroed)", time_us() - t, N / 10);
    t = time_us();
    for (i = 0; i < N / 100; i++) {
        vm_alloc(0, va, 64, PROT_READ | PROT_WRITE);
        vm_free(0, va, 64);
    }
    result("page64", "vm_alloc() and vm_free() 64 pages", time_us() - t, N / 100);
}

static void spawns(void)
{
    char *argv[] = {"true", 0};
    unsigned t = time_us();
    int i, st, n = 20;
    for (i = 0; i < n; i++)
        waitpid(spawn("/bin/true", argv, 0, 0, 0), &st, 0);
    result("spawn", "spawn() /bin/true and waitpid() for it", time_us() - t, n);
}

static char buf[4096];

static void files(void)
{
    int fd, i, n, total = 0;
    unsigned t;
    /* once to have it in the file server's cache, then timed */
    for (i = 0; i < 2; i++) {
        fd = open("/bin/sh", O_RDONLY);
        total = 0;
        t = time_us();
        while ((n = read(fd, buf, sizeof buf)) > 0)
            total += n;
        t = time_us() - t;
        close(fd);
    }
    rate("read", "read() a file of 24 KB in the file server's cache, 4 KB at a time", t, total);
    fd = open("/tmp/kbench", O_WRONLY | O_CREAT | O_TRUNC, 0644);
    t = time_us();
    for (i = 0; i < 16; i++)
        write(fd, buf, sizeof buf);
    t = time_us() - t;
    close(fd);
    unlink("/tmp/kbench");
    rate("write", "write() 64 KB to a new file, 4 KB at a time (through to the card)", t,
         16 * sizeof buf);
}

static void pipes(void)
{
    char *argv[] = {"kbench", "sink", 0};
    int p[2], fds[3], pid, st, i;
    unsigned t;
    pipe(p);
    fds[0] = p[0];
    fds[1] = 1;
    fds[2] = 2;
    pid = spawn("/bin/kbench", argv, 0, fds, 3);
    close(p[0]);
    t = time_us();
    for (i = 0; i < 64; i++)
        write(p[1], buf, sizeof buf);
    close(p[1]);
    waitpid(pid, &st, 0);
    t = time_us() - t;
    rate("pipe", "write() 256 KB into a pipe that another process reads, 4 KB at a time", t,
         64 * sizeof buf);
}

static const struct {
    const char *name;
    void (*fn)(void);
} tests[] = {
    {"syscall", null_syscall},
    {"notify", notify_self},
    {"ipc_thread", ipc_thread},
    {"ipc_process", ipc_process},
    {"page", pages},
    {"spawn", spawns},
    {"files", files},
    {"pipe", pipes},
    {0, 0},
};

int main(int argc, char **argv)
{
    int i;
    if (argc > 1 && !strcmp(argv[1], "sink")) {
        while (read(0, buf, sizeof buf) > 0)
            ;
        return 0;
    }
    if (argc > 1 && !strcmp(argv[1], "serve")) {
        int port = port_create();
        name_register("kbench", port);
        serve(port);
    }
    mhz = sysinfo(SI_CLOCK) / 1000000;
    setvbuf(stdout, 0, _IOLBF, 0);
    printf("kbench: ns and cycles at %u MHz an operation, or KB/s\n", mhz);
    for (i = 0; tests[i].name; i++) {
        int k, want = argc == 1;
        for (k = 1; k < argc; k++)
            want |= !strcmp(argv[k], tests[i].name);
        if (want)
            tests[i].fn();
    }
    printf("kbench: done\n");
    return 0;
}
