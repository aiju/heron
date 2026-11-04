/* The driver: an archive of compressed files, as the harness links it
   in, each inflated and checked as its container says, and some plain
   files put through the compressor and back.

   The archive is a list of entries: a kind ('z' zlib, 'g' gzip, 'p'
   PNG, 'r' a file for the round trip), the length of the name and the
   name, the length of the file (4 bytes, little-endian) and the file. */

#include "bench.h"
#include "inflate.h"

extern const unsigned char archive[];
extern unsigned archive_len;

static unsigned char zbuf[24 * 1024];   /* the round trip's compressed stream */
static unsigned char back[24 * 1024];   /* and what it inflates to */

int main(void)
{
    unsigned pos = 0, in = 0;
    int files = 0, errors = 0;
    while (pos + 6 <= archive_len) {
        int kind = archive[pos], k, err;
        unsigned namelen = archive[pos + 1], size;
        const unsigned char *data;
        char name[32];
        for (k = 0; k < (int)namelen && k < 31; k++)
            name[k] = (char)archive[pos + 2 + k];
        name[k] = 0;
        pos += 2 + namelen;
        size = get32le(archive + pos);
        data = archive + pos + 4;
        pos += 4 + size;
        if (pos > archive_len)
            break;
        switch (kind) {
        case 'z': err = zlib_file(name, data, size); break;
        case 'g': err = gzip_file(name, data, size); break;
        case 'p': err = png_file(name, data, size); break;
        case 'r': err = round_trip(name, data, size, zbuf, sizeof zbuf, back, sizeof back); break;
        default:  err = Z_BAD_HEADER;
        }
        files++;
        in += size;
        if (err)
            errors++;
    }
    bench_report("files", files);
    bench_report("bytes", in);
    bench_report("errors", errors);
    return 0;
}
