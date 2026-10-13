/* String and memory functions for the C library. */

#include <string.h>

void *memcpy(void *dst, const void *src, size_t n)
{
    char *d = dst;
    const char *s = src;
    if ((((unsigned)d | (unsigned)s) & 3) == 0) {
        while (n >= 4) {
            *(unsigned *)d = *(const unsigned *)s;
            d += 4;
            s += 4;
            n -= 4;
        }
    }
    while (n--)
        *d++ = *s++;
    return dst;
}

void *memmove(void *dst, const void *src, size_t n)
{
    char *d = dst;
    const char *s = src;
    if (d <= s || d >= s + n)
        return memcpy(dst, src, n);
    d += n;
    s += n;
    while (n--)
        *--d = *--s;
    return dst;
}

void *memset(void *dst, int c, size_t n)
{
    unsigned char *d = dst;
    if (((unsigned)d & 3) == 0 && n >= 4) {
        unsigned w = (unsigned char)c;
        w |= w << 8;
        w |= w << 16;
        while (n >= 4) {
            *(unsigned *)d = w;
            d += 4;
            n -= 4;
        }
    }
    while (n--)
        *d++ = c;
    return dst;
}

int memcmp(const void *a, const void *b, size_t n)
{
    const unsigned char *p = a, *q = b;
    while (n--) {
        int d = *p++ - *q++;
        if (d)
            return d;
    }
    return 0;
}

void *memchr(const void *s, int c, size_t n)
{
    const unsigned char *p = s;
    c = (unsigned char)c;
    while (n--) {
        if (*p == c)
            return (void *)p;
        p++;
    }
    return 0;
}

size_t strlen(const char *s)
{
    const char *p = s;
    while (*p)
        p++;
    return p - s;
}

char *strcpy(char *dst, const char *src)
{
    char *d = dst;
    while ((*d++ = *src++) != 0)
        ;
    return dst;
}

char *strncpy(char *dst, const char *src, size_t n)
{
    char *d = dst;
    while (n && (*d = *src++) != 0) {
        d++;
        n--;
    }
    while (n--)
        *d++ = 0;
    return dst;
}

char *strcat(char *dst, const char *src)
{
    strcpy(dst + strlen(dst), src);
    return dst;
}

char *strncat(char *dst, const char *src, size_t n)
{
    char *d = dst + strlen(dst);
    while (n-- && *src)
        *d++ = *src++;
    *d = 0;
    return dst;
}

int strcmp(const char *a, const char *b)
{
    int c;
    while ((c = *a++) == *b++)
        if (c == 0)
            return 0;
    return c - b[-1];
}

int strncmp(const char *a, const char *b, size_t n)
{
    while (n--) {
        int c = *a++;
        int d = c - *b++;
        if (d)
            return d;
        if (c == 0)
            return 0;
    }
    return 0;
}

char *strchr(const char *s, int c)
{
    c = (char)c;
    for (;; s++) {
        if (*s == c)
            return (char *)s;
        if (*s == 0)
            return 0;
    }
}

char *strrchr(const char *s, int c)
{
    const char *r = 0;
    c = (char)c;
    for (;; s++) {
        if (*s == c)
            r = s;
        if (*s == 0)
            return (char *)r;
    }
}

char *strstr(const char *h, const char *n)
{
    size_t len = strlen(n);
    if (len == 0)
        return (char *)h;
    for (; *h; h++)
        if (*h == *n && strncmp(h, n, len) == 0)
            return (char *)h;
    return 0;
}

size_t strspn(const char *s, const char *accept)
{
    const char *p = s;
    while (*p && strchr(accept, *p))
        p++;
    return p - s;
}

size_t strcspn(const char *s, const char *reject)
{
    const char *p = s;
    while (*p && !strchr(reject, *p))
        p++;
    return p - s;
}
