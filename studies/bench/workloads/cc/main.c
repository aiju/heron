/* The driver: compiles the source the harness links in, and reports
   checksums of the assembly it made and counts of what it saw.

   It also holds what the other parts share: the arenas, the formatting
   of assembly lines, the current function's lines and the output. */

#include <stdio.h>
#include <stdlib.h>
#include "bench.h"
#include "cc.h"

extern const unsigned char source[];
extern unsigned source_len;

int nerrors;
int ninsns, npeep;

/* ---- arenas ---------------------------------------------------------- */

/* Two arenas: one for what lives as long as the compilation (names,
   types, global symbols, strings), one for a function's syntax tree and
   locals, emptied when the function has been written out. Sizes are
   rounded up to 8 so that the host's 8-byte pointers stay aligned. */

#ifndef PERM_SIZE
#define PERM_SIZE (48 * 1024)
#define FUNC_SIZE (48 * 1024)
#endif

static char perm_arena[PERM_SIZE], func_arena[FUNC_SIZE];
static int perm_used, func_used;

/* An error the compiler can't go on from. */
static void fatal(const char *msg)
{
    printf("fatal: %s\n", msg);
    exit(1);
}

void *perm_alloc(int n)
{
    char *p = perm_arena + perm_used;
    n = (n + 7) & ~7;
    if (perm_used + n > PERM_SIZE)
        fatal("out of memory");
    perm_used += n;
    return p;
}

void *func_alloc(int n)
{
    char *p = func_arena + func_used;
    n = (n + 7) & ~7;
    if (func_used + n > FUNC_SIZE)
        fatal("function too big");
    func_used += n;
    return p;
}

void func_free(void)
{
    func_used = 0;
}

void error(const char *msg)
{
#ifdef CC_DEBUG
    printf("line %d: %s (at %s)\n", tok.line, msg, tokname(tok.kind));
#endif
    (void)msg;
    nerrors++;
}

/* ---- assembly lines -------------------------------------------------- */

/* A function's lines, as text in a pool that is emptied once they have
   been written out. */
#define POOL_SIZE (32 * 1024)

char *lines[MAXLINES];
int nlines_fn;
static char pool[POOL_SIZE];
static int pool_used;

/* The whole program's assembly: the functions as they are finished,
   then the data. */
#ifndef OUT_SIZE
#define OUT_SIZE  (96 * 1024)
#define DATA_SIZE (16 * 1024)
#endif

static char out[OUT_SIZE + DATA_SIZE];
static int out_used;
static char data[DATA_SIZE];
static int data_used;
static int out_lines;

static char *put_str(char *d, const char *s)
{
    while (*s)
        *d++ = *s++;
    return d;
}

static char *put_int(char *d, int v)
{
    char buf[12];
    int k = 0;
    unsigned u = v < 0 ? -(unsigned)v : (unsigned)v;
    if (v < 0)
        *d++ = '-';
    do {
        buf[k++] = (char)('0' + u % 10);
        u /= 10;
    } while (u);
    while (k)
        *d++ = buf[--k];
    return d;
}

static char *put_reg(char *d, int r)
{
    if (r == 15)
        return put_str(d, "sp");
    *d++ = 'r';
    return put_int(d, r);
}

/* An operand in the assembler's syntax: r3, #12, [sp + 8],
   byte [_table + r2*4], [r9 - 4]. */
static char *put_operand(char *d, struct operand *o)
{
    int any = 0;
    switch (o->kind) {
    case O_REG:
        return put_reg(d, o->reg);
    case O_IMM:
        *d++ = '#';
        return put_int(d, o->off);
    }
    if (o->size == 1)
        d = put_str(d, "byte ");
    *d++ = '[';
    if (o->sym) {
        *d++ = '_';
        d = put_str(d, o->sym->str);
        any = 1;
    } else if (o->reg >= 0) {
        d = put_reg(d, o->reg);
        any = 1;
    }
    if (o->index >= 0) {
        if (any)
            d = put_str(d, " + ");
        d = put_reg(d, o->index);
        if (o->scale > 1) {
            *d++ = '*';
            d = put_int(d, o->scale);
        }
        any = 1;
    }
    if (o->off || !any) {
        if (any)
            d = put_str(d, o->off < 0 ? " - " : " + ");
        d = put_int(d, any && o->off < 0 ? -o->off : o->off);
    }
    *d++ = ']';
    return d;
}

