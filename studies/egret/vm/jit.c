/* A compiler from Egret's bytecode to draft 1b or draft 2 machine code
   (__V2__, which the C compiler defines for draft 2), running on the
   machine: each method is compiled the first time it runs.

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
   value stack's next free slot, r11 the frame, r12 the literals, r14 nil
   (on draft 2, interp_v2.s, the frame is r14 and nil r11: FP and NILR);
   r8 is set only when the bytecode's address is needed. A call passes the
   new frame's bp in r4 and the caller's bytecode address to go on at in
   r8; the callee's prologue pops the return address into the caller's
   frame (Frame.nip), so a return is JMP [fp + nip].

   On draft 2 a call leaves the return address in r7: the prologue stores
   it, stubs that call C keep it on the stack meanwhile, and the bytecode a
   send through the method cache passes (gsend) is in r5. */

#ifdef EGRET_JIT

#include "compiler.h"

/* the assembly side (jit_v1b.s, jit_v2.s) */
extern char jit_glue_slow[], jit_glue_send_miss[], jit_glue_prim_failed[], jit_glue_gsend_miss[],
    jit_glue_redo[];
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

static void code_full(void) { fatal("jit: out of permanent space for native code"); }

/* a macro, not a function: the C compiler doesn't inline, and a call
   cost more than the store (put was a third of compiling) */
#define put(w) do { if (ncode >= maxcode) code_full(); code[ncode++] = (w); } while (0)

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

enum { EQ, NE, HS, LO, MI, PL, VS, VC, HI, LS, GE, LT, GT, LE, RA, LINK };
enum { R0, R1, R2, R3, R4, R5, R6, R7, R8, R9, R10, R11, R12, R13, R14, SP };
#ifdef __V2__
/* Draft 2: a parcel is an opcode byte (its low byte) and a register byte
   (rd or a mode in bits 15-12, rs or the mode's register in 11-8). The
   two-operand operations are rows of the map, with the mode as the
   column; LEA has cells of its own, and JMP and CALL take the mode from
   the register byte. */
enum { MOV = 0x10, ST = 0x20, MOVS = 0x30, ADD = 0x40, SUB = 0x50, CMP = 0x60, AND = 0x80,
       OR = 0x90, XOR = 0xA0, LEA = 0x100, JEA = 0x200 };
#define SEND_IP R5                          /* the bytecode, for gsend: r7 is the link */
#define FP R14                              /* the frame record: mode E reaches its fields */
#define NILR R11
static void opw_other(int op, int d, int m, int r)
{
    if (op == LEA) {
        if (m == 2)                         /* LEA rd, [R] is MOV rd, R */
            put(MOV | d << 12 | r << 8);
        else
            put((m == 3 ? 0x04 : m == 4 ? 0x05 : m == 5 ? 0x06 : 0x07) | d << 12 | r << 8);
    } else
        put((0xF0 | d) | m << 12 | r << 8); /* JEA; d: 0 JMP, 1 CALL */
}
/* a macro for the rows, as put is (the C compiler doesn't inline) */
#define OPW(op, d, m, r) do { if ((op) < LEA) put((op) | (m) | (d) << 12 | (r) << 8); \
                              else opw_other(op, d, m, r); } while (0)
/* a short branch: cc and the 8-bit offset in parcels from the next */
#define BCC(c, d) put(0xB0 | (c) | ((d) & 0xFF) << 8)
#else
enum { MOV = 1, ST, LEA, ADD, SUB, CMP, AND, OR, XOR, JEA = 0xB };
#define MOVS MOV                            /* a MOV that sets N and Z: every MOV on 1b */
#define SEND_IP R7                          /* the bytecode, for gsend */
#define FP R11                              /* the frame record */
#define NILR R14
#define OPW(op, d, m, r) put((op) << 12 | (d) << 8 | (m) << 4 | (r))
#define BCC(c, d) put(0xE000 | c << 8 | (d & 0xFF))
#endif

static void ea_r(int op, int d, int r) { OPW(op, d, 0, r); }

