/* The lexer. Newlines end statements, except inside parentheses and
   brackets, after an operator or a comma, and before a line that starts
   with `.name` (a method chain). */

#include "compiler.h"

static const char *const keywords[] = {
    "and", "attr", "break", "catch", "class", "continue", "def", "do", "elif",
    "else", "end", "false", "for", "if", "in", "nil", "not", "or", "return",
    "self", "super", "then", "true", "try", "while", 0
};

static const char *const names[NTOKENS] = {
    "end of input", "newline", "number", "string", "symbol", "name", "@name",
    "and", "attr", "break", "catch", "class", "continue", "def", "do", "elif",
    "else", "end", "false", "for", "if", "in", "nil", "not", "or", "return",
    "self", "super", "then", "true", "try", "while",
    "(", ")", "[", "]", "{", "}", ",", ".", ":", ";", "=", "==", "!=", "<", "<=",
    ">", ">=", "<=>", "+", "-", "*", "/", "%", "**", "&", "|", "^", "<<", ">>",
    "~", "..", "..<", "+=", "-=", "*=", "/=", "%=", "&=", "|=", "^=", "<<=", ">>="
};

const char *tok_name(int t) { return t >= 0 && t < NTOKENS ? names[t] : "?"; }

void fatal_at(Lexer *lx, int line, const char *msg);

#ifdef EGRET_GUI
static int gui_line;            /* the line to tell the splash at next */
#endif

void lex_init(Lexer *lx, const char *src, unsigned len, int line, const char *file)
{
#ifdef EGRET_GUI
    gui_line = 0;
#endif
    memset(lx, 0, sizeof *lx);
    lx->src = lx->p = src;
    lx->end = src + len;
    lx->line = line;
    lx->file = file;
    lx->tok = T_NEWLINE;
    lx->prev = T_NEWLINE;
}

static int is_alpha(int c) { return (c >= 'a' && c <= 'z') || (c >= 'A' && c <= 'Z') || c == '_'; }
static int is_digit(int c) { return c >= '0' && c <= '9'; }
static int is_alnum(int c) { return is_alpha(c) || is_digit(c); }

/* tokens after which an operand can't have ended */
static int continues(int t)
{
    switch (t) {
    case T_NEWLINE: case T_COMMA: case T_DOT: case T_LPAREN: case T_LBRACK:
    case T_LBRACE: case T_AND: case T_OR: case T_NOT: case T_ASSIGN: case T_EQ:
    case T_NE: case T_LT: case T_LE: case T_GT: case T_GE: case T_CMP: case T_PLUS:
    case T_MINUS: case T_STAR: case T_SLASH: case T_PERCENT: case T_POW:
    case T_AMP: case T_PIPE: case T_CARET: case T_SHL: case T_SHR: case T_TILDE:
    case T_DOTDOT: case T_DOTDOTLT: case T_PLUS_EQ: case T_MINUS_EQ: case T_STAR_EQ:
    case T_SLASH_EQ: case T_PERCENT_EQ: case T_AMP_EQ: case T_PIPE_EQ:
    case T_CARET_EQ: case T_SHL_EQ: case T_SHR_EQ: case T_COLON: case T_SEMI:
        return 1;
    }
    return 0;
}

/* tokens that end an operand (so a following ':' is punctuation) */
static int ends_operand(int t)
{
    switch (t) {
    case T_INT: case T_STRING: case T_SYMBOL: case T_IDENT: case T_IVAR:
    case T_RPAREN: case T_RBRACK: case T_RBRACE: case T_TRUE: case T_FALSE:
    case T_NIL: case T_SELF: case T_END:
        return 1;
    }
    return 0;
}

/* p is just after an opening quote; returns the closing quote. Skips
   interpolated expressions, which may hold strings of their own. */
