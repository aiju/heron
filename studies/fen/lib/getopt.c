/* getopt, the POSIX way, without the GNU extensions. */

#include <stdio.h>
#include <string.h>
#include <unistd.h>

char *optarg;
int optind = 1, opterr = 1, optopt;
static int optpos = 1;

int getopt(int argc, char *const argv[], const char *opts)
{
    const char *o;
    char *arg;
    if (optind >= argc || !argv[optind] || argv[optind][0] != '-' || !argv[optind][1])
        return -1;
    arg = argv[optind];
    if (!strcmp(arg, "--")) {
        optind++;
        return -1;
    }
    optopt = arg[optpos];
    o = strchr(opts, optopt);
    if (!o || optopt == ':') {
        if (opterr && *opts != ':')
            fprintf(stderr, "%s: unknown option -%c\n", argv[0], optopt);
        if (!arg[++optpos]) {
            optind++;
            optpos = 1;
        }
        return '?';
    }
    if (o[1] == ':') {
        if (arg[optpos + 1]) {
            optarg = arg + optpos + 1;
        } else if (optind + 1 < argc) {
            optarg = argv[++optind];
        } else {
            if (opterr && *opts != ':')
                fprintf(stderr, "%s: -%c needs an argument\n", argv[0], optopt);
            optind++;
            optpos = 1;
            return *opts == ':' ? ':' : '?';
        }
        optind++;
        optpos = 1;
        return optopt;
    }
    if (!arg[++optpos]) {
        optind++;
        optpos = 1;
    }
    return optopt;
}
