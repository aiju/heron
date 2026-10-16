/* The POSIX-shaped calls, over Fen's servers. There's no fork: spawn()
 * (fen/spawn.h) starts a program. */
#ifndef _UNISTD_H
#define _UNISTD_H
#include <stddef.h>
#include <errno.h>
#include <fen/fs.h>
#define STDIN_FILENO 0
#define STDOUT_FILENO 1
#define STDERR_FILENO 2
typedef int ssize_t;
typedef int pid_t;
typedef int off_t;
int open(const char *path, int flags, ...);
int close(int fd);
ssize_t read(int fd, void *buf, size_t n);
ssize_t write(int fd, const void *buf, size_t n);
off_t lseek(int fd, off_t off, int whence);
int dup(int fd);
int dup2(int fd, int to);
int pipe(int fds[2]);
int unlink(const char *path);
int rmdir(const char *path);
int mkdir(const char *path, int mode);
int chdir(const char *path);
char *getcwd(char *buf, size_t size);
int isatty(int fd);
int ftruncate(int fd, off_t len);
int truncate(const char *path, off_t len);
int ioctl(int fd, int req, int arg);
unsigned sleep(unsigned s);
int usleep(unsigned us);
void _exit(int status);
int getpid(void);
int getppid(void);
int getopt(int argc, char *const argv[], const char *opts);
extern char *optarg;
extern int optind, opterr, optopt;
extern char **environ;
int sync(void);
#endif