/* Formats an assembly line. %i starts an instruction: the indent, and
   the mnemonic that follows padded to the operands' column. %d an int,
   %s a string, %r a register, %o an operand, %L a local label, %n a C
   name (with its underscore). */
char *format(char *d, const char *fmt, va_list ap)
{
    char *mnemonic = 0;
    for (; *fmt; fmt++) {
        if (*fmt != '%') {
            if (*fmt == ' ' && mnemonic) {
                while (d - mnemonic < 4)
                    *d++ = ' ';
                mnemonic = 0;
            }
            *d++ = *fmt;
            continue;
        }
        switch (*++fmt) {
        case 'i':
            d = put_str(d, "        ");
            mnemonic = d;
            break;
        case 'd':
            d = put_int(d, va_arg(ap, int));
            break;
        case 's':
            d = put_str(d, va_arg(ap, const char *));
            break;
        case 'r':
            d = put_reg(d, va_arg(ap, int));
            break;
        case 'o':
            d = put_operand(d, va_arg(ap, struct operand *));
            break;
        case 'L':
            d = put_str(d, ".L");
            d = put_int(d, va_arg(ap, int));
            break;
        case 'n':
            *d++ = '_';
            d = put_str(d, va_arg(ap, struct name *)->str);
            break;
        default:
            *d++ = *fmt;
        }
    }
    *d = 0;
    return d;
}

void emit(const char *fmt, ...)
{
    va_list ap;
    char *start = pool + pool_used;
    if (nlines_fn >= MAXLINES || pool_used > POOL_SIZE - 256) {
        error("function too long");
        return;
    }
    va_start(ap, fmt);
    pool_used = format(start, fmt, ap) - pool + 1;
    va_end(ap);
    lines[nlines_fn++] = start;
}

/* A line the peephole optimiser rewrote, kept in the pool. */
char *keep_line(const char *text)
{
    char *p = pool + pool_used;
    int len = strlen(text);
    if (pool_used + len + 1 > POOL_SIZE) {
        error("function too long");
        return 0;
    }
    memcpy(p, text, len + 1);
    pool_used += len + 1;
    return p;
}

void data_emit(const char *fmt, ...)
{
    va_list ap;
    char *end;
    if (data_used > DATA_SIZE - 256) {
        error("too much data");
        return;
    }
    va_start(ap, fmt);
    end = format(data + data_used, fmt, ap);
    va_end(ap);
    *end++ = '\n';
    data_used = end - data;
}

/* Appends the function's lines to the output, and empties the pool. */
void text_flush(void)
{
    int i;
    for (i = 0; i < nlines_fn; i++) {
        int len;
        if (!lines[i])
            continue;
        len = strlen(lines[i]);
        if (out_used + len + 1 > OUT_SIZE) {
            error("too much output");
            break;
        }
        memcpy(out + out_used, lines[i], len);
        out_used += len;
        out[out_used++] = '\n';
        out_lines++;
        if (lines[i][0] == ' ' && lines[i][8] != '.')
            ninsns++;
    }
    nlines_fn = 0;
    pool_used = 0;
}

/* ---- the program ----------------------------------------------------- */

int main(void)
{
    int i;
    sym_init();
    lex_init(source, source_len);
    parse_program();
    /* the data after the code */
    memcpy(out + out_used, data, data_used);
    out_used += data_used;
    for (i = 0; i < data_used; i++)
        if (data[i] == '\n')
            out_lines++;
#ifdef CC_DUMP
    fwrite(out, 1, out_used, stdout);
#endif
    bench_report("asm", bench_hash(BENCH_HASH0, out, out_used));
    bench_report("bytes", out_used);
    bench_report("lines", out_lines);
    bench_report("insns", ninsns);
    bench_report("peephole", npeep);
    bench_report("source", nlines);
    bench_report("tokens", ntokens);
    bench_report("nodes", nnodes);
    bench_report("symbols", nsyms);
    bench_report("functions", nfuncs);
    bench_report("strings", nstrings);
    bench_report("errors", nerrors);
    return 0;
}
