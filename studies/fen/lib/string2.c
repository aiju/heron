/* The string functions the compiler's library hasn't got. */

#include <ctype.h>
#include <stdlib.h>
#include <string.h>
#include <fen/abi.h>

size_t strnlen(const char *s, size_t n)
{
    size_t i = 0;
    while (i < n && s[i])
        i++;
    return i;
}

size_t strlcpy(char *d, const char *s, size_t n)
{
    size_t k = strlen(s);
    if (n) {
        size_t c = k < n - 1 ? k : n - 1;
        memcpy(d, s, c);
        d[c] = 0;
    }
    return k;
}

size_t strlcat(char *d, const char *s, size_t n)
{
    size_t k = strnlen(d, n);
    if (k == n)
        return k + strlen(s);
    return k + strlcpy(d + k, s, n - k);
}

int strcasecmp(const char *a, const char *b)
{
    while (*a && tolower((unsigned char)*a) == tolower((unsigned char)*b)) {
        a++;
        b++;
    }
    return tolower((unsigned char)*a) - tolower((unsigned char)*b);
}

int strncasecmp(const char *a, const char *b, size_t n)
{
    while (n && *a && tolower((unsigned char)*a) == tolower((unsigned char)*b)) {
        a++;
        b++;
        n--;
    }
    return n ? tolower((unsigned char)*a) - tolower((unsigned char)*b) : 0;
}

char *strpbrk(const char *s, const char *accept)
{
    s += strcspn(s, accept);
    return *s ? (char *)s : 0;
}

char *strtok_r(char *s, const char *delim, char **save)
{
    char *end;
    if (!s)
        s = *save;
    s += strspn(s, delim);
    if (!*s) {
        *save = s;
        return 0;
    }
    end = s + strcspn(s, delim);
    if (*end)
        *end++ = 0;
    *save = end;
    return s;
}

char *strtok(char *s, const char *delim)
{
    static char *save;
    return strtok_r(s, delim, &save);
}

char *strdup(const char *s)
{
    size_t n = strlen(s) + 1;
    char *d = malloc(n);
    if (d)
        memcpy(d, s, n);
    return d;
}

char *strndup(const char *s, size_t n)
{
    size_t k = strnlen(s, n);
    char *d = malloc(k + 1);
    if (d) {
        memcpy(d, s, k);
        d[k] = 0;
    }
    return d;
}

char *strerror(int e)
{
    static char other[24];
    switch (e) {
    case 0: return "no error";
    case EPERM: return "not permitted";
    case ENOENT: return "no such file or directory";
    case ESRCH: return "no such process";
    case EINTR: return "interrupted";
    case EIO: return "I/O error";
    case E2BIG: return "argument list too long";
    case ENOEXEC: return "not an executable";
    case EBADF: return "bad descriptor";
    case ECHILD: return "no child processes";
    case EAGAIN: return "try again";
    case ENOMEM: return "out of memory";
    case EACCES: return "permission denied";
    case EFAULT: return "bad address";
    case EBUSY: return "busy";
    case EEXIST: return "file exists";
    case EXDEV: return "not on the same server";
    case ENODEV: return "no such device";
    case ENOTDIR: return "not a directory";
    case EISDIR: return "is a directory";
    case EINVAL: return "invalid argument";
    case ENFILE: return "too many open files in the system";
    case EMFILE: return "too many open files";
    case ENOTTY: return "not a console";
    case EFBIG: return "file too big";
    case ENOSPC: return "no space left";
    case ESPIPE: return "can't seek";
    case EROFS: return "read-only file system";
    case EPIPE: return "broken pipe";
    case ERANGE: return "out of range";
    case ENAMETOOLONG: return "name too long";
    case ENOSYS: return "not implemented";
    case ENOTEMPTY: return "directory not empty";
    case ENOTSUP: return "not supported";
    }
    {
        extern int snprintf(char *, size_t, const char *, ...);
        snprintf(other, sizeof other, "error %d", e);
    }
    return other;
}
