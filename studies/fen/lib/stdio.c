/* Standard I/O: FILEs buffered over descriptors. stdout is line-buffered
 * when it's a console, stderr unbuffered. The formatter is the compiler's
 * library's (studies/c_compiler/cc/lib/stdio.c), writing to a FILE or a
 * string. */

#include <errno.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <fen/fs.h>

static unsigned char inbuf[BUFSIZ], outbuf[BUFSIZ];
static FILE files[FOPEN_MAX] = {
    {0, _F_READ, inbuf, BUFSIZ, 0, 0, -1},
    {1, _F_WRITE, outbuf, BUFSIZ, 0, 0, -1},
    {2, _F_WRITE | _F_UNBUF, 0, 0, 0, 0, -1},
};
FILE *stdin = &files[0], *stdout = &files[1], *stderr = &files[2];

/* lib/start.c: stdout line-buffered on a console */
void __stdio_init(void)
{
    if (isatty(1))
        stdout->flags |= _F_LINE;
}

static int flush_out(FILE *f)
{
    int done = 0;
    while (done < f->pos) {
        int n = write(f->fd, f->buf + done, f->pos - done);
        if (n <= 0) {
            f->flags |= _F_ERR;
            f->pos = 0;
            return EOF;
        }
        done += n;
    }
    f->pos = 0;
    return 0;
}

int fflush(FILE *f)
{
    int i, r = 0;
    if (!f) {
        for (i = 0; i < FOPEN_MAX; i++)
            if (files[i].flags & _F_WRITE)
                r |= fflush(&files[i]);
        return r;
    }
    if ((f->flags & _F_WRITE) && f->pos)
        return flush_out(f);
    return 0;
}

void __stdio_exit(void)
{
    fflush(0);
}

int fputc(int c, FILE *f)
{
    unsigned char ch = c;
    if (!(f->flags & _F_WRITE))
        return EOF;
    if (f->flags & _F_UNBUF || !f->buf) {
        if (write(f->fd, &ch, 1) != 1) {
            f->flags |= _F_ERR;
            return EOF;
        }
        return ch;
    }
    f->buf[f->pos++] = ch;
    if (f->pos == f->size || (ch == '\n' && (f->flags & _F_LINE)))
        if (flush_out(f) < 0)
            return EOF;
    return ch;
}

int putc(int c, FILE *f)
{
    return fputc(c, f);
}

int putchar(int c)
{
    return fputc(c, stdout);
}

size_t fwrite(const void *buf, size_t size, size_t n, FILE *f)
{
    const unsigned char *p = buf;
    size_t total = size * n, i;
    if (!(f->flags & _F_WRITE) || !total)
        return 0;
    if (f->flags & _F_UNBUF || !f->buf || total > (size_t)f->size) {
        if (fflush(f) < 0)
            return 0;
        i = 0;
        while (i < total) {
            int k = write(f->fd, p + i, total - i);
            if (k <= 0) {
                f->flags |= _F_ERR;
                break;
            }
            i += k;
        }
        return i / size;
    }
    for (i = 0; i < total; i++)
        if (fputc(p[i], f) == EOF)
            break;
    return i / size;
}

int fputs(const char *s, FILE *f)
{
    size_t n = strlen(s);
    return fwrite(s, 1, n, f) == n ? 0 : EOF;
}

int puts(const char *s)
{
    if (fputs(s, stdout) == EOF)
        return EOF;
    return fputc('\n', stdout) == EOF ? EOF : 0;
}

static int fill(FILE *f)
{
    int n;
    if (f == stdin)
        fflush(stdout);
    n = read(f->fd, f->buf, f->size);
    if (n <= 0) {
        f->flags |= n == 0 ? _F_EOF : _F_ERR;
        return EOF;
    }
    f->pos = 0;
    f->len = n;
    return 0;
}

int fgetc(FILE *f)
{
    if (!(f->flags & _F_READ))
        return EOF;
    if (f->unget >= 0) {
        int c = f->unget;
        f->unget = -1;
        return c;
    }
    if (f->pos >= f->len && fill(f) < 0)
        return EOF;
    return f->buf[f->pos++];
}

