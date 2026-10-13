/* stdlib for the C library: numbers, a heap, rand, qsort. */

#include <stdlib.h>
#include <stdio.h>
#include <string.h>
#include <ctype.h>

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

/* ---- heap: first fit, address-ordered free list ---- */

extern char _end[];                    /* the end of the program image */
#define HEAP_LIMIT ((char *)0xF0000)   /* leave 64 KB for the stack */

struct block {
    size_t size;                       /* bytes, including this header */
    struct block *next;
};

static struct block *free_list;
static char *brk;

void *malloc(size_t n)
{
    struct block **pp, *b;
    size_t need = (n + sizeof(struct block) + 7) & ~7;
    if (n == 0)
        return 0;
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
    if (brk == 0)
        brk = (char *)(((unsigned)_end + 7) & ~7);
    if (brk + need > HEAP_LIMIT)
        return 0;
    b = (struct block *)brk;
    brk += need;
    b->size = need;
    return b + 1;
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

void __assert_fail(const char *expr, const char *file, int line)
{
    printf("%s:%d: assertion failed: %s\n", file, line, expr);
    abort();
}