static const char *skip_string(Lexer *lx, const char *p, int q)
{
    while (p < lx->end && *p != q) {
        if (*p == '\\' && p + 1 < lx->end) {
            p += 2;
            continue;
        }
        if (*p == '\n')
            lx->line++;
        if (*p == '{' && q == '"') {
            int depth = 1;
            p++;
            while (p < lx->end && depth) {
                if (*p == '"' || *p == '\'') {
                    p = skip_string(lx, p + 1, *p);
                    if (p < lx->end)
                        p++;
                    continue;
                }
                if (*p == '{')
                    depth++;
                else if (*p == '}')
                    depth--;
                else if (*p == '\n')
                    lx->line++;
                p++;
            }
            continue;
        }
        p++;
    }
    return p;
}

static int peek_chain(Lexer *lx)
{
    /* after a newline: is the next code line a `.name` continuation? */
    const char *p = lx->p;
    for (;;) {
        while (p < lx->end && (*p == ' ' || *p == '\t' || *p == '\r' || *p == '\n'))
            p++;
        if (p < lx->end && *p == '#') {
            while (p < lx->end && *p != '\n')
                p++;
            continue;
        }
        break;
    }
    return p + 1 < lx->end && p[0] == '.' && is_alpha(p[1]);
}

static int token(Lexer *lx)
{
    const char *p;
    int c;
again:
    p = lx->p;
    while (p < lx->end && (*p == ' ' || *p == '\t' || *p == '\r'))
        p++;
    if (p < lx->end && *p == '#') {
        while (p < lx->end && *p != '\n')
            p++;
    }
    if (p < lx->end && *p == '\\' && p + 1 < lx->end && p[1] == '\n') {
        lx->line++;
        lx->p = p + 2;
        goto again;
    }
    lx->tstart = p;
    lx->tline = lx->line;
#ifdef EGRET_GUI
    if (lx->line >= gui_line)   /* the splash's progress bar (HACK: see studies/egret_gui) */
        gui_line = gui_compiling(lx->file, lx->line);
#endif
    if (p >= lx->end) {
        lx->p = p;
        return T_EOF;
    }
    c = *p++;
    lx->p = p;
    if (c == '\n') {
        lx->line++;
        if ((lx->depth > 0 && lx->nest[lx->depth - 1] != '{') || continues(lx->prev)
            || peek_chain(lx))
            goto again;
        return T_NEWLINE;
    }
    if (is_alpha(c)) {
        int i;
        while (p < lx->end && is_alnum(*p))
            p++;
        if (p < lx->end && (*p == '?' || *p == '!') && !(p + 1 < lx->end && p[1] == '='))
            p++;
        static Value kwsyms[T_WHILE - T_AND + 1];
        Value sym;
        lx->p = p;
        lx->tlen = p - lx->tstart;
        if (!kwsyms[0])
            for (i = 0; keywords[i]; i++)
                kwsyms[i] = intern_c(keywords[i]);
        sym = intern(lx->tstart, lx->tlen);
        if (*lx->tstart >= 'a' && *lx->tstart <= 'w')
            for (i = 0; i <= T_WHILE - T_AND; i++)
                if (kwsyms[i] == sym)
                    return T_AND + i;
        lx->tval = sym;
        return T_IDENT;
    }
    if (c == '@' && p < lx->end && is_alpha(*p)) {
        while (p < lx->end && is_alnum(*p))
            p++;
        lx->p = p;
        lx->tval = intern(lx->tstart + 1, p - lx->tstart - 1);
        return T_IVAR;
    }
    if (is_digit(c)) {
        if (c == '0' && p < lx->end && (*p == 'x' || *p == 'X')) {
            Value v = MKINT(0);
            p++;
            push_root(&v);
            while (p < lx->end && (is_alnum(*p))) {
                int d = *p;
                if (d == '_') { p++; continue; }
                d = is_digit(d) ? d - '0' : (d | 32) >= 'a' && (d | 32) <= 'f' ? (d | 32) - 'a' + 10 : -1;
                if (d < 0) {
                    pop_roots(1);
                    fatal_at(lx, lx->line, "bad hex number");
                }
                v = int_add(int_mul(v, MKINT(16)), MKINT(d));
                if (!v) {
                    pop_roots(1);
                    fatal_at(lx, lx->line, "number too big");
                }
                p++;
            }
            pop_roots(1);
            lx->p = p;
            lx->tval = v;
            return T_INT;
        } else {
            char buf[400];
            unsigned n = 0;
            p--;
            while (p < lx->end && (is_digit(*p) || *p == '_')) {
                if (*p != '_' && n < sizeof buf)
                    buf[n++] = *p;
                p++;
            }
            lx->p = p;
            lx->tval = int_from_s((const unsigned char *)buf, n);
            if (!lx->tval)
                fatal_at(lx, lx->line, "number too big");
            return T_INT;
        }
    }
    if (c == '"' || c == '\'') {
        const char *e = skip_string(lx, p, c);
        if (e >= lx->end)
            fatal_at(lx, lx->tline, "unterminated string");
        lx->tstart = p;
        lx->tlen = e - p;
        lx->tval = c == '\'';
        lx->p = e + 1;
        return T_STRING;
    }
    if (c == ':' && p < lx->end && is_alpha(*p) && !ends_operand(lx->prev)) {
        const char *s = p;
        while (p < lx->end && is_alnum(*p))
            p++;
        if (p < lx->end && (*p == '?' || *p == '!' || *p == '='))
            p++;
        lx->p = p;
        lx->tval = intern(s, p - s);
        return T_SYMBOL;
    }
#define NEXT_IS(ch) (p < lx->end && *p == (ch) ? (lx->p = ++p, 1) : 0)
    switch (c) {
    case '(':
    case '[':
    case '{':
        if (lx->depth < 64)
            lx->nest[lx->depth] = c;
        lx->depth++;
        return c == '(' ? T_LPAREN : c == '[' ? T_LBRACK : T_LBRACE;
    case ')':
    case ']':
    case '}':
        if (lx->depth > 0)
            lx->depth--;
        return c == ')' ? T_RPAREN : c == ']' ? T_RBRACK : T_RBRACE;
    case ',': return T_COMMA;
    case ';': return T_SEMI;
    case ':': return T_COLON;
    case '~': return T_TILDE;
    case '.':
        if (NEXT_IS('.'))
            return NEXT_IS('<') ? T_DOTDOTLT : T_DOTDOT;
        return T_DOT;
    case '=': return NEXT_IS('=') ? T_EQ : T_ASSIGN;
    case '!':
        if (NEXT_IS('='))
            return T_NE;
        break;
    case '<':
        if (NEXT_IS('<'))
            return NEXT_IS('=') ? T_SHL_EQ : T_SHL;
        if (NEXT_IS('='))
            return NEXT_IS('>') ? T_CMP : T_LE;
        return T_LT;
    case '>':
        if (NEXT_IS('>'))
            return NEXT_IS('=') ? T_SHR_EQ : T_SHR;
        return NEXT_IS('=') ? T_GE : T_GT;
    case '+': return NEXT_IS('=') ? T_PLUS_EQ : T_PLUS;
    case '-': return NEXT_IS('=') ? T_MINUS_EQ : T_MINUS;
    case '*':
        if (NEXT_IS('*'))
            return T_POW;
        return NEXT_IS('=') ? T_STAR_EQ : T_STAR;
    case '/': return NEXT_IS('=') ? T_SLASH_EQ : T_SLASH;
    case '%': return NEXT_IS('=') ? T_PERCENT_EQ : T_PERCENT;
    case '&': return NEXT_IS('=') ? T_AMP_EQ : T_AMP;
    case '|': return NEXT_IS('=') ? T_PIPE_EQ : T_PIPE;
    case '^': return NEXT_IS('=') ? T_CARET_EQ : T_CARET;
    }
    fatal_at(lx, lx->line, "unexpected character");
    return T_EOF;
}

int lex_next(Lexer *lx)
{
    int t = token(lx);
    if (t == T_NEWLINE && lx->prev == T_NEWLINE)
        t = token(lx);
    lx->tlen = lx->p - lx->tstart;
    if (t == T_STRING)
        lx->tlen = lx->p - 1 - lx->tstart;
    lx->prev = lx->tok = t;
    return t;
}
