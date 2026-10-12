/* Console I/O and printf for the tmc C library. */

#include <stdio.h>
#include <tmc.h>

struct __file { int fd; };
static FILE f_in = {0}, f_out = {1}, f_err = {2};
FILE *stdin = &f_in, *stdout = &f_out, *stderr = &f_err;

int putchar(int c)
{
    TMC_CONSOLE = c;
    return c & 255;
}

int getchar(void)
{
    return (int)TMC_CONSOLE;        /* -1 at the end of input */
}

int fputc(int c, FILE *f) { return putchar(c); }
int putc(int c, FILE *f) { return putchar(c); }
int fgetc(FILE *f) { return getchar(); }
int getc(FILE *f) { return getchar(); }

int fputs(const char *s, FILE *f)
{
    int c;
    while ((c = *s++) != 0)
        TMC_CONSOLE = c;
    return 0;
}

int puts(const char *s)
{
    fputs(s, stdout);
    TMC_CONSOLE = '\n';
    return 0;
}

char *fgets(char *buf, int size, FILE *f)
{
    char *p = buf;
    int c;
    if (size <= 0)
        return 0;
    while (--size > 0) {
        c = getchar();
        if (c < 0) {
            if (p == buf)
                return 0;
            break;
        }
        *p++ = c;
        if (c == '\n')
            break;
    }
    *p = 0;
    return buf;
}

/* ---- printf ---- */

struct sink {
    char *buf;          /* 0: the console */
    size_t room;        /* bytes left in buf, including the final NUL */
    int n;              /* characters produced */
};

static void out(struct sink *s, int c)
{
    s->n++;
    if (s->buf == 0) {
        TMC_CONSOLE = c;
    } else if (s->room > 1) {
        *s->buf++ = c;
        s->room--;
    }
}

static void pad(struct sink *s, int c, int n)
{
    while (n-- > 0)
        out(s, c);
}

static int format(struct sink *s, const char *fmt, va_list ap)
{
    char digits[12];
    int c;
    while ((c = *fmt++) != 0) {
        int left = 0, zero = 0, plus = 0, space = 0, alt = 0;
        int width = 0, prec = -1;
        int len, neg, base, upper;
        unsigned u;
        char *str;
        if (c != '%') {
            out(s, c);
            continue;
        }
        for (;;) {
            c = *fmt;
            if (c == '-') left = 1;
            else if (c == '0') zero = 1;
            else if (c == '+') plus = 1;
            else if (c == ' ') space = 1;
            else if (c == '#') alt = 1;
            else break;
            fmt++;
        }
        if (*fmt == '*') {
            width = va_arg(ap, int);
            if (width < 0) {
                left = 1;
                width = -width;
            }
            fmt++;
        } else {
            while (*fmt >= '0' && *fmt <= '9')
                width = width * 10 + (*fmt++ - '0');
        }
        if (*fmt == '.') {
            fmt++;
            prec = 0;
            if (*fmt == '*') {
                prec = va_arg(ap, int);
                fmt++;
            } else {
                while (*fmt >= '0' && *fmt <= '9')
                    prec = prec * 10 + (*fmt++ - '0');
            }
        }
        while (*fmt == 'l' || *fmt == 'h' || *fmt == 'z')
            fmt++;
        c = *fmt++;
        neg = 0;
        upper = 0;
        switch (c) {
        case 'd':
        case 'i': {
            int v = va_arg(ap, int);
            if (v < 0) {
                neg = 1;
                u = -(unsigned)v;
            } else {
                u = v;
            }
            base = 10;
            break;
        }
        case 'u':
            u = va_arg(ap, unsigned);
            base = 10;
            break;
        case 'X':
            upper = 1;
        case 'x':
            u = va_arg(ap, unsigned);
            base = 16;
            break;
        case 'p':
            u = (unsigned)va_arg(ap, void *);
            base = 16;
            alt = 1;
            break;
        case 'o':
            u = va_arg(ap, unsigned);
            base = 8;
            break;
        case 'c':
            pad(s, ' ', left ? 0 : width - 1);
            out(s, va_arg(ap, int));
            pad(s, ' ', left ? width - 1 : 0);
            continue;
        case 's':
            str = va_arg(ap, char *);
            if (str == 0)
                str = "(null)";
            for (len = 0; str[len] && (prec < 0 || len < prec); len++)
                ;
            if (!left)
                pad(s, ' ', width - len);
            for (base = 0; base < len; base++)
                out(s, str[base]);
            if (left)
                pad(s, ' ', width - len);
            continue;
        case 0:
            fmt--;
            continue;
        default:
            out(s, c);
            continue;
        }
        /* digits, least significant first */
        len = 0;
        do {
            unsigned d = u % base;
            digits[len++] = d < 10 ? '0' + d : (upper ? 'A' : 'a') + d - 10;
            u /= base;
        } while (u);
        {
            int sign = neg || plus || space;
            int prefix = alt && base == 16 ? 2 : (alt && base == 8 && digits[len - 1] != '0');
            int zeros = prec > len ? prec - len : 0;
            int total = sign + prefix + zeros + len;
            if (zero && !left && prec < 0 && width > total) {
                zeros += width - total;
                total = width;
            }
            if (!left)
                pad(s, ' ', width - total);
            if (sign)
                out(s, neg ? '-' : (plus ? '+' : ' '));
            if (prefix) {
                out(s, '0');
                if (base == 16)
                    out(s, upper ? 'X' : 'x');
            }
            pad(s, '0', zeros);
            while (len > 0)
                out(s, digits[--len]);
            if (left)
                pad(s, ' ', width - total);
        }
    }
    return s->n;
}

int vprintf(const char *fmt, va_list ap)
{
    struct sink s;
    s.buf = 0;
    s.room = 0;
    s.n = 0;
    return format(&s, fmt, ap);
}

int printf(const char *fmt, ...)
{
    va_list ap;
    va_start(ap, fmt);
    return vprintf(fmt, ap);
}

int fprintf(FILE *f, const char *fmt, ...)
{
    va_list ap;
    va_start(ap, fmt);
    return vprintf(fmt, ap);
}

int vsnprintf(char *buf, size_t size, const char *fmt, va_list ap)
{
    struct sink s;
    int n;
    s.buf = buf;
    s.room = size;
    s.n = 0;
    n = format(&s, fmt, ap);
    if (size > 0)
        *s.buf = 0;
    return n;
}

int vsprintf(char *buf, const char *fmt, va_list ap)
{
    return vsnprintf(buf, 0x7fffffff, fmt, ap);
}

int sprintf(char *buf, const char *fmt, ...)
{
    va_list ap;
    va_start(ap, fmt);
    return vsnprintf(buf, 0x7fffffff, fmt, ap);
}

int snprintf(char *buf, size_t size, const char *fmt, ...)
{
    va_list ap;
    va_start(ap, fmt);
    return vsnprintf(buf, size, fmt, ap);
}
