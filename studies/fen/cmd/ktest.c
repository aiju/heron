/* ktest: the kernel's own test, run as init (build.py's "ktest" boot
 * image). It prints to the kernel's log, and ends with "ktest: N failed". */

#include <stdio.h>
#include <string.h>
#include <fen/sys.h>
#include <fen/spawn.h>

static int failed, passed;

static void say(const char *fmt, ...)
{
    char buf[200];
    va_list ap;
    va_start(ap, fmt);
    vsnprintf(buf, sizeof buf, fmt, ap);
    va_end(ap);
    kdebug(buf, strlen(buf));
}

#define CHECK(c) do { if (c) passed++; else { failed++; say("FAIL %s:%d: %s\n", __FILE__, __LINE__, #c); } } while (0)

static char stack1[4096], stack2[4096];
static volatile int server_port;
static volatile int server_ready;
static volatile int deferring;

/* a server thread: echoes word 1 + 1 in word 0; op 2 reads the client's
 * string and writes it back upper-cased; op 3 defers its reply until
 * the next op 4 */
static void server(unsigned arg)
{
    msg_t m;
    int pid, rcvid, deferred = 0;
    server_port = port_create();
    server_ready = 1;
    for (;;) {
        rcvid = ipc_recv(server_port, &m, &pid);
        if (rcvid == 0) {
            /* a notification: tell whoever is deferred */
            if (deferred) {
                m.w[0] = (int)m.w[0];
                ipc_reply(deferred, &m);
                deferred = 0;
            }
            continue;
        }
        switch (m.w[0]) {
        case 1:
            m.w[0] = m.w[1] + 1;
            m.w[7] = m.w[6] * 2;
            ipc_reply(rcvid, &m);
            break;
        case 2: {
            char buf[64];
            int n = m.w[2], i;
            if (n > 63)
                n = 63;
            ipc_read(rcvid, (void *)m.w[1], buf, n);
            for (i = 0; i < n; i++)
                if (buf[i] >= 'a' && buf[i] <= 'z')
                    buf[i] -= 32;
            ipc_write(rcvid, (void *)m.w[1], buf, n);
            m.w[0] = n;
            ipc_reply(rcvid, &m);
            break;
        }
        case 3:
            deferred = rcvid;
            deferring = 1;
            break;
        case 9:
            m.w[0] = 0;
            ipc_reply(rcvid, &m);
            thread_exit();
        }
    }
}

static volatile int counter;

/* spins, and releases the server's deferred reply with a notification */
static void spinner(unsigned arg)
{
    for (;;) {
        if (deferring == 1) {
            deferring = 2;
            notify(server_port, 0x40);
        }
        counter++;
    }
}

int main(int argc, char **argv)
{
    msg_t m;
    char s[32];
    int t, r, i, pid, status;
    unsigned t0, t1;
    say("ktest: starting\n");

    /* threads and calls */
    t = thread_create(0, (void *)server, stack1 + sizeof stack1, 0);
    CHECK(t > 0);
    while (!server_ready)
        yield();
    CHECK(server_port > 0);
    CHECK(name_register("ktest", server_port) == 0);
    CHECK(name_lookup("ktest") == server_port);
    CHECK(name_lookup("nonesuch") == -ENOENT);
    for (i = 0; i < 100; i++) {
        m.w[0] = 1;
        m.w[1] = i;
        m.w[6] = 5;
        r = ipc_call(server_port, &m);
        if (r != i + 1 || m.w[7] != 10)
            break;
    }
    CHECK(i == 100);

    /* reading and writing the caller's memory */
    strcpy(s, "hello, fen");
    m.w[0] = 2;
    m.w[1] = (int)s;
    m.w[2] = strlen(s);
    r = ipc_call(server_port, &m);
    CHECK(r == 10);
    CHECK(strcmp(s, "HELLO, FEN") == 0);

    /* a deferred reply, released by a notification from another thread */
    t = thread_create(0, (void *)spinner, stack2 + sizeof stack2, 0);
    CHECK(t > 0);
    /* a deferred reply: the server holds the call until the spinner's
     * notification */
    m.w[0] = 3;
    r = ipc_call(server_port, &m);
    CHECK(r == 0x40);
    CHECK(counter > 0);

    /* sleeping */
    t0 = time_us();
    sleep_us(50000);
    t1 = time_us();
    CHECK(t1 - t0 >= 50000 && t1 - t0 < 70000);
    say("ktest: slept %u us\n", t1 - t0);

    /* memory */
    CHECK(vm_alloc(0, (void *)0x00800000, 4, PROT_READ | PROT_WRITE) == 0);
    *(int *)0x00803FFC = 42;
    CHECK(*(int *)0x00803FFC == 42);
    CHECK(*(int *)0x00800000 == 0);
    CHECK(vm_alloc(0, (void *)0x00801000, 1, PROT_READ) == -EEXIST);
    CHECK(vm_free(0, (void *)0x00800000, 4) == 0);

    /* children: one that answers, one that crashes, one that never ends */
    pid = boot_spawn("ktchild", 0);
    CHECK(pid > 0);
    r = proc_wait(pid, 0, &status);
    CHECK(r == pid);
    CHECK(status == 7);
    say("ktest: child %d exited with %d\n", r, status);

    pid = boot_spawn("ktcrash", 0);
    CHECK(pid > 0);
    r = proc_wait(pid, 0, &status);
    CHECK(r == pid && status == 128 + 11);
    say("ktest: crasher exited with %d\n", status);

    pid = boot_spawn("ktspin", 0);
    CHECK(pid > 0);
    sleep_us(30000);
    CHECK(proc_wait(pid, WNOHANG, &status) == 0);
    CHECK(proc_kill(pid, 99) == 1);
    r = proc_wait(pid, 0, &status);
    CHECK(r == pid && status == 99);
    CHECK(proc_wait(0, 0, &status) == -ECHILD);

    /* the server thread ends */
    m.w[0] = 9;
    CHECK(ipc_call(server_port, &m) == 0);

    say("ktest: %d passed, %d failed\n", passed, failed);
    return failed;
}
