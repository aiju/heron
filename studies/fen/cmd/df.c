/* df: the file system's space */
#include <stdio.h>
#include <sys/stat.h>
int main(void)
{
    struct statfs s;
    if (statfs("/", &s) < 0) {
        perror("df");
        return 1;
    }
    printf("     KB    used    free  files free\n");
    printf("%7u %7u %7u %6u %4u  /\n", s.f_blocks * s.f_bsize / 1024,
           (s.f_blocks - s.f_bfree) * s.f_bsize / 1024, s.f_bfree * s.f_bsize / 1024,
           s.f_files, s.f_ffree);
    return 0;
}
