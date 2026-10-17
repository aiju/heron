/* Start-up: the core classes, the primitives, the prelude, then the
   program from the console. And the platform: output, input, the cycle
   counter. */

#include "egret.h"

#ifdef __HERON__
#include <heron.h>
extern char _end[];
#else
#include <stdio.h>
#include <stdlib.h>
char egret_ram[RAM_SIZE] __attribute__((aligned(16)));
#endif

extern const char prelude_src[];
extern const unsigned prelude_len;

const unsigned char *input_data;
unsigned input_len, input_pos;
static int repl;
static int check_only;          /* #!check: compile the program, don't run it */

/* ---- the platform ------------------------------------------------------------- */

void out_char(int c)
{
#ifdef __HERON__
    HERON_CONSOLE = c;
#else
    putchar(c);
#endif
}

void out_str(const char *s)
{
    while (*s)
        out_char(*s++);
}

void out_bytes(const unsigned char *s, unsigned n)
{
    while (n--)
        out_char(*s++);
}

void out_int(SValue n)
{
    char buf[12], *p = buf + sizeof buf;
    unsigned u = n < 0 ? 0u - (unsigned)n : (unsigned)n;
    *--p = 0;
    do {
        *--p = '0' + u % 10;
        u /= 10;
    } while (u);
    if (n < 0)
        *--p = '-';
    out_str(p);
}

void out_flush(void)
{
#ifndef __HERON__
    fflush(stdout);
#endif
}

void fatal(const char *msg)
{
    if (msg) {
        out_str("fatal: ");
        out_str(msg);
        out_char('\n');
    }
    out_flush();
#ifdef __HERON__
    exit(msg ? 1 : 0);
#else
    exit(msg ? 3 : 0);
#endif
}

unsigned cycles(void)
{
#ifdef __HERON__
    return HERON_CYCLES;
#else
    return 0;
#endif
}

/* the console input, into INPUT */
static unsigned read_input(void)
{
    unsigned char *buf = BP(INPUT_LO);
    unsigned n = 0, max = INPUT_HI - INPUT_LO;
#ifdef __HERON__
    for (;;) {
        unsigned c = HERON_CONSOLE;
        if (c == 0xFFFFFFFF)
            break;
        if (n >= max)
            fatal("the program and its input are too big");
        buf[n++] = c;
    }
#else
    int c;
    while ((c = getchar()) != EOF) {
        if (n >= max)
            fatal("the program and its input are too big");
        buf[n++] = c;
    }
#endif
    return n;
}

/* ---- running source -------------------------------------------------------------- */

/* Compiles the source, then runs it. A script is compiled whole before
   any of it runs, so a syntax error stops it before it starts; at the
   REPL each statement runs as soon as it's compiled. */
#define MAX_STATEMENTS 2048

static int run_source(const char *src, unsigned len, const char *name)
{
    Value m, statements = 0;
    int n = 0, i;
    compile_source(src, len, name);
    if (!repl) {
        while ((m = compile_next()) != 0) {
            if (!statements)
                statements = perm_obj(cls_Array, MAX_STATEMENTS);
            if (n >= MAX_STATEMENTS)
                fatal("too many top-level statements");
            F(statements, n++) = m;
        }
        if (compile_errors)
            return 0;
        if (check_only)
            return 1;
        for (i = 0; i < n; i++)
            if (!run_toplevel(F(statements, i)))
                return 0;
        return 1;
    }
    while ((m = compile_next()) != 0) {
        Value r, s;
        if (!run_toplevel(m))
            continue;
        /* run_toplevel left the result just above the stack */
        r = vm_sp[1];
        if (r != NIL) {
            s = send0(r, sym_inspect);
            if (s && !IS_INT(s) && CLASSW(s) == cls_String) {
                out_str("=> ");
                out_bytes(BYTES(s), SIZE(s));
                out_char('\n');
            }
        }
    }
    return compile_errors == 0;
}

