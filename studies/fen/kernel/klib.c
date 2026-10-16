/* The kernel's own little library: memory and string functions, and its
 * messages, which go to the board's debug port and a ring kept for the
 * klog system call (dmesg). */

#include <stdarg.h>
#include "kernel.h"

void *memset(void *p, int c, unsigned n)
{
    unsigned char *d = p;
    u32 w;
    if ((((u32)d) & 3) == 0) {
        w = (c & 0xFF) * 0x01010101u;
        while (n >= 4) {
            *(u32 *)d = w;
            d += 4;
            n -= 4;
        }
    }
    while (n--)
        *d++ = c;
    return p;
}

void *memcpy(void *dst, const void *src, unsigned n)
{
    unsigned char *d = dst;
    const unsigned char *s = src;
    if (((((u32)d) | ((u32)s)) & 3) == 0) {
        while (n >= 4) {
            *(u32 *)d = *(const u32 *)s;
            d += 4;
            s += 4;
            n -= 4;
        }
    }
    while (n--)
        *d++ = *s++;
    return dst;
}

int strcmp(const char *a, const char *b)
{
    while (*a && *a == *b) {
        a++;
        b++;
    }
    return (unsigned char)*a - (unsigned char)*b;
}

int strncmp(const char *a, const char *b, unsigned n)
{
    while (n && *a && *a == *b) {
        a++;
        b++;
        n--;
    }
    return n ? (unsigned char)*a - (unsigned char)*b : 0;
}

unsigned strlen(const char *s)
{
    const char *p = s;
    while (*p)
        p++;
    return p - s;
}

void strlcpy(char *d, const char *s, unsigned n)
{
    if (!n)
        return;
    while (--n && *s)
        *d++ = *s++;
    *d = 0;
}

/* the log: a ring of LOG_SIZE bytes; log_end counts every byte ever
 * written, so a reader can ask for what came after a point */
#define LOG_SIZE 4096
static char log_buf[LOG_SIZE];
static unsigned log_end;

static void kputc(int c)
{
    INFO_DEBUG = c;
    log_buf[log_end % LOG_SIZE] = c;
    log_end++;
}

void kputs(const char *s)
{
    while (*s)
        kputc(*s++);
}

int klog_read(char *buf, unsigned n, unsigned from)
{
    unsigned i = 0;
    if (log_end > LOG_SIZE && from < log_end - LOG_SIZE)
        from = log_end - LOG_SIZE;
    while (from + i < log_end && i < n) {
        buf[i] = log_buf[(from + i) % LOG_SIZE];
        i++;
    }
    return i;
}

static void put_num(u32 v, int base, int width, int zero, int neg)
{
    char tmp[12];
    int i = 0;
    do {
        int d = v % base;
        tmp[i++] = d < 10 ? '0' + d : 'a' + d - 10;
        v /= base;
    } while (v);
    if (neg)
        tmp[i++] = '-';
    while (i < width--)
        kputc(zero ? '0' : ' ');
    while (i)
        kputc(tmp[--i]);
}

static void vkprintf(const char *fmt, va_list ap)
{
    for (; *fmt; fmt++) {
        int width = 0, zero = 0;
        if (*fmt != '%') {
            kputc(*fmt);
            continue;
        }
        fmt++;
        if (*fmt == '0') {
            zero = 1;
            fmt++;
        }
        while (*fmt >= '0' && *fmt <= '9')
            width = width * 10 + *fmt++ - '0';
        switch (*fmt) {
        case 'd': {
            int v = va_arg(ap, int);
            if (v < 0)
                put_num(-(u32)v, 10, width, zero, 1);
            else
                put_num(v, 10, width, zero, 0);
            break;
        }
        case 'u':
            put_num(va_arg(ap, u32), 10, width, zero, 0);
            break;
        case 'x':
            put_num(va_arg(ap, u32), 16, width, zero, 0);
            break;
        case 's': {
            const char *s = va_arg(ap, const char *);
            kputs(s ? s : "(null)");
            break;
        }
        case 'c':
            kputc(va_arg(ap, int));
            break;
        case '%':
            kputc('%');
            break;
        default:
            kputc('%');
            kputc(*fmt);
        }
    }
}

void kprintf(const char *fmt, ...)
{
    va_list ap;
    va_start(ap, fmt);
    vkprintf(fmt, ap);
    va_end(ap);
}

void panic(const char *fmt, ...)
{
    va_list ap;
    kputs("\npanic: ");
    va_start(ap, fmt);
    vkprintf(fmt, ap);
    va_end(ap);
    kputs("\n");
    halt();
}
