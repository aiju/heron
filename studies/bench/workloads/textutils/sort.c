/* sort and uniq.

   sort [-rnfu] [-t c] [-k f1[,f2]] [file]: lines in order, as Fen's sort
   (studies/fen/cmd/sort.c) with keys. A key is fields f1 to f2 (to the end
   of the line without f2), fields separated by the character c, or else
   by runs of blanks, which are skipped. -n compares the keys as numbers,
   -f folds case, -r reverses, -u keeps the first line of each run of
   equal keys. Lines with equal keys are ordered by the whole line, and
   then by where they were in the input: no two lines ever tie, so the
   order doesn't depend on the C library's qsort.

   uniq [-c] [-d] [-u]: adjacent lines that repeat, once, as Fen's uniq;
   -c counts them, -d shows only the repeated ones, -u only the others. */

#include <stdlib.h>
#include <string.h>
#include "tu.h"

typedef struct {
    const char *s;              /* the line, without its '\n' */
    const char *key;            /* where its key starts */
    int klen;                   /* and how long it is */
    int num;                    /* -n: the key's value */
    int at;                     /* its place in the input */
} Line;

static int rev, num, foldf, uniqf, sep, f1, f2;

/* a number at the start of s, after blanks, as atoi */
static int number_at(const char *s, int n)
{
    int v = 0, neg = 0, k = 0;
    while (k < n && (s[k] == ' ' || s[k] == '\t'))
        k++;
    if (k < n && s[k] == '-') {
        neg = 1;
        k++;
    }
    while (k < n && (unsigned)(s[k] - '0') < 10)
        v = v * 10 + s[k++] - '0';
    return neg ? -v : v;
}

/* field f (from 1) of s: its start; *end its end */
static const char *field(const char *s, int f, const char **end)
{
    if (sep) {
        while (--f > 0) {
            while (*s && *s != sep)
                s++;
            if (*s)
                s++;
        }
        for (*end = s; **end && **end != sep; ++*end)
            ;
    } else {
        for (;;) {
            while (*s == ' ' || *s == '\t')
                s++;
            if (--f == 0)
                break;
            while (*s && *s != ' ' && *s != '\t')
                s++;
        }
        for (*end = s; **end && **end != ' ' && **end != '\t'; ++*end)
            ;
    }
    return s;
}

static void make_key(Line *l)
{
    const char *e;
    if (!f1) {
        l->key = l->s;
        l->klen = strlen(l->s);
    } else {
        l->key = field(l->s, f1, &e);
        if (f2)
            field(l->s, f2, &e);
        else
            e = l->s + strlen(l->s);
        l->klen = e > l->key ? e - l->key : 0;
    }
    if (num)
        l->num = number_at(l->key, l->klen);
}

/* the keys of two lines: < 0, 0 or > 0 */
static int keycmp(const Line *x, const Line *y)
{
    const unsigned char *a = (const unsigned char *)x->key, *b = (const unsigned char *)y->key;
    int n = x->klen < y->klen ? x->klen : y->klen, k, c;
    if (num)
        return x->num < y->num ? -1 : x->num > y->num;
    if (foldf) {
        for (k = 0; k < n; k++)
            if ((c = fold(a[k]) - fold(b[k])) != 0)
                return c;
    } else {
        for (k = 0; k < n; k++)
            if (a[k] != b[k])
                return a[k] - b[k];
    }
    return x->klen - y->klen;
}

static int cmp(const void *pa, const void *pb)
{
    const Line *x = *(Line *const *)pa, *y = *(Line *const *)pb;
    int c = keycmp(x, y);
    if (c == 0 && !uniqf)
        c = strcmp(x->s, y->s);
    if (rev)
        c = -c;
    return c ? c : x->at - y->at;
}

/* an option's argument: the rest of this word, or the next word */
static const char *opt_arg(int argc, char **argv, int *i, const char *o)
{
    if (o[1])
        return o + 1;
    if (*i + 1 < argc)
        return argv[++*i];
    return "";
}

int cmd_sort(int argc, char **argv, Buf *in, Buf *out)
{
    int i = 1, n = 0, len, k;
    char *text, *p, *end;
    Line *lines, **order;
    Buf *f;
    rev = num = foldf = uniqf = sep = f1 = f2 = 0;
    for (; i < argc && argv[i][0] == '-' && argv[i][1]; i++) {
        const char *o, *a;
        for (o = argv[i] + 1; *o; o++) {
            if (*o == 'r') rev = 1;
            else if (*o == 'n') num = 1;
            else if (*o == 'f') foldf = 1;
            else if (*o == 'u') uniqf = 1;
            else if (*o == 't') {
                sep = *opt_arg(argc, argv, &i, o);
                break;
            } else if (*o == 'k') {
                a = opt_arg(argc, argv, &i, o);
                f1 = number_at(a, strlen(a));
                a = strchr(a, ',');
                if (a)
                    f2 = number_at(a + 1, strlen(a + 1));
                break;
            }
        }
    }
    if (!(f = input(argc, argv, i, in, "sort")))
        return 1;

    /* the input in one block, split into lines in place */
    len = f->len - f->pos;
    text = malloc(len + 1);
    memcpy(text, f->s + f->pos, len);
    text[len] = 0;
    for (p = text; p < text + len; p++)
        n += *p == '\n';
    if (len && text[len - 1] != '\n')
        n++;
    lines = malloc((n + 1) * sizeof *lines);
    order = malloc((n + 1) * sizeof *order);
    for (p = text, k = 0; k < n; k++) {
        end = strchr(p, '\n');
        if (end)
            *end = 0;
        lines[k].s = p;
        lines[k].at = k;
        make_key(&lines[k]);
        order[k] = &lines[k];
        p = end ? end + 1 : p + strlen(p);
    }

    qsort(order, n, sizeof *order, cmp);

    for (k = 0; k < n; k++) {
        if (uniqf && k > 0 && keycmp(order[k - 1], order[k]) == 0)
            continue;
        buf_puts(out, order[k]->s);
        buf_putc(out, '\n');
    }
    free(order);
    free(lines);
    free(text);
    return 0;
}

int cmd_uniq(int argc, char **argv, Buf *in, Buf *out)
{
    char prev[LINEMAX], line[LINEMAX];
    int have = 0, count = 0, c = 0, d = 0, u = 0, i;
    for (i = 1; i < argc && argv[i][0] == '-'; i++) {
        c |= strchr(argv[i], 'c') != 0;
        d |= strchr(argv[i], 'd') != 0;
        u |= strchr(argv[i], 'u') != 0;
    }
    if (!(in = input(argc, argv, i, in, "uniq")))
        return 1;
    for (;;) {
        int more = buf_gets(line, sizeof line, in) != 0;
        if (more && have && !strcmp(line, prev)) {
            count++;
            continue;
        }
        if (have && !(d && count == 1) && !(u && count > 1)) {
            if (c)
                buf_printf(out, "%7d ", count);
            buf_puts(out, prev);
        }
        if (!more)
            break;
        strcpy(prev, line);
        have = 1;
        count = 1;
    }
    return 0;
}
