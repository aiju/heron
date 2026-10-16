/* grep [-ivnc] pattern [file...]: lines with a match of a pattern: . [..]
 * * ^ $ as in ed, and \ for a literal. */
#include <ctype.h>
#include <stdio.h>
#include <string.h>

static int icase, invert, number, countf;

static int same(int a, int b)
{
    return icase ? tolower(a) == tolower(b) : a == b;
}

/* one element of the pattern against c: its length in the pattern, or 0 */
static int elem(const char *p, int c, int *len)
{
    if (*p == '\\' && p[1]) {
        *len = 2;
        return same(p[1], c);
    }
    if (*p == '.') {
        *len = 1;
        return c != 0;
    }
    if (*p == '[') {
        const char *q = p + 1;
        int neg = *q == '^', ok = 0;
        if (neg)
            q++;
        do {
            if (q[1] == '-' && q[2] && q[2] != ']') {
                if (c >= *q && c <= q[2])
                    ok = 1;
                q += 3;
            } else {
                if (same(*q, c))
                    ok = 1;
                q++;
            }
        } while (*q && *q != ']');
        *len = (*q ? q + 1 : q) - p;
        return c && ok != neg;
    }
    *len = 1;
    return same(*p, c);
}

static int here(const char *p, const char *s)
{
    int len;
    if (!*p)
        return 1;
    if (*p == '$' && !p[1])
        return !*s;
    elem(p, 'x', &len);
    if (p[len] == '*') {
        do {
            if (here(p + len + 1, s))
                return 1;
        } while (*s && elem(p, *s++, &len));
        return 0;
    }
    if (*s && elem(p, *s, &len))
        return here(p + len, s + 1);
    return 0;
}

static int matches(const char *p, const char *s)
{
    if (*p == '^')
        return here(p + 1, s);
    do {
        if (here(p, s))
            return 1;
    } while (*s++);
    return 0;
}

static int grep(FILE *f, const char *pat, const char *name)
{
    char line[1024];
    int n = 0, found = 0;
    while (fgets(line, sizeof line, f)) {
        int k = strlen(line);
        n++;
        if (k && line[k - 1] == '\n')
            line[--k] = 0;
        if (matches(pat, line) != invert) {
            found++;
            if (countf)
                continue;
            if (name)
                printf("%s:", name);
            if (number)
                printf("%d:", n);
            printf("%s\n", line);
        }
    }
    if (countf) {
        if (name)
            printf("%s:", name);
        printf("%d\n", found);
    }
    return found;
}

int main(int argc, char **argv)
{
    int i = 1, found = 0;
    while (i < argc && argv[i][0] == '-' && argv[i][1]) {
        const char *o;
        for (o = argv[i] + 1; *o; o++) {
            if (*o == 'i') icase = 1;
            else if (*o == 'v') invert = 1;
            else if (*o == 'n') number = 1;
            else if (*o == 'c') countf = 1;
        }
        i++;
    }
    if (i >= argc) {
        fprintf(stderr, "usage: grep [-ivnc] pattern [file...]\n");
        return 2;
    }
    if (i + 1 == argc)
        return grep(stdin, argv[i], 0) ? 0 : 1;
    for (int k = i + 1; k < argc; k++) {
        FILE *f = fopen(argv[k], "r");
        if (!f) {
            fprintf(stderr, "grep: %s: %s\n", argv[k], strerror(errno));
            continue;
        }
        found += grep(f, argv[i], argc - i > 2 ? argv[k] : 0);
        fclose(f);
    }
    return found ? 0 : 1;
}
