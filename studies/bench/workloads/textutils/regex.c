/* Regular expressions for grep and sed (tu.h): the pattern compiled to
   an array of nodes, one for each character, class or set, with the
   repeat that follows it; matched by backtracking, trying the longest run
   of a repeat first.

   Fen's grep interprets the pattern's text at every step; compiling it
   once makes a set a bitmap test and lets the search skip ahead to the
   first character a match must start with, as real greps do. */

#include <stdlib.h>
#include <string.h>
#include "tu.h"

enum { R_CHAR, R_ANY, R_SET, R_EOL, R_END };   /* what a node matches */
enum { ONE, STAR, PLUS, QUEST };                /* how many times */

typedef struct {
    unsigned char op, rep, c;
    unsigned char set[32];      /* R_SET: a bit for each character */
} Node;

struct Re {
    Node *node;
    int bol;                    /* ^: only at the start */
    int icase;
    int first;                  /* the character every match starts with, or -1 */
};

#define FOLD(c) ((unsigned)((c) - 'A') < 26 ? (c) + 32 : (c))

int fold(int c)
{
    return FOLD(c);
}

static void set_add(Node *p, int c, int icase)
{
    p->set[c >> 3] |= 1 << (c & 7);
    if (icase && (unsigned)(c - 'a') < 26)
        p->set[(c - 32) >> 3] |= 1 << ((c - 32) & 7);
    if (icase && (unsigned)(c - 'A') < 26)
        p->set[(c + 32) >> 3] |= 1 << ((c + 32) & 7);
}

/* a bracket expression after its '[': where the pattern goes on, or 0 if
   the ']' is missing. A ']' first is in the set, as is a '-' at either
   end. */
static const char *compile_set(Node *p, const char *s, int icase)
{
    int neg = 0, k;
    memset(p->set, 0, sizeof p->set);
    p->op = R_SET;
    if (*s == '^') {
        neg = 1;
        s++;
    }
    do {
        if (!*s)
            return 0;
        if (s[1] == '-' && s[2] && s[2] != ']') {
            for (k = (unsigned char)s[0]; k <= (unsigned char)s[2]; k++)
                set_add(p, k, icase);
            s += 3;
        } else {
            set_add(p, (unsigned char)*s, icase);
            s++;
        }
    } while (*s != ']');
    if (neg)
        for (k = 0; k < 32; k++)
            p->set[k] = ~p->set[k];
    p->set[0] &= ~1;            /* never NUL */
    return s + 1;
}

Re *re_compile(const char *pat, int icase)
{
    Re *re = malloc(sizeof *re);
    Node *p;
    re->node = p = malloc((strlen(pat) + 1) * sizeof(Node));
    re->icase = icase;
    re->bol = *pat == '^';
    if (re->bol)
        pat++;
    while (*pat) {
        p->rep = ONE;
        if (*pat == '$' && !pat[1]) {
            p->op = R_EOL;
            pat++;
            p++;
            continue;
        }
        if (*pat == '.') {
            p->op = R_ANY;
            pat++;
        } else if (*pat == '[') {
            pat = compile_set(p, pat + 1, icase);
            if (!pat) {
                re_free(re);
                return 0;
            }
        } else {
            if (*pat == '\\' && pat[1])
                pat++;
            p->op = R_CHAR;
            p->c = icase ? FOLD((unsigned char)*pat) : *pat;
            pat++;
        }
        if (*pat == '*')
            p->rep = STAR;
        else if (*pat == '+')
            p->rep = PLUS;
        else if (*pat == '?')
            p->rep = QUEST;
        if (p->rep != ONE)
            pat++;
        p++;
    }
    p->op = R_END;
    p = re->node;
    re->first = p->op == R_CHAR && !icase && (p->rep == ONE || p->rep == PLUS) ? p->c : -1;
    return re;
}

void re_free(Re *re)
{
    free(re->node);
    free(re);
}

/* does node p take the character c */
static int takes(const Node *p, int c, int icase)
{
    if (p->op == R_CHAR)
        return (icase ? FOLD(c) : c) == p->c;
    if (p->op == R_ANY)
        return 1;
    return p->set[c >> 3] >> (c & 7) & 1;
}

/* the nodes from p on matched at s, the text ending at e: where the
   match ends, or 0 */
static const char *here(const Node *p, const char *s, const char *e, int icase)
{
    for (;; p++) {
        const char *t, *r;
        int min;
        if (p->op == R_END)
            return s;
        if (p->op == R_EOL)
            return s == e ? s : 0;
        if (p->rep == ONE) {
            if (s == e || !takes(p, (unsigned char)*s, icase))
                return 0;
            s++;
            continue;
        }
        /* a repeat: the longest run, then shorter ones until the rest matches */
        t = s;
        if (p->rep == QUEST) {
            if (t < e && takes(p, (unsigned char)*t, icase))
                t++;
        } else {
            while (t < e && takes(p, (unsigned char)*t, icase))
                t++;
        }
        min = p->rep == PLUS;
        if (t - s < min)
            return 0;
        for (;;) {
            r = here(p + 1, t, e, icase);
            if (r)
                return r;
            if (t - s == min)
                return 0;
            t--;
        }
    }
}

int re_search(const Re *re, const char *s, int n, int from, int *m0, int *m1)
{
    const char *p = s + from, *e = s + n, *r;
    if (re->bol) {
        if (from > 0)
            return 0;
        r = here(re->node, s, e, re->icase);
        if (!r)
            return 0;
        *m0 = 0;
        *m1 = r - s;
        return 1;
    }
    for (; p <= e; p++) {
        if (re->first >= 0) {
            /* a match can only start at its first character */
            while (p < e && *p != re->first)
                p++;
            if (p == e)
                return 0;
        }
        r = here(re->node, p, e, re->icase);
        if (r) {
            *m0 = p - s;
            *m1 = r - s;
            return 1;
        }
    }
    return 0;
}
