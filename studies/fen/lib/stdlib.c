/* stdlib: the heap, exit, the environment, numbers, sorting.
 *
 * The heap is first fit on an address-ordered free list, as in the
 * compiler's library, growing from the end of the program a page at a
 * time with vm_alloc. */

#include <errno.h>
#include <stdlib.h>
#include <stdio.h>
#include <string.h>
#include <ctype.h>
#include <fen/sys.h>
#include <fen/spawn.h>

extern char __end[] __asm__("__end");

int abs(int x) { return x < 0 ? -x : x; }
long labs(long x) { return x < 0 ? -x : x; }

unsigned long strtoul(const char *s, char **end, int base)
{
    unsigned long v = 0;
    int neg = 0;
    const char *start = s;
    while (isspace(*s))
        s++;
    if (*s == '-' || *s == '+')
        neg = *s++ == '-';
    if ((base == 0 || base == 16) && s[0] == '0' && (s[1] | 32) == 'x') {
        s += 2;
        base = 16;
    } else if (base == 0) {
        base = *s == '0' ? 8 : 10;
    }
    for (;;) {
        int c = *s, d;
        if (isdigit(c))
            d = c - '0';
        else if (isalpha(c))
            d = (c | 32) - 'a' + 10;
        else
            break;
        if (d >= base)
            break;
        v = v * base + d;
        s++;
        start = s;
    }
    if (end)
        *end = (char *)start;
    return neg ? -v : v;
}

long strtol(const char *s, char **end, int base)
{
    return (long)strtoul(s, end, base);
}

int atoi(const char *s) { return (int)strtol(s, 0, 10); }
long atol(const char *s) { return strtol(s, 0, 10); }

/* ---- the heap ---- */

struct block {
    size_t size;                       /* bytes, including this header */
    struct block *next;
};

static struct block *free_list;
static char *brk_cur, *brk_top;        /* the heap's end, and the end of its pages */
#define HEAP_LIMIT ((char *)MMAP_BASE)

void *sbrk(int n)
{
    char *old;
    if (!brk_cur)
        brk_cur = brk_top = (char *)(((unsigned)__end + 4095) & ~4095);
    old = brk_cur;
    if (n > 0 && brk_cur + n > brk_top) {
        unsigned need = (unsigned)(brk_cur + n - brk_top + 4095) & ~4095;
        if (brk_top + need > HEAP_LIMIT)
            return (void *)-1;
        if (vm_alloc(0, brk_top, need >> 12, PROT_READ | PROT_WRITE) < 0)
            return (void *)-1;
        brk_top += need;
    }
    brk_cur += n;
    return old;
}

static struct block *grow(size_t need)
{
    size_t n = need < 16384 ? 16384 : need;
    struct block *b = sbrk(n);
    if (b == (void *)-1) {
        n = need;
        b = sbrk(n);
        if (b == (void *)-1)
            return 0;
    }
    b->size = n;
    return b;
}

void *malloc(size_t n)
{
    struct block **pp, *b;
    size_t need = (n + sizeof(struct block) + 7) & ~7;
    if (n == 0)
        n = 1;
    for (;;) {
        for (pp = &free_list; (b = *pp) != 0; pp = &b->next) {
            if (b->size >= need) {
                if (b->size - need >= 16) {
                    struct block *rest = (struct block *)((char *)b + need);
                    rest->size = b->size - need;
                    rest->next = b->next;
                    *pp = rest;
                    b->size = need;
                } else {
                    *pp = b->next;
                }
                return b + 1;
            }
        }
        b = grow(need);
        if (!b) {
            errno = ENOMEM;
            return 0;
        }
        free(b + 1);
    }
}

void free(void *p)
{
    struct block *b, **pp, *next;
    if (p == 0)
        return;
    b = (struct block *)p - 1;
    for (pp = &free_list; *pp != 0 && *pp < b; pp = &(*pp)->next)
        ;
    next = *pp;
    if (next != 0 && (char *)b + b->size == (char *)next) {
        b->size += next->size;
        next = next->next;
    }
    b->next = next;
    *pp = b;
    if (pp != &free_list) {
        struct block *prev = (struct block *)((char *)pp - sizeof(size_t));
        if ((char *)prev + prev->size == (char *)b) {
            prev->size += b->size;
            prev->next = b->next;
        }
    }
}

void *calloc(size_t n, size_t size)
{
    size_t total = n * size;
    void *p = malloc(total);
    if (p)
        memset(p, 0, total);
    return p;
}

