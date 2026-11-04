/* The text utilities: Fen's shell tools (studies/fen/cmd) run as
   functions on in-memory files, with pipes as buffers between them.

   A Buf is a file or a pipe: bytes, and how far a reader has got. A
   command reads its standard input from one Buf and writes its standard
   output to another, as Fen's commands read and write their descriptors;
   the shell (sh.c) wires them up. */

#ifndef TU_H
#define TU_H

#define LINEMAX 1024            /* a line, as the commands' fgets buffers */

typedef struct {
    char *s;
    int len, cap;
    int pos;                    /* the next byte a reader gets */
} Buf;

Buf *buf_new(int cap);
void buf_free(Buf *b);
void buf_putc(Buf *b, int c);
void buf_write(Buf *b, const char *s, int n);
void buf_puts(Buf *b, const char *s);
void buf_printf(Buf *b, const char *fmt, ...);
/* the next line, '\n' included, into line[0..size), as fgets; 0 at the end */
char *buf_gets(char *line, int size, Buf *b);

/* a file by name: its Buf, rewound for reading; 0 if there's none */
Buf *file_open(const char *name);

/* a command: argv[0] is its name; in is standard input (empty if the
   command has none), out its standard output, err for its complaints;
   the result is the exit status */
typedef int (*Cmd)(int argc, char **argv, Buf *in, Buf *out);
extern Buf *err;

/* each a command of Fen's, cut down to what the scripts use */
int cmd_cat(int argc, char **argv, Buf *in, Buf *out);
int cmd_head(int argc, char **argv, Buf *in, Buf *out);
int cmd_tail(int argc, char **argv, Buf *in, Buf *out);
int cmd_wc(int argc, char **argv, Buf *in, Buf *out);
int cmd_tr(int argc, char **argv, Buf *in, Buf *out);
int cmd_cut(int argc, char **argv, Buf *in, Buf *out);
int cmd_grep(int argc, char **argv, Buf *in, Buf *out);
int cmd_sed(int argc, char **argv, Buf *in, Buf *out);
int cmd_sort(int argc, char **argv, Buf *in, Buf *out);
int cmd_uniq(int argc, char **argv, Buf *in, Buf *out);

/* the input of a command that takes file names: the file argv[i], or
   standard input if there are no more arguments; 0 (and a complaint) if
   the file doesn't exist */
Buf *input(int argc, char **argv, int i, Buf *in, const char *cmd);

/* ---- regular expressions (regex.c) ----

   ed's and grep's basic ones, with egrep's + and ?: c, \c, ., [set],
   [^set] (ranges a-z), each followed by *, + or ? or not, and ^ and $
   anchoring the ends. Compiled to an array of nodes, matched by
   backtracking, the repeats greedy. */

typedef struct Re Re;

/* the pattern compiled; icase folds letters; 0 if it is malformed */
Re *re_compile(const char *pat, int icase);
void re_free(Re *re);
/* the leftmost match in s[0..n) from s + from on: 1 and its extent in
   *m0 and *m1 (offsets into s), or 0. s needn't end in a NUL. */
int re_search(const Re *re, const char *s, int n, int from, int *m0, int *m1);

/* string helpers the C library lacks */
char *xstrdup(const char *s);
int fold(int c);

#endif
