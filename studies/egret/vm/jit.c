/* A compiler from Egret's bytecode to draft 1b machine code, running on
   the machine: each method is compiled the first time it runs.

   The native code keeps the interpreter's frames and value stack (as V8's
   Sparkplug does), so at every bytecode boundary the state is the
   interpreter's, and anything uncommon can go to the C interpreter's
   single-stepper: the native code puts the bytecode's address in r8 and
   jumps to jit_glue_slow (jit_v1b.s), which runs that bytecode in C and
   comes back to the native code for wherever the C code left off, through
   the method's map from bytecode offsets to native addresses.

   What the native code saves over the interpreter: the dispatch, decoding
   operands (they're constants in the code), and the method cache, for
   sends: a send is a monomorphic inline cache, a compare with the class
   last seen there and a call, patched by jit_send_miss.

   Registers as in the assembly interpreter (interp_v1b.s): r9 bp, r10 the
   value stack's next free slot, r11 the frame, r12 the literals, r14 nil;
   r8 is set only when the bytecode's address is needed. A call passes the
   new frame's bp in r4 and the caller's bytecode address to go on at in
   r8; the callee's prologue pops the return address into the caller's
   frame (Frame.nip), so a return is JMP [r11 + nip]. */

#ifdef EGRET_JIT

#include "compiler.h"

/* the assembly side (jit_v1b.s) */
extern char jit_glue_slow[], jit_glue_send_miss[], jit_glue_prim_failed[];
extern Value mcache_cls[], mcache_sel[], mcache_method[];
extern Frame *egret_frames_end;
extern Value *egret_vstack_end;
extern Value egret_blockcall, egret_serial;
#define ADDR(x) V(x)

/* ---- an encoder for the instructions it uses -------------------------------------- */

/* The code goes straight into the permanent space, where perm_bytes
   will put it once it's finished; the compiler's own tables are in the
   scratch space, which only the source compiler uses otherwise. */
static unsigned short *code;
static unsigned ncode, maxcode;
static Value code_base;                  /* where the code is */

static void put(unsigned w)
{
    if (ncode >= maxcode)
        fatal("jit: out of permanent space for native code");
    code[ncode++] = w & 0xFFFF;
}

static void begin_code(void)
{
    code_base = perm_hp + 8;
    code = (unsigned short *)BP(code_base);
    ncode = 0;
    maxcode = (PERM_HI - code_base) / 2 - 64;
}

/* the code as a perm object, where it already is */
static Value end_code(void)
{
    Value obj = perm_hp;
    perm_hp += 8 + ((2 * ncode + 3) & ~3u);
    P(obj)[0] = cls_Array;
    P(obj)[1] = HDR(2 * ncode, 0, 1);
    return code_base;
}
static Value here(void) { return code_base + 2 * ncode; }

enum { MOV = 1, ST, LEA, ADD, SUB, CMP, AND, OR, XOR, JEA = 0xB };
enum { EQ, NE, HS, LO, MI, PL, VS, VC, HI, LS, GE, LT, GT, LE, RA, LINK };
enum { R0, R1, R2, R3, R4, R5, R6, R7, R8, R9, R10, R11, R12, R13, R14, SP };
#define OPW(op, d, m, r) put((op) << 12 | (d) << 8 | (m) << 4 | (r))

static void ea_r(int op, int d, int r) { OPW(op, d, 0, r); }

static void ea_k(int op, int d, SValue v)
{
    if (v >= 0 && v <= 15)
        OPW(op, d, 1, v);
    else if (v >= -16 && v < 0)
        OPW(op, d, 0xD, -v - 1);
    else if (v >= -32768 && v <= 32767) {
        OPW(op, d, 0xF, 0);
        put(v);
    } else if ((unsigned)v <= 0xFFFF) {
        OPW(op, d, 0xF, 1);
        put(v);
    } else if (((unsigned)v & 0xFFFF) == 0) {
        OPW(op, d, 0xF, 2);
        put((unsigned)v >> 16);
    } else {
        OPW(op, d, 0xF, 3);
        put(v);
        put((unsigned)v >> 16);
    }
}

/* a 32-bit constant, always: its parcels can be patched */
static Value ea_k32(int op, int d, Value v)
{
    Value at;
    OPW(op, d, 0xF, 3);
    at = here();
    put(v);
    put(v >> 16);
    return at;
}

static void ea_m(int op, int d, int base, SValue disp)
{
    if (disp == 0)
        OPW(op, d, 2, base);
    else if (base == SP && disp >= 0 && disp <= 60 && !(disp & 3))
        OPW(op, d, 4, disp >> 2);
    else {
        OPW(op, d, 3, base);
        put(disp);
    }
}

static void ea_pi(int op, int d, int base) { OPW(op, d, 6, base); }
static void ea_pd(int op, int d, int base) { OPW(op, d, 7, base); }

static void ea_abs(int op, int d, Value a)
{
    if ((SValue)a >= -32768 && (SValue)a <= 32767) {
        OPW(op, d, 0xF, 4);
        put(a);
    } else {
        OPW(op, d, 0xF, 7);
        put(a);
        put(a >> 16);
    }
}

/* [base + x * (1 << slog) + d8], a word */
static void ea_idx(int op, int d, int base, int x, int slog, int d8)
{
    OPW(op, d, 5, base);
    put(x << 12 | slog << 10 | 2 << 8 | (d8 & 0xFF));
}

