/* The console for cc65's library: draft 1's I/O page through the page
   map, at 0xE000 (data) and 0xE002 (status, bit 0: a byte is waiting). */
#define CONSOLE (*(volatile unsigned char *)0xE000)
#define STATUS  (*(volatile unsigned char *)0xE002)

int write(int fd, const void *buf, unsigned count)
{
    const unsigned char *p = buf;
    unsigned n = count;
    (void)fd;
    while (n--)
        CONSOLE = *p++;
    return count;
}

int read(int fd, void *buf, unsigned count)
{
    unsigned char *p = buf;
    unsigned n = 0;
    (void)fd;
    while (n < count && (STATUS & 1)) {
        p[n] = CONSOLE;
        if (p[n++] == '\n')
            break;
    }
    return n;
}
