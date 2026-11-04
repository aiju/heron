/* grep and sed, on the regular expressions of regex.c.

   grep [-ivcno] pattern [file...]: the lines with a match, as Fen's grep
   (studies/fen/cmd/grep.c), and -o for each match on a line of its own.

   sed [-n] script [file...]: a stream editor's commands, separated by
   ';': s/re/replacement/[g] (& is the match), d and p, each after an
   optional address /re/ that limits it to the lines that match. */

#include <stdlib.h>
#include <string.h>
#include "tu.h"

/* ---- grep ---- */

static int icase, invert, countf, number, only;

static int grep(const Re *re, Buf *f, const char *name, Buf *out)
{
    char line[LINEMAX];
    int n = 0, found = 0, k, m0, m1, from;
    while (buf_gets(line, sizeof line, f)) {
        k = strlen(line);
        n++;
        if (k && line[k - 1] == '\n')
            line[--k] = 0;
        if (only && !invert) {
            /* every match, each on a line */
            for (from = 0; from <= k && re_search(re, line, k, from, &m0, &m1); ) {
                if (m1 > m0) {
                    if (name)
                        buf_printf(out, "%s:", name);
                    buf_write(out, line + m0, m1 - m0);
                    buf_putc(out, '\n');
                    found++;
                    from = m1;
                } else {
                    from = m0 + 1;
                }
            }
            continue;
        }
        if (re_search(re, line, k, 0, &m0, &m1) != invert) {
            found++;
            if (countf)
                continue;
            if (name)
                buf_printf(out, "%s:", name);
            if (number)
                buf_printf(out, "%d:", n);
            buf_write(out, line, k);
            buf_putc(out, '\n');
        }
    }
    if (countf) {
        if (name)
            buf_printf(out, "%s:", name);
        buf_printf(out, "%d\n", found);
    }
    return found;
}

int cmd_grep(int argc, char **argv, Buf *in, Buf *out)
{
    int i = 1, k, found = 0;
    Re *re;
    icase = invert = countf = number = only = 0;
    while (i < argc && argv[i][0] == '-' && argv[i][1]) {
        const char *o;
        for (o = argv[i] + 1; *o; o++) {
            if (*o == 'i') icase = 1;
            else if (*o == 'v') invert = 1;
            else if (*o == 'n') number = 1;
            else if (*o == 'c') countf = 1;
            else if (*o == 'o') only = 1;
        }
        i++;
    }
    if (i >= argc) {
        buf_puts(err, "usage: grep [-ivcno] pattern [file...]\n");
        return 2;
    }
    re = re_compile(argv[i], icase);
    if (!re) {
        buf_printf(err, "grep: bad pattern: %s\n", argv[i]);
        return 2;
    }
    k = ++i;
    do {
        Buf *f = input(argc, argv, k, in, "grep");
        if (f)
            found += grep(re, f, argc - i > 1 ? argv[k] : 0, out);
    } while (++k < argc);
    re_free(re);
    return found ? 0 : 1;
}

/* ---- sed ---- */

typedef struct {
    Re *addr;                   /* only the lines this matches; 0: every line */
    int op;                     /* 's', 'd' or 'p' */
    Re *re;                     /* s: the pattern, */
    char *rep;                  /* the replacement */
    int global;                 /* and g: every match, not just the first */
} SedCmd;

#define MAXSED 8

/* text up to the delimiter d into a new string, \d as d; *sp moves past
   the delimiter. 0 if there's no delimiter. */
static char *delimited(const char **sp, int d)
{
    const char *s = *sp;
    char *t = malloc(strlen(s) + 1), *q = t;
    while (*s && *s != d) {
        if (*s == '\\' && s[1] == d)
            s++;
        else if (*s == '\\' && s[1])
            *q++ = *s++;
        *q++ = *s++;
    }
    *q = 0;
    if (!*s) {
        free(t);
        return 0;
    }
    *sp = s + 1;
    return t;
}

