/* Fen's system calls, as C functions (the stubs are lib/ipc.s and the
 * generated usys.s; studies/fen/syscalls.py has the numbers). Most return
 * a result >= 0, or an error from fen/abi.h, negated. */

#ifndef FEN_SYS_H
#define FEN_SYS_H

#include <fen/abi.h>

void _exit(int status);         /* end the process now: exit() flushes first */
int yield(void);
int sleep_us(unsigned us);
unsigned time_us(void);         /* microseconds since boot (wraps in 71 minutes) */
int kdebug(const char *buf, unsigned n);
int getpid(void);
int getppid(void);
int gettid(void);
unsigned sysinfo(int key);

int ipc_call(int port, msg_t *m);
int ipc_recv(int port, msg_t *m, int *pid);
int ipc_reply(int rcvid, msg_t *m);
int ipc_reply_recv(int rcvid, msg_t *m, int port, int *pid);
int ipc_read(int rcvid, const void *from, void *buf, unsigned n);
int ipc_write(int rcvid, void *to, const void *buf, unsigned n);
int ipc_map(int rcvid, const void *client_va, void *va, unsigned npages);
int port_create(void);
int port_destroy(int port);
int notify(int port, unsigned bits);
int name_register(const char *name, int port);
int name_lookup(const char *name);
int irq_bind(int level, int port, unsigned bits);
int irq_ack(int level);
int exit_watch(int port, unsigned bits);
int exit_log(unsigned seq, struct exit_entry *buf, int n);
/* notify a port of ours with bits once, us microseconds from now (0:
 * cancel its alarm); a port has one alarm */
int alarm(int port, unsigned bits, unsigned us);

int proc_create(const char *name, int flags);
int vm_alloc(int pid, void *va, unsigned npages, int prot);
int vm_free(int pid, void *va, unsigned npages);
int vm_write(int pid, void *va, const void *src, unsigned n);
int vm_protect(int pid, void *va, unsigned npages, int prot);
int vm_map_phys(void *va, unsigned pa, unsigned npages, int prot);
int vm_phys(void *va);          /* the physical address, for a driver (PROC_IO) */
int vm_share(int pid, void *va, void *my_va, unsigned npages);
int thread_create(int pid, void *pc, void *sp, unsigned arg);
int thread_exit(void);
int proc_wait(int pid, int options, int *status);  /* options: WNOHANG */
int proc_kill(int pid, int status);
int proc_list(struct proc_info *buf, int n);
int set_priority(int tid, int prio);
int klog(char *buf, unsigned n, unsigned from);
int setpgid(int pid, int pgid);
int getpgid(int pid);
int boot_spawn(const char *name, int flags);

#endif
