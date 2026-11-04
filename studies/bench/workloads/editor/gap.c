/* The gap buffer (ed.h): the text in one block of memory with a gap in
   it where the editing is. Inserting at the gap is a copy into it;
   editing elsewhere first moves the gap there, copying the text between
   across it. The gap is never shorter than GAP_MIN after it grows. */

#include <stdlib.h>
#include <string.h>
#include "ed.h"

#define GAP_MIN 2048

void gap_init(Gap *g, const char *s, int n)
{
    g->size = n + GAP_MIN;
    g->buf = malloc(g->size);
    memcpy(g->buf, s, n);
    g->gap0 = n;
    g->gap1 = g->size;
}

int gap_len(const Gap *g)
{
    return g->size - (g->gap1 - g->gap0);
}

int gap_at(const Gap *g, int pos)
{
    return (unsigned char)(pos < g->gap0 ? g->buf[pos] : g->buf[pos + g->gap1 - g->gap0]);
}

/* the gap to pos */
static void gap_move(Gap *g, int pos)
{
    int n;
    if (pos < g->gap0) {
        /* the text from pos to the gap goes to its other side */
        n = g->gap0 - pos;
        memmove(g->buf + g->gap1 - n, g->buf + pos, n);
        g->gap0 = pos;
        g->gap1 -= n;
    } else if (pos > g->gap0) {
        n = pos - g->gap0;
        memmove(g->buf + g->gap0, g->buf + g->gap1, n);
        g->gap0 += n;
        g->gap1 += n;
    }
}

void gap_insert(Gap *g, int pos, const char *s, int n)
{
    gap_move(g, pos);
    if (g->gap1 - g->gap0 < n) {
        /* a bigger block, the text after the gap moved to its end */
        int tail = g->size - g->gap1, size = g->size * 3 / 2 + n + GAP_MIN;
        g->buf = realloc(g->buf, size);
        memmove(g->buf + size - tail, g->buf + g->gap1, tail);
        g->gap1 = size - tail;
        g->size = size;
    }
    memcpy(g->buf + g->gap0, s, n);
    g->gap0 += n;
}

void gap_delete(Gap *g, int pos, int n)
{
    gap_move(g, pos);
    g->gap1 += n;
}

const char *gap_run(const Gap *g, int pos, int *n)
{
    if (pos < g->gap0) {
        *n = g->gap0 - pos;
        return g->buf + pos;
    }
    *n = g->size - g->gap1 - (pos - g->gap0);
    return g->buf + g->gap1 + (pos - g->gap0);
}

int gap_line(const Gap *g, int pos, char *out, int max, int *next)
{
    int len = 0, n, k;
    const char *s;
    for (;;) {
        s = gap_run(g, pos, &n);
        if (n == 0) {
            *next = pos;            /* the end of the text */
            return len;
        }
        for (k = 0; k < n && s[k] != '\n'; k++)
            if (len < max)
                out[len++] = s[k];
        pos += k;
        if (k < n) {
            *next = pos + 1;
            return len;
        }
    }
}

int gap_find(const Gap *g, int from, const char *s, int n)
{
    int end = gap_len(g) - n, len, k, j;
    const char *run;
    int first = (unsigned char)s[0];
    while (from <= end) {
        /* a piece of text without the gap: look in it for the first
           character, and compare the rest where it is */
        run = gap_run(g, from, &len);
        if (len > end - from + 1)
            len = end - from + 1;
        for (k = 0; k < len; k++) {
            if ((unsigned char)run[k] != first)
                continue;
            for (j = 1; j < n && gap_at(g, from + k + j) == (unsigned char)s[j]; j++)
                ;
            if (j == n)
                return from + k;
        }
        from += len;
    }
    return -1;
}
