/* The simpler commands, each as Fen's (studies/fen/cmd) where Fen has it:

   cat [file...]               the files one after the other
   head [-n N | -N] [file]     the first N (10) lines
   tail [-n N | -N] [file]     the last N (10) lines
   wc [-lwc] [file...]         lines, words and bytes, and a total
   tr [-cds] set1 [set2]       characters translated, deleted, squeezed
   cut -d c -f list [file]     fields; cut -c list: columns */

#include <stdlib.h>
#include <string.h>
#include "tu.h"

int cmd_cat(int argc, char **argv, Buf *in, Buf *out)
{
    int i = 1, status = 0;
    do {
        Buf *f = input(argc, argv, i, in, "cat");
        if (f) {
            buf_write(out, f->s + f->pos, f->len - f->pos);
            f->pos = f->len;
        } else {
            status = 1;
        }
    } while (++i < argc);
    return status;
}

/* -n N or -N: the count, and i past it */
static int count_opt(int argc, char **argv, int *i)
{
    int n = 10;
    if (*i + 1 < argc && !strcmp(argv[*i], "-n")) {
        n = atoi(argv[*i + 1]);
        *i += 2;
    } else if (*i < argc && argv[*i][0] == '-' && argv[*i][1]) {
        n = atoi(argv[*i] + 1);
        ++*i;
    }
    return n;
}

int cmd_head(int argc, char **argv, Buf *in, Buf *out)
{
    char line[LINEMAX];
    int i = 1, n = count_opt(argc, argv, &i), c;
    Buf *f = input(argc, argv, i, in, "head");
    if (!f)
        return 1;
    for (c = 0; c < n && buf_gets(line, sizeof line, f); c++)
        buf_puts(out, line);
    return 0;
}

int cmd_tail(int argc, char **argv, Buf *in, Buf *out)
{
    char line[LINEMAX], **lines;
    int i = 1, n = count_opt(argc, argv, &i), k = 0, j;
    Buf *f = input(argc, argv, i, in, "tail");
    if (!f)
        return 1;
    if (n <= 0)
        return 0;
    /* the last n lines seen, in a ring */
    lines = calloc(n, sizeof *lines);
    while (buf_gets(line, sizeof line, f)) {
        free(lines[k % n]);
        lines[k % n] = xstrdup(line);
        k++;
    }
    for (j = k > n ? k - n : 0; j < k; j++)
        buf_puts(out, lines[j % n]);
    for (j = 0; j < n; j++)
        free(lines[j]);
    free(lines);
    return 0;
}

/* ---- wc ---- */

static int fl, fw, fc;
static unsigned tl, tw, tc;

static void wc_show(Buf *out, unsigned l, unsigned w, unsigned c, const char *name)
{
    if (fl)
        buf_printf(out, "%7u", l);
    if (fw)
        buf_printf(out, "%8u", w);
    if (fc)
        buf_printf(out, "%8u", c);
    if (name)
        buf_printf(out, " %s", name);
    buf_putc(out, '\n');
}

static void wc_count(Buf *out, Buf *f, const char *name)
{
    const unsigned char *s = (const unsigned char *)f->s + f->pos;
    unsigned l = 0, w = 0, c = f->len - f->pos, k;
    int in = 0, ch;
    if (fl || fw) {
        for (k = 0; k < c; k++) {
            ch = s[k];
            if (ch > ' ') {
                /* most characters: in a word, perhaps a new one */
                if (!in) {
                    in = 1;
                    w++;
                }
            } else if (ch == ' ' || ch == '\t' || ch == '\n' || ch == '\r') {
                l += ch == '\n';
                in = 0;
            } else if (!in) {
                in = 1;
                w++;
            }
        }
    }
    f->pos = f->len;
    wc_show(out, l, w, c, name);
    tl += l;
    tw += w;
    tc += c;
}

int cmd_wc(int argc, char **argv, Buf *in, Buf *out)
{
    int i = 1, status = 0, files;
    tl = tw = tc = 0;
    if (argc > 1 && argv[1][0] == '-' && argv[1][1]) {
        fl = strchr(argv[1], 'l') != 0;
        fw = strchr(argv[1], 'w') != 0;
        fc = strchr(argv[1], 'c') != 0;
        i++;
    } else {
        fl = fw = fc = 1;
    }
    files = argc - i;
    do {
        Buf *f = input(argc, argv, i, in, "wc");
        if (f)
            wc_count(out, f, files ? argv[i] : 0);
        else
            status = 1;
    } while (++i < argc);
    if (files > 1)
        wc_show(out, tl, tw, tc, "total");
    return status;
}

/* ---- tr ---- */

/* a set's characters in order into s[], ranges a-z and \n \t \\ expanded:
   how many */
static int tr_set(const char *p, unsigned char *s)
{
    int n = 0, c, k;
    while (*p) {
        c = (unsigned char)*p++;
        if (c == '\\' && *p) {
            c = (unsigned char)*p++;
            c = c == 'n' ? '\n' : c == 't' ? '\t' : c;
        }
        if (*p == '-' && p[1]) {
            int hi = (unsigned char)p[1];
            for (k = c; k <= hi && n < 256; k++)
                s[n++] = k;
            p += 2;
        } else if (n < 256) {
            s[n++] = c;
        }
    }
    return n;
}