enum { NOT, NEG, INC, DEC, RLC, RRC, SWAP, SXB, ZXB, SXH, ZXH, CLZ };
static void un(int f, int d, int s) { put(0xC000 | d << 8 | s << 4 | f); }
enum { LSL, LSR, ASR, ROR };
static void shk(int kind, int d, int n) { put(0xD000 | d << 8 | (n & 15) << 4 | (n >= 16) << 2 | kind); }
static void shr(int kind, int d, int s) { put(0xD000 | d << 8 | s << 4 | 2 << 2 | kind); }
enum { ADC, SBC, BIC, TST, MULU, MULS, DIVU, DIVS, DIVUL };
static void rr(int f, int d, int s) { put(0xF000 | d << 8 | s << 4 | f); }
static void ret(void) { put(0x0004); }
static void jmp_r(int s) { put(0x0002 | s << 4); }
static void call_r(int s) { put(0x0003 | s << 4); }
static void mfhi(int d) { put(0x000A | d << 8 | 1 << 4); }
static void push(int r) { ea_pd(ST, r, SP); }
static void pop(int r) { ea_pi(MOV, r, SP); }

/* branches: Jcc with a 16-bit displacement (patched later), or to an
   absolute address */
static unsigned jcc_fwd(int c)
{
    put(0xA000 | c << 8);
    put(0);
    return ncode - 1;
}

static void jcc_to(int c, Value target)
{
    /* a Bcc if the target is in reach of its 8 bits (counted from the
       next parcel), else a Jcc with 16 */
    SValue d = ((SValue)target - (SValue)(here() + 2)) / 2;
    if (d >= -128 && d <= 127 && c != LINK) {
        put(0xE000 | c << 8 | (d & 0xFF));
        return;
    }
    put(0xA000 | c << 8);
    put(((SValue)target - (SValue)(here() + 2)) / 2);
}

static void patch_fwd(unsigned at, Value target)
{
    code[at] = ((SValue)target - (SValue)(code_base + 2 * at + 2)) / 2;
}

static Value jcc_abs(int c, Value target)
{
    Value at;
    put(0xA000 | c << 8 | 0x10);
    at = here();
    put(target);
    put(target >> 16);
    return at;
}

/* ---- inline caches -------------------------------------------------------------- */

typedef struct Site {
    Value class_at, target_at;      /* the patchable constants */
    Value start;                    /* the first instruction */
    Value super;                    /* for a super send, the class to look in */
} Site;
/* in chunks in the permanent space, each made before the code that uses it */
#define SITE_CHUNK 256
#define MAX_CHUNKS 32
static Site *site_chunks[MAX_CHUNKS];
static int nsites;
#define SITE(i) (&site_chunks[(i) / SITE_CHUNK][(i) % SITE_CHUNK])

/* room for n more sites before the code starts */
static void reserve_sites(int n)
{
    while ((nsites + n + SITE_CHUNK - 1) / SITE_CHUNK > 0
           && !site_chunks[(nsites + n - 1) / SITE_CHUNK]) {
        int c = (nsites + n - 1) / SITE_CHUNK;
        int k;
        for (k = 0; k <= c; k++)
            if (!site_chunks[k]) {
                if (k >= MAX_CHUNKS)
                    fatal("jit: too many send sites");
                site_chunks[k] = (Site *)&F(perm_bytes(cls_Array, SITE_CHUNK * sizeof(Site)), 0);
            }
    }
}

static void patch32(Value at, Value v)
{
    ((unsigned short *)BP(at))[0] = v & 0xFFFF;
    ((unsigned short *)BP(at))[1] = v >> 16;
}

/* methods were added: every inline cache starts over */
void jit_flush_ics(void)
{
    int i;
    for (i = 0; i < nsites; i++)
        patch32(SITE(i)->class_at, 0);
}

/* ---- slow paths ------------------------------------------------------------------- */

/* A branch to code that sends the bytecode at ip to C: undo what the fast
   path did to the stack (adjust bytes), set r8 and go. */
/* Out-of-line code, after the method's body: a slow path (undo what the
   fast path did to the stack, set r8, go to C), a SmallInt receiver's
   class for a send, or a send's inline cache miss. */
enum { SK_SLOW, SK_INT, SK_MISS };
typedef struct Stub {
    Value ip;
    unsigned short branch;          /* the Jcc's displacement parcel */
    unsigned short back;            /* SK_INT: where to go on */
    unsigned short site;            /* SK_MISS */
    unsigned char kind;
    unsigned char adjust;           /* SK_SLOW: bytes to put back on the stack */
} Stub;
#define MAX_STUBS 1536
static Stub stubs[MAX_STUBS];
static int nstubs;

static Stub *stub(int kind, int c)
{
    Stub *s;
    if (nstubs >= MAX_STUBS)
        fatal("jit: too many slow paths in a method");
    s = &stubs[nstubs++];
    s->kind = kind;
    s->branch = jcc_fwd(c);
    return s;
}

static void to_slow(int c, Value ip, int adjust)
{
    Stub *s = stub(SK_SLOW, c);
    s->ip = ip;
    s->adjust = adjust;
}

static void emit_stubs(void)
{
    int i;
    for (i = 0; i < nstubs; i++) {
        Stub *s = &stubs[i];
        patch_fwd(s->branch, here());
        switch (s->kind) {
        case SK_SLOW:
            if (s->adjust)
                ea_k(ADD, R10, s->adjust);
            ea_k32(MOV, R8, s->ip);
            jcc_abs(RA, ADDR(jit_glue_slow));
            break;
        case SK_INT:
            ea_abs(MOV, R2, ADDR(&cls_Int));
            jcc_to(RA, code_base + 2 * s->back);
            break;
        case SK_MISS:
            ea_k32(MOV, R8, s->ip);
            ea_k(MOV, R6, s->site);
            jcc_abs(RA, ADDR(jit_glue_send_miss));
            break;
        }
    }
}