#ifdef EGRET_INTERACTIVE
/* ---- at a terminal --------------------------------------------------------------

   Built with EGRET_INTERACTIVE, the VM is a REPL at a terminal instead of a
   program's run (studies/websim, where the console waits for what's
   typed): after the prelude it reads a statement at a time, runs it and
   prints its value as #!repl does, and carries on after an error. A
   statement ends with a line where its brackets, strings and blocks are
   closed and nothing says it goes on (an operator, a comma, a backslash);
   an empty line ends it anyway, and the compiler says what's wrong. The
   console's end of input (^D) ends the session.

   A stopgap, to be replaced: statement_complete is a second, cruder
   lexer, which knows the language's block keywords and continuation
   rules on its own and can disagree with the parser (a line that starts
   with `.name` goes on the one before it, but not here). The lexer or the
   parser should say instead whether the input so far needs more. And every
   statement's method stays in the permanent space, so a session ends with
   "out of permanent space" after about a thousand statements. */

static int is_word(int c)
{
    return (c >= 'a' && c <= 'z') || (c >= 'A' && c <= 'Z') || (c >= '0' && c <= '9') || c == '_';
}

/* p is just after an opening quote: past the closing one, or 0 if the
   string doesn't end before e. Interpolations may hold strings. */
static const char *past_string(const char *p, const char *e, int q)
{
    while (p < e && *p != q) {
        if (*p == '\\') {
            p += 2;
            continue;
        }
        if (*p == '{' && q == '"') {
            int depth = 1;
            p++;
            while (p < e && depth) {
                if (*p == '"' || *p == '\'') {
                    p = past_string(p + 1, e, *p);
                    if (!p)
                        return 0;
                    continue;
                }
                depth += *p == '{' ? 1 : *p == '}' ? -1 : 0;
                p++;
            }
            continue;
        }
        p++;
    }
    return p < e ? p + 1 : 0;
}

static int word_is(const char *w, unsigned n, const char *kw)
{
    return strlen(kw) == n && memcmp(w, kw, n) == 0;
}

/* Whether src[0..n) is whole statements: brackets and blocks closed, no
   string open, and the last line not ending in something that goes on
   (the lexer's `continues`). Blocks are counted by their keywords: class,
   if, try, while, for, a do that isn't a while's or a for's, and a def
   unless it's def name(...) = expression; end closes one. */
static int statement_complete(const char *src, unsigned n)
{
    const char *p = src, *e = src + n;
    int brackets = 0, blocks = 0, loop = 0, def_at = -1, last = 0;
    while (p < e) {
        int c = *p;
        if (c == '#') {
            while (p < e && *p != '\n')
                p++;
        } else if (c == '"' || c == '\'') {
            p = past_string(p + 1, e, c);
            if (!p)
                return 0;
            last = 'a';
        } else if (c == '\\' && p + 1 < e && p[1] == '\n') {
            p += 2;
        } else if (c == '\n') {
            if (def_at >= 0)
                blocks++;
            def_at = -1;
            loop = 0;
            p++;
        } else if (c == ' ' || c == '\t' || c == '\r') {
            p++;
        } else if (is_word(c)) {
            const char *w = p;
            int after = p > src ? p[-1] : 0;
            unsigned k;
            while (p < e && is_word(*p))
                p++;
            k = p - w;
            last = 'a';
            if (p < e && (*p == '?' || *p == '!') && !(p + 1 < e && p[1] == '='))
                p++;
            else if (after == '.' || after == '@' || after == ':' || (c >= '0' && c <= '9'))
                ;
            else if (word_is(w, k, "class") || word_is(w, k, "if") || word_is(w, k, "try"))
                blocks++;
            else if (word_is(w, k, "while") || word_is(w, k, "for")) {
                blocks++;
                loop = 1;
            } else if (word_is(w, k, "do")) {
                if (loop)
                    loop = 0;
                else
                    blocks++;
            } else if (word_is(w, k, "end"))
                blocks--;
            else if (word_is(w, k, "and") || word_is(w, k, "or") || word_is(w, k, "not"))
                last = '&';
            else if (word_is(w, k, "def")) {
                /* past the method's name: a word (x, x?, x=) or an operator ([]=, <=>) */
                while (p < e && (*p == ' ' || *p == '\t'))
                    p++;
                if (p < e && is_word(*p)) {
                    while (p < e && is_word(*p))
                        p++;
                    if (p < e && (*p == '?' || *p == '!' || (*p == '=' && p + 1 < e && p[1] == '(')))
                        p++;
                } else {
                    while (p < e && *p != '(' && *p != ' ' && *p != '\n')
                        p++;
                }
                def_at = brackets;
            }
        } else {
            if (c == '(' || c == '[' || c == '{')
                brackets++;
            else if (c == ')' || c == ']' || c == '}')
                brackets--;
            else if (c == '=' && def_at == brackets && !(p + 1 < e && p[1] == '='))
                def_at = -1;                    /* def name(...) = expression */
            last = c == ')' || c == ']' || c == '}' ? 'a' : c;
            p++;
        }
    }
    if (def_at >= 0)
        blocks++;
    return brackets <= 0 && blocks <= 0 && !(last && strchr(",.([{&|^~+-*/%<>=:;", last));
}

