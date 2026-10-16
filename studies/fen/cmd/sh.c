/* sh: Fen's shell, small and Bourne-flavoured.
 *
 *   cmd args...           run a program from $PATH, wait for it
 *   a | b | c             a pipeline
 *   < f  > f  >> f  2> f  2>&1   redirections
 *   a ; b   a && b   a || b   a &   lists, and a job in the background
 *   'x' "x $v" \x         quoting; $VAR ${VAR} $? $$; ~ is $HOME
 *   *.c  a?  [abc]        file names, in the last part of a path
 *   NAME=value            set a variable (exported: there's one kind)
 *
 * Builtins: cd pwd exit export unset set wait jobs source (.) help echo
 * true false. There's no fork, so a pipeline's programs are spawned, each
 * with the pipes and files it should have as its descriptors, in a
 * process group of their own that the console's ^C ends. */

#include <ctype.h>
#include <dirent.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <sys/stat.h>
#include <fen/sys.h>
#include <fen/spawn.h>

extern char **environ;
int __find_program(const char *file, char *out, unsigned size);

#define MAXARGS 128
#define MAXCMDS 16
#define QUOTE 1                 /* in a word: the next character was quoted */

static int last_status;
static int interactive;

/* ---- jobs in the background ---- */

#define MAXJOBS 16
static struct {
    int pids[MAXCMDS];
    int n;
    int num;
    char cmd[64];
} jobs[MAXJOBS];
static int next_job = 1;

static void reap(int report)
{
    int i, k, status, pid;
    while ((pid = waitpid(-1, &status, WNOHANG)) > 0) {
        for (i = 0; i < MAXJOBS; i++) {
            for (k = 0; k < jobs[i].n; k++)
                if (jobs[i].pids[k] == pid) {
                    jobs[i].pids[k] = jobs[i].pids[--jobs[i].n];
                    if (jobs[i].n == 0 && report)
                        printf("[%d] done  %s\n", jobs[i].num, jobs[i].cmd);
                    break;
                }
        }
    }
}

/* ---- words ---- */

struct word {
    char *s;
    int glob;                   /* has an unquoted * ? or [ */
};

struct cmd {
    struct word argv[MAXARGS];
    int argc;
    char *in, *out, *err;
    int append, err_to_out;
    char *assign[16];
    int nassign;
};

static char *var(const char *name)
{
    static char buf[16];
    if (!strcmp(name, "?")) {
        snprintf(buf, sizeof buf, "%d", last_status);
        return buf;
    }
    if (!strcmp(name, "$")) {
        snprintf(buf, sizeof buf, "%d", getpid());
        return buf;
    }
    return getenv(name);
}

/* A growing string. */
struct str {
    char *s;
    int n, cap;
};

static void add(struct str *b, int c)
{
    if (b->n + 2 > b->cap) {
        b->cap = b->cap ? 2 * b->cap : 32;
        b->s = realloc(b->s, b->cap);
    }
    b->s[b->n++] = c;
    b->s[b->n] = 0;
}

static void add_quoted(struct str *b, int c)
{
    if (c == '*' || c == '?' || c == '[' || c == QUOTE)
        add(b, QUOTE);
    add(b, c);
}

static int is_op(int c)
{
    return c == '|' || c == '&' || c == ';' || c == '<' || c == '>';
}

/* The next word from *pp, with its quotes and variables done: 0 at an
 * operator or the end. */