/* the same, straight away (a bytecode with no fast path) */
static void go_slow(Value ip)
{
    ea_k32(MOV, R8, ip);
    jcc_abs(RA, ADDR(jit_glue_slow));
}

/* ---- the templates ------------------------------------------------------------------ */

typedef struct Fix {
    unsigned short at;              /* a forward branch's displacement parcel */
    unsigned short target;          /* bytecode offset */
} Fix;
#define MAX_FIXES 2048
static Fix fixes[MAX_FIXES];
static int nfixes;
static unsigned short *native_at;      /* bytecode offset -> parcel, or 0xFFFF */

static void branch_to(int c, unsigned target)
{
    if (native_at[target] != 0xFFFF) {
        jcc_to(c, code_base + 2 * native_at[target]);
        return;
    }
    if (nfixes >= MAX_FIXES)
        fatal("jit: too many branches in a method");
    fixes[nfixes].at = jcc_fwd(c);
    fixes[nfixes].target = target;
    nfixes++;
}

#define SLOT(i) (4 * (i))
#define FLD(i) (8 + 4 * (i))

/* r1 = b, r2 = a for a binary operator's fast path: both popped */
static void pop2(void)
{
    ea_pd(MOV, R2, R10);
    ea_pd(MOV, R1, R10);
}

/* both SmallInts, or to the slow path (with the two operands back) */
static void tag2(Value ip)
{
    ea_r(MOV, R3, R1);
    ea_r(AND, R3, R2);
    ea_k(AND, R3, 1);
    to_slow(EQ, ip, 8);
}

static void push_bool(int cond_false)
{
    /* the flags are set; TRUE unless cond_false holds */
    unsigned f = jcc_fwd(cond_false), e;
    ea_k(MOV, R1, TRUE_V);
    e = jcc_fwd(RA);
    patch_fwd(f, here());
    ea_k(MOV, R1, FALSE_V);
    patch_fwd(e, here());
    ea_pi(ST, R1, R10);
}

static int opcode_len(unsigned char *p)
{
    switch (p[0]) {
    case OP_PUSH_INT: case OP_PUSH_LIT: case OP_PUSH_LOCAL: case OP_STORE_LOCAL: case OP_POP_LOCAL:
    case OP_PUSH_BOXED: case OP_STORE_BOXED: case OP_PUSH_CAPT: case OP_STORE_CAPT:
    case OP_PUSH_CAPT_BOXED: case OP_STORE_CAPT_BOXED: case OP_PUSH_IVAR: case OP_STORE_IVAR:
    case OP_PUSH_BIVAR: case OP_STORE_BIVAR: case OP_PUSH_GLOBAL: case OP_STORE_GLOBAL:
    case OP_MAKE_LIST: case OP_MAKE_MAP: case OP_MAKE_RANGE: case OP_CONCAT: case OP_ITER_PREP:
    case OP_MAKE_BOX:
        return 2;
    case OP_SEND: case OP_SEND_SUPER: case OP_JUMP: case OP_JUMP_FALSE: case OP_JUMP_TRUE:
    case OP_JUMP_FALSE_OR_POP: case OP_JUMP_TRUE_OR_POP: case OP_RANGE_PREP: case OP_TRY:
    case OP_INC_LOCAL:
        return 3;
    case OP_RANGE_NEXT: case OP_ITER_NEXT:
        return 4;
    case OP_CLOSURE:
        return 3 + 2 * p[2];
    }
    return 1;
}

#define W16(p) ((SValue)(short)((p)[0] | (p)[1] << 8))

/* a send: the inline cache; super != 0 for a super send */
static void send_site(Value ip, int argc, Value super)
{
    Site *s;
    Stub *st, *to_int = 0;
    s = SITE(nsites);
    s->start = here();
    s->super = super;
    ea_m(LEA, R4, R10, -4 * (argc + 1));    /* the receiver: the callee's bp */
    if (super) {
        ea_k32(MOV, R2, super);
    } else {
        ea_m(MOV, R1, R4, 0);
        un(RRC, R2, R1);
        to_int = stub(SK_INT, HS);
        ea_m(MOV, R2, R1, 0);
    }
    if (to_int)
        to_int->back = ncode;
    s->class_at = ea_k32(CMP, R2, 0);
    st = stub(SK_MISS, NE);
    st->ip = ip + 3;
    st->site = nsites;
    ea_k32(MOV, R8, ip + 3);
    s->target_at = jcc_abs(LINK, 0);
    nsites++;
}

static Value lit_of(Value *lits, unsigned char *p) { return lits[p[1]]; }

Value jit_closure(Value *bp, Frame *fp, unsigned char *ip);