void *realloc(void *p, size_t n)
{
    struct block *b;
    void *q;
    if (p == 0)
        return malloc(n);
    b = (struct block *)p - 1;
    if (b->size - sizeof(struct block) >= n)
        return p;
    q = malloc(n);
    if (q) {
        memcpy(q, p, b->size - sizeof(struct block));
        free(p);
    }
    return q;
}

/* ---- exit ---- */

static void (*exit_funcs[16])(void);
static int nexit;

int atexit(void (*f)(void))
{
    if (nexit == 16)
        return -1;
    exit_funcs[nexit++] = f;
    return 0;
}

void exit(int status)
{
    extern void __stdio_exit(void);
    while (nexit)
        exit_funcs[--nexit]();
    __stdio_exit();
    _exit(status);
}

void abort(void)
{
    fflush(0);
    _exit(128 + 6);
}

void __assert_fail(const char *expr, const char *file, int line)
{
    fprintf(stderr, "%s:%d: assertion failed: %s\n", file, line, expr);
    abort();
}

/* ---- the environment ---- */

extern char **environ;
static int env_own;     /* environ is our own copy, which we may grow */

char *getenv(const char *name)
{
    size_t k = strlen(name);
    char **e;
    if (!environ)
        return 0;
    for (e = environ; *e; e++)
        if (!strncmp(*e, name, k) && (*e)[k] == '=')
            return *e + k + 1;
    return 0;
}

int unsetenv(const char *name)
{
    size_t k = strlen(name);
    char **e, **d;
    if (!environ)
        return 0;
    for (e = d = environ; *e; e++)
        if (strncmp(*e, name, k) || (*e)[k] != '=')
            *d++ = *e;
    *d = 0;
    return 0;
}

int setenv(const char *name, const char *value, int overwrite)
{
    size_t n = 0;
    char **e, *s;
    if (getenv(name)) {
        if (!overwrite)
            return 0;
        unsetenv(name);
    }
    if (environ)
        for (e = environ; *e; e++)
            n++;
    if (!env_own) {
        char **ne = malloc((n + 2) * sizeof *ne);
        if (!ne)
            return -1;
        if (n)
            memcpy(ne, environ, n * sizeof *ne);
        environ = ne;
        env_own = 1;
    } else {
        char **ne = realloc(environ, (n + 2) * sizeof *ne);
        if (!ne)
            return -1;
        environ = ne;
    }
    s = malloc(strlen(name) + strlen(value) + 2);
    if (!s)
        return -1;
    strcpy(s, name);
    strcat(s, "=");
    strcat(s, value);
    environ[n] = s;
    environ[n + 1] = 0;
    return 0;
}

int system(const char *cmd)
{
    char *argv[4];
    int pid, status;
    argv[0] = "sh";
    argv[1] = "-c";
    argv[2] = (char *)cmd;
    argv[3] = 0;
    pid = spawn("/bin/sh", argv, environ, 0, 0);
    if (pid < 0)
        return -1;
    if (waitpid(pid, &status, 0) < 0)
        return -1;
    return status;
}

/* ---- rand: the C standard's example generator ---- */

static unsigned long next_rand = 1;

int rand(void)
{
    next_rand = next_rand * 1103515245 + 12345;
    return (unsigned)(next_rand >> 16) & 32767;
}

void srand(unsigned seed) { next_rand = seed; }

/* ---- qsort: shell sort (no recursion, no extra memory) ---- */

static void swap_bytes(char *a, char *b, size_t size)
{
    while (size--) {
        char t = *a;
        *a++ = *b;
        *b++ = t;
    }
}

void qsort(void *base, size_t n, size_t size, int (*cmp)(const void *, const void *))
{
    char *a = base;
    size_t gap, i, j;
    for (gap = n / 2; gap > 0; gap /= 2)
        for (i = gap; i < n; i++)
            for (j = i; j >= gap && cmp(a + (j - gap) * size, a + j * size) > 0; j -= gap)
                swap_bytes(a + (j - gap) * size, a + j * size, size);
}

void *bsearch(const void *key, const void *base, size_t n, size_t size,
              int (*cmp)(const void *, const void *))
{
    const char *a = base;
    size_t lo = 0, hi = n;
    while (lo < hi) {
        size_t mid = (lo + hi) / 2;
        int c = cmp(key, a + mid * size);
        if (c == 0)
            return (void *)(a + mid * size);
        if (c < 0)
            hi = mid;
        else
            lo = mid + 1;
    }
    return 0;
}
