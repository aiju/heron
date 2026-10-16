/* What servers of the file protocol (fen/fs.h) share: a descriptor table
 * for each process, descriptors that outlive their process cleaned up
 * from the kernel's exit log, and requests a server answers later.
 *
 * An open file (srv_file) is the server's: a descriptor in a process's
 * table points at one, and FS_DUPTO makes another descriptor for the same
 * file, in any process's table. When its last descriptor closes, the
 * server's release function frees what the file holds. */

#ifndef FEN_SRV_H
#define FEN_SRV_H

#include <fen/abi.h>

struct srv_file {
    int refs;
    int flags;          /* open's O_ flags */
    unsigned off;
    int kind;           /* the server's */
    void *obj;          /* the server's */
};

/* A request waiting for its answer (a read of a pipe or a console with
 * nothing to read yet, say). */
struct srv_req {
    int rcvid;
    int pid;
    msg_t m;
    unsigned done;      /* how far the server has got with it */
    struct srv_req *next;
};

/* the notification bit for "a process has ended" */
#define SRV_EXIT_BIT 0x80000000u

/* Start: watch for processes ending on `port`; `release` frees an open
 * file's object when its last descriptor closes. */
void srv_init(int port, void (*release)(struct srv_file *f));

/* A process's descriptor, or 0. */
struct srv_file *srv_fd(int pid, int fd);
/* A new open file with one descriptor in pid's table: the descriptor, or
 * an error. */
int srv_open(int pid, int kind, void *obj, int flags);
/* Another descriptor for the same file in topid's table. */
int srv_dupto(int pid, int fd, int topid);
/* Close one descriptor. */
int srv_close(int pid, int fd);
/* Read the exit log, and close every descriptor of the processes that have
 * ended; `gone` is told of each (or 0). Call it on SRV_EXIT_BIT. */
void srv_exits(void (*gone)(int pid));

/* A request kept for later: a copy of it, on a list. */
struct srv_req *srv_keep(struct srv_req **list, int rcvid, int pid, msg_t *m);
/* Answer a kept request with a status (word 0), and free it. */
void srv_answer(struct srv_req **list, struct srv_req *r, int status);
/* Answer every kept request of a process that has gone. */
void srv_drop_pid(struct srv_req **list, int pid);

/* Reply with a status in word 0. */
int srv_reply(int rcvid, int status);

/* A reply to send with the next srv_recv, so that replying and receiving
 * are one system call (ipc_reply_recv, which the kernel switches straight
 * through). A reply already kept goes at once. */
void srv_reply_next(int rcvid, const msg_t *reply);
/* Receive on port, sending the kept reply first: as ipc_recv. */
int srv_recv(int port, msg_t *m, int *pid);

/* A path from the client: copied into buf (size bytes), NUL-terminated. */
int srv_path(int rcvid, msg_t *m, int which, char *buf, unsigned size);

#endif
