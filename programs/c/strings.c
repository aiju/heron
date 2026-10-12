/* strings: exercises the string library (strlen, strcpy, strcmp, memcpy,
   memset, memmove), then reverses a string in place, converts one to upper
   case and counts the words in a paragraph. */
#include <stdio.h>
#include <string.h>

static const char alpha[] = "0123456789abcdefghijklmnopqrstuvwxyz";
static const char hello[] = "Hello, world!";
static const char fox[] = "The quick brown fox jumps over the lazy dog.";
static const char paragraph[] =
    "  It was the best of times, it was the worst of times,\n"
    "\tit was the age of wisdom,  it was the age of foolishness,\n"
    "it was the epoch of belief, it was the epoch of incredulity, \n"
    "it was the season of Light, it was the season of Darkness...\n\n";

static int sign(int x) { return x; }

int main(void)
{
    static const char *const strs[] = {"", "x", hello, fox};
    static const char *const pairs[][2] = {
        {"abc", "abc"}, {"abc", "abd"}, {"abd", "abc"}, {"ab", "abc"},
        {"abc", "ab"}, {"", ""}, {"Zebra", "apple"}, {"\xe9t\xe9", "abc"},
    };
    static const int copies[][3] = {{0, 0, 11}, {3, 5, 9}, {4, 1, 7}, {2, 2, 20}, {5, 7, 1}};
    char buf[64], *p, *q;
    int i, words, inword;
    for (i = 0; i < 4; i++)
        printf("strlen(\"%s\") = %d\n", strs[i], (int)strlen(strs[i]));
    strcpy(buf, "copy me");
    printf("strcpy -> \"%s\"\n", buf);
    for (i = 0; i < 8; i++)
        printf("strcmp(\"%s\", \"%s\") = %d\n", pairs[i][0], pairs[i][1],
               sign(strcmp(pairs[i][0], pairs[i][1])));
    for (i = 0; i < 5; i++) {
        memset(buf, '.', 32);
        buf[32] = 0;
        memcpy(buf + copies[i][0], alpha + copies[i][1], copies[i][2]);
        printf("memcpy  %s\n", buf);
    }
    memset(buf, '-', 24);
    buf[24] = 0;
    memset(buf + 3, '*', 9);
    memset(buf + 14, '#', 6);
    printf("memset  %s\n", buf);
    memcpy(buf, alpha, 11);
    buf[11] = 0;
    memmove(buf + 2, buf, 6);
    printf("memmove %s\n", buf);
    memmove(buf, buf + 3, 7);
    printf("memmove %s\n", buf);
    strcpy(buf, hello);
    for (p = buf, q = buf + strlen(buf) - 1; p < q; p++, q--) {
        char t = *p;
        *p = *q;
        *q = t;
    }
    printf("reverse \"%s\"\n", buf);
    strcpy(buf, fox);
    for (p = buf; *p; p++)
        if (*p >= 'a' && *p <= 'z')
            *p -= 'a' - 'A';
    printf("upper   \"%s\"\n", buf);
    words = inword = 0;
    for (p = (char *)paragraph; *p; p++) {
        if (*p > ' ') {
            if (!inword)
                words++;
            inword = 1;
        } else {
            inword = 0;
        }
    }
    printf("words in paragraph: %d\n", words);
    return 0;
}
