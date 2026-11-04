/* CSV as spreadsheets write it (db.h): records a line each, fields
   separated by commas; a field in double quotes may hold commas, and a
   doubled quote stands for one. */

#include <stdlib.h>
#include <string.h>
#include "db.h"

void csv_open(Csv *c, const unsigned char *text, unsigned n)
{
    c->s = (const char *)text;
    c->end = c->s + n;
    c->line = 0;
    c->nfield = 0;
}

int csv_next(Csv *c)
{
    const char *p = c->s, *end = c->end;
    char *o = c->rec, *lim = c->rec + sizeof c->rec - 1;
    int n = 0;
    if (p >= end)
        return 0;
    c->line++;
    for (;;) {
        if (n < MAXFIELDS)
            c->field[n++] = o;
        if (p < end && *p == '"') {
            /* quoted: up to the lone closing quote */
            for (p++; p < end; p++) {
                if (*p == '"') {
                    if (p + 1 < end && p[1] == '"')
                        p++;
                    else {
                        p++;
                        break;
                    }
                }
                if (o < lim)
                    *o++ = *p;
            }
        }
        while (p < end && *p != ',' && *p != '\n') {
            if (o < lim)
                *o++ = *p;
            p++;
        }
        *o = 0;
        if (o < lim)
            o++;
        if (p < end && *p == ',') {
            p++;
            continue;
        }
        break;
    }
    if (p < end && *p == '\n')
        p++;
    c->s = p;
    c->nfield = n;
    return n;
}

int csv_int(const char *s, int *v)
{
    char *end;
    int neg = *s == '-';
    if (neg)
        s++;
    if ((unsigned)(*s - '0') >= 10)
        return 0;
    *v = (int)(unsigned)strtoul(s, &end, 10);
    if (neg)
        *v = -*v;
    return *end == 0;
}

int csv_money(const char *s, int *v)
{
    char *end;
    unsigned units, pence = 0;
    if ((unsigned)(*s - '0') >= 10)
        return 0;
    units = (unsigned)strtoul(s, &end, 10);
    if (*end == '.') {
        if ((unsigned)(end[1] - '0') >= 10 || (unsigned)(end[2] - '0') >= 10 || end[3])
            return 0;
        pence = (end[1] - '0') * 10 + end[2] - '0';
    } else if (*end) {
        return 0;
    }
    *v = units * 100 + pence;
    return 1;
}

char *xstrdup(const char *s)
{
    int n = strlen(s) + 1;
    char *t = malloc(n);
    memcpy(t, s, n);
    return t;
}
