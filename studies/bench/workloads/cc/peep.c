/* The peephole optimiser: a pass over a function's assembly text, as
   Unix's c2 made over the C compiler's output. Each line is taken apart
   into a label, or a mnemonic and its operands, the rules below rewrite
   or delete lines until none applies, and the lines that changed are
   written out again.

   - moves: a move of a register to itself goes; a load from where the
     line before stored goes, or becomes a register move; a register set
     and then set again before it is read loses the first setting;
   - branches: a branch to a branch goes to the second one's target; a
     branch over an unconditional branch becomes the opposite branch; a
     branch to the next line goes; code after an unconditional branch,
     up to the next label, is never reached and goes;
   - flags: a compare with 0 that only feeds EQ or NE goes when the
     instruction before set N and Z from the same register, and a load
     followed by such a compare becomes draft 2's MOVS;
   - labels that nothing branches to go. */

#include "cc.h"

enum { L_DEAD, L_LABEL, L_INSN, L_OTHER };

/* The mnemonics the rules know; any other is OP_OTHER. */
enum { OP_OTHER, OP_MOV, OP_MOVS, OP_CMP, OP_BRA, OP_RET, OP_BCC, OP_SETCC, OP_ALU };

struct insn {
    int kind;
    int dirty;                  /* changed: to be written out again */
    int code;                   /* OP_*, for an instruction */
    int cond;                   /* OP_BCC's and OP_SETCC's condition */
    int target;                 /* a branch's label's line, or -1 */
    char op[8];
    char a[32];                 /* the first operand, or a label's name */
    char b[40];                 /* the second operand, or "" */
};

static struct insn ins[MAXLINES];
static int n;

static void classify(struct insn *in);

/* ---- taking lines apart ---------------------------------------------- */

static int copy_field(char *dst, const char *src, int len, int max)
{
    if (len >= max)
        return 0;
    memcpy(dst, src, len);
    dst[len] = 0;
    return 1;
}

static void parse_line(struct insn *in, const char *s)
{
    const char *p, *q;
    int depth = 0;
    in->dirty = 0;
    in->op[0] = in->a[0] = in->b[0] = 0;
    if (!s) {
        in->kind = L_DEAD;
        return;
    }
    in->kind = L_OTHER;
    if (s[0] == 0)
        return;
    if (s[0] != ' ') {
        for (p = s; *p && *p != ':'; p++)
            ;
        if (copy_field(in->a, s, p - s, sizeof in->a))
            in->kind = L_LABEL;
        return;
    }
    for (p = s; *p == ' '; p++)
        ;
    if (*p == '.')
        return;                 /* a directive */
    for (q = p; *q && *q != ' '; q++)
        ;
    if (!copy_field(in->op, p, q - p, sizeof in->op))
        return;
    while (*q == ' ')
        q++;
    /* the operands split at the comma outside brackets */
    for (p = q; *p; p++) {
        if (*p == '[')
            depth++;
        else if (*p == ']')
            depth--;
        else if (*p == ',' && depth == 0)
            break;
    }
    if (!copy_field(in->a, q, p - q, sizeof in->a))
        return;
    if (*p == ',') {
        p++;
        while (*p == ' ')
            p++;
        if (!copy_field(in->b, p, strlen(p), sizeof in->b))
            return;
    }
    in->kind = L_INSN;
    classify(in);
}

/* Puts a line together again: "        OP   a, b". */
static void render(struct insn *in, char *buf)
{
    char *d = buf;
    int k;
    for (k = 0; k < 8; k++)
        *d++ = ' ';
    for (k = 0; in->op[k]; k++)
        *d++ = in->op[k];
    while (k++ < 4)
        *d++ = ' ';
    *d++ = ' ';
    strcpy(d, in->a);
    d += strlen(d);
    if (in->b[0]) {
        *d++ = ',';
        *d++ = ' ';
        strcpy(d, in->b);
        d += strlen(d);
    }
    *d = 0;
}

/* ---- what an instruction is ------------------------------------------ */

static const char *const conds[] = {
    "EQ", "NE", "LT", "GE", "GT", "LE", "LO", "HS", "HI", "LS", "MI", "PL", 0
};
static const char *const opposite[] = {
    "NE", "EQ", "GE", "LT", "LE", "GT", "HS", "LO", "LS", "HI", "PL", "MI"
};

/* Instructions that set N and Z from the register they write, their
   first operand. */
static const char *const alu_ops[] = {
    "ADD", "SUB", "AND", "OR", "XOR", "NEG", "NOT", "INC", "DEC", "LSL",
    "ASR", "LSR", "ZXB", 0
};

