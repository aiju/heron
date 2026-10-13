#ifndef _STDIO_H
#define _STDIO_H
#include <stddef.h>
#include <stdarg.h>
/* Console I/O only: stdout and stdin are the console. */
#define EOF (-1)
typedef struct __file FILE;
extern FILE *stdin, *stdout, *stderr;
int putchar(int c);
int getchar(void);
int puts(const char *s);
int fputs(const char *s, FILE *f);
int fputc(int c, FILE *f);
int putc(int c, FILE *f);
int fgetc(FILE *f);
int getc(FILE *f);
char *fgets(char *buf, int size, FILE *f);
int printf(const char *fmt, ...);
int fprintf(FILE *f, const char *fmt, ...);
int sprintf(char *buf, const char *fmt, ...);
int snprintf(char *buf, size_t size, const char *fmt, ...);
int vprintf(const char *fmt, va_list ap);
int vsprintf(char *buf, const char *fmt, va_list ap);
int vsnprintf(char *buf, size_t size, const char *fmt, va_list ap);
#endif
