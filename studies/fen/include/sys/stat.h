#ifndef _SYS_STAT_H
#define _SYS_STAT_H
#include <fen/fs.h>
int stat(const char *path, struct stat *st);
int fstat(int fd, struct stat *st);
int mkdir(const char *path, int mode);
int statfs(const char *path, struct statfs *st);
#endif