int cmd_tr(int argc, char **argv, Buf *in, Buf *out)
{
    unsigned char s1[256], s2[256], map[256], del[256], squeeze[256], chunk[512];
    int i = 1, comp = 0, delf = 0, sq = 0, n1, n2 = 0, c, k, last = -1, nchunk = 0;
    const unsigned char *p, *e;
    for (; i < argc && argv[i][0] == '-' && argv[i][1]; i++) {
        comp |= strchr(argv[i], 'c') != 0;
        delf |= strchr(argv[i], 'd') != 0;
        sq |= strchr(argv[i], 's') != 0;
    }
    if (i >= argc) {
        buf_puts(err, "usage: tr [-cds] set1 [set2]\n");
        return 2;
    }
    n1 = tr_set(argv[i], s1);
    if (i + 1 < argc)
        n2 = tr_set(argv[i + 1], s2);
    if (comp) {
        /* the complement: every character not in set1, in order */
        unsigned char in1[256];
        memset(in1, 0, sizeof in1);
        for (k = 0; k < n1; k++)
            in1[s1[k]] = 1;
        for (n1 = 0, c = 0; c < 256; c++)
            if (!in1[c])
                s1[n1++] = c;
    }
    for (c = 0; c < 256; c++)
        map[c] = c;
    memset(del, 0, sizeof del);
    memset(squeeze, 0, sizeof squeeze);
    for (k = 0; k < n1; k++) {
        if (delf)
            del[s1[k]] = 1;
        else if (n2)
            map[s1[k]] = s2[k < n2 ? k : n2 - 1];   /* set2 padded with its last */
    }
    /* -s squeezes runs of set2's characters (set1's when deleting or
       there's no set2) */
    if (sq) {
        if (n2 && !delf)
            for (k = 0; k < n2; k++)
                squeeze[s2[k]] = 1;
        else
            for (k = 0; k < n1; k++)
                squeeze[s1[k]] = 1;
    }
    p = (const unsigned char *)in->s + in->pos;
    e = (const unsigned char *)in->s + in->len;
    for (; p < e; p++) {
        c = *p;
        if (del[c])
            continue;
        c = map[c];
        if (squeeze[c] && c == last)
            continue;
        last = c;
        chunk[nchunk++] = c;
        if (nchunk == sizeof chunk) {
            buf_write(out, (char *)chunk, nchunk);
            nchunk = 0;
        }
    }
    buf_write(out, (char *)chunk, nchunk);
    in->pos = in->len;
    return 0;
}

/* ---- cut ---- */

/* the fields or columns a list such as "1,3-5,7-" selects: pick[i] for
   field or column i (from 1), each one past the end of the line too */
static void cut_list(const char *s, unsigned char *pick)
{
    int lo, hi, k;
    memset(pick, 0, LINEMAX + 1);
    while (*s) {
        lo = *s == '-' ? 1 : atoi(s);
        while ((unsigned)(*s - '0') < 10)
            s++;
        hi = lo;
        if (*s == '-') {
            s++;
            hi = (unsigned)(*s - '0') < 10 ? atoi(s) : LINEMAX;
            while ((unsigned)(*s - '0') < 10)
                s++;
        }
        for (k = lo; k <= hi && k <= LINEMAX; k++)
            pick[k] = 1;
        if (*s != ',')
            break;
        s++;
    }
}

int cmd_cut(int argc, char **argv, Buf *in, Buf *out)
{
    static unsigned char pick[LINEMAX + 1];
    char line[LINEMAX], res[LINEMAX + 1];
    int delim = '\t', chars = 0, i = 1;
    Buf *f;
    for (; i < argc && argv[i][0] == '-'; i++) {
        const char *o = argv[i] + 1, *a = o[1] ? o + 1 : i + 1 < argc ? argv[++i] : "";
        if (*o == 'd')
            delim = *a;
        else if (*o == 'f' || *o == 'c') {
            chars = *o == 'c';
            cut_list(a, pick);
        }
    }
    if (!(f = input(argc, argv, i, in, "cut")))
        return 1;
    while (buf_gets(line, sizeof line, f)) {
        int len = strlen(line), n = 0, k, fno = 1, first = 1;
        if (len && line[len - 1] == '\n')
            line[--len] = 0;
        if (chars) {
            for (k = 0; k < len; k++)
                if (pick[k + 1])
                    res[n++] = line[k];
        } else if (!strchr(line, delim)) {
            /* a line without the delimiter is passed on whole */
            memcpy(res, line, len);
            n = len;
        } else {
            for (k = 0; k <= len; k++, fno++) {
                int start = k;
                while (k < len && line[k] != delim)
                    k++;
                if (fno <= LINEMAX && pick[fno]) {
                    if (!first)
                        res[n++] = delim;
                    memcpy(res + n, line + start, k - start);
                    n += k - start;
                    first = 0;
                }
            }
        }
        res[n++] = '\n';
        buf_write(out, res, n);
    }
    return 0;
}
