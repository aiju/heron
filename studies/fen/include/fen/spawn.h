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
#define SPAWN_NEWPGRP 1
/* spawn, with flags: SPAWN_NEWPGRP puts the child in a process group of its own */
int spawnx(const char *path, char *const argv[], char *const envp[], const int *fds, int n,
           int flags);
/* wait for a child (pid, or any with -1): its pid, and its exit status */
int waitpid(int pid, int *status, int options);
int wait(int *status);
int kill(int pid, int status);
#endif