static int word(const char **pp, struct word *w)
{
    const char *p = *pp;
    struct str b = {0, 0, 0};
    int any = 0;
    w->glob = 0;
    while (*p == ' ' || *p == '\t')
        p++;
    if (!*p || *p == '#' || *p == '\n' || is_op(*p) ||
        (p[0] == '2' && p[1] == '>')) {
        *pp = p;
        return 0;
    }
    if (*p == '~' && (p[1] == '/' || !p[1] || p[1] == ' ')) {
        const char *h = getenv("HOME");
        for (h = h ? h : "/"; *h; h++)
            add_quoted(&b, *h);
        p++;
        any = 1;
    }
    while (*p && *p != ' ' && *p != '\t' && *p != '\n' && !is_op(*p)) {
        any = 1;
        if (*p == '\\' && p[1]) {
            add_quoted(&b, p[1]);
            p += 2;
        } else if (*p == '\'') {
            p++;
            while (*p && *p != '\'')
                add_quoted(&b, *p++);
            if (*p)
                p++;
        } else if (*p == '"') {
            p++;
            while (*p && *p != '"') {
                if (*p == '\\' && (p[1] == '"' || p[1] == '\\' || p[1] == '$')) {
                    add_quoted(&b, p[1]);
                    p += 2;
                } else if (*p == '$' && (isalnum((unsigned char)p[1]) || p[1] == '_' ||
                                         p[1] == '?' || p[1] == '{' || p[1] == '$')) {
                    char name[64];
                    int k = 0;
                    const char *v;
                    p++;
                    if (*p == '{') {
                        p++;
                        while (*p && *p != '}' && k < 63)
                            name[k++] = *p++;
                        if (*p)
                            p++;
                    } else if (*p == '?' || *p == '$') {
                        name[k++] = *p++;
                    } else {
                        while ((isalnum((unsigned char)*p) || *p == '_') && k < 63)
                            name[k++] = *p++;
                    }
                    name[k] = 0;
                    for (v = var(name); v && *v; v++)
                        add_quoted(&b, *v);
                } else
                    add_quoted(&b, *p++);
            }
            if (*p)
                p++;
        } else if (*p == '$' && (isalnum((unsigned char)p[1]) || p[1] == '_' || p[1] == '?' ||
                                 p[1] == '{' || p[1] == '$')) {
            char name[64];
            int k = 0;
            const char *v;
            p++;
            if (*p == '{') {
                p++;
                while (*p && *p != '}' && k < 63)
                    name[k++] = *p++;
                if (*p)
                    p++;
            } else if (*p == '?' || *p == '$') {
                name[k++] = *p++;
            } else {
                while ((isalnum((unsigned char)*p) || *p == '_') && k < 63)
                    name[k++] = *p++;
            }
            name[k] = 0;
            for (v = var(name); v && *v; v++)
                add_quoted(&b, *v);
        } else {
            if (*p == '*' || *p == '?' || *p == '[')
                w->glob = 1;
            add(&b, *p++);
        }
    }
    *pp = p;
    if (!any)
        return 0;
    if (!b.s) {
        b.s = malloc(1);
        b.s[0] = 0;
    }
    w->s = b.s;
    return 1;
}

/* the word with its quote marks taken out */
static char *plain(const char *s)
{
    char *out = malloc(strlen(s) + 1), *d = out;
    while (*s) {
        if (*s == QUOTE && s[1])
            s++;
        *d++ = *s++;
    }
    *d = 0;
    return out;
}

/* ---- globbing ---- */

static int match(const char *pat, const char *s)
{
    for (; *pat; pat++, s++) {
        if (*pat == QUOTE && pat[1]) {
            pat++;
            if (*s != *pat)
                return 0;
            continue;
        }
        if (*pat == '*') {
            while (pat[1] == '*')
                pat++;
            if (!pat[1])
                return 1;
            for (; *s; s++)
                if (match(pat + 1, s))
                    return 1;
            return 0;
        }
        if (!*s)
            return 0;
        if (*pat == '?')
            continue;
        if (*pat == '[') {
            const char *q = pat + 1;
            int neg = *q == '!' || *q == '^', ok = 0;
            if (neg)
                q++;
            for (; *q && *q != ']'; q++) {
                if (q[1] == '-' && q[2] && q[2] != ']') {
                    if (*s >= *q && *s <= q[2])
                        ok = 1;
                    q += 2;
                } else if (*q == *s)
                    ok = 1;
            }
            if (ok == neg || !*q)
                return 0;
            pat = q;
            continue;
        }
        if (*pat != *s)
            return 0;
    }
    return !*s;
}

static int cmpstr(const void *a, const void *b)
{
    return strcmp(*(char *const *)a, *(char *const *)b);
}