static int find_cond(const char *c)
{
    int k;
    for (k = 0; conds[k]; k++)
        if (c[0] == conds[k][0] && c[1] == conds[k][1] && c[2] == 0)
            return k;
    return -1;
}

/* Looks up an instruction's mnemonic, once, when its line is read. */
static void classify(struct insn *in)
{
    const char *op = in->op;
    int k;
    in->code = OP_OTHER;
    in->cond = -1;
    if (op[0] == 'B') {
        if (strcmp(op, "BRA") == 0)
            in->code = OP_BRA;
        else if ((in->cond = find_cond(op + 1)) >= 0)
            in->code = OP_BCC;
    } else if (op[0] == 'S' && op[1] == 'E' && op[2] == 'T') {
        if ((in->cond = find_cond(op + 3)) >= 0)
            in->code = OP_SETCC;
    } else if (strcmp(op, "MOV") == 0) {
        in->code = OP_MOV;
    } else if (strcmp(op, "MOVS") == 0) {
        in->code = OP_MOVS;
    } else if (strcmp(op, "CMP") == 0) {
        in->code = OP_CMP;
    } else if (strcmp(op, "RET") == 0) {
        in->code = OP_RET;
    } else {
        for (k = 0; alu_ops[k]; k++)
            if (strcmp(op, alu_ops[k]) == 0)
                in->code = OP_ALU;
    }
}

static int is(struct insn *in, int code)
{
    return in->kind == L_INSN && in->code == code;
}

static int is_branch(struct insn *in)
{
    return is(in, OP_BRA) || is(in, OP_BCC);
}

static int is_reg(const char *s)
{
    return s[0] == 'r' && s[1] >= '0' && s[1] <= '9' &&
           (s[2] == 0 || (s[2] >= '0' && s[2] <= '9' && s[3] == 0));
}

/* Does the text name register r (as "r3", not inside "r30")? */
static int mentions(const char *s, const char *r)
{
    int len = strlen(r);
    const char *p;
    for (p = s; *p; p++)
        if (p[0] == r[0] && strncmp(p, r, len) == 0 &&
            (p == s || !(p[-1] >= 'a' && p[-1] <= 'z')) &&
            !(p[len] >= '0' && p[len] <= '9'))
            return 1;
    return 0;
}

static int sets_nz(struct insn *in)
{
    return (is(in, OP_ALU) || is(in, OP_MOVS)) && is_reg(in->a);
}

static void kill(int i)
{
    ins[i].kind = L_DEAD;
    ins[i].dirty = 1;
}

/* The next line from i on that is an instruction, past dead lines and,
   if skip_labels, labels; n if none. */
static int next_insn(int i, int skip_labels)
{
    while (i < n && (ins[i].kind == L_DEAD ||
                     (skip_labels && ins[i].kind == L_LABEL)))
        i++;
    return i;
}

/* ---- the labels ------------------------------------------------------ */

#define LABELBUCKETS 256

static int label_head[LABELBUCKETS];
static int label_next[MAXLINES];
static int label_refs[MAXLINES];

static int find_label(const char *name)
{
    int i = label_head[hash_bytes(name, strlen(name)) & (LABELBUCKETS - 1)];
    while (i >= 0 && strcmp(ins[i].a, name) != 0)
        i = label_next[i];
    return i;
}

/* Finds each branch's label, once: a hash table of the labels, looked
   up by name. */
static void index_labels(void)
{
    int i;
    for (i = 0; i < LABELBUCKETS; i++)
        label_head[i] = -1;
    for (i = 0; i < n; i++) {
        if (ins[i].kind == L_LABEL) {
            int h = hash_bytes(ins[i].a, strlen(ins[i].a)) & (LABELBUCKETS - 1);
            label_next[i] = label_head[h];
            label_head[h] = i;
        }
    }
    for (i = 0; i < n; i++)
        ins[i].target = is_branch(&ins[i]) ? find_label(ins[i].a) : -1;
}

/* ---- the rules ------------------------------------------------------- */

static int moves(void)
{
    int i, j, c = 0;
    for (i = 0; i < n; i++) {
        struct insn *in = &ins[i], *nx;
        if (!is(in, OP_MOV))
            continue;
        if (is_reg(in->a) && strcmp(in->a, in->b) == 0) {
            kill(i);
            c++;
            continue;
        }
        j = next_insn(i + 1, 0);
        if (j >= n)
            continue;
        nx = &ins[j];
        if (!is(nx, OP_MOV))
            continue;
        if (in->a[0] == '[' && is_reg(in->b) && strcmp(in->a, nx->b) == 0 &&
            is_reg(nx->a)) {
            /* MOV [m], rA; MOV rB, [m]: words only, since a byte store
               keeps only rA's low byte */
            if (strcmp(nx->a, in->b) == 0) {
                kill(j);
            } else {
                strcpy(nx->b, in->b);
                nx->dirty = 1;
            }
            c++;
        } else if (is_reg(in->a) && is_reg(in->b) && strcmp(in->a, nx->b) == 0 &&
                   strcmp(in->b, nx->a) == 0) {
            /* MOV rA, rB; MOV rB, rA */
            kill(j);
            c++;
        } else if (is_reg(in->a) && strcmp(in->a, nx->a) == 0 &&
                   !mentions(nx->b, in->a)) {
            /* rA set twice */
            kill(i);
            c++;
        }
    }
    return c;
}