/* the body of one bytecode at p (offset off); returns its length */
static int template(Value m, Value *lits, unsigned char *start, unsigned char *p)
{
    Value ip = V(p);
    unsigned off = p - start;
    int op = p[0], len = opcode_len(p);
    unsigned next = off + len;
    switch (op) {
    case OP_PUSH_NIL:
        ea_pi(ST, R14, R10);
        break;
    case OP_PUSH_TRUE:
    case OP_PUSH_FALSE:
        ea_k(MOV, R1, op == OP_PUSH_TRUE ? TRUE_V : FALSE_V);
        ea_pi(ST, R1, R10);
        break;
    case OP_PUSH_SELF:
        ea_m(MOV, R1, R9, 0);
        ea_pi(ST, R1, R10);
        break;
    case OP_PUSH_BSELF:
        ea_m(MOV, R1, R9, 0);
        ea_m(MOV, R1, R1, FLD(CL_SELF));
        ea_pi(ST, R1, R10);
        break;
    case OP_PUSH_INT:
        ea_k(MOV, R1, MKINT((signed char)p[1]));
        ea_pi(ST, R1, R10);
        break;
    case OP_PUSH_LIT:
        ea_k(MOV, R1, lit_of(lits, p));
        ea_pi(ST, R1, R10);
        break;
    case OP_PUSH_LOCAL:
        ea_m(MOV, R1, R9, SLOT(p[1]));
        ea_pi(ST, R1, R10);
        break;
    case OP_STORE_LOCAL:
        ea_m(MOV, R1, R10, -4);
        ea_m(ST, R1, R9, SLOT(p[1]));
        break;
    case OP_POP_LOCAL:
        ea_pd(MOV, R1, R10);
        ea_m(ST, R1, R9, SLOT(p[1]));
        break;
    case OP_PUSH_BOXED:
        ea_m(MOV, R1, R9, SLOT(p[1]));
        ea_m(MOV, R1, R1, FLD(0));
        ea_pi(ST, R1, R10);
        break;
    case OP_STORE_BOXED:
        ea_m(MOV, R1, R9, SLOT(p[1]));
        ea_m(MOV, R2, R10, -4);
        ea_m(ST, R2, R1, FLD(0));
        break;
    case OP_PUSH_CAPT:
    case OP_PUSH_CAPT_BOXED:
        ea_m(MOV, R1, R9, 0);
        ea_m(MOV, R1, R1, FLD(CL_CAPT + p[1]));
        if (op == OP_PUSH_CAPT_BOXED)
            ea_m(MOV, R1, R1, FLD(0));
        ea_pi(ST, R1, R10);
        break;
    case OP_STORE_CAPT:
        ea_m(MOV, R1, R9, 0);
        ea_m(MOV, R2, R10, -4);
        ea_m(ST, R2, R1, FLD(CL_CAPT + p[1]));
        break;
    case OP_STORE_CAPT_BOXED:
        ea_m(MOV, R1, R9, 0);
        ea_m(MOV, R1, R1, FLD(CL_CAPT + p[1]));
        ea_m(MOV, R2, R10, -4);
        ea_m(ST, R2, R1, FLD(0));
        break;
    case OP_PUSH_IVAR:
    case OP_PUSH_BIVAR:
        ea_m(MOV, R1, R9, 0);
        if (op == OP_PUSH_BIVAR)
            ea_m(MOV, R1, R1, FLD(CL_SELF));
        ea_m(MOV, R1, R1, FLD(p[1]));
        ea_pi(ST, R1, R10);
        break;
    case OP_STORE_IVAR:
    case OP_STORE_BIVAR:
        ea_m(MOV, R1, R9, 0);
        if (op == OP_STORE_BIVAR)
            ea_m(MOV, R1, R1, FLD(CL_SELF));
        ea_m(MOV, R2, R10, -4);
        ea_m(ST, R2, R1, FLD(p[1]));
        break;
    case OP_PUSH_GLOBAL:
        ea_abs(MOV, R1, lit_of(lits, p));
        to_slow(EQ, ip, 0);
        ea_pi(ST, R1, R10);
        break;
    case OP_STORE_GLOBAL:
        ea_m(MOV, R1, R10, -4);
        ea_abs(ST, R1, lit_of(lits, p));
        break;
    case OP_POP:
        ea_k(SUB, R10, 4);
        break;
    case OP_DUP:
        ea_m(MOV, R1, R10, -4);
        ea_pi(ST, R1, R10);
        break;

    case OP_SEND:
        send_site(ip, p[2], 0);
        break;
    case OP_SEND_SUPER: {
        Value super = F(F(m, M_OWNER), C_SUPER);
        if (super == NIL)
            go_slow(ip);
        else
            send_site(ip, p[2], super);
        break;
    }

    case OP_ADD:
    case OP_SUB:
        pop2();
        tag2(ip);
        un(DEC, R2, R2);
        ea_r(op == OP_ADD ? ADD : SUB, R1, R2);
        to_slow(VS, ip, 8);
        ea_pi(ST, R1, R10);
        break;
    case OP_MUL:
        pop2();
        tag2(ip);
        shk(ASR, R1, 1);
        un(DEC, R2, R2);
        rr(MULS, R1, R2);
        to_slow(VS, ip, 8);
        un(INC, R1, R1);
        ea_pi(ST, R1, R10);
        break;
    case OP_DIV:
    case OP_MOD: {
        unsigned skip;
        pop2();
        tag2(ip);
        ea_k(CMP, R2, 1);
        to_slow(EQ, ip, 8);
        ea_k(CMP, R2, -1);
        to_slow(EQ, ip, 8);
        shk(ASR, R1, 1);
        shk(ASR, R2, 1);
        rr(DIVS, R1, R2);
        mfhi(R3);
        rr(TST, R3, R3);
        skip = jcc_fwd(EQ);
        if (op == OP_DIV) {
            ea_r(XOR, R3, R2);
            {
                unsigned s2 = jcc_fwd(PL);
                un(DEC, R1, R1);
                patch_fwd(s2, here());
            }
            patch_fwd(skip, here());
        } else {
            unsigned s2;
            ea_r(MOV, R4, R3);
            ea_r(XOR, R4, R2);
            s2 = jcc_fwd(PL);
            ea_r(ADD, R3, R2);
            patch_fwd(s2, here());
            patch_fwd(skip, here());
            ea_r(MOV, R1, R3);
        }
        ea_idx(LEA, R1, R0, R1, 1, 1);
        ea_pi(ST, R1, R10);
        break;
    }
    case OP_LT: case OP_LE: case OP_GT: case OP_GE: {
        /* followed by a conditional jump: compare and branch, with no
           boolean (the jump's own code is still there, for a slow path
           that comes back with the boolean on the stack) */
        static const int false_cond[] = { GE, GT, LE, LT };
        static const int true_cond[] = { LT, LE, GT, GE };
        int k = op - OP_LT;
        pop2();
        tag2(ip);
        ea_r(CMP, R1, R2);
        if (p[1] == OP_JUMP_FALSE || p[1] == OP_JUMP_TRUE) {
            unsigned tgt = next + 3 + W16(p + 2);
            branch_to(p[1] == OP_JUMP_FALSE ? false_cond[k] : true_cond[k], tgt);
            branch_to(RA, next + 3);
        } else {
            push_bool(false_cond[k]);
        }
        break;
    }
    case OP_EQ: {
        unsigned t, f1, f2, f3, done;
        pop2();
        ea_r(CMP, R1, R2);
        t = jcc_fwd(EQ);
        ea_r(MOV, R3, R1);
        ea_r(OR, R3, R2);
        ea_k(AND, R3, 1);
        f1 = jcc_fwd(NE);
        ea_m(LEA, R3, R1, -FALSE_V);
        ea_k(CMP, R3, TRUE_V - FALSE_V);
        f2 = jcc_fwd(LS);
        ea_m(LEA, R3, R2, -FALSE_V);
        ea_k(CMP, R3, TRUE_V - FALSE_V);
        f3 = jcc_fwd(LS);
        ea_k(ADD, R10, 8);
        go_slow(ip);
        patch_fwd(t, here());
        ea_k(MOV, R1, TRUE_V);
        done = jcc_fwd(RA);
        patch_fwd(f1, here());
        patch_fwd(f2, here());
        patch_fwd(f3, here());
        ea_k(MOV, R1, FALSE_V);
        patch_fwd(done, here());
        ea_pi(ST, R1, R10);
        break;
    }
    case OP_BAND: case OP_BOR: case OP_BXOR:
        pop2();
        tag2(ip);
        ea_r(op == OP_BAND ? AND : op == OP_BOR ? OR : XOR, R1, R2);
        if (op == OP_BXOR)
            ea_k(OR, R1, 1);
        ea_pi(ST, R1, R10);
        break;
    case OP_SHL:
        pop2();
        tag2(ip);
        shk(ASR, R2, 1);
        ea_k(CMP, R2, 30);
        to_slow(HI, ip, 8);
        un(DEC, R1, R1);
        ea_r(MOV, R3, R1);
        shr(LSL, R3, R2);
        ea_r(MOV, R4, R3);
        shr(ASR, R4, R2);
        ea_r(CMP, R4, R1);
        to_slow(NE, ip, 8);
        un(INC, R3, R3);
        ea_pi(ST, R3, R10);
        break;
    case OP_SHR:
        pop2();
        tag2(ip);
        shk(ASR, R2, 1);
        ea_k(CMP, R2, 31);
        to_slow(HI, ip, 8);
        shr(ASR, R1, R2);
        ea_k(OR, R1, 1);
        ea_pi(ST, R1, R10);
        break;
    case OP_AT:
        ea_m(MOV, R2, R10, -4);         /* the index */
        ea_m(MOV, R1, R10, -8);         /* the List */
        un(RRC, R3, R2);
        to_slow(LO, ip, 0);
        un(RRC, R3, R1);
        to_slow(HS, ip, 0);
        ea_m(MOV, R3, R1, 0);
        ea_abs(CMP, R3, ADDR(&cls_List));
        to_slow(NE, ip, 0);
        ea_m(CMP, R2, R1, FLD(L_SIZE));
        to_slow(HS, ip, 0);
        ea_m(MOV, R3, R1, FLD(L_ITEMS));
        shk(ASR, R2, 1);
        ea_idx(MOV, R1, R3, R2, 2, 8);
        ea_k(SUB, R10, 4);
        ea_m(ST, R1, R10, -4);
        break;
    case OP_AT_PUT:
        ea_m(MOV, R4, R10, -4);         /* the value */
        ea_m(MOV, R2, R10, -8);         /* the index */
        ea_m(MOV, R1, R10, -12);        /* the List */
        un(RRC, R3, R2);
        to_slow(LO, ip, 0);
        un(RRC, R3, R1);
        to_slow(HS, ip, 0);
        ea_m(MOV, R3, R1, 0);
        ea_abs(CMP, R3, ADDR(&cls_List));
        to_slow(NE, ip, 0);
        ea_m(CMP, R2, R1, FLD(L_SIZE));
        to_slow(HS, ip, 0);
        ea_m(MOV, R3, R1, FLD(L_ITEMS));
        shk(ASR, R2, 1);
        ea_idx(ST, R4, R3, R2, 2, 8);
        ea_k(SUB, R10, 8);
        ea_m(ST, R4, R10, -4);
        break;
    case OP_NOT:
        ea_pd(MOV, R1, R10);
        ea_k(OR, R1, 8);
        ea_r(CMP, R1, R14);
        push_bool(NE);
        break;

    case OP_JUMP:
        branch_to(RA, next + W16(p + 1));
        break;
    case OP_JUMP_FALSE:
    case OP_JUMP_TRUE:
        ea_pd(MOV, R1, R10);
        ea_k(OR, R1, 8);
        ea_r(CMP, R1, R14);
        branch_to(op == OP_JUMP_FALSE ? EQ : NE, next + W16(p + 1));
        break;
    case OP_JUMP_FALSE_OR_POP:
    case OP_JUMP_TRUE_OR_POP:
        ea_m(MOV, R1, R10, -4);
        ea_k(OR, R1, 8);
        ea_r(CMP, R1, R14);
        branch_to(op == OP_JUMP_FALSE_OR_POP ? EQ : NE, next + W16(p + 1));
        ea_k(SUB, R10, 4);
        break;

    case OP_RANGE_NEXT:                 /* slot = the counter, slot + 1 = the last */
        ea_m(MOV, R1, R9, SLOT(p[1]));
        ea_k(ADD, R1, 2);
        ea_m(CMP, R1, R9, SLOT(p[1] + 1));
        branch_to(GT, next + W16(p + 2));
        ea_m(ST, R1, R9, SLOT(p[1]));
        ea_pi(ST, R1, R10);
        break;
    case OP_ITER_NEXT: {
        unsigned range, done;
        ea_m(MOV, R2, R9, SLOT(p[1]));
        ea_m(MOV, R3, R2, 0);
        ea_abs(CMP, R3, ADDR(&cls_List));
        range = jcc_fwd(NE);
        ea_m(MOV, R3, R9, SLOT(p[1] + 1));
        ea_m(CMP, R3, R2, FLD(L_SIZE));
        branch_to(GE, next + W16(p + 2));
        ea_m(MOV, R4, R2, FLD(L_ITEMS));
        ea_r(MOV, R5, R3);
        shk(ASR, R5, 1);
        ea_idx(MOV, R5, R4, R5, 2, 8);
        ea_pi(ST, R5, R10);
        ea_k(ADD, R3, 2);
        ea_m(ST, R3, R9, SLOT(p[1] + 1));
        done = jcc_fwd(RA);
        patch_fwd(range, here());
        ea_m(MOV, R3, R9, SLOT(p[1] + 1));
        ea_k(ADD, R3, 2);
        ea_m(CMP, R3, R2, FLD(R_LAST));
        branch_to(GT, next + W16(p + 2));
        ea_m(ST, R3, R9, SLOT(p[1] + 1));
        ea_pi(ST, R3, R10);
        patch_fwd(done, here());
        break;
    }
    case OP_INC_LOCAL: {
        /* a SmallInt in the slot: add and jump over the general code that
           follows; otherwise fall into it */
        SValue step = (signed char)p[2];
        unsigned gen1, gen2;
        ea_m(MOV, R1, R9, SLOT(p[1]));
        un(RRC, R2, R1);
        gen1 = jcc_fwd(LO);
        ea_k(ADD, R1, 2 * step);
        gen2 = jcc_fwd(VS);
        ea_m(ST, R1, R9, SLOT(p[1]));
        branch_to(RA, next + 7);
        patch_fwd(gen1, here());
        patch_fwd(gen2, here());
        break;
    }

    case OP_CLOSURE:
        ea_m(LEA, R1, R10, -4);
        ea_abs(ST, R1, ADDR(&vm_sp));
        ea_r(MOV, R1, R9);
        ea_r(MOV, R2, R11);
        ea_k32(MOV, R3, ip + 1);
        jcc_abs(LINK, V((char *)jit_closure));
        ea_pi(ST, R1, R10);
        break;

    case OP_RETURN: {
        unsigned flags, retp;
        ea_pd(MOV, R1, R10);
        ea_m(MOV, R2, R11, 16);         /* Frame.flags */
        flags = jcc_fwd(NE);
        retp = ncode;
        ea_m(ST, R1, R9, 0);
        ea_m(LEA, R10, R9, 4);
        ea_m(LEA, R11, R11, -(SValue)sizeof(Frame));
        ea_m(MOV, R9, R11, 4);
        ea_m(MOV, R2, R11, 8);
        ea_m(MOV, R12, R2, FLD(M_LITSP));
        ea_m(JEA, 0, R11, 20);          /* JMP [r11 + nip] */
        patch_fwd(flags, here());
        ea_k(CMP, R2, FR_CONSTRUCT);
        {
            unsigned slow = jcc_fwd(NE);
            ea_m(MOV, R1, R9, 0);       /* new: the object, not init's result */
            jcc_to(RA, code_base + 2 * retp);
            patch_fwd(slow, here());
            ea_k(ADD, R10, 4);
            go_slow(ip);
        }
        break;
    }

    default:
        /* RETURN_NLR, the makers, the loop preparations, try, boxes: C */
        go_slow(ip);
        break;
    }
    (void)lits;
    return len;
}

