/* The lexer: the source as tokens, one at a time, with one token of
   lookahead. Identifiers are interned, so the parser and the symbol
   table compare names by pointer, and keywords are names with their
   token attached, found by the same hash lookup. String literals go to
   a table that the code generator writes out as data. */

#include "cc.h"

struct token tok;               /* the current token */
static struct token ahead;      /* the one after it, if have_ahead */
static int have_ahead;

static const unsigned char *src, *src_end;
static int line;

struct strlit strings[MAXSTRINGS];
int nstrings;
int ntokens;
int nlines;

/* ---- interning ------------------------------------------------------- */

#define NAMEBUCKETS 512
static struct name *names[NAMEBUCKETS];

unsigned hash_bytes(const char *s, int len)
{
    unsigned h = 2166136261u;           /* FNV-1a */
    while (len-- > 0)
        h = (h ^ (unsigned char)*s++) * 16777619u;
    return h;
}

struct name *intern(const char *s, int len)
{
    unsigned h = hash_bytes(s, len);
    struct name **pp = &names[h & (NAMEBUCKETS - 1)], *n;
    for (n = *pp; n; n = n->next)
        if (n->hash == h && n->len == len && memcmp(n->str, s, len) == 0)
            return n;
    n = perm_alloc(sizeof *n);
    n->str = perm_alloc(len + 1);
    memcpy(n->str, s, len);
    n->str[len] = 0;
    n->len = len;
    n->hash = h;
    n->kw = 0;
    n->next = *pp;
    *pp = n;
    return n;
}

static const char *const keywords[] = {
    "int", "char", "void", "struct", "enum", "if", "else", "while", "do",
    "for", "return", "break", "continue", "sizeof", "static", 0
};

/* The spellings of the tokens above T_EOF, for messages. */
static const char *const spellings[] = {
    "end of file", "identifier", "number", "string",
    "int", "char", "void", "struct", "enum", "if", "else", "while", "do",
    "for", "return", "break", "continue", "sizeof", "static",
    "==", "!=", "<=", ">=", "&&", "||", "<<", ">>", "++", "--", "->",
    "+=", "-=", "*=", "/=", "%=", "&=", "|=", "^=", "<<=", ">>="
};

const char *tokname(int kind)
{
    static char one[2];
    if (kind >= T_EOF)
        return spellings[kind - T_EOF];
    one[0] = (char)kind;
    return one;
}

void lex_init(const unsigned char *s, unsigned len)
{
    int i;
    src = s;
    src_end = s + len;
    line = 1;
    for (i = 0; keywords[i]; i++)
        intern(keywords[i], strlen(keywords[i]))->kw = K_INT + i;
    have_ahead = 0;
    next();
}

/* ---- scanning -------------------------------------------------------- */

static int is_alpha(int c)
{
    return (c >= 'a' && c <= 'z') || (c >= 'A' && c <= 'Z') || c == '_';
}

static int is_digit(int c)
{
    return c >= '0' && c <= '9';
}

static int hex_value(int c)
{
    if (is_digit(c))
        return c - '0';
    c |= 32;
    if (c >= 'a' && c <= 'f')
        return c - 'a' + 10;
    return -1;
}

/* Skips blanks and comments, counting lines. */
static void skip_space(void)
{
    const unsigned char *p = src;
    for (;;) {
        while (p < src_end && (*p == ' ' || *p == '\t' || *p == '\n' || *p == '\r')) {
            if (*p == '\n')
                line++;
            p++;
        }
        if (p + 1 < src_end && p[0] == '/' && p[1] == '/') {
            while (p < src_end && *p != '\n')
                p++;
        } else if (p + 1 < src_end && p[0] == '/' && p[1] == '*') {
            p += 2;
            while (p + 1 < src_end && !(p[0] == '*' && p[1] == '/')) {
                if (*p == '\n')
                    line++;
                p++;
            }
            p += 2;
        } else {
            break;
        }
    }
    src = p;
}

/* One character of a character or string literal, escapes decoded. */
static int literal_char(void)
{
    int c = *src++, v;
    if (c != '\\')
        return c;
    c = *src++;
    switch (c) {
    case 'n': return '\n';
    case 't': return '\t';
    case 'r': return '\r';
    case '0': return 0;
    case 'x':
        v = 0;
        while (src < src_end && hex_value(*src) >= 0)
            v = v * 16 + hex_value(*src++);
        return v & 255;
    default:  return c;         /* \\, \', \" */
    }
}

