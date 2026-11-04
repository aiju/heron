/* The shell: a script of pipelines over in-memory files, as a user at
   Fen's shell (studies/fen/cmd/sh.c) would type them.

   Each line of the script is a pipeline, a | b | c, with words quoted
   'like this' or "like this" or by \, and < file for the first command's
   input and > file for the last one's output. A pipe is a Buf: each
   command runs to the end, writing into it, and then the next reads it,
   as a pipe with room for everything. What a pipeline writes to the
   terminal is hashed and reported, a line for each.

   The files are linked in by the harness (workload.py makes them). */

#include <stdarg.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "bench.h"
#include "tu.h"

/* ---- buffers ---- */

Buf *buf_new(int cap)
{
    Buf *b = malloc(sizeof *b);
    b->cap = cap > 16 ? cap : 16;
    b->s = malloc(b->cap);
    b->len = b->pos = 0;
    return b;
}

void buf_free(Buf *b)
{
    free(b->s);
    free(b);
}

static void buf_room(Buf *b, int n)
{
    if (b->len + n > b->cap) {
        while (b->len + n > b->cap)
            b->cap *= 2;
        b->s = realloc(b->s, b->cap);
    }
}

void buf_putc(Buf *b, int c)
{
    if (b->len == b->cap)
        buf_room(b, 1);
    b->s[b->len++] = c;
}

void buf_write(Buf *b, const char *s, int n)
{
    buf_room(b, n);
    memcpy(b->s + b->len, s, n);
    b->len += n;
}

void buf_puts(Buf *b, const char *s)
{
    buf_write(b, s, strlen(s));
}

void buf_printf(Buf *b, const char *fmt, ...)
{
    char tmp[256];
    va_list ap;
    va_start(ap, fmt);
    vsprintf(tmp, fmt, ap);
    va_end(ap);
    buf_puts(b, tmp);
}

char *buf_gets(char *line, int size, Buf *b)
{
    const char *s = b->s + b->pos, *e = b->s + b->len;
    char *p = line;
    if (s == e)
        return 0;
    while (--size > 0 && s < e) {
        if ((*p++ = *s++) == '\n')
            break;
    }
    *p = 0;
    b->pos = s - b->s;
    return line;
}

char *xstrdup(const char *s)
{
    int n = strlen(s) + 1;
    char *t = malloc(n);
    memcpy(t, s, n);
    return t;
}

/* ---- files ---- */

extern const unsigned char f_syslog[], f_notes[], f_main[], f_passwd[];
extern unsigned f_syslog_len, f_notes_len, f_main_len, f_passwd_len;

#define MAXFILES 16

static struct {
    char name[16];
    Buf *b;
    int linked;                 /* the data linked in: never written or freed */
} files[MAXFILES];
static int nfiles;

/* a file over the data linked in, where it is */
static void file_const(const char *name, const unsigned char *s, unsigned n)
{
    Buf *b = malloc(sizeof *b);
    b->s = (char *)s;
    b->len = b->cap = n;
    b->pos = 0;
    strcpy(files[nfiles].name, name);
    files[nfiles].linked = 1;
    files[nfiles++].b = b;
}

Buf *file_open(const char *name)
{
    int i;
    for (i = 0; i < nfiles; i++)
        if (!strcmp(files[i].name, name)) {
            files[i].b->pos = 0;
            return files[i].b;
        }
    return 0;
}

/* > name: the file is now b */
static void file_set(const char *name, Buf *b)
{
    int i;
    for (i = 0; i < nfiles; i++)
        if (!strcmp(files[i].name, name)) {
            if (!files[i].linked)
                buf_free(files[i].b);
            files[i].b = b;
            files[i].linked = 0;
            return;
        }
    if (nfiles == MAXFILES) {
        buf_printf(err, "sh: %s: too many files\n", name);
        buf_free(b);
        return;
    }
    strcpy(files[nfiles].name, name);
    files[nfiles++].b = b;
}

Buf *err;

Buf *input(int argc, char **argv, int i, Buf *in, const char *cmd)
{
    Buf *f;
    if (i >= argc)
        return in;
    f = file_open(argv[i]);
    if (!f)
        buf_printf(err, "%s: %s: no such file\n", cmd, argv[i]);
    return f;
}

/* ---- the shell ---- */

static const struct {
    const char *name;
    Cmd fn;
} commands[] = {
    {"cat", cmd_cat}, {"cut", cmd_cut}, {"grep", cmd_grep}, {"head", cmd_head},
    {"sed", cmd_sed}, {"sort", cmd_sort}, {"tail", cmd_tail}, {"tr", cmd_tr},
    {"uniq", cmd_uniq}, {"wc", cmd_wc},
};

#define MAXARGS 16
#define MAXCMDS 8

typedef struct {
    char *argv[MAXARGS + 1];
    int argc;
} Stage;

typedef struct {
    Stage st[MAXCMDS];
    int n;
    char *in, *out;             /* < and > files, or 0 */
    char words[LINEMAX];        /* the words' text */
} Pipeline;

/* the characters that end a word */
static int special(int c)
{
    return c == ' ' || c == '\t' || c == '|' || c == '<' || c == '>' || c == '#';
}

/* one line of the script into a pipeline: 0 on a syntax error. Words are
   copied into p->words with their quotes taken off. */