/* ---- methods -------------------------------------------------------------------- */

#define NEW_ENTRY 4                 /* bytes from the new entry to the plain one */

static void prologue(Value m)
{
    unsigned over, over2 = 0, nl = F(m, M_NLOCALS), i;
    unsigned to_push;
    /* entry - 4: for new, the frame returns the receiver */
    ea_k(MOV, R5, FR_CONSTRUCT);
    to_push = jcc_fwd(RA);
    /* entry */
    ea_k(MOV, R5, 0);
    patch_fwd(to_push, here());
    pop(R1);                                    /* where the caller goes on */
    ea_m(ST, R1, R11, 20);                      /* Frame.nip */
    ea_m(ST, R8, R11, 0);                       /* Frame.ip */
    ea_m(LEA, R11, R11, sizeof(Frame));
    ea_abs(CMP, R11, ADDR(&egret_frames_end));
    over = jcc_fwd(HS);
    ea_m(ST, R4, R11, 4);
    ea_k32(MOV, R1, m);
    ea_m(ST, R1, R11, 8);
    ea_m(ST, R0, R11, 12);
    ea_m(ST, R5, R11, 16);
    ea_r(MOV, R9, R4);
    if (nl) {
        ea_abs(CMP, R10, ADDR(&egret_vstack_end));
        over2 = jcc_fwd(HS);
        for (i = 0; i < nl; i++)
            ea_pi(ST, R14, R10);
    }
    ea_k32(MOV, R12, F(m, M_LITSP));
    {
        unsigned body = jcc_fwd(RA);
        /* too deep: undo, and let C make the send again (and raise) */
        if (over2) {
            patch_fwd(over2, here());
            ea_m(MOV, R9, R11, 4 - (SValue)sizeof(Frame));
        }
        patch_fwd(over, here());
        ea_m(LEA, R11, R11, -(SValue)sizeof(Frame));
        ea_k(CMP, R5, FR_CONSTRUCT);            /* new: put the class back */
        {
            unsigned plain = jcc_fwd(NE);
            ea_m(MOV, R1, R4, 0);
            ea_m(MOV, R1, R1, 0);
            ea_m(ST, R1, R4, 0);
            patch_fwd(plain, here());
        }
        ea_k(SUB, R8, 3);
        jcc_abs(RA, ADDR(jit_glue_slow));
        patch_fwd(body, here());
    }
}