static int in_char(void)
{
#ifdef __HERON__
    unsigned c = HERON_CONSOLE;
    return c == 0xFFFFFFFF ? -1 : (int)c;
#else
    return getchar();
#endif
}

static void interactive(void)
{
    char *buf = (char *)BP(INPUT_LO);
    unsigned n = 0, max = INPUT_HI - INPUT_LO, line;
    int c = 0;
    repl = 1;
    while (c >= 0) {
        out_str(n ? "  ...> " : "egret> ");
        out_flush();
        line = n;
        while ((c = in_char()) >= 0) {
            if (n < max)
                buf[n++] = c;
            if (c == '\n')
                break;
        }
        if (n >= max) {
            out_str("error: the statement is too long\n");
            n = 0;
            continue;
        }
        if (c >= 0 && n > line + 1 && !statement_complete(buf, n))
            continue;
        if (n && !(c < 0 && n == line && line == 0))
            run_source(buf, n, "input");
        n = 0;
    }
    out_char('\n');
}
#endif

int main(void)
{
    unsigned n, src_len, i;
    const unsigned char *in;
#ifdef __HERON__
    if ((unsigned)_end > INPUT_LO)
        fatal("the VM is too big for its memory map");
#endif
    mem_init();
    boot_classes();
    interp_init();
    prims_init();
    if (!run_source(prelude_src, prelude_len, "prelude"))
        fatal("the prelude failed");
#ifdef EGRET_INTERACTIVE
    interactive();
    out_flush();
    return 0;
#endif
    n = read_input();
    in = BP(INPUT_LO);
    /* the program ends at a line __END__; what follows is its input */
    src_len = n;
    for (i = 0; i + 7 <= n; i++)
        if ((i == 0 || in[i - 1] == '\n') && memcmp(in + i, "__END__", 7) == 0
            && (i + 7 == n || in[i + 7] == '\n')) {
            src_len = i;
            input_data = in + (i + 8 <= n ? i + 8 : n);
            input_len = in + n - input_data;
            break;
        }
    if (n >= 6 && memcmp(in, "#!repl", 6) == 0)
        repl = 1;
    if (n >= 7 && memcmp(in, "#!check", 7) == 0)
        check_only = 1;
    i = run_source((const char *)in, src_len, "program");
    out_flush();
#if defined(EGRET_STATS) && !defined(__HERON__)
    fprintf(stderr, "stats: bytecodes %u sends %u misses %u prims %u blocks %u int_fast %u int_slow %u "
            "frames_max %u nlr %u allocs %u alloc_words %u gcs %u gc_words %u perm %u code %u methods %u\n",
            stats.bytecodes, stats.sends, stats.cache_misses, stats.prim_calls, stats.block_calls,
            stats.int_fast, stats.int_slow, stats.frames_max, stats.nlr, alloc_count, alloc_words,
            gc_count, gc_words, perm_hp - PERM_LO, stats.code_bytes, stats.methods);
#endif
    return i ? 0 : 1;
}