static int parse(const char *s, Pipeline *p)
{
    char *w = p->words, **redir = 0;
    Stage *st = &p->st[0];
    memset(p, 0, sizeof *p - sizeof p->words);  /* all but the words, which are last */
    p->n = 1;
    for (;;) {
        char *word;
        while (*s == ' ' || *s == '\t')
            s++;
        if (!*s || *s == '#')
            break;
        if (*s == '|') {
            if (!st->argc || p->n == MAXCMDS)
                return 0;
            st = &p->st[p->n++];
            s++;
            continue;
        }
        if (*s == '<' || *s == '>') {
            redir = *s == '<' ? &p->in : &p->out;
            s++;
            continue;
        }
        /* a word: up to an unquoted blank, |, < or > */
        word = w;
        while (*s && !special(*s)) {
            if (*s == '\'' || *s == '"') {
                int q = *s++;
                while (*s && *s != q)
                    *w++ = *s++;
                if (!*s)
                    return 0;
                s++;
            } else if (*s == '\\' && s[1]) {
                *w++ = s[1];
                s += 2;
            } else {
                *w++ = *s++;
            }
        }
        *w++ = 0;
        if (redir) {
            *redir = word;
            redir = 0;
        } else if (st->argc < MAXARGS) {
            st->argv[st->argc++] = word;
        }
    }
    return st->argc > 0 && !redir;
}

static Cmd lookup(const char *name)
{
    int i;
    for (i = 0; i < (int)(sizeof commands / sizeof commands[0]); i++)
        if (!strcmp(commands[i].name, name))
            return commands[i].fn;
    return 0;
}

/* a pipeline run: what it leaves for the terminal (0 if it went to a file) */
static Buf *run(Pipeline *p)
{
    Buf *in = 0, *out = 0;
    int i;
    if (p->in && !(in = file_open(p->in))) {
        buf_printf(err, "sh: %s: no such file\n", p->in);
        return buf_new(16);
    }
    for (i = 0; i < p->n; i++) {
        Stage *st = &p->st[i];
        Cmd fn = lookup(st->argv[0]);
        Buf *empty = 0;
        if (!in)
            in = empty = buf_new(16);
        out = buf_new(1024);
        if (fn)
            fn(st->argc, st->argv, in, out);
        else
            buf_printf(err, "sh: %s: not found\n", st->argv[0]);
        /* the pipe it read from is done with; files stay */
        if (i > 0 || empty)
            buf_free(in);
        in = out;
        in->pos = 0;
    }
    if (p->out) {
        file_set(p->out, out);
        return 0;
    }
    return out;
}

/* The script: what someone looking through a machine's log, a document
   and a program's source might type. The word count is McIlroy's. The
   first PIPES lines are run (workload.py's size), so the first few are
   a mix. */
static const char *const script[] = {
    "wc syslog notes.txt main.c passwd",
    "grep ERROR syslog | cut -d' ' -f5 | sed 's/\\[.*//' | sort | uniq -c | sort -rn",
    "tr -cs A-Za-z '\\n' < notes.txt | tr A-Z a-z | sort | uniq -c | sort -rn | head -12",
    "grep -o '[A-Za-z_][A-Za-z_0-9]*' main.c | sort | uniq -c | sort -rn | head -10",
    "sort -t: -n -k3 passwd | cut -d: -f1,3,5 | head -6",
    "grep -c ERROR syslog",
    "sed -n '/failed password/p' syslog | cut -d' ' -f10 | sort | uniq -c | sort -rn -k1 | head -5",
    "grep 'GET /docs/.*\\.html 200' syslog | cut -d' ' -f9 > docs",
    "sort docs | uniq -c | sort -rn",
    "cut -c1-12 syslog | uniq -c | sort -rn | head -5",
    "grep kernel syslog | sed 's/[0-9][0-9]*/N/g' | cut -d' ' -f6- | sort -u",
    "tail -n 20 syslog | grep -v INFO | cut -d' ' -f3,5-7",
    "grep -o '[A-Z][a-z]*' notes.txt | sort -f | uniq -c | sort -rn | head -5",
    "grep -n '^[a-z].*(.*)$' main.c | cut -d'(' -f1 | sort -t' ' -k2 | head -8",
    "sed '/^ *\\/\\*/d; /^$/d' main.c | wc -l",
    "grep -c '^static' main.c",
    "cut -d: -f7 passwd | sort | uniq -c",
};

int main(void)
{
    static Pipeline p;
    unsigned all = BENCH_HASH0;
    int i, k, lines;
    char label[16];

    err = buf_new(256);
    file_const("syslog", f_syslog, f_syslog_len);
    file_const("notes.txt", f_notes, f_notes_len);
    file_const("main.c", f_main, f_main_len);
    file_const("passwd", f_passwd, f_passwd_len);

    for (i = 0; i < (int)(sizeof script / sizeof script[0]); i++) {
        Buf *out;
        if (i == PIPES)
            break;
        if (!parse(script[i], &p)) {
            buf_printf(err, "sh: syntax error: %s\n", script[i]);
            continue;
        }
        out = run(&p);
        if (!out)
            continue;
        for (lines = 0, k = 0; k < out->len; k++)
            lines += out->s[k] == '\n';
#ifdef SHOW
        /* to see what the pipelines make: on the host, -DSHOW */
        printf("$ %s\n%.*s", script[i], out->len, out->s);
#endif
        sprintf(label, "%02d.lines %3d", i, lines);
        bench_report(label, bench_hash(BENCH_HASH0, out->s, out->len));
        all = bench_hash(all, out->s, out->len);
        buf_free(out);
    }
    bench_report("all", all);
    bench_report("errors", err->len);
    return 0;
}
