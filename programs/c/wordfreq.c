/* wordfreq: word frequencies of a text read from the console. A word is a
   maximal run of ASCII letters, compared case-insensitively. Prints the
   number of words, the number of distinct words, and the 15 most frequent
   as "count word", by count descending, ties in alphabetical order. */
#include <stdio.h>
#include <string.h>

#define TABLE 1024

struct entry {
    char *word;
    int count;
};

static struct entry table[TABLE];
static char pool[16384];
static struct entry *sorted[TABLE];

static int before(const struct entry *a, const struct entry *b)
{
    if (a->count != b->count)
        return a->count > b->count;
    return strcmp(a->word, b->word) < 0;
}

int main(void)
{
    char *free_ptr = pool;
    int words = 0, distinct = 0, c, i, j;
    c = getchar();
    for (;;) {
        char *w;
        unsigned h = 0;
        struct entry *e;
        while (c >= 0 && !((c | 32) >= 'a' && (c | 32) <= 'z'))
            c = getchar();
        if (c < 0)
            break;
        w = free_ptr;
        while ((c | 32) >= 'a' && (c | 32) <= 'z') {
            c |= 32;
            *free_ptr++ = c;
            h = h * 31 + c;
            c = getchar();
        }
        *free_ptr++ = 0;
        words++;
        for (e = &table[h % TABLE]; e->word; ) {
            if (strcmp(e->word, w) == 0)
                break;
            if (++e == table + TABLE)
                e = table;
        }
        if (e->word) {
            e->count++;
            free_ptr = w;
        } else {
            e->word = w;
            e->count = 1;
            sorted[distinct++] = e;
        }
    }
    for (i = 1; i < distinct; i++) {
        struct entry *e = sorted[i];
        for (j = i; j > 0 && before(e, sorted[j - 1]); j--)
            sorted[j] = sorted[j - 1];
        sorted[j] = e;
    }
    printf("words: %d\ndistinct: %d\n", words, distinct);
    for (i = 0; i < 15 && i < distinct; i++)
        printf("%d %s\n", sorted[i]->count, sorted[i]->word);
    return 0;
}