/* Expand a word into argv; how many it became. */
static int expand(struct word *w, char **argv, int room)
{
    char *slash, dir[256], *pat;
    DIR *d;
    struct dirent *e;
    int n = 0, first;
    if (!w->glob || room <= 0) {
        if (room <= 0)
            return 0;
        argv[0] = plain(w->s);
        return 1;
    }
    slash = strrchr(w->s, '/');
    if (slash) {
        int k = slash - w->s;
        char *t = malloc(k + 2);
        memcpy(t, w->s, k);
        t[k] = 0;
        pat = slash + 1;
        {
            char *pd = plain(t);
            strlcpy(dir, *pd ? pd : "/", sizeof dir);
            free(pd);
        }
        free(t);
    } else {
        strcpy(dir, ".");
        pat = w->s;
    }
    d = opendir(dir);
    first = 0;
    if (d) {
        while ((e = readdir(d)) != 0 && n < room) {
            char full[300];
            if (e->d_name[0] == '.' && pat[0] != '.')
                continue;
            if (!match(pat, e->d_name))
                continue;
            if (slash) {
                char *pd;
                int k = slash - w->s;
                char *t = malloc(k + 1);
                memcpy(t, w->s, k);
                t[k] = 0;
                pd = plain(t);
                snprintf(full, sizeof full, "%s/%s", pd, e->d_name);
                free(pd);
                free(t);
            } else
                strlcpy(full, e->d_name, sizeof full);
            argv[n++] = strdup(full);
        }
        closedir(d);
    }
    if (n == 0) {
        argv[0] = plain(w->s);
        return 1;
    }
    qsort(argv + first, n, sizeof *argv, cmpstr);
    return n;
}

/* ---- parsing ---- */

/* One command up to | or a list's end; 0 for a syntax error. */
static int parse_cmd(const char **pp, struct cmd *c)
{
    const char *p;
    struct word w;
    memset(c, 0, sizeof *c);
    for (;;) {
        p = *pp;
        while (*p == ' ' || *p == '\t')
            p++;
        *pp = p;
        if (*p == '<' || *p == '>' || (p[0] == '2' && p[1] == '>')) {
            char **target;
            if (*p == '<') {
                target = &c->in;
                p++;
            } else if (*p == '>') {
                target = &c->out;
                p++;
                if (*p == '>') {
                    c->append = 1;
                    p++;
                }
            } else {
                p += 2;
                if (p[0] == '&' && p[1] == '1') {
                    c->err_to_out = 1;
                    *pp = p + 2;
                    continue;
                }
                target = &c->err;
            }
            *pp = p;
            if (!word(pp, &w)) {
                fprintf(stderr, "sh: a redirection needs a file\n");
                return 0;
            }
            *target = plain(w.s);
            free(w.s);
            continue;
        }
        if (!word(pp, &w))
            break;
        if (c->argc == 0 && !w.glob) {
            /* NAME=value before the command */
            char *eq = strchr(w.s, '='), *q;
            int ok = eq && eq != w.s;
            for (q = w.s; ok && q < eq; q++)
                if (!isalnum((unsigned char)*q) && *q != '_')
                    ok = 0;
            if (ok && c->nassign < 16) {
                c->assign[c->nassign++] = plain(w.s);
                free(w.s);
                continue;
            }
        }
        if (c->argc < MAXARGS - 1)
            c->argv[c->argc++] = w;
    }
    return 1;
}

static void free_cmd(struct cmd *c)
{
    int i;
    for (i = 0; i < c->argc; i++)
        free(c->argv[i].s);
    for (i = 0; i < c->nassign; i++)
        free(c->assign[i]);
    free(c->in);
    free(c->out);
    free(c->err);
}

/* ---- builtins ---- */

static int run_list(const char *line);
static int run_file(FILE *f);

static int b_cd(int argc, char **argv)
{
    const char *d = argc > 1 ? argv[1] : getenv("HOME");
    char buf[256];
    if (!d)
        d = "/";
    if (chdir(d) < 0) {
        fprintf(stderr, "cd: %s: %s\n", d, strerror(errno));
        return 1;
    }
    if (getcwd(buf, sizeof buf))
        setenv("PWD", buf, 1);
    return 0;
}

static int b_pwd(int argc, char **argv)
{
    char buf[256];
    printf("%s\n", getcwd(buf, sizeof buf) ? buf : "?");
    return 0;
}

static int b_export(int argc, char **argv)
{
    int i;
    for (i = 1; i < argc; i++) {
        char *eq = strchr(argv[i], '=');
        if (eq) {
            *eq = 0;
            setenv(argv[i], eq + 1, 1);
            *eq = '=';
        }
    }
    return 0;
}

static int b_unset(int argc, char **argv)
{
    int i;
    for (i = 1; i < argc; i++)
        unsetenv(argv[i]);
    return 0;
}

static int b_set(int argc, char **argv)
{
    char **e;
    for (e = environ; e && *e; e++)
        printf("%s\n", *e);
    return 0;
}