int getc(FILE *f)
{
    return fgetc(f);
}

int getchar(void)
{
    return fgetc(stdin);
}

int ungetc(int c, FILE *f)
{
    if (c == EOF)
        return EOF;
    f->unget = c & 0xFF;
    f->flags &= ~_F_EOF;
    return c;
}

char *fgets(char *buf, int size, FILE *f)
{
    int i = 0;
    while (i < size - 1) {
        int c = fgetc(f);
        if (c == EOF)
            break;
        buf[i++] = c;
        if (c == '\n')
            break;
    }
    if (i == 0)
        return 0;
    buf[i] = 0;
    return buf;
}

size_t fread(void *buf, size_t size, size_t n, FILE *f)
{
    unsigned char *p = buf;
    size_t total = size * n, i = 0;
    if (!(f->flags & _F_READ))
        return 0;
    if (f->unget >= 0 && total) {
        p[i++] = f->unget;
        f->unget = -1;
    }
    while (i < total) {
        int k;
        if (f->pos < f->len) {
            k = f->len - f->pos;
            if (k > (int)(total - i))
                k = total - i;
            memcpy(p + i, f->buf + f->pos, k);
            f->pos += k;
            i += k;
            continue;
        }
        if (total - i >= (size_t)f->size) {
            k = read(f->fd, p + i, total - i);
            if (k <= 0) {
                f->flags |= k == 0 ? _F_EOF : _F_ERR;
                break;
            }
            i += k;
            continue;
        }
        if (fill(f) < 0)
            break;
    }
    return i / size;
}

FILE *fdopen(int fd, const char *mode)
{
    int i;
    for (i = 3; i < FOPEN_MAX; i++) {
        FILE *f = &files[i];
        if (!f->flags) {
            f->fd = fd;
            f->flags = mode[0] == 'r' && mode[1] != '+' ? _F_READ
                     : mode[0] == 'r' ? _F_READ | _F_WRITE : _F_WRITE;
            if (strchr(mode, '+'))
                f->flags |= _F_READ | _F_WRITE;
            f->buf = malloc(BUFSIZ);
            f->size = BUFSIZ;
            f->pos = f->len = 0;
            f->unget = -1;
            if (!f->buf)
                f->flags |= _F_UNBUF;
            else
                f->flags |= _F_MYBUF;
            return f;
        }
    }
    errno = EMFILE;
    return 0;
}

FILE *fopen(const char *path, const char *mode)
{
    int flags, fd;
    FILE *f;
    switch (mode[0]) {
    case 'r': flags = O_RDONLY; break;
    case 'w': flags = O_WRONLY | O_CREAT | O_TRUNC; break;
    case 'a': flags = O_WRONLY | O_CREAT | O_APPEND; break;
    default:
        errno = EINVAL;
        return 0;
    }
    if (strchr(mode, '+'))
        flags = (flags & ~O_ACCMODE) | O_RDWR;
    fd = open(path, flags, 0644);
    if (fd < 0)
        return 0;
    f = fdopen(fd, mode);
    if (!f)
        close(fd);
    return f;
}

int fclose(FILE *f)
{
    int r = fflush(f);
    if (close(f->fd) < 0)
        r = EOF;
    if (f->flags & _F_MYBUF)
        free(f->buf);
    if (f >= &files[3])
        f->flags = 0;
    else
        f->flags &= _F_READ | _F_WRITE | _F_UNBUF | _F_LINE;
    return r;
}

int fseek(FILE *f, long off, int whence)
{
    if (fflush(f) < 0)
        return -1;
    if (whence == SEEK_CUR && (f->flags & _F_READ))
        off -= f->len - f->pos;
    f->pos = f->len = 0;
    f->unget = -1;
    f->flags &= ~_F_EOF;
    return lseek(f->fd, off, whence) < 0 ? -1 : 0;
}

long ftell(FILE *f)
{
    long p = lseek(f->fd, 0, SEEK_CUR);
    if (p < 0)
        return -1;
    if (f->flags & _F_WRITE)
        return p + f->pos;
    return p - (f->len - f->pos);
}

