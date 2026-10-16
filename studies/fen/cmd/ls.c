/* ls [-la] [path...]: list directories, sorted, in columns (or one a line
 * with -l: type, size, date, name). */
#include <dirent.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include <unistd.h>
#include <sys/stat.h>

static int all, longf, status;

static int cmp(const void *a, const void *b)
{
    return strcmp(*(char *const *)a, *(char *const *)b);
}

static void entry(const char *dir, const char *name)
{
    char path[512];
    struct stat st;
    if (!longf) {
        printf("%s\n", name);
        return;
    }
    snprintf(path, sizeof path, "%s/%s", dir, name);
    if (stat(path, &st) < 0) {
        printf("?          ? %s\n", name);
        return;
    }
    {
        time_t t = st.st_mtime;
        struct tm *tm = gmtime(&t);
        static const char *mon[] = {"Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug",
                                    "Sep", "Oct", "Nov", "Dec"};
        char type = S_ISDIR(st.st_mode) ? 'd' : S_ISCHR(st.st_mode) ? 'c' :
                    S_ISFIFO(st.st_mode) ? 'p' : '-';
        printf("%c %8u %s %2d %02d:%02d %s%s\n", type, st.st_size, mon[tm->tm_mon], tm->tm_mday,
               tm->tm_hour, tm->tm_min, name, S_ISDIR(st.st_mode) ? "/" : "");
    }
}

static void columns(char **names, int n)
{
    int width = 0, i, cols, rows, r, c;
    for (i = 0; i < n; i++)
        if ((int)strlen(names[i]) > width)
            width = strlen(names[i]);
    width += 2;
    cols = 80 / width;
    if (cols < 1)
        cols = 1;
    rows = (n + cols - 1) / cols;
    for (r = 0; r < rows; r++) {
        for (c = 0; c < cols; c++) {
            i = c * rows + r;
            if (i < n)
                printf("%-*s", c == cols - 1 || i + rows >= n ? 0 : width, names[i]);
        }
        printf("\n");
    }
}

static void list(const char *path, int header)
{
    struct stat st;
    DIR *d;
    struct dirent *e;
    char **names = 0;
    int n = 0, cap = 0, i;
    if (stat(path, &st) < 0) {
        fprintf(stderr, "ls: %s: %s\n", path, strerror(errno));
        status = 1;
        return;
    }
    if (!S_ISDIR(st.st_mode)) {
        char *slash = strrchr(path, '/');
        if (longf)
            entry(".", path);
        else
            printf("%s\n", slash && slash[1] ? path : path);
        return;
    }
    d = opendir(path);
    if (!d) {
        fprintf(stderr, "ls: %s: %s\n", path, strerror(errno));
        status = 1;
        return;
    }
    while ((e = readdir(d)) != 0) {
        if (e->d_name[0] == '.' && !all)
            continue;
        if (n == cap) {
            cap = cap ? 2 * cap : 64;
            names = realloc(names, cap * sizeof *names);
        }
        names[n++] = strdup(e->d_name);
    }
    closedir(d);
    qsort(names, n, sizeof *names, cmp);
    if (header)
        printf("%s:\n", path);
    if (longf || !isatty(1)) {
        for (i = 0; i < n; i++)
            entry(path, names[i]);
    } else {
        columns(names, n);
    }
    for (i = 0; i < n; i++)
        free(names[i]);
    free(names);
}

int main(int argc, char **argv)
{
    int c, i;
    while ((c = getopt(argc, argv, "la")) != -1) {
        if (c == 'l')
            longf = 1;
        else if (c == 'a')
            all = 1;
        else
            return 2;
    }
    if (optind == argc)
        list(".", 0);
    for (i = optind; i < argc; i++) {
        if (i > optind)
            printf("\n");
        list(argv[i], argc - optind > 1);
    }
    return status;
}