static int b_wait(int argc, char **argv)
{
    int status, i, pid;
    while ((pid = waitpid(-1, &status, 0)) > 0) {
        int k;
        for (i = 0; i < MAXJOBS; i++)
            for (k = 0; k < jobs[i].n; k++)
                if (jobs[i].pids[k] == pid)
                    jobs[i].pids[k] = jobs[i].pids[--jobs[i].n];
    }
    return 0;
}

static int b_jobs(int argc, char **argv)
{
    int i;
    reap(1);
    for (i = 0; i < MAXJOBS; i++)
        if (jobs[i].n)
            printf("[%d] running  %s\n", jobs[i].num, jobs[i].cmd);
    return 0;
}

static int b_source(int argc, char **argv)
{
    FILE *f;
    int r;
    if (argc < 2)
        return 1;
    f = fopen(argv[1], "r");
    if (!f) {
        fprintf(stderr, "sh: %s: %s\n", argv[1], strerror(errno));
        return 1;
    }
    r = run_file(f);
    fclose(f);
    return r;
}

static int b_echo(int argc, char **argv)
{
    int i = 1, nl = 1;
    if (argc > 1 && !strcmp(argv[1], "-n")) {
        nl = 0;
        i++;
    }
    for (; i < argc; i++) {
        fputs(argv[i], stdout);
        if (i < argc - 1)
            putchar(' ');
    }
    if (nl)
        putchar('\n');
    return 0;
}

static int b_exit(int argc, char **argv)
{
    exit(argc > 1 ? atoi(argv[1]) : last_status);
}

static int b_true(int argc, char **argv) { return 0; }
static int b_false(int argc, char **argv) { return 1; }

static int b_help(int argc, char **argv)
{
    printf("Fen's shell. Builtins: cd pwd exit export unset set wait jobs source echo\n"
           "Programs are in /bin: ls /bin. a | b, a > f, a < f, a >> f, 2> f, 2>&1,\n"
           "a ; b, a && b, a || b, a &, $VAR, $?, 'quotes', \"quotes\", *.c\n");
    return 0;
}

static struct {
    const char *name;
    int (*fn)(int, char **);
} builtins[] = {
    {"cd", b_cd}, {"pwd", b_pwd}, {"export", b_export}, {"unset", b_unset}, {"set", b_set},
    {"wait", b_wait}, {"jobs", b_jobs}, {"source", b_source}, {".", b_source},
    {"echo", b_echo}, {"exit", b_exit}, {"true", b_true}, {"false", b_false},
    {"help", b_help},
};
#define NBUILTINS (sizeof builtins / sizeof builtins[0])

/* ---- running ---- */

/* argv for a command, expanded */
static int build_argv(struct cmd *c, char **argv)
{
    int i, n = 0;
    for (i = 0; i < c->argc; i++)
        n += expand(&c->argv[i], argv + n, MAXARGS - 1 - n);
    argv[n] = 0;
    return n;
}

static void free_argv(char **argv)
{
    while (*argv)
        free(*argv++);
}

static int open_redir(const char *path, int flags)
{
    int fd = open(path, flags, 0644);
    if (fd < 0)
        fprintf(stderr, "sh: %s: %s\n", path, strerror(errno));
    return fd;
}

/* the descriptors a command's redirections give: in, out, err (-1 if not) */
static int redirect(struct cmd *c, int fds[3])
{
    fds[0] = fds[1] = fds[2] = -1;
    if (c->in && (fds[0] = open_redir(c->in, O_RDONLY)) < 0)
        return -1;
    if (c->out && (fds[1] = open_redir(c->out, O_WRONLY | O_CREAT |
                                       (c->append ? O_APPEND : O_TRUNC))) < 0)
        return -1;
    if (c->err && (fds[2] = open_redir(c->err, O_WRONLY | O_CREAT | O_TRUNC)) < 0)
        return -1;
    return 0;
}

static void close_fds(int *fds, int n)
{
    int i;
    for (i = 0; i < n; i++)
        if (fds[i] > 2)
            close(fds[i]);
}

static int builtin_index(const char *name)
{
    unsigned i;
    for (i = 0; i < NBUILTINS; i++)
        if (!strcmp(builtins[i].name, name))
            return i;
    return -1;
}