void rewind(FILE *f)
{
    fseek(f, 0, SEEK_SET);
    f->flags &= ~_F_ERR;
}

int feof(FILE *f) { return (f->flags & _F_EOF) != 0; }
int ferror(FILE *f) { return (f->flags & _F_ERR) != 0; }
void clearerr(FILE *f) { f->flags &= ~(_F_EOF | _F_ERR); }
int fileno(FILE *f) { return f->fd; }

int setvbuf(FILE *f, char *buf, int mode, size_t size)
{
    f->flags &= ~(_F_LINE | _F_UNBUF);
    if (mode == _IONBF)
        f->flags |= _F_UNBUF;
    else if (mode == _IOLBF)
        f->flags |= _F_LINE;
    if (buf && size) {
        if (f->flags & _F_MYBUF)
            free(f->buf);
        f->flags &= ~_F_MYBUF;
        f->buf = (unsigned char *)buf;
        f->size = size;
    }
    return 0;
}

void setbuf(FILE *f, char *buf)
{
    setvbuf(f, buf, buf ? _IOFBF : _IONBF, BUFSIZ);
}

/* ---- printf ---- */

/* The formatter writes to a FILE, or into a buffer with room for `room`
 * bytes including the final NUL. */
#define OUT(ch) do { int c_ = (ch); n++; if (f) fputc(c_, f); \
                     else if (room > 1) { *buf++ = c_; room--; } } while (0)

static int format(FILE *f, char **bufp, size_t room, const char *fmt, va_list ap)
{
    char *buf = bufp ? *bufp : 0;
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
    if (bufp)
        *bufp = buf;
    return n;
}

int vfprintf(FILE *f, const char *fmt, va_list ap)
{
    return format(f, 0, 0, fmt, ap);
}

int vprintf(const char *fmt, va_list ap)
{
    return format(stdout, 0, 0, fmt, ap);
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
    int n;
    va_start(ap, fmt);
    n = vfprintf(f, fmt, ap);
    return n;
}

int vsnprintf(char *buf, size_t size, const char *fmt, va_list ap)
{
    char *end = buf;
    int n = format(0, &end, size, fmt, ap);
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

int dprintf(int fd, const char *fmt, ...)
{
    char buf[256];
    va_list ap;
    int n;
    va_start(ap, fmt);
    n = vsnprintf(buf, sizeof buf, fmt, ap);
    write(fd, buf, n < (int)sizeof buf ? n : (int)sizeof buf - 1);
    return n;
}

void perror(const char *s)
{
    if (s && *s)
        fprintf(stderr, "%s: %s\n", s, strerror(errno));
    else
        fprintf(stderr, "%s\n", strerror(errno));
}

/* sscanf: %d %u %x %s %c and literal text, enough for the programs */
int sscanf(const char *s, const char *fmt, ...)
{
    va_list ap;
    int n = 0;
    va_start(ap, fmt);
    while (*fmt) {
        if (*fmt == ' ') {
            while (*s == ' ' || *s == '\t' || *s == '\n')
                s++;
            fmt++;
            continue;
        }
        if (*fmt != '%') {
            if (*s != *fmt)
                break;
            s++;
            fmt++;
            continue;
        }
        fmt++;
        if (*fmt == 'd' || *fmt == 'u' || *fmt == 'x') {
            char *end;
            long v;
            while (*s == ' ' || *s == '\t')
                s++;
            v = strtol(s, &end, *fmt == 'x' ? 16 : 10);
            if (end == s)
                break;
            *va_arg(ap, int *) = v;
            s = end;
            n++;
        } else if (*fmt == 's') {
            char *d = va_arg(ap, char *);
            while (*s == ' ' || *s == '\t')
                s++;
            if (!*s)
                break;
            while (*s && *s != ' ' && *s != '\t' && *s != '\n')
                *d++ = *s++;
            *d = 0;
            n++;
        } else if (*fmt == 'c') {
            if (!*s)
                break;
            *va_arg(ap, char *) = *s++;
            n++;
        } else
            break;
        fmt++;
    }
    va_end(ap);
    return n;
}
