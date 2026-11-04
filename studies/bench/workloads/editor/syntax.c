/* C's colouring (ed.h), as Heron Mini's editor does it (edit.c's
   ed_syn_line): a line at a time, from whether it starts inside a block
   comment. Keywords, comments (block and //), strings and character
   constants, numbers, and preprocessor lines. */

#include <string.h>
#include "ed.h"

static const char *const keywords[] = {
    "auto", "break", "case", "char", "const", "continue", "default", "do", "else", "enum",
    "extern", "for", "goto", "if", "int", "long", "register", "return", "short", "signed",
    "sizeof", "static", "struct", "switch", "typedef", "union", "unsigned", "void", "volatile",
    "while", 0,
};

/* each character's kind: 1 a letter or '_', 2 a digit; 4 a keyword's first letter */
static unsigned char ctype[256];

static void ctype_init(void)
{
    int c, k;
    for (c = 'a'; c <= 'z'; c++)
        ctype[c] = ctype[c - 'a' + 'A'] = 1;
    ctype['_'] = 1;
    for (c = '0'; c <= '9'; c++)
        ctype[c] = 2;
    for (k = 0; keywords[k]; k++)
        ctype[(unsigned char)keywords[k][0]] |= 4;
}

static int keyword(const char *s, int n)
{
    int k;
    if (n < 2 || n > 8 || !(ctype[(unsigned char)s[0]] & 4))
        return 0;
    for (k = 0; keywords[k]; k++)
        if (keywords[k][0] == s[0] && keywords[k][1] == s[1] && !keywords[k][n] &&
            !memcmp(keywords[k], s, n))
            return 1;
    return 0;
}

int syn_line(const char *s, int n, int cin, unsigned char *cls)
{
    int i, j, base = A_TEXT, c;
    if (!ctype['a'])
        ctype_init();
    for (j = 0; j < n && (s[j] == ' ' || s[j] == '\t'); j++)
        cls[j] = A_TEXT;
    if (!cin && j < n && s[j] == '#')
        base = A_PREPROC;
    i = cin ? 0 : j;
    while (i < n) {
        c = (unsigned char)s[i];
        if (cin) {
            cls[i++] = A_COMMENT;
            if (c == '*' && i < n && s[i] == '/') {
                cls[i++] = A_COMMENT;
                cin = 0;
            }
        } else if (c == '/' && i + 1 < n && s[i + 1] == '*') {
            cls[i] = cls[i + 1] = A_COMMENT;
            i += 2;
            cin = 1;
        } else if (c == '/' && i + 1 < n && s[i + 1] == '/') {
            while (i < n)
                cls[i++] = A_COMMENT;
        } else if (c == '"' || c == '\'') {
            j = i + 1;
            while (j < n && s[j] != c)
                j += s[j] == '\\' ? 2 : 1;
            if (j < n)
                j++;
            if (j > n)
                j = n;
            while (i < j)
                cls[i++] = A_STRING;
        } else if (ctype[c] & 3) {
            int k = A_NUMBER;
            j = i;
            while (j < n && (ctype[(unsigned char)s[j]] & 3))
                j++;
            if (ctype[c] & 1)
                k = base == A_TEXT && keyword(s + i, j - i) ? A_KEYWORD : base;
            else if (base == A_PREPROC)
                k = base;
            while (i < j)
                cls[i++] = k;
        } else {
            cls[i++] = base;
        }
    }
    return cin;
}

/* the same walk as syn_line's, keeping only what decides the state:
   comments, and strings, which hide comment marks */
int syn_state(const char *s, int n, int cin)
{
    int i = 0, c;
    while (i < n) {
        c = (unsigned char)s[i++];
        if (cin) {
            if (c == '*' && i < n && s[i] == '/') {
                i++;
                cin = 0;
            }
        } else if (c == '/' && i < n && s[i] == '*') {
            i++;
            cin = 1;
        } else if (c == '/' && i < n && s[i] == '/') {
            break;
        } else if (c == '"' || c == '\'') {
            while (i < n && (unsigned char)s[i] != c)
                i += s[i] == '\\' ? 2 : 1;
            i++;
        }
    }
    return cin;
}
