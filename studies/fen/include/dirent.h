#ifndef _DIRENT_H
#define _DIRENT_H
#include <fen/fs.h>
typedef struct {
    int fd;
    int pos, len;
    struct dirent buf[8];
} DIR;
DIR *opendir(const char *path);
struct dirent *readdir(DIR *d);
int closedir(DIR *d);
#endif