/* Compiles m: its native code and map in the permanent space, and
   M_NATIVE (the plain entry) and M_NMAP. */
void jit_compile(Value m)
{
    unsigned char *start = BYTES(F(m, M_CODE)), *p, *end;
    Value *lits = P(F(m, M_LITSP));
    unsigned n = SIZE(F(m, M_CODE)), i;
    int nsends = 0;
    char *mark;
    Value map;
    if (F(m, M_NATIVE))
        return;
    end = start + n;
    for (p = start; p < end; p += opcode_len(p))
        nsends += p[0] == OP_SEND || p[0] == OP_SEND_SUPER;
    reserve_sites(nsends);
    mark = scratch_mark();
    native_at = (unsigned short *)scratch_alloc(2 * n);
    nfixes = 0;
    nstubs = 0;
    for (i = 0; i < n; i++)
        native_at[i] = 0xFFFF;
    begin_code();
    prologue(m);
    for (p = start; p < end;) {
        native_at[p - start] = ncode;
        p += template(m, lits, start, p);
    }
    emit_stubs();
    for (i = 0; i < (unsigned)nfixes; i++) {
        unsigned t = native_at[fixes[i].target];
        if (t == 0xFFFF)
            fatal("jit: a branch into the middle of a bytecode");
        patch_fwd(fixes[i].at, code_base + 2 * t);
    }
    end_code();
    map = perm_bytes(cls_Array, 2 * n);
    memcpy(BYTES(map), native_at, 2 * n);
    F(m, M_NMAP) = V(BYTES(map));
    F(m, M_NATIVE) = code_base + NEW_ENTRY;
#ifdef EGRET_STATS
    stats.native_bytes += 2 * ncode;
#endif
    scratch_release(mark);
}

