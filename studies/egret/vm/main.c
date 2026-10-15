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
#ifdef EGRET_GUI
    gui_out_char(c);            /* the Transcript's copy (HACK: see studies/egret_gui) */
#endif
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

/* the console input, into INPUT, after the n bytes read already; with
   line, only up to the end of a line */
static unsigned read_input(unsigned n, int line)
{
    unsigned char *buf = BP(INPUT_LO);
    unsigned max = INPUT_HI - INPUT_LO;
#ifdef __HERON__
    for (;;) {
        unsigned c = HERON_CONSOLE;
        if (c == 0xFFFFFFFF)
            break;
        if (n >= max)
            fatal("the program and its input are too big");
        buf[n++] = c;
        if (line && c == '\n')
            break;
    }
#else
    int c;
    while ((c = getchar()) != EOF) {
        if (n >= max)
            fatal("the program and its input are too big");
        buf[n++] = c;
        if (line && c == '\n')
            break;
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

int main(void)
{
    unsigned n, src_len, i;
    const unsigned char *in;
#ifdef __HERON__
    if ((unsigned)_end > INPUT_LO || (unsigned)_end > PERM_LO)
        fatal("the VM is too big for its memory map");
#endif
    mem_init();
    boot_classes();
    interp_init();
    prims_init();
#ifdef EGRET_GUI
    /* the input first: its first line says how to draw the splash, and
       all of it how long the progress bar is */
    n = read_input(0, 1);
    gui_boot(BP(INPUT_LO), n);
    n = read_input(n, 0);
    gui_boot(BP(INPUT_LO), n);
#endif
    if (!run_source(prelude_src, prelude_len, "prelude"))
        fatal("the prelude failed");
#ifndef EGRET_GUI
    n = read_input(0, 0);
#endif
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