/* a builtin, with its redirections done in the shell itself */
static int run_builtin(int b, struct cmd *c, char **argv, int argc)
{
    int fds[3], saved[3], i, r;
    if (redirect(c, fds) < 0) {
        close_fds(fds, 3);
        return 1;
    }
    if (c->err_to_out && fds[2] < 0)
        fds[2] = fds[1] >= 0 ? dup(fds[1]) : -1;
    fflush(stdout);
    for (i = 0; i < 3; i++) {
        saved[i] = -1;
        if (fds[i] >= 0) {
            saved[i] = dup(i);
            dup2(fds[i], i);
            close(fds[i]);
        }
    }
    r = builtins[b].fn(argc, argv);
    fflush(stdout);
    for (i = 0; i < 3; i++)
        if (saved[i] >= 0) {
            dup2(saved[i], i);
            close(saved[i]);
        }
    return r;
}

/* the environment for a command: ours with its NAME=value in front */
static char **command_env(struct cmd *c)
{
    char **env;
    int n = 0, i;
    if (!c->nassign)
        return environ;
    while (environ && environ[n])
        n++;
    env = malloc((n + c->nassign + 1) * sizeof *env);
    for (i = 0; i < c->nassign; i++)
        env[i] = c->assign[i];
    for (i = 0; i < n; i++)
        env[c->nassign + i] = environ[i];
    env[n + c->nassign] = 0;
    return env;
}

static void status_note(int status)
{
    if (status == 128 + 2)
        return;
    if (status > 128)
        fprintf(stderr, "%s\n", status == 128 + 11 ? "memory fault" :
                status == 128 + 4 ? "illegal instruction" :
                status == 128 + 8 ? "arithmetic error" :
                status == 128 + 7 ? "bus error" : "killed");
}

/* A pipeline: its exit status, or with `bg` 0 at once. */
static int run_pipeline(struct cmd *cmds, int n, int bg, const char *text)
{
    int pids[MAXCMDS], npids = 0;
    int prev_read = -1, pgid = 0, i, status = 0, b;
    char *argv[MAXARGS];
    if (n == 1 && cmds[0].argc == 0) {
        /* only assignments */
        for (i = 0; i < cmds[0].nassign; i++) {
            char *eq = strchr(cmds[0].assign[i], '=');
            *eq = 0;
            setenv(cmds[0].assign[i], eq + 1, 1);
            *eq = '=';
        }
        return 0;
    }
    if (n == 1 && !bg) {
        int argc = build_argv(&cmds[0], argv);
        if (argc && (b = builtin_index(argv[0])) >= 0) {
            status = run_builtin(b, &cmds[0], argv, argc);
            free_argv(argv);
            return status;
        }
        free_argv(argv);
    }
    for (i = 0; i < n; i++) {
        struct cmd *c = &cmds[i];
        int p[2] = {-1, -1}, fds[3], child[3], pid;
        char path[256];
        char **env;
        int argc = build_argv(c, argv);
        if (!argc) {
            free_argv(argv);
            continue;
        }
        if (i < n - 1 && pipe(p) < 0) {
            perror("sh: pipe");
            free_argv(argv);
            break;
        }
        child[0] = prev_read >= 0 ? prev_read : 0;
        child[1] = p[1] >= 0 ? p[1] : 1;
        child[2] = 2;
        if (redirect(c, fds) < 0) {
            close_fds(fds, 3);
            free_argv(argv);
            status = 1;
            if (p[1] >= 0)
                close(p[1]);
            if (prev_read >= 0)
                close(prev_read);
            prev_read = p[0];
            continue;
        }
        if (fds[0] >= 0)
            child[0] = fds[0];
        if (fds[1] >= 0)
            child[1] = fds[1];
        if (fds[2] >= 0)
            child[2] = fds[2];
        if (c->err_to_out)
            child[2] = child[1];
        env = command_env(c);
        if (__find_program(argv[0], path, sizeof path) < 0) {
            fprintf(stderr, "sh: %s: not found\n", argv[0]);
            status = 127;
            pid = -1;
        } else {
            pid = spawnx(path, argv, env, child, 3, SPAWN_PGID, pgid);
            if (pid < 0) {
                fprintf(stderr, "sh: %s: %s\n", argv[0], strerror(errno));
                status = 126;
            }
        }
        if (env != environ)
            free(env);
        if (pid > 0) {
            if (!pgid)
                pgid = pid;
            pids[npids++] = pid;
        }
        close_fds(fds, 3);
        if (prev_read >= 0)
            close(prev_read);
        if (p[1] >= 0)
            close(p[1]);
        prev_read = p[0];
        free_argv(argv);
    }
    if (prev_read >= 0)
        close(prev_read);
    if (!npids)
        return status;
    if (bg) {
        for (i = 0; i < MAXJOBS && jobs[i].n; i++)
            ;
        if (i < MAXJOBS) {
            memcpy(jobs[i].pids, pids, npids * sizeof pids[0]);
            jobs[i].n = npids;
            jobs[i].num = next_job++;
            strlcpy(jobs[i].cmd, text, sizeof jobs[i].cmd);
            if (interactive)
                printf("[%d] %d\n", jobs[i].num, pgid);
        }
        return 0;
    }
    ioctl(0, IO_SETFG, pgid);
    for (i = 0; i < npids; i++) {
        int st = 0;
        if (waitpid(pids[i], &st, 0) == pids[i] && i == npids - 1)
            status = st;
    }
    ioctl(0, IO_SETFG, getpgid(0));
    if (interactive)
        status_note(status);
    return status;
}

