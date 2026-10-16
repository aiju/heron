/* init: the first process. It starts the servers the system needs from the
 * boot archive (the file server and the serial console), then what the
 * boot flags ask for from the disk: the window system with a terminal, or
 * a shell on the serial console. A shell that ends is started again. */

#include <stdio.h>
#include <string.h>
#include <unistd.h>
#include <fen/sys.h>
#include <fen/spawn.h>

static void say(const char *s)
{
    kdebug(s, strlen(s));
}

/* start a boot module, and wait until its server's name is there */
static int boot_server(const char *module, const char *name)
{
    int pid = boot_spawn(module, PROC_IO), i, status;
    char buf[80];
    if (pid < 0) {
        snprintf(buf, sizeof buf, "init: can't start %s: %d\n", module, pid);
        say(buf);
        return pid;
    }
    for (i = 0; i < 1000; i++) {
        if (name_lookup(name) > 0)
            return pid;
        if (proc_wait(pid, WNOHANG, &status) == pid) {
            snprintf(buf, sizeof buf, "init: %s ended with %d\n", module, status);
            say(buf);
            return -1;
        }
        sleep_us(10000);
    }
    snprintf(buf, sizeof buf, "init: %s didn't start\n", module);
    say(buf);
    return -1;
}

static char *env[] = {"PATH=/bin", "HOME=/home", "USER=fen", 0};

static int start(const char *path, char *const argv[], int flags)
{
    int pid = spawnx(path, argv, env, 0, 0, flags, 0);
    if (pid < 0) {
        char buf[80];
        snprintf(buf, sizeof buf, "init: can't start %s\n", path);
        say(buf);
    }
    return pid;
}

int main(void)
{
    int boot = sysinfo(SI_BOOT), status, shell = -1;
    char *sh_argv[] = {"sh", "-l", 0};
    if (boot_server("fs", "fs") < 0)
        return 1;
    if (boot_server("cons", "cons") < 0)
        return 1;
    if (open("/dev/cons", O_RDWR) != 0 || dup(0) != 1 || dup(0) != 2)
        say("init: no console\n");
    setvbuf(stdout, 0, _IOLBF, 0);
    chdir("/home");
    /* what init starts from here on runs at the users' priority */
    set_priority(0, 10);
    printf("\nFen on Heron (draft 2), %u KB of RAM, %u KB free\n\n", sysinfo(SI_RAM) >> 10,
           sysinfo(SI_FREE) >> 10);
    if (!(boot & BOOT_SERIAL)) {
        char *ws_argv[] = {"wsys", 0};
        if (start("/bin/wsys", ws_argv, SPAWN_IO) < 0)
            boot |= BOOT_SERIAL;
    }
    if (boot & BOOT_SERIAL)
        shell = start("/bin/sh", sh_argv, 0);
    for (;;) {
        int pid = waitpid(-1, &status, 0);
        if (pid < 0) {
            sleep(1);
            continue;
        }
        if (pid == shell) {
            printf("\n");
            shell = start("/bin/sh", sh_argv, 0);
        }
    }
}