/* where the native code for the bytecode at ip of method goes on */
Value jit_resume_addr(Value method, unsigned char *ip)
{
    unsigned off;
    unsigned short at;
    if (!F(method, M_NATIVE))
        jit_compile(method);
    off = ip - BYTES(F(method, M_CODE));
    at = ((unsigned short *)P(F(method, M_NMAP)))[off];
    if (at == 0xFFFF)
        fatal("jit: no native code for this bytecode");
    return F(method, M_NATIVE) - NEW_ENTRY + 2 * at;
}

typedef struct VMState {
    Value *sp, *bp;
    Frame *fp;
    unsigned char *ip;
    Value *lits;
} VMStateHead;                              /* the start of interp.c's VMState */

Value jit_resume(VMStateHead *st) { return jit_resume_addr(st->fp->method, st->ip); }

/* ---- stubs for what a send can find besides an Egret method ------------------------ */

static Value finish_stub(void) { return end_code(); }
static void begin_stub(void) { begin_code(); }

/* a C primitive with argc arguments: called like an Egret method's native
   entry (bp in r4, r8 where the caller goes on, the return address on the
   stack) */
static Value prim_stub(Value m)
{
    unsigned fail;
    if (F(m, M_NATIVE))
        return F(m, M_NATIVE);
    begin_stub();
    ea_m(LEA, R1, R10, -4);
    ea_abs(ST, R1, ADDR(&vm_sp));
    ea_r(MOV, R1, R4);
    ea_k(MOV, R2, MI_NARGS(F(m, M_INFO)));
    push(R4);
    jcc_abs(LINK, V((char *)prim_table[F(m, M_PRIM)]));
    pop(R4);
    rr(TST, R1, R1);
    fail = jcc_fwd(EQ);
    ea_m(ST, R1, R4, 0);
    ea_m(LEA, R10, R4, 4);
    ret();
    patch_fwd(fail, here());
    pop(R1);                                    /* no return: raise */
    jcc_abs(RA, ADDR(jit_glue_prim_failed));
    F(m, M_NATIVE) = finish_stub();
    return F(m, M_NATIVE);
}

