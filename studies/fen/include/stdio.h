/* Standard I/O over Fen's descriptors: buffered FILEs, printf and friends. */
#ifndef _STDIO_H
#define _STDIO_H
#include <stddef.h>
#include <stdarg.h>

#define EOF (-1)
#define BUFSIZ 1024
#define FOPEN_MAX 16
#ifndef SEEK_SET
#define SEEK_SET 0
#define SEEK_CUR 1
#define SEEK_END 2
#endif

typedef struct __file {
    int fd;
    int flags;          /* _F_READ, _F_WRITE, _F_EOF, _F_ERR, _F_LINE, _F_UNBUF */
    unsigned char *buf;
    int size;           /* the buffer's size */
    int pos;            /* reading: the next byte; writing: bytes waiting */
    int len;            /* reading: bytes in the buffer */
    int unget;          /* a byte pushed back, or -1 */
} FILE;

#define _F_READ 1
#define _F_WRITE 2
#define _F_EOF 4
#define _F_ERR 8
#define _F_LINE 16
#define _F_UNBUF 32
#define _F_MYBUF 64

extern FILE *stdin, *stdout, *stderr;

FILE *fopen(const char *path, const char *mode);
FILE *fdopen(int fd, const char *mode);
int fclose(FILE *f);
int fflush(FILE *f);
size_t fread(void *buf, size_t size, size_t n, FILE *f);
size_t fwrite(const void *buf, size_t size, size_t n, FILE *f);
int fgetc(FILE *f);
int getc(FILE *f);
int getchar(void);
int ungetc(int c, FILE *f);
char *fgets(char *buf, int size, FILE *f);
int fputc(int c, FILE *f);
int putc(int c, FILE *f);
int putchar(int c);
int fputs(const char *s, FILE *f);
int puts(const char *s);
int fseek(FILE *f, long off, int whence);
long ftell(FILE *f);
void rewind(FILE *f);
int feof(FILE *f);
int ferror(FILE *f);
void clearerr(FILE *f);
int fileno(FILE *f);
void setbuf(FILE *f, char *buf);
int setvbuf(FILE *f, char *buf, int mode, size_t size);
#define _IOFBF 0
#define _IOLBF 1
#define _IONBF 2

int printf(const char *fmt, ...);
int fprintf(FILE *f, const char *fmt, ...);
int dprintf(int fd, const char *fmt, ...);
int sprintf(char *buf, const char *fmt, ...);
int snprintf(char *buf, size_t size, const char *fmt, ...);
int vprintf(const char *fmt, va_list ap);
int vfprintf(FILE *f, const char *fmt, va_list ap);
int vsprintf(char *buf, const char *fmt, va_list ap);
int vsnprintf(char *buf, size_t size, const char *fmt, va_list ap);
int sscanf(const char *s, const char *fmt, ...);
void perror(const char *s);
int remove(const char *path);
int rename(const char *from, const char *to);
#endif