static void scan_string(struct token *t)
{
    static char buf[1024];
    int n = 0;
    src++;                      /* the opening quote */
    while (src < src_end && *src != '"') {
        int c = literal_char();
        if (n < (int)sizeof buf - 1)
            buf[n++] = (char)c;
    }
    src++;
    if (nstrings == MAXSTRINGS) {
        error("too many strings");
        nstrings = 0;
    }
    strings[nstrings].s = perm_alloc(n + 1);
    memcpy(strings[nstrings].s, buf, n);
    strings[nstrings].s[n] = 0;
    strings[nstrings].len = n;
    strings[nstrings].label = 0;
    t->kind = T_STR;
    t->val = nstrings++;
}

static void scan_number(struct token *t)
{
    unsigned v = 0;
    if (src[0] == '0' && (src[1] | 32) == 'x') {
        src += 2;
        while (src < src_end && hex_value(*src) >= 0)
            v = v * 16 + hex_value(*src++);
    } else {
        while (src < src_end && is_digit(*src))
            v = v * 10 + (*src++ - '0');
    }
    t->kind = T_NUM;
    t->val = (int)v;
}

/* The punctuators: c, c=, cc and cc= for the characters that make them. */
static int scan_punct(void)
{
    int c = *src++, d = src < src_end ? *src : 0;
    switch (c) {
    case '=': if (d == '=') { src++; return P_EQ; } return c;
    case '!': if (d == '=') { src++; return P_NE; } return c;
    case '*': if (d == '=') { src++; return P_MULEQ; } return c;
    case '/': if (d == '=') { src++; return P_DIVEQ; } return c;
    case '%': if (d == '=') { src++; return P_MODEQ; } return c;
    case '^': if (d == '=') { src++; return P_XOREQ; } return c;
    case '+':
        if (d == '+') { src++; return P_INC; }
        if (d == '=') { src++; return P_ADDEQ; }
        return c;
    case '-':
        if (d == '-') { src++; return P_DEC; }
        if (d == '=') { src++; return P_SUBEQ; }
        if (d == '>') { src++; return P_ARROW; }
        return c;
    case '&':
        if (d == '&') { src++; return P_ANDAND; }
        if (d == '=') { src++; return P_ANDEQ; }
        return c;
    case '|':
        if (d == '|') { src++; return P_OROR; }
        if (d == '=') { src++; return P_OREQ; }
        return c;
    case '<':
        if (d == '<') {
            src++;
            if (src < src_end && *src == '=') { src++; return P_SHLEQ; }
            return P_SHL;
        }
        if (d == '=') { src++; return P_LE; }
        return c;
    case '>':
        if (d == '>') {
            src++;
            if (src < src_end && *src == '=') { src++; return P_SHREQ; }
            return P_SHR;
        }
        if (d == '=') { src++; return P_GE; }
        return c;
    default:
        return c;
    }
}

static void scan(struct token *t)
{
    int c;
    skip_space();
    t->line = line;
    t->name = 0;
    if (src >= src_end) {
        t->kind = T_EOF;
        return;
    }
    ntokens++;
    c = *src;
    if (is_alpha(c)) {
        const unsigned char *start = src;
        while (src < src_end && (is_alpha(*src) || is_digit(*src)))
            src++;
        t->name = intern((const char *)start, src - start);
        t->kind = t->name->kw ? t->name->kw : T_ID;
    } else if (is_digit(c)) {
        scan_number(t);
    } else if (c == '\'') {
        src++;
        t->kind = T_NUM;
        t->val = literal_char();
        src++;                  /* the closing quote */
    } else if (c == '"') {
        scan_string(t);
    } else {
        t->kind = scan_punct();
    }
}

void next(void)
{
    if (have_ahead) {
        tok = ahead;
        have_ahead = 0;
    } else {
        scan(&tok);
    }
    nlines = tok.line;
}

int peek(void)
{
    if (!have_ahead) {
        scan(&ahead);
        have_ahead = 1;
    }
    return ahead.kind;
}