/* a block's call with argc arguments */
static Value block_stubs[16];
static Value block_stub(int argc)
{
    unsigned slow1, slow2;
    if (block_stubs[argc])
        return block_stubs[argc];
    begin_stub();
    ea_m(MOV, R1, R4, 0);
    ea_m(MOV, R3, R1, FLD(CL_METHOD));
    ea_m(MOV, R2, R3, FLD(M_ARITY));
    ea_k(CMP, R2, argc);
    slow1 = jcc_fwd(NE);
    ea_m(MOV, R1, R3, FLD(M_NATIVE));
    slow2 = jcc_fwd(EQ);
    jmp_r(R1);
    patch_fwd(slow1, here());
    patch_fwd(slow2, here());
    pop(R1);
    ea_k(SUB, R8, 3);                           /* C makes the send */
    jcc_abs(RA, ADDR(jit_glue_slow));
    return block_stubs[argc] = finish_stub();
}

/* new (or call) of a class of plain objects, with argc arguments for init:
   when init is in the method cache and compiled, make the object here and
   go to init's new entry */
static Value new_stubs[16];
static Value new_stub(int argc)
{
    unsigned s[6], i;
    if (new_stubs[argc])
        return new_stubs[argc];
    begin_stub();
    ea_m(MOV, R1, R4, 0);                       /* the class */
    ea_m(MOV, R2, R1, FLD(C_KIND));
    ea_k(CMP, R2, MKINT(K_OBJECT));
    s[0] = jcc_fwd(NE);
    ea_abs(MOV, R2, ADDR(&sym_init));
    ea_r(MOV, R3, R1);
    ea_r(XOR, R3, R2);
    ea_k(AND, R3, 0xFFC);
    ea_m(CMP, R1, R3, ADDR(mcache_cls));
    s[1] = jcc_fwd(NE);
    ea_m(CMP, R2, R3, ADDR(mcache_sel));
    s[2] = jcc_fwd(NE);
    ea_m(MOV, R3, R3, ADDR(mcache_method));
    ea_m(MOV, R2, R3, FLD(M_ARITY));
    ea_k(CMP, R2, argc);
    s[3] = jcc_fwd(NE);
    ea_m(MOV, R5, R3, FLD(M_NATIVE));
    s[4] = jcc_fwd(EQ);
    ea_m(LEA, R2, R10, -4);
    ea_abs(ST, R2, ADDR(&vm_sp));
    push(R4);
    push(R5);
    ea_m(MOV, R2, R1, FLD(C_NIVARS));
    shk(ASR, R2, 1);
    jcc_abs(LINK, V((char *)alloc_obj));
    pop(R5);
    pop(R4);
    ea_m(ST, R1, R4, 0);                        /* the object in place of the class */
    ea_k(SUB, R5, NEW_ENTRY);
    jmp_r(R5);
    for (i = 0; i < 5; i++)
        patch_fwd(s[i], here());
    pop(R1);
    ea_k(SUB, R8, 3);
    jcc_abs(RA, ADDR(jit_glue_slow));
    return new_stubs[argc] = finish_stub();
}

/* ---- the inline caches' misses ----------------------------------------------------- */

extern Value egret_lookup(Value cls, Value sel);

/* The send at st->ip (the SEND bytecode) missed its inline cache: bind the
   site to what the send finds, and return the site's address to run it
   again; or 0, and the glue has C make the send. */
Value jit_send_miss(VMStateHead *st, int si)
{
    Site *s = SITE(si);
    unsigned char *ip = st->ip;
    Value sel = st->lits[ip[1]], cls, m, target = 0, rcv;
    int argc = ip[2];
    rcv = st->sp[-argc];
    cls = s->super ? s->super : CLASS_OF(rcv);
    m = egret_lookup(cls, sel);
    if (!m)
        return 0;
    if (F(m, M_ARITY) == (Value)argc) {
        jit_compile(m);
        target = F(m, M_NATIVE);
    } else if (F(m, M_ARITY) == ARITY_PRIM + (Value)argc) {
        target = prim_stub(m);
    } else if (m == egret_blockcall && argc < 16) {
        target = block_stub(argc);
    } else if (F(m, M_PRIM) == PR_NEW && argc < 16) {
        target = new_stub(argc);
    }
    if (!target)
        return 0;
    patch32(s->class_at, cls);
    patch32(s->target_at, target);
    return s->start;
}

/* CLOSURE, from native code: ip points at its operands */
Value jit_closure(Value *bp, Frame *fp, unsigned char *ip)
{
    Value bm = P(F(fp->method, M_LITSP))[ip[0]], c;
    unsigned n = ip[1], i;
    c = alloc_obj(cls_Block, CL_CAPT + n);
    F(c, CL_METHOD) = bm;
    if (F(fp->method, M_INFO) & MF_BLOCK) {
        Value outer = bp[0];
        F(c, CL_SELF) = F(outer, CL_SELF);
        F(c, CL_HOME) = F(outer, CL_HOME);
        F(c, CL_SERIAL) = F(outer, CL_SERIAL);
    } else {
        F(c, CL_SELF) = bp[0];
        F(c, CL_HOME) = V(fp);
        if (!fp->serial)
            fp->serial = egret_serial += 2;
        F(c, CL_SERIAL) = fp->serial;
    }
    for (i = 0; i < n; i++) {
        unsigned k = ip[2 + 2 * i], x = ip[3 + 2 * i];
        F(c, CL_CAPT + i) = k == CK_LOCAL ? bp[x] : F(bp[0], CL_CAPT + x);
    }
    return c;
}

#endif