static void ea_k(int op, int d, SValue v)
{
    if (v >= 0 && v <= 15)
        OPW(op, d, 1, v);
#ifdef __V2__
    else if ((op == MOV || op == CMP) && v >= 16 && v <= 127)
        put((op == MOV ? 0x70 : 0x78) | (v & 7) | d << 12 | (v >> 3) << 8);
#endif
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
#ifdef __V2__
    else if (base == R14 && op != LEA && disp >= 0 && disp <= 60 && !(disp & 3))
        OPW(op, d, 0xE, disp >> 2);         /* [r14 + 4R], mode E */
#endif
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

enum { LSL, LSR, ASR, ROR };
#ifdef __V2__
enum { NOT, NEG, INC, DEC, RLC, RRC, SWAP, SXB, SXH, ZXB, ZXH, CLZ };
static void un(int f, int d, int s) { put((0xD0 + f) | d << 12 | s << 8); }
static void shk(int kind, int d, int n) { put((0xC0 + 4 * kind + (n & 1)) | d << 12 | (n >> 1) << 8); }
static void shr(int kind, int d, int s) { put((0xC2 + 4 * kind) | d << 12 | s << 8); }
enum { ADC, SBC, BIC, TST, MULU, MULS, MULA, DIVU, DIVS, DIVUL };
static void rr(int f, int d, int s) { put((0xE0 + f) | d << 12 | s << 8); }
static void ret(void) { put(0xF0 | R7 << 8); }      /* JMP r7 */
static void jmp_r(int s) { put(0xF0 | s << 8); }
static void call_r(int s) { put(0xF1 | s << 8); }
static void mfhi(int d) { put(0x0E | d << 12 | 1 << 8); }
/* CLR [base + disp] */
static void clr_m(int base, SValue disp)
{
    if (base == R14 && disp >= 0 && disp <= 60 && !(disp & 3)) {
        put(0x20 | 0xE << 12 | (disp >> 2) << 8);
        return;
    }
    put(0x20 | 3 << 12 | base << 8);
    put(disp);
}
#define JCC_REL(c) put(0xF2 | (c) << 12)   /* Jcc with a 16-bit displacement */
#define JCC_ABS(c) put(0xF3 | (c) << 12)   /* Jcc to a 32-bit address */
#else
enum { NOT, NEG, INC, DEC, RLC, RRC, SWAP, SXB, ZXB, SXH, ZXH, CLZ };
static void un(int f, int d, int s) { put(0xC000 | d << 8 | s << 4 | f); }
static void shk(int kind, int d, int n) { put(0xD000 | d << 8 | (n & 15) << 4 | (n >= 16) << 2 | kind); }
static void shr(int kind, int d, int s) { put(0xD000 | d << 8 | s << 4 | 2 << 2 | kind); }
enum { ADC, SBC, BIC, TST, MULU, MULS, DIVU, DIVS, DIVUL };
static void rr(int f, int d, int s) { put(0xF000 | d << 8 | s << 4 | f); }
static void ret(void) { put(0x0004); }
static void jmp_r(int s) { put(0x0002 | s << 4); }
static void call_r(int s) { put(0x0003 | s << 4); }
static void mfhi(int d) { put(0x000A | d << 8 | 1 << 4); }
#define JCC_REL(c) put(0xA000 | c << 8)
#define JCC_ABS(c) put(0xA000 | c << 8 | 0x10)
#endif
static void push(int r) { ea_pd(ST, r, SP); }
static void pop(int r) { ea_pi(MOV, r, SP); }

/* branches: Jcc with a 16-bit displacement (patched later), or to an
   absolute address */
static unsigned jcc_fwd(int c)
{
    JCC_REL(c);
    put(0);
    return ncode - 1;
}

static void jcc_to(int c, Value target)
{
    /* a Bcc if the target is in reach of its 8 bits (counted from the
       next parcel), else a Jcc with 16 */
    SValue d = ((SValue)target - (SValue)(here() + 2)) / 2;
    if (d >= -128 && d <= 127 && c != LINK) {
        BCC(c, d);
        return;
    }
    JCC_REL(c);
    put(((SValue)target - (SValue)(here() + 2)) / 2);
}

static void patch_fwd(unsigned at, Value target)
{
    code[at] = ((SValue)target - (SValue)(code_base + 2 * at + 2)) / 2;
}

static Value jcc_abs(int c, Value target)
{
    Value at;
    JCC_ABS(c);
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
    Value misses;                   /* how often it was bound */
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
   fast path did to the stack, set r8, go to C), an operator's send when
   its fast path doesn't apply, a SmallInt receiver's class for a send, or
   a send's inline cache miss. */
enum { SK_SLOW, SK_SEND, SK_INT, SK_MISS, SK_OVER, SK_OVER2 };
typedef struct Stub {
    Value ip;
    Value konst;                    /* SK_SEND: a constant operand to push, or 0 */
    unsigned short branch;          /* the Jcc's displacement parcel */
    unsigned short back;            /* SK_INT: where to go on; SK_SEND: where it starts */
    unsigned short site;            /* SK_MISS */
    unsigned char kind;
    unsigned char adjust;           /* SK_SLOW, SK_SEND: bytes to put back on the stack */
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

static int is_operator(int op) { return op >= OP_ADD && op <= OP_SHR; }

/* the slow path of the bytecode at ip: an operator sends its selector,
   anything else goes to C */
static Stub *to_slow(int c, Value ip, int adjust)
{
    Stub *s = stub(is_operator(*BP(ip)) ? SK_SEND : SK_SLOW, c);
    s->ip = ip;
    s->adjust = adjust;
    s->konst = 0;
    return s;
}

/* the slow path of PUSH_INT k fused with the operator at ip: push k and
   send the operator */
static void to_send_k(int c, Value ip, int adjust, Value k)
{
    to_slow(c, ip, adjust)->konst = k;
}

static void branch_to(int c, unsigned target);
static unsigned char *bc_start;
static Value gsend(int argc);
extern Value egret_special[];
extern Value egret_find(Value cls, Value sel);
#define OP_ENTRY 4                  /* bytes from gsend's entry for operators to the plain one */

static void emit_stubs(void)
{
    int i;
    /* (the sends add stubs as they go) */
    for (i = 0; i < nstubs; i++) {
        Stub *s = &stubs[i], *t = i ? s - 1 : 0;
        if (s->kind == SK_SEND && t && t->kind == SK_SEND && t->ip == s->ip
            && t->adjust == s->adjust && t->konst == s->konst) {
            /* a template's slow paths share one send */
            s->back = t->back;
            patch_fwd(s->branch, code_base + 2 * s->back);
            continue;
        }
        patch_fwd(s->branch, here());
        switch (s->kind) {
        case SK_SLOW:
            if (s->adjust)
                ea_k(ADD, R10, s->adjust);
            ea_k32(MOV, R8, s->ip);
            jcc_abs(RA, ADDR(jit_glue_slow));
            break;
        case SK_SEND: {
            /* the operands back on the stack, the selector in r6 and the
               bytecode in r7 (r5 on draft 2: SEND_IP), for a send through
               the method cache (gsend) */
            unsigned char *p = BP(s->ip);
            s->back = ncode;
            if (s->adjust)
                ea_k(ADD, R10, s->adjust);
            if (s->konst) {
                ea_k(MOV, R1, s->konst);
                ea_pi(ST, R1, R10);
            }
            ea_k(MOV, R6, egret_special[p[0]]);
            ea_k32(MOV, SEND_IP, s->ip);
            jcc_abs(LINK, gsend(p[0] == OP_AT_PUT ? 2 : 1) - OP_ENTRY);
            branch_to(RA, p + 1 - bc_start);
            break;
        }
        case SK_INT:
            ea_abs(MOV, R2, ADDR(&cls_Int));
            jcc_to(RA, code_base + 2 * s->back);
            break;
        case SK_MISS:
            ea_k32(MOV, R8, s->ip);         /* the send's bytecode */
            ea_k(MOV, R6, s->site);
            jcc_abs(RA, ADDR(jit_glue_send_miss));
            break;
        case SK_OVER2:
            /* the value stack is too deep: the frame was pushed */
            ea_m(MOV, R9, FP, 4 - (SValue)sizeof(Frame));
            /* fall through */
        case SK_OVER: {
            /* the frame stack is too deep: undo, put back a new's class,
               and let C make the send again (and raise) */
            unsigned plain;
            ea_m(LEA, FP, FP, -(SValue)sizeof(Frame));
            ea_k(CMP, R5, FR_CONSTRUCT);
            plain = jcc_fwd(NE);
            ea_m(MOV, R1, R4, 0);
            ea_m(MOV, R1, R1, 0);
            ea_m(ST, R1, R4, 0);
            patch_fwd(plain, here());
            jcc_abs(RA, ADDR(jit_glue_redo));
            break;
        }
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

/* the send of the bytecode at p (a SEND, SEND_SUPER or an operator): the
   inline cache; super != 0 for a super send */
static void send_site(unsigned char *p, int argc, Value super)
{
    Value ip = V(p);
    Site *s;
    Stub *st, *to_int = 0;
    if (!site_chunks[nsites / SITE_CHUNK])
        fatal("jit: more send sites than reserved");
    s = SITE(nsites);
    s->start = here();
    s->super = super;
    s->misses = 0;
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
    st->ip = ip;
    st->site = nsites;
    ea_k32(MOV, R8, ip + opcode_len(p));
    s->target_at = jcc_abs(LINK, 0);
    nsites++;
}

static Value lit_of(Value *lits, unsigned char *p) { return lits[p[1]]; }

Value jit_closure(Value *bp, Frame *fp, unsigned char *ip);

static const int false_cond[] = { GE, GT, LE, LT };   /* LT LE GT GE false */
static const int true_cond[] = { LT, LE, GT, GE };

/* ---- fused bytecodes ----------------------------------------------------------

   Some short sequences compile better together: a constant operand
   (PUSH_INT k; ADD is an ADD #2k), a comparison and the conditional jump
   that tests it (compare and branch, no boolean), == against nil, true,
   false or a SmallInt (an identity compare). The bytecodes a fused
   sequence covers after its first still get their own code, out of line,
   in case the C side comes back in at one of them (the map points there);
   a sequence is only fused if nothing jumps into its middle. */

static unsigned char *deferred;         /* bytecode offset: compiled out of line */
static unsigned char *jtarget;          /* bytecode offset: a jump goes there */
static unsigned char *bc_end;

static int covers(unsigned char *q)
{
    return q < bc_end && !jtarget[q - bc_start];
}

static int is_cjump(unsigned char *q)
{
    return covers(q) && (q[0] == OP_JUMP_FALSE || q[0] == OP_JUMP_TRUE);
}

/* the flags say how x compares with y; the comparison k (0-3 for LT LE GT
   GE) is followed by the conditional jump at q, or not (q = 0): branch,
   or push the boolean. Returns the bytes taken (the jump's, or 0). */
static int compare_result(int k, unsigned char *q)
{
    if (q) {
        unsigned target = (q - bc_start) + 3 + W16(q + 1);
        branch_to(q[0] == OP_JUMP_FALSE ? false_cond[k] : true_cond[k], target);
        deferred[q - bc_start] = 1;
        return 3;
    }
    push_bool(false_cond[k]);
    return 0;
}

/* identity: the flags of CMP; EQ, then maybe NOT, then maybe a jump */
static int identity_result(unsigned char *q)
{
    int invert = 0, taken = 0;
    if (covers(q) && q[0] == OP_NOT) {
        deferred[q - bc_start] = 1;
        invert = 1;
        q += 1;
        taken = 1;
    }
    if (is_cjump(q)) {
        unsigned target = (q - bc_start) + 3 + W16(q + 1);
        int jump_if_equal = (q[0] == OP_JUMP_TRUE) != invert;
        branch_to(jump_if_equal ? EQ : NE, target);
        deferred[q - bc_start] = 1;
        return taken + 3;
    }
    push_bool(invert ? EQ : NE);
    return taken;
}

/* p is PUSH_INT, PUSH_NIL, PUSH_TRUE or PUSH_FALSE: the constant as a value */
static Value const_of(unsigned char *p)
{
    switch (p[0]) {
    case OP_PUSH_INT: return MKINT((signed char)p[1]);
    case OP_PUSH_NIL: return NIL;
    case OP_PUSH_TRUE: return TRUE_V;
    }
    return FALSE_V;
}

/* Compile a fused sequence starting at p, if there's one; the bytes it
   took, or 0. */
static int fused(unsigned char *p)
{
    Value ip = V(p);
    int len = p[0] == OP_PUSH_INT ? 2 : 1;
    unsigned char *q = p + len;
    int op;
    if (p[0] >= OP_LT && p[0] <= OP_GE && is_cjump(p + 1)) {
        pop2();
        tag2(ip);
        ea_r(CMP, R1, R2);
        return 1 + compare_result(p[0] - OP_LT, p + 1);
    }
    if (p[0] != OP_PUSH_INT && p[0] != OP_PUSH_NIL && p[0] != OP_PUSH_TRUE && p[0] != OP_PUSH_FALSE)
        return 0;
    if (!covers(q))
        return 0;
    op = q[0];
    if (op == OP_EQ) {
        /* x == constant: a SmallInt or nil, true or false is equal only to itself */
        ea_pd(MOV, R1, R10);
        if (p[0] == OP_PUSH_NIL)
            ea_r(CMP, R1, NILR);
        else
            ea_k(CMP, R1, const_of(p));
        deferred[q - bc_start] = 1;
        return len + 1 + identity_result(q + 1);
    }
    if (p[0] != OP_PUSH_INT)
        return 0;
    if (op == OP_ADD || op == OP_SUB) {
        SValue k = (signed char)p[1];
        ea_m(MOV, R1, R10, -4);
        un(RRC, R3, R1);
        to_send_k(LO, V(q), 0, const_of(p));
        ea_k(op == OP_ADD ? ADD : SUB, R1, 2 * k);
        to_send_k(VS, V(q), 0, const_of(p));
        ea_m(ST, R1, R10, -4);
        deferred[q - bc_start] = 1;
        return len + 1;
    }
    if (op >= OP_LT && op <= OP_GE) {
        ea_pd(MOV, R1, R10);
        un(RRC, R3, R1);
        to_send_k(LO, V(q), 4, const_of(p));
        ea_k(CMP, R1, const_of(p));
        deferred[q - bc_start] = 1;
        return len + 1 + compare_result(op - OP_LT, is_cjump(q + 1) ? q + 1 : 0);
    }
    return 0;
}

/* the body of one bytecode at p (offset off); returns its length */
static int template(Value m, Value *lits, unsigned char *start, unsigned char *p)
{
    Value ip = V(p);
    unsigned off = p - start;
    int op = p[0], len = opcode_len(p);
    unsigned next = off + len;
    switch (op) {
    case OP_PUSH_NIL:
        ea_pi(ST, NILR, R10);
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
        ea_abs(MOVS, R1, lit_of(lits, p));
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
        send_site(p, p[2], 0);
        break;
    case OP_SEND_SUPER: {
        Value super = F(F(m, M_OWNER), C_SUPER);
        if (super == NIL)
            go_slow(ip);
        else
            send_site(p, p[2], super);
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
#ifdef __V2__
        ea_idx(LEA, R1, R1, R1, 0, 1);      /* 2x + 1: r0 isn't 0 on draft 2 */
#else
        ea_idx(LEA, R1, R0, R1, 1, 1);
#endif
        ea_pi(ST, R1, R10);
        break;
    }
    case OP_LT: case OP_LE: case OP_GT: case OP_GE:
        pop2();
        tag2(ip);
        ea_r(CMP, R1, R2);
        push_bool(false_cond[op - OP_LT]);
        break;
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
        to_slow(RA, ip, 8);
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
        ea_r(CMP, R1, NILR);
        push_bool(NE);
        break;

    case OP_JUMP:
        branch_to(RA, next + W16(p + 1));
        break;
    case OP_JUMP_FALSE:
    case OP_JUMP_TRUE:
        ea_pd(MOV, R1, R10);
        ea_k(OR, R1, 8);
        ea_r(CMP, R1, NILR);
        branch_to(op == OP_JUMP_FALSE ? EQ : NE, next + W16(p + 1));
        break;
    case OP_JUMP_FALSE_OR_POP:
    case OP_JUMP_TRUE_OR_POP:
        ea_m(MOV, R1, R10, -4);
        ea_k(OR, R1, 8);
        ea_r(CMP, R1, NILR);
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
        ea_r(MOV, R2, FP);
        ea_k32(MOV, R3, ip + 1);
        jcc_abs(LINK, V((char *)jit_closure));
        ea_pi(ST, R1, R10);
        break;

    case OP_RETURN: {
        unsigned flags, retp;
        ea_pd(MOV, R1, R10);
        ea_m(MOVS, R2, FP, 16);        /* Frame.flags */
        flags = jcc_fwd(NE);
        retp = ncode;
        ea_m(ST, R1, R9, 0);
        ea_m(LEA, R10, R9, 4);
        ea_m(LEA, FP, FP, -(SValue)sizeof(Frame));
        ea_m(MOV, R9, FP, 4);
        ea_m(JEA, 0, FP, 20);           /* JMP [fp + nip] */
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
    unsigned nl = F(m, M_NLOCALS), i;
    /* entry - 4: for new, the frame returns the receiver */
    ea_k(MOV, R5, FR_CONSTRUCT);
    BCC(RA, 1);                                 /* BRA over the next */
    /* entry */
    ea_k(MOV, R5, 0);
#ifdef __V2__
    ea_m(ST, R7, FP, 20);                      /* Frame.nip: where the caller goes on */
#else
    pop(R1);                                    /* where the caller goes on */
    ea_m(ST, R1, FP, 20);                      /* Frame.nip */
#endif
    ea_m(ST, R8, FP, 0);                       /* Frame.ip */
    ea_m(LEA, FP, FP, sizeof(Frame));
    ea_abs(CMP, FP, ADDR(&egret_frames_end));
    stub(SK_OVER, HS);
    ea_m(ST, R4, FP, 4);
    ea_k32(MOV, R1, m);
    ea_m(ST, R1, FP, 8);
#ifdef __V2__
    clr_m(FP, 12);
#else
    ea_m(ST, R0, FP, 12);
#endif
    ea_m(ST, R5, FP, 16);
    ea_r(MOV, R9, R4);
    if (nl) {
        ea_abs(CMP, R10, ADDR(&egret_vstack_end));
        stub(SK_OVER2, HS);
        for (i = 0; i < nl; i++)
            ea_pi(ST, NILR, R10);
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
    gsend(1);                           /* (not while the code is being made) */
    gsend(2);
    end = start + n;
    for (p = start; p < end; p += opcode_len(p))
        nsends += p[0] == OP_SEND || p[0] == OP_SEND_SUPER;
    reserve_sites(nsends);
    mark = scratch_mark();
    native_at = (unsigned short *)scratch_alloc(2 * n);
    deferred = (unsigned char *)scratch_alloc(n + 1);
    jtarget = (unsigned char *)scratch_alloc(n + 1);
    bc_start = start;
    bc_end = end;
    nfixes = 0;
    nstubs = 0;
    for (i = 0; i < n; i++)
        native_at[i] = 0xFFFF;
    /* where jumps go (and INC_LOCAL's fast path) */
    for (p = start; p < end; p += opcode_len(p)) {
        unsigned next = p - start + opcode_len(p), t = 0xFFFF;
        switch (p[0]) {
        case OP_JUMP: case OP_JUMP_FALSE: case OP_JUMP_TRUE: case OP_JUMP_FALSE_OR_POP:
        case OP_JUMP_TRUE_OR_POP: case OP_TRY:
            t = next + W16(p + 1);
            break;
        case OP_RANGE_NEXT: case OP_ITER_NEXT:
            t = next + W16(p + 2);
            break;
        case OP_INC_LOCAL:
            t = next + 7;
            break;
        }
        if (t < n)
            jtarget[t] = 1;
    }
    begin_code();
    prologue(m);
    for (p = start; p < end;) {
        int k;
        if (deferred[p - start]) {
            p += opcode_len(p);
            continue;
        }
        native_at[p - start] = ncode;
        k = fused(p);
        p += k ? k : template(m, lits, start, p);
    }
    /* the bytecodes fused sequences covered, on their own, out of line */
    for (p = start; p < end;) {
        unsigned char *q;
        if (!deferred[p - start]) {
            p += opcode_len(p);
            continue;
        }
        native_at[p - start] = ncode;
        q = p + template(m, lits, start, p);
        if (q < end && !deferred[q - start])
            branch_to(RA, q - start);
        p = q;
    }
    F(m, M_NSTUBS) = here();
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
   stack, or in r7 on draft 2) */
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
#ifdef __V2__
    push(R7);
#endif
    push(R4);
    jcc_abs(LINK, V((char *)prim_table[F(m, M_PRIM)]));
    pop(R4);
#ifdef __V2__
    pop(R7);
#endif
    rr(TST, R1, R1);
    fail = jcc_fwd(EQ);
    ea_m(ST, R1, R4, 0);
    ea_m(LEA, R10, R4, 4);
    ret();
    patch_fwd(fail, here());
#ifndef __V2__
    pop(R1);                                    /* no return: raise */
#endif
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
    ea_m(MOVS, R1, R3, FLD(M_NATIVE));
    slow2 = jcc_fwd(EQ);
    jmp_r(R1);
    patch_fwd(slow1, here());
    patch_fwd(slow2, here());
#ifndef __V2__
    pop(R1);
#endif
    jcc_abs(RA, ADDR(jit_glue_redo));           /* C makes the send */
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
    ea_m(MOVS, R5, R3, FLD(M_NATIVE));
    s[4] = jcc_fwd(EQ);
    ea_m(LEA, R2, R10, -4);
    ea_abs(ST, R2, ADDR(&vm_sp));
#ifdef __V2__
    push(R7);
#endif
    push(R4);
    push(R5);
    ea_m(MOV, R2, R1, FLD(C_NIVARS));
    shk(ASR, R2, 1);
    jcc_abs(LINK, V((char *)alloc_obj));
    pop(R5);
    pop(R4);
#ifdef __V2__
    pop(R7);
#endif
    ea_m(ST, R1, R4, 0);                        /* the object in place of the class */
    ea_k(SUB, R5, NEW_ENTRY);
    jmp_r(R5);
    for (i = 0; i < 5; i++)
        patch_fwd(s[i], here());
#ifndef __V2__
    pop(R1);
#endif
    jcc_abs(RA, ADDR(jit_glue_redo));
    return new_stubs[argc] = finish_stub();
}

/* A send through the method cache, rather than an inline cache of its own,
   as the asm loop makes them: an operator's when its fast path doesn't
   apply (so that a method's operators cost little to compile), and a send
   that saw too many classes. r6 is the selector, r7 the bytecode (r5 on
   draft 2: SEND_IP), r8 the bytecode after it (the entry OP_ENTRY bytes
   before sets it, for an operator), the return address on the stack (in
   r7 on draft 2). A miss, or a method not yet compiled, goes to
   jit_gsend_miss. */
static Value gsend_stubs[16];
static Value gsend(int argc)
{
    unsigned to_int, probe, m1, m2, m3, m4, ok;
    if (gsend_stubs[argc])
        return gsend_stubs[argc];
    begin_stub();
    ea_m(LEA, R8, SEND_IP, 1);
    ea_m(LEA, R4, R10, -4 * (argc + 1));
    ea_m(MOV, R1, R4, 0);
    un(RRC, R2, R1);
    to_int = jcc_fwd(HS);
    ea_m(MOV, R2, R1, 0);
    probe = ncode;
    ea_r(MOV, R3, R2);
    ea_r(XOR, R3, R6);
    ea_k(AND, R3, 0xFFC);
    ea_m(CMP, R2, R3, ADDR(mcache_cls));
    m1 = jcc_fwd(NE);
    ea_m(CMP, R6, R3, ADDR(mcache_sel));
    m2 = jcc_fwd(NE);
    ea_m(MOV, R3, R3, ADDR(mcache_method));
    ea_m(MOV, R1, R3, FLD(M_ARITY));
    ea_k(CMP, R1, argc);
    ok = jcc_fwd(EQ);
    ea_k(CMP, R1, ARITY_PRIM + argc);
    m3 = jcc_fwd(NE);
    patch_fwd(ok, here());
    ea_m(MOVS, R1, R3, FLD(M_NATIVE));
    m4 = jcc_fwd(EQ);
    jmp_r(R1);
    patch_fwd(to_int, here());
    ea_abs(MOV, R2, ADDR(&cls_Int));
    jcc_to(RA, code_base + 2 * probe);
    patch_fwd(m1, here());
    patch_fwd(m2, here());
    patch_fwd(m3, here());
    patch_fwd(m4, here());
    jcc_abs(RA, ADDR(jit_glue_gsend_miss));
    return gsend_stubs[argc] = finish_stub() + OP_ENTRY;
}

/* what native code calls for m, sent with argc arguments, or 0 */
static Value native_target(Value m, int argc)
{
    if (F(m, M_ARITY) == (Value)argc) {
        jit_compile(m);
        return F(m, M_NATIVE);
    }
    if (F(m, M_ARITY) == ARITY_PRIM + (Value)argc)
        return prim_stub(m);
    if (m == egret_blockcall && argc < 16)
        return block_stub(argc);
    if (F(m, M_PRIM) == PR_NEW && argc < 16)
        return new_stub(argc);
    return 0;
}

/* gsend missed: ip is the send's bytecode (st->ip the one after). Fill
   the method cache and return what to call, with its bp in jit_bp; or 0,
   with st->ip at the send for C to make it. */
Value jit_bp;
Value jit_gsend_miss(VMStateHead *st, unsigned char *ip)
{
    Value sel, m, target = 0;
    int argc;
    if (ip[0] == OP_SEND) {
        sel = st->lits[ip[1]];
        argc = ip[2];
    } else {
        sel = egret_special[ip[0]];
        argc = ip[0] == OP_AT_PUT ? 2 : 1;
    }
    m = egret_find(CLASS_OF(st->sp[-argc]), sel);
    if (m)
        target = native_target(m, argc);
    if (!target) {
        st->ip = ip;
        return 0;
    }
    jit_bp = V(st->sp - argc);
    return target;
}

/* A send native code can't make (st->ip is the bytecode after it): back
   up to the send, for C to make it. */
void jit_back_up(VMStateHead *st)
{
    unsigned char *p = BYTES(F(st->fp->method, M_CODE)), *q;
    while ((q = p + opcode_len(p)) < st->ip)
        p = q;
    st->ip = p;
}

/* ---- the inline caches' misses ----------------------------------------------------- */


/* a site that was bound this often sends through the method cache */
#define MEGAMORPHIC 3

/* The send at st->ip (a SEND bytecode) missed its inline cache: bind the
   site to what the send finds, and return the site's address to run it
   again; or 0, and the glue has C make the send. A site that keeps
   missing goes megamorphic: its class check becomes a branch over it, and
   it calls a stub of its own that sends through the method cache. */
Value jit_send_miss(VMStateHead *st, int si)
{
    Site *s = SITE(si);
    unsigned char *ip = st->ip;
    Value sel = st->lits[ip[1]], cls, m, target;
    int argc = ip[2];
    cls = s->super ? s->super : CLASS_OF(st->sp[-argc]);
    if (++s->misses >= MEGAMORPHIC && !s->super && argc < 16) {
        Value mega, g = gsend(argc);
        begin_stub();
        ea_k(MOV, R6, sel);
        ea_k32(MOV, SEND_IP, V(ip));
        jcc_abs(RA, g);
        mega = finish_stub();
        /* CMP r2, #class (3 parcels); Jcc NE miss (2): BRA over them */
#ifdef __V2__
        ((unsigned short *)BP(s->class_at))[-1] = 0xB0 | RA | 4 << 8;
#else
        ((unsigned short *)BP(s->class_at))[-1] = 0xE000 | RA << 8 | 4;
#endif
        patch32(s->target_at, mega);
        return s->start;
    }
    m = egret_find(cls, sel);
    if (!m || !(target = native_target(m, argc)))
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
