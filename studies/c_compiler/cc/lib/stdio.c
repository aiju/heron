/* Console I/O and printf for the C library. */

#include <stdio.h>
#include <heron.h>

struct __file { int fd; };
static FILE f_in = {0}, f_out = {1}, f_err = {2};
FILE *stdin = &f_in, *stdout = &f_out, *stderr = &f_err;

int putchar(int c)
{
    HERON_CONSOLE = c;
    return c & 255;
}

int getchar(void)
{
    return (int)HERON_CONSOLE;        /* -1 at the end of input */
}

int fputc(int c, FILE *f) { return putchar(c); }
int putc(int c, FILE *f) { return putchar(c); }
int fgetc(FILE *f) { return getchar(); }
int getc(FILE *f) { return getchar(); }

int fputs(const char *s, FILE *f)
{
    int c;
    while ((c = *s++) != 0)
        HERON_CONSOLE = c;
    return 0;
}

int puts(const char *s)
{
    fputs(s, stdout);
    HERON_CONSOLE = '\n';
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

/* The formatter writes either to the console (buf == 0) or into a buffer
   with room for `room` bytes including the final NUL. The output state is
   kept in locals so it lives in registers. */

#define OUT(ch) do { int c_ = (ch); n++; if (buf == 0) HERON_CONSOLE = c_; \
                     else if (room > 1) { *buf++ = c_; room--; } } while (0)

static int format(char **bufp, size_t room, const char *fmt, va_list ap)
{
    char *buf = *bufp;
    char digits[12];
    int n = 0, c;
    while ((c = *fmt++) != 0) {
        int left = 0, zero = 0, plus = 0, space = 0, alt = 0;
        int width = 0, prec = -1;
        int len, neg, base, upper, k;
        unsigned u;
        char *str;
        if (c != '%') {
            OUT(c);
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
            while ((unsigned)(*fmt - '0') < 10)
                width = width * 10 + (*fmt++ - '0');
        }
        if (*fmt == '.') {
            fmt++;
            prec = 0;
            if (*fmt == '*') {
                prec = va_arg(ap, int);
                fmt++;
            } else {
                while ((unsigned)(*fmt - '0') < 10)
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
            for (k = 1; !left && k < width; k++)
                OUT(' ');
            OUT(va_arg(ap, int));
            for (k = 1; left && k < width; k++)
                OUT(' ');
            continue;
        case 's':
            str = va_arg(ap, char *);
            if (str == 0)
                str = "(null)";
            for (len = 0; str[len] && (prec < 0 || len < prec); len++)
                ;
            for (k = len; !left && k < width; k++)
                OUT(' ');
            for (k = 0; k < len; k++)
                OUT(str[k]);
            for (k = len; left && k < width; k++)
                OUT(' ');
            continue;
        case 0:
            fmt--;
            continue;
        default:
            OUT(c);
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
            for (k = total; !left && k < width; k++)
                OUT(' ');
            if (sign)
                OUT(neg ? '-' : (plus ? '+' : ' '));
            if (prefix) {
                OUT('0');
                if (base == 16)
                    OUT(upper ? 'X' : 'x');
            }
            while (zeros-- > 0)
                OUT('0');
            while (len > 0)
                OUT(digits[--len]);
            for (k = total; left && k < width; k++)
                OUT(' ');
        }
    }
    *bufp = buf;
    return n;
}

int vprintf(const char *fmt, va_list ap)
{
    char *none = 0;
    return format(&none, 0, fmt, ap);
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
    char *end = buf;
    int n = format(&end, size, fmt, ap);
    if (size > 0)
        *end = 0;
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