static int branches(void)
{
    int i, j, k, c = 0;
    for (i = 0; i < n; i++) {
        struct insn *in = &ins[i];
        if (in->kind == L_DEAD)
            continue;
        if (is(in, OP_BRA) || is(in, OP_RET)) {
            /* unreachable until the next label */
            for (j = i + 1; j < n && ins[j].kind != L_LABEL; j++)
                if (ins[j].kind == L_INSN) {
                    kill(j);
                    c++;
                }
        }
        if (!is_branch(in))
            continue;
        /* a branch to a branch */
        j = in->target;
        if (j >= 0) {
            k = next_insn(j, 1);
            if (k < n && is(&ins[k], OP_BRA) && ins[k].target != j) {
                strcpy(in->a, ins[k].a);
                in->target = ins[k].target;
                in->dirty = 1;
                c++;
            }
        }
        /* a branch to where it would fall through anyway */
        for (j = i + 1; j < n && (ins[j].kind == L_DEAD || ins[j].kind == L_LABEL); j++)
            if (j == in->target) {
                kill(i);
                c++;
                break;
            }
        if (in->kind == L_DEAD)
            continue;
        /* Bcc L1; BRA L2; L1: becomes B!cc L2 */
        k = in->cond;
        j = next_insn(i + 1, 0);
        if (is(in, OP_BCC) && j < n && is(&ins[j], OP_BRA)) {
            int l = next_insn(j + 1, 0);
            while (l < n && ins[l].kind == L_LABEL && l != in->target)
                l = next_insn(l + 1, 0);
            if (l < n && l == in->target) {
                in->op[1] = opposite[k][0];
                in->op[2] = opposite[k][1];
                in->cond = find_cond(opposite[k]);
                strcpy(in->a, ins[j].a);
                in->target = ins[j].target;
                in->dirty = 1;
                kill(j);
                c++;
            }
        }
    }
    return c;
}

static int flags(void)
{
    int i, j, k, c = 0;
    for (i = 0; i < n; i++) {
        struct insn *in = &ins[i], *br;
        if (in->kind != L_INSN)
            continue;
        j = next_insn(i + 1, 0);
        if (j >= n || !is(&ins[j], OP_CMP) || strcmp(ins[j].b, "#0") != 0 ||
            strcmp(ins[j].a, in->a) != 0)
            continue;
        k = next_insn(j + 1, 0);
        if (k >= n)
            continue;
        br = &ins[k];
        if (!(is(br, OP_BCC) || is(br, OP_SETCC)) || br->cond > 1)
            continue;           /* not EQ or NE */
        if (sets_nz(in)) {
            kill(j);
            c++;
        } else if (is(in, OP_MOV) && is_reg(in->a) && in->b[0] != '#') {
            strcpy(in->op, "MOVS");
            in->code = OP_MOVS;
            in->dirty = 1;
            kill(j);
            c++;
        }
    }
    return c;
}

static int labels(void)
{
    int i, j, c = 0;
    for (i = 0; i < n; i++)
        label_refs[i] = 0;
    for (i = 0; i < n; i++)
        if (is_branch(&ins[i]) && (j = ins[i].target) >= 0)
            label_refs[j]++;
    for (i = 0; i < n; i++)
        if (ins[i].kind == L_LABEL && ins[i].a[0] == '.' && label_refs[i] == 0) {
            kill(i);
            c++;
        }
    return c;
}

int peephole(void)
{
    char buf[128];
    int i, c, total = 0, passes = 0;
    n = nlines_fn;
    for (i = 0; i < n; i++)
        parse_line(&ins[i], lines[i]);
    index_labels();             /* lines only ever go, so once will do */
    do {
        c = moves() + branches() + flags() + labels();
        total += c;
    } while (c && ++passes < 8);
    for (i = 0; i < n; i++) {
        if (!ins[i].dirty)
            continue;
        if (ins[i].kind == L_DEAD) {
            lines[i] = 0;
        } else {
            render(&ins[i], buf);
            lines[i] = keep_line(buf);
        }
    }
    return total;
}