/* The text of an and-or list from *pp: up to ; & or the end. */
static int run_list(const char *line)
{
    const char *p = line;
    while (*p) {
        struct cmd cmds[MAXCMDS];
        int n = 0, bg = 0, ok = 1, op, i;
        const char *start;
        /* an and-or list: pipelines joined by && and || */
        int skip = 0, chain_op = 0;
        while (*p == ' ' || *p == '\t' || *p == ';' || *p == '\n')
            p++;
        if (!*p || *p == '#')
            break;
        for (;;) {
            start = p;
            n = 0;
            for (;;) {
                if (n == MAXCMDS) {
                    fprintf(stderr, "sh: pipeline too long\n");
                    ok = 0;
                    break;
                }
                if (!parse_cmd(&p, &cmds[n])) {
                    ok = 0;
                    n++;
                    break;
                }
                n++;
                while (*p == ' ' || *p == '\t')
                    p++;
                if (p[0] == '|' && p[1] != '|') {
                    p++;
                    continue;
                }
                break;
            }
            op = 0;
            if (p[0] == '&' && p[1] == '&') {
                op = 1;
                p += 2;
            } else if (p[0] == '|' && p[1] == '|') {
                op = 2;
                p += 2;
            } else if (*p == '&') {
                bg = 1;
                p++;
            } else if (*p == ';' || *p == '\n') {
                p++;
            } else if (*p && *p != '#') {
                fprintf(stderr, "sh: syntax error near '%c'\n", *p);
                ok = 0;
                p += strlen(p);
            }
            if (ok && !skip) {
                char text[64];
                int k = p - start;
                if (k > 63)
                    k = 63;
                memcpy(text, start, k);
                text[k] = 0;
                last_status = run_pipeline(cmds, n, bg, text);
            }
            for (i = 0; i < n; i++)
                free_cmd(&cmds[i]);
            if (!ok)
                return last_status = 2;
            if (!op)
                break;
            chain_op = op;
            skip = (chain_op == 1 && last_status != 0) || (chain_op == 2 && last_status == 0);
        }
    }
    return last_status;
}

static int run_file(FILE *f)
{
    char line[1024];
    while (fgets(line, sizeof line, f))
        run_list(line);
    return last_status;
}

int main(int argc, char **argv)
{
    char line[1024];
    int login = 0;
    if (argc > 2 && !strcmp(argv[1], "-c"))
        return run_list(argv[2]);
    if (argc > 1 && !strcmp(argv[1], "-l"))
        login = 1;
    else if (argc > 1) {
        FILE *f = fopen(argv[1], "r");
        if (!f) {
            fprintf(stderr, "sh: %s: %s\n", argv[1], strerror(errno));
            return 127;
        }
        return run_file(f);
    }
    interactive = isatty(0);
    setpgid(0, 0);
    if (login) {
        FILE *f = fopen("/etc/profile", "r");
        if (f) {
            run_file(f);
            fclose(f);
        }
    }
    for (;;) {
        char cwd[256];
        reap(interactive);
        if (interactive) {
            const char *home = getenv("HOME");
            const char *d = getcwd(cwd, sizeof cwd) ? cwd : "?";
            if (home && !strncmp(d, home, strlen(home)) &&
                (d[strlen(home)] == 0 || d[strlen(home)] == '/'))
                printf("~%s%% ", d + strlen(home));
            else
                printf("%s%% ", d);
            fflush(stdout);
        }
        if (!fgets(line, sizeof line, stdin))
            break;
        run_list(line);
    }
    if (interactive)
        printf("\n");
    return last_status;
}
