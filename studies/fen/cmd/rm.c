/* rm [-r] [-f] path... */
#include <dirent.h>
#include <stdio.h>
#include <string.h>
#include <unistd.h>
#include <sys/stat.h>

static int recursive, force;

static int rm(const char *path)
{
    struct stat st;
    if (stat(path, &st) < 0) {
        if (!force)
            fprintf(stderr, "rm: %s: %s\n", path, strerror(errno));
        return !force;
    }
    if (S_ISDIR(st.st_mode)) {
        DIR *d;
        struct dirent *e;
        int status = 0;
        if (!recursive) {
            fprintf(stderr, "rm: %s is a directory\n", path);
            return 1;
        }
        d = opendir(path);
        while (d && (e = readdir(d)) != 0) {
            char sub[512];
            if (!strcmp(e->d_name, ".") || !strcmp(e->d_name, ".."))
                continue;
            snprintf(sub, sizeof sub, "%s/%s", path, e->d_name);
            status |= rm(sub);
            /* the directory changed under us: read it again */
            closedir(d);
            d = opendir(path);
        }
        if (d)
            closedir(d);
        if (status)
            return status;
    }
    if (unlink(path) < 0) {
        fprintf(stderr, "rm: %s: %s\n", path, strerror(errno));
        return 1;
    }
    return 0;
}

int main(int argc, char **argv)
{
    int c, i, status = 0;
    while ((c = getopt(argc, argv, "rf")) != -1) {
        if (c == 'r')
            recursive = 1;
        else if (c == 'f')
            force = 1;
        else
            return 2;
    }
    for (i = optind; i < argc; i++)
        status |= rm(argv[i]);
    return status;
}
