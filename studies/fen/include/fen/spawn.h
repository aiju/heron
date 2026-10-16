/* Starting programs: there's no fork. spawn loads an executable into a new
 * process and starts it with the arguments, the environment, the working
 * directory and the descriptors it's given. */
#ifndef FEN_SPAWN_H
#define FEN_SPAWN_H
/* fds[i] is the parent's descriptor that becomes the child's i, or -1; n
 * of them. With fds 0, the child gets the parent's 0, 1 and 2. */
int spawn(const char *path, char *const argv[], char *const envp[], const int *fds, int n);
/* spawn with the program found in $PATH (or /bin) when path has no '/' */
int spawnp(const char *file, char *const argv[], char *const envp[], const int *fds, int n);
#define WNOHANG 1
#define SPAWN_PGID 1            /* put the child in process group pgid, or its own if 0 */
#define SPAWN_IO 2              /* the child may map devices and take interrupts */
/* spawn, with flags */
int spawnx(const char *path, char *const argv[], char *const envp[], const int *fds, int n,
           int flags, int pgid);
/* spawn, with the child's descriptors given as they are at their servers
 * (for a server that gives its own to its child) */
struct fd_desc;
int spawnd(const char *path, char *const argv[], char *const envp[], const struct fd_desc *d,
           int n, int flags, int pgid);
/* wait for a child (pid, or any with -1): its pid, and its exit status */
int waitpid(int pid, int *status, int options);
int wait(int *status);
int kill(int pid, int status);
#endif