/* the script's commands into c[]: how many, or -1 if it's malformed */
static int sed_parse(const char *s, SedCmd *c)
{
    int n = 0;
    char *t;
    for (;;) {
        while (*s == ' ' || *s == ';' || *s == '\n')
            s++;
        if (!*s)
            return n;
        if (n == MAXSED)
            return -1;
        memset(&c[n], 0, sizeof c[n]);
        if (*s == '/') {
            s++;
            if (!(t = delimited(&s, '/')))
                return -1;
            c[n].addr = re_compile(t, 0);
            free(t);
            if (!c[n].addr)
                return -1;
        }
        c[n].op = *s;
        if (*s == 's') {
            int d = s[1];
            s += 2;
            if (!(t = delimited(&s, d)))
                return -1;
            c[n].re = re_compile(t, 0);
            free(t);
            if (!c[n].re || !(c[n].rep = delimited(&s, d)))
                return -1;
            if (*s == 'g') {
                c[n].global = 1;
                s++;
            }
        } else if (*s == 'd' || *s == 'p') {
            s++;
        } else {
            return -1;
        }
        n++;
    }
}

/* s on line[0..*len): 1 if it replaced anything */
static int subst(const SedCmd *c, char *line, int *len)
{
    char res[LINEMAX];
    int n = 0, from = 0, did = 0, m0, m1, k;
    const char *r;
    while (from <= *len && re_search(c->re, line, *len, from, &m0, &m1)) {
        for (k = from; k < m0 && n < LINEMAX - 1; k++)
            res[n++] = line[k];
        for (r = c->rep; *r && n < LINEMAX - 1; r++) {
            if (*r == '&') {
                for (k = m0; k < m1 && n < LINEMAX - 1; k++)
                    res[n++] = line[k];
            } else {
                if (*r == '\\' && r[1])
                    r++;
                res[n++] = *r;
            }
        }
        did = 1;
        from = m1;
        if (m1 == m0) {
            /* an empty match: step over a character, so the next is further on */
            if (m0 < *len && n < LINEMAX - 1)
                res[n++] = line[m0];
            from++;
        }
        if (!c->global)
            break;
    }
    if (!did)
        return 0;
    for (k = from; k < *len && n < LINEMAX - 1; k++)
        res[n++] = line[k];
    memcpy(line, res, n);
    line[n] = 0;
    *len = n;
    return 1;
}

static void sed(const SedCmd *c, int nc, int quiet, Buf *f, Buf *out)
{
    char line[LINEMAX];
    int len, i, m0, m1, gone;
    while (buf_gets(line, sizeof line, f)) {
        len = strlen(line);
        if (len && line[len - 1] == '\n')
            line[--len] = 0;
        gone = 0;
        for (i = 0; i < nc && !gone; i++) {
            if (c[i].addr && !re_search(c[i].addr, line, len, 0, &m0, &m1))
                continue;
            if (c[i].op == 's')
                subst(&c[i], line, &len);
            else if (c[i].op == 'd')
                gone = 1;
            else {
                buf_write(out, line, len);
                buf_putc(out, '\n');
            }
        }
        if (!gone && !quiet) {
            buf_write(out, line, len);
            buf_putc(out, '\n');
        }
    }
}

int cmd_sed(int argc, char **argv, Buf *in, Buf *out)
{
    SedCmd c[MAXSED];
    int i = 1, k, n, quiet = 0;
    if (i < argc && !strcmp(argv[i], "-n")) {
        quiet = 1;
        i++;
    }
    if (i >= argc) {
        buf_puts(err, "usage: sed [-n] script [file...]\n");
        return 2;
    }
    n = sed_parse(argv[i], c);
    if (n < 0) {
        buf_printf(err, "sed: bad script: %s\n", argv[i]);
        return 2;
    }
    k = ++i;
    do {
        Buf *f = input(argc, argv, k, in, "sed");
        if (f)
            sed(c, n, quiet, f, out);
    } while (++k < argc);
    for (k = 0; k < n; k++) {
        if (c[k].addr)
            re_free(c[k].addr);
        if (c[k].re) {
            re_free(c[k].re);
            free(c[k].rep);
        }
    }
    return 0;
}
