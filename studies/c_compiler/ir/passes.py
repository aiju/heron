"""Target-independent optimisations on SSA form.

Nothing clever. `optimize` runs, per function: mem2reg (ir.ssa), and
at level 0 nothing else; then constant folding and algebraic simplification
(including strength reduction of multiplies and divides by powers of two),
global value numbering over the dominator tree, redundant load elimination
within a block, dead code elimination and control-flow cleanup, to a fixed
point; loop-invariant code motion and the fixed point again; strength
reduction of induction variables (with linear function test replacement)
and the fixed point again; given the target's free_imm, constants it can't
take as cheap immediates loaded into registers before loops; and last,
sinking steps like p + 1 below p's last use.
"""

from .ir import Instr, Const, SymAddr, Param, Slot, Undef, M32, s32, BINOPS, CMPOPS, UNOPS, COMMUTATIVE, PURE, CMP_SWAP, CMP_NEG
from .cfg import DomTree, natural_loops, remove_unreachable
from .ssa import mem2reg


# --------------------------------------------------------------------------
# Constant folding


def fold_binop(op, a, b):
    """Fold op on two 32-bit unsigned ints. None if it can't be folded."""
    sa, sb = s32(a), s32(b)
    if op == "add": return a + b
    if op == "sub": return a - b
    if op == "mul": return a * b
    if op == "and": return a & b
    if op == "or": return a | b
    if op == "xor": return a ^ b
    if op == "shl": return a << (b & 31)
    if op == "shr": return a >> (b & 31)
    if op == "sar": return sa >> (b & 31)
    if op == "rotr": return (a >> (b & 31)) | (a << (32 - (b & 31)))
    if op in ("divu", "remu", "divs", "rems") and b == 0:
        return None
    if op == "divu": return a // b
    if op == "remu": return a % b
    if op in ("divs", "rems"):
        if sa == -(1 << 31) and sb == -1:
            return sa if op == "divs" else 0
        q = abs(sa) // abs(sb)
        if (sa < 0) != (sb < 0):
            q = -q
        return q if op == "divs" else sa - q * sb
    if op == "eq": return int(a == b)
    if op == "ne": return int(a != b)
    if op == "lt": return int(sa < sb)
    if op == "le": return int(sa <= sb)
    if op == "gt": return int(sa > sb)
    if op == "ge": return int(sa >= sb)
    if op == "ltu": return int(a < b)
    if op == "leu": return int(a <= b)
    if op == "gtu": return int(a > b)
    if op == "geu": return int(a >= b)
    return None


def fold_unop(op, a):
    if op == "neg": return -a
    if op == "not": return ~a
    if op == "sext8": return a & 0xFF | (-0x100 if a & 0x80 else 0)
    if op == "sext16": return a & 0xFFFF | (-0x10000 if a & 0x8000 else 0)
    if op == "zext8": return a & 0xFF
    if op == "zext16": return a & 0xFFFF
    if op == "copy": return a
    return None


def log2(c):
    """k if c == 2**k (c > 0), else None."""
    if c > 0 and c & (c - 1) == 0:
        return c.bit_length() - 1
    return None


# --------------------------------------------------------------------------
# Known bits (a cheap range analysis for removing extensions and masks)


def ubits(v, depth=0):
    """An upper bound on the number of significant bits of v as unsigned."""
    if isinstance(v, Const):
        return v.value.bit_length()
    if not isinstance(v, Instr) or depth > 6:
        return 32
    op = v.op
    if op in CMPOPS:
        return 1
    if op == "load":
        return 8 * v.size if not v.signed else 32
    if op == "zext8":
        return min(8, ubits(v.args[0], depth + 1))
    if op == "zext16":
        return min(16, ubits(v.args[0], depth + 1))
    if op == "and":
        return min(ubits(v.args[0], depth + 1), ubits(v.args[1], depth + 1))
    if op in ("or", "xor"):
        return max(ubits(v.args[0], depth + 1), ubits(v.args[1], depth + 1))
    if op == "shr" and isinstance(v.args[1], Const):
        return max(0, ubits(v.args[0], depth + 1) - (v.args[1].value & 31))
    if op == "shl" and isinstance(v.args[1], Const):
        return min(32, ubits(v.args[0], depth + 1) + (v.args[1].value & 31))
    if op == "remu" and isinstance(v.args[1], Const) and v.args[1].value:
        return min(ubits(v.args[0], depth + 1), (v.args[1].value - 1).bit_length())
    if op == "divu":
        return ubits(v.args[0], depth + 1)
    if op == "add":
        a, b = ubits(v.args[0], depth + 1), ubits(v.args[1], depth + 1)
        return min(32, max(a, b) + 1)
    if op == "mul":
        return min(32, ubits(v.args[0], depth + 1) + ubits(v.args[1], depth + 1))
    if op == "phi":
        # a phi in a loop refers to itself; assume the worst on cycles
        return 32
    return 32


def sext_from(v, bits, depth=0):
    """True if v is known to equal the sign extension of its low `bits` bits."""
    if isinstance(v, Const):
        return -(1 << (bits - 1)) <= v.signed < (1 << (bits - 1))
    if not isinstance(v, Instr) or depth > 6:
        return False
    if v.op == "load" and v.signed and 8 * v.size <= bits:
        return True
    if v.op == "sext8" and bits >= 8:
        return True
    if v.op == "sext16" and bits >= 16:
        return True
    return ubits(v, depth + 1) < bits


def nonneg(v, depth=0, assumed=None):
    """True if v, read as a signed number, is known to be >= 0. Relies on
    signed adds not overflowing (the nsw flag, set from C's signed int
    arithmetic)."""
    if isinstance(v, Const):
        return v.signed >= 0
    if not isinstance(v, Instr) or depth > 8:
        return False
    if ubits(v) < 32:
        return True
    assumed = assumed if assumed is not None else set()
    op, a = v.op, v.args
    if op == "phi":
        if v in assumed:
            return True             # inductively
        assumed.add(v)
        ok = all(nonneg(x, depth + 1, assumed) for x in a)
        if not ok:
            assumed.discard(v)
        return ok
    if op in ("add", "mul") and v.signed:
        return nonneg(a[0], depth + 1, assumed) and nonneg(a[1], depth + 1, assumed)
    if op == "and":
        return nonneg(a[0], depth + 1, assumed) or nonneg(a[1], depth + 1, assumed)
    if op in ("or", "xor", "divs"):
        return nonneg(a[0], depth + 1, assumed) and nonneg(a[1], depth + 1, assumed)
    if op == "shr":
        return isinstance(a[1], Const) and a[1].value & 31 != 0 or nonneg(a[0], depth + 1, assumed)
    if op in ("sar", "rems"):
        return nonneg(a[0], depth + 1, assumed)
    return False


# --------------------------------------------------------------------------
# Simplification


class Simplifier:
    def __init__(self, func):
        self.func = func
        self.changed = False

    def new(self, before, op, args, **kw):
        """Insert a new instruction before `before`."""
        i = Instr(op, args, **kw)
        for a in args:
            self.uses[a] = self.uses.get(a, 0) + 1
        b = before.block
        b.insert(b.instrs.index(before), i)
        return i

    def simplify(self, i):
        """Returns a replacement value for i, or None. May rewrite i in place."""
        op, args = i.op, i.args
        if op in BINOPS or op in CMPOPS:
            a, b = args
            if isinstance(a, Const) and isinstance(b, Const):
                r = fold_binop(op, a.value, b.value)
                if r is not None:
                    return Const(r)
            if op in COMMUTATIVE and isinstance(a, Const) and not isinstance(b, Const):
                i.args = [b, a]
                self.changed = True
                return self.simplify(i)
            if op in CMPOPS and isinstance(a, Const) and not isinstance(b, Const):
                i.op = CMP_SWAP[op]
                i.args = [b, a]
                self.changed = True
                return self.simplify(i)
            if op in BINOPS:
                return self.simplify_binop(i, op, a, b)
            return self.simplify_cmp(i, op, a, b)
        if op in UNOPS:
            a = args[0]
            if isinstance(a, Const):
                return Const(fold_unop(op, a.value))
            return self.simplify_unop(i, op, a)
        if op == "phi":
            return self.simplify_phi(i)
        if op == "store" and i.size < 4:
            # a narrow store ignores the bits an extension would set
            v = args[0]
            while isinstance(v, Instr) and v.op in ("zext8", "sext8", "zext16", "sext16") \
                    and (8 if v.op.endswith("8") else 16) >= 8 * i.size:
                v = v.args[0]
            if v is not args[0]:
                i.args = [v, args[1]]
                self.changed = True
        return None

    def simplify_binop(self, i, op, a, b):
        c = b.value if isinstance(b, Const) else None
        sc = s32(c) if c is not None else None
        if op == "add":
            if c == 0:
                return a
            if isinstance(a, SymAddr) and c is not None:
                return SymAddr(a.name, a.offset + sc)
            # (x + c1) + c2 -> x + (c1 + c2)
            if c is not None and isinstance(a, Instr) and a.op == "add" and isinstance(a.args[1], Const):
                total = a.args[1].signed + sc
                i.signed = i.signed and a.signed and -(1 << 31) <= total < (1 << 31)
                i.args = [a.args[0], Const(total)]
                self.changed = True
                return self.simplify(i)
            # x + (y + c) -> (x + y) + c: constants move outwards, where an
            # address displacement can absorb them
            if c is None:
                for x, y in ((a, b), (b, a)):
                    if (isinstance(y, Instr) and y.op == "add" and isinstance(y.args[1], Const)
                            and not isinstance(x, Const) and not isinstance(y.args[0], Const)):
                        inner = self.new(i, "add", [x, y.args[0]])
                        i.args, i.signed = [inner, y.args[1]], False
                        self.changed = True
                        return None
            # x + (-y) -> x - y
            if isinstance(b, Instr) and b.op == "neg":
                i.op, i.args, i.signed = "sub", [a, b.args[0]], False
                self.changed = True
                return None
        elif op == "sub":
            if c is not None:
                i.signed = i.signed and sc != -(1 << 31)
                i.op, i.args = "add", [a, Const(-c)]
                self.changed = True
                return self.simplify(i)
            if a is b:
                return Const(0)
            if isinstance(a, Const) and a.value == 0:
                i.op, i.args = "neg", [b]
                self.changed = True
                return None
            if isinstance(a, SymAddr) and isinstance(b, SymAddr) and a.name == b.name:
                return Const(a.offset - b.offset)
        elif op == "mul":
            if c == 0:
                return Const(0)
            if (c is not None and isinstance(a, Instr) and a.op == "add"
                    and isinstance(a.args[1], Const) and not isinstance(a.args[0], Const)):
                inner = self.new(i, "mul", [a.args[0], Const(c)])
                i.op, i.args, i.signed = "add", [inner, Const(a.args[1].value * c)], False
                self.changed = True
                return None
            if c == 1:
                return a
            if c == M32:
                i.op, i.args = "neg", [a]
                self.changed = True
                return None
            if c is not None and log2(c) is not None:
                i.op, i.args = "shl", [a, Const(log2(c))]
                self.changed = True
                return None
        elif op in ("and", "or", "xor"):
            if a is b:
                return Const(0) if op == "xor" else a
            if op == "and":
                if c == 0:
                    return Const(0)
                if c is not None and ubits(a) <= (c + 1).bit_length() - 1 and log2(c + 1) is not None:
                    return a                        # mask doesn't remove anything
                if c == 0xFF:
                    i.op, i.args = "zext8", [a]
                    self.changed = True
                    return self.simplify(i)
                if c == 0xFFFF:
                    i.op, i.args = "zext16", [a]
                    self.changed = True
                    return self.simplify(i)
                if c is not None and isinstance(a, Instr) and a.op == "and" and isinstance(a.args[1], Const):
                    i.args = [a.args[0], Const(a.args[1].value & c)]
                    self.changed = True
                    return self.simplify(i)
            elif op == "or":
                if c == 0:
                    return a
                if c == M32:
                    return Const(M32)
                r = self.rotate(i, a, b)
                if r:
                    return None
            else:
                if c == 0:
                    return a
                if c == M32:
                    i.op, i.args = "not", [a]
                    self.changed = True
                    return None
        elif op in ("shl", "shr", "sar", "rotr"):
            if c is not None and c & 31 == 0:
                return a
            # (x + c2) << c  ->  (x << c) + (c2 << c): the constant can then
            # go into an address displacement, and x << c be strength-reduced
            if (op == "shl" and c is not None and isinstance(a, Instr) and a.op == "add"
                    and isinstance(a.args[1], Const) and not isinstance(a.args[0], Const)):
                inner = self.new(i, "shl", [a.args[0], Const(c & 31)])
                i.op, i.args, i.signed = "add", [inner, Const(a.args[1].value << (c & 31))], False
                self.changed = True
                return None
            if isinstance(a, Const) and a.value == 0:
                return Const(0)
            if c is not None and c > 31:
                i.args = [a, Const(c & 31)]
                self.changed = True
            if op == "rotr":
                if c is not None and isinstance(a, Instr) and a.op == "rotr" \
                        and isinstance(a.args[1], Const):
                    i.args = [a.args[0], Const((a.args[1].value + c) & 31)]
                    self.changed = True
                    return self.simplify(i)
                return None
            # (x >> c1) >> c2 for the same kind of shift
            if (c is not None and isinstance(a, Instr) and a.op == op
                    and isinstance(a.args[1], Const)):
                tot = (a.args[1].value & 31) + (c & 31)
                if tot < 32:
                    i.args = [a.args[0], Const(tot)]
                    self.changed = True
                    return None
                if op != "sar":
                    return Const(0)
        elif op == "divu":
            if c == 1:
                return a
            if c is not None and log2(c) is not None:
                i.op, i.args = "shr", [a, Const(log2(c))]
                self.changed = True
                return None
        elif op == "remu":
            if c == 1:
                return Const(0)
            if c is not None and log2(c) is not None:
                i.op, i.args = "and", [a, Const(c - 1)]
                self.changed = True
                return self.simplify(i)
        elif op == "divs":
            if c == 1:
                return a
            if c == M32:
                i.op, i.args = "neg", [a]
                self.changed = True
                return None
            k = log2(c) if c is not None else None
            if k is not None and k < 31:
                # round toward zero: add 2^k - 1 to negative dividends first
                if nonneg(a):
                    i.op, i.args = "shr", [a, Const(k)]
                    self.changed = True
                    return None
                bias = self.biased(i, a, k)
                i.op, i.args = "sar", [bias, Const(k)]
                self.changed = True
                return None
        elif op == "rems":
            if c in (1, M32):
                return Const(0)
            k = log2(c) if c is not None else None
            if k is not None and k < 31:
                if nonneg(a):
                    i.op, i.args = "and", [a, Const(c - 1)]
                    self.changed = True
                    return None
                # x - ((x + bias) & -2^k)
                bias = self.biased(i, a, k)
                m = self.new(i, "and", [bias, Const(-(1 << k))])
                i.op, i.args = "sub", [a, m]
                self.changed = True
                return None
        return None

    def rotate(self, i, a, b):
        """(x >> n) | (x << (32 - n)) is a rotate."""
        def shift(v, op):
            if isinstance(v, Instr) and v.op == op and isinstance(v.args[1], Const):
                return v.args[0], v.args[1].value & 31
            return None, None
        for x, y in ((a, b), (b, a)):
            v1, n1 = shift(x, "shr")
            v2, n2 = shift(y, "shl")
            if v1 is not None and v1 is v2 and n1 + n2 == 32:
                i.op, i.args = "rotr", [v1, Const(n1)]
                self.changed = True
                return True
        return False

    def biased(self, i, a, k):
        """x + (2^k - 1 if x < 0 else 0), computed before i."""
        if k == 1:
            adj = self.new(i, "shr", [a, Const(31)])
        else:
            sign = self.new(i, "sar", [a, Const(31)])
            adj = self.new(i, "shr", [sign, Const(32 - k)])
        return self.new(i, "add", [a, adj])

    def simplify_cmp(self, i, op, a, b):
        c = b.value if isinstance(b, Const) else None
        if a is b:
            return Const(1 if op in ("eq", "le", "ge", "leu", "geu") else 0)
        if c is not None:
            if op == "ltu" and c == 0:
                return Const(0)
            if op == "geu" and c == 0:
                return Const(1)
            if op == "gtu" and c == 0:
                i.op = "ne"
                self.changed = True
                return None
            if op == "leu" and c == 0:
                i.op = "eq"
                self.changed = True
                return None
            # a compare against 0 or 1 of a boolean
            if isinstance(a, Instr) and a.op in CMPOPS:
                if (op == "ne" and c == 0) or (op == "eq" and c == 1):
                    return a
                if (op == "eq" and c == 0) or (op == "ne" and c == 1):
                    i.op, i.args = CMP_NEG[a.op], list(a.args)
                    self.changed = True
                    return None
                if op in ("eq", "ne") and c > 1:
                    return Const(0 if op == "eq" else 1)
            # x == c where x + k is computed before: compare x + k with c + k
            # instead, so x can die at the add (while (n--) ...). For < and >
            # only if the add can't overflow.
            if isinstance(a, (Instr, Param)) and op in ("eq", "ne", "lt", "le", "gt", "ge"):
                for u in self.users.get(a, ()):
                    if (u.op == "add" and u.args[0] is a and isinstance(u.args[1], Const)
                            and u.block is i.block and u in self.pos and i in self.pos
                            and self.pos[u] < self.pos[i]):
                        k = u.args[1].signed
                        if op not in ("eq", "ne") and not (
                                u.signed and -(1 << 31) <= s32(c) + k < (1 << 31)):
                            continue
                        i.args = [u, Const(c + k)]
                        self.changed = True
                        return None
            if c == 0 and op in ("lt", "ge") and nonneg(a):
                return Const(0 if op == "lt" else 1)
            # out-of-range compares of zero-extended values
            bits = ubits(a)
            if op in ("eq", "ne") and bits < 32 and c >= (1 << bits):
                return Const(0 if op == "eq" else 1)
        return None

    def simplify_unop(self, i, op, a):
        if op == "copy":
            return a
        if op == "not" and isinstance(a, Instr) and a.op == "not":
            return a.args[0]
        if op == "neg" and isinstance(a, Instr) and a.op == "neg":
            return a.args[0]
        if op in ("zext8", "zext16"):
            bits = 8 if op == "zext8" else 16
            if ubits(a) <= bits:
                return a
            if isinstance(a, Instr) and a.op in ("sext8", "sext16", "zext8", "zext16"):
                inner = 8 if a.op.endswith("8") else 16
                if inner >= bits:          # zext8(sext16 x) = zext8 x
                    i.args = [a.args[0]]
                    self.changed = True
                    return self.simplify(i)
            if isinstance(a, Instr) and a.op == "load" and a.size == bits // 8:
                # zext of a sign-extending load of the same size: load unsigned
                if a.signed and self.single_use(a):
                    a.signed = False
                    self.changed = True
                    return a
        if op in ("sext8", "sext16"):
            bits = 8 if op == "sext8" else 16
            if sext_from(a, bits):
                return a
            if isinstance(a, Instr) and a.op in ("sext8", "sext16", "zext8", "zext16"):
                inner = 8 if a.op.endswith("8") else 16
                if inner >= bits:
                    i.args = [a.args[0]]
                    self.changed = True
                    return self.simplify(i)
            if isinstance(a, Instr) and a.op == "load" and a.size == bits // 8 and not a.signed:
                if self.single_use(a):
                    a.signed = True
                    self.changed = True
                    return a
        return None

    def single_use(self, v):
        return self.uses.get(v, 0) == 1

    def simplify_phi(self, i):
        vals = []
        for v in i.args:
            if v is i or v is Undef:
                continue
            if v not in vals:
                vals.append(v)
        if not vals:
            return Undef
        if len(vals) == 1:
            v = vals[0]
            if len(set(id(x) for x in i.args if x is not i)) == 1:
                return v
            # phi(x, undef): only if x is available everywhere
            if isinstance(v, (Const, SymAddr, Param, Slot)):
                return v
            if isinstance(v, Instr) and self.dom is not None and v.block in self.dom.pre \
                    and i.block in self.dom.pre and self.dom.dominates(v.block, i.block) \
                    and v.block is not i.block:
                return v
        return None

    def run(self):
        f = self.func
        self.dom = DomTree(f)
        self.uses = f.use_counts()
        self.users = f.users()
        self.pos = {i: n for b in f.blocks for n, i in enumerate(b.instrs)}
        mapping = {}

        def res(v):
            while v in mapping:
                v = mapping[v]
            return v
        for b in self.dom.rpo:
            for i in list(b.instrs):
                i.args = [res(a) for a in i.args]
                r = self.simplify(i)
                if r is not None and r is not i:
                    mapping[i] = r
                    self.uses[r] = self.uses.get(r, 0) + self.uses.get(i, 0)
                    b.instrs.remove(i)
                    self.changed = True
        f.replace_uses(mapping)
        # branches on constants
        for b in f.blocks:
            t = b.terminator
            if t is None:
                continue
            if t.op == "br":
                c = t.args[0]
                if t.targets[0] is t.targets[1]:
                    t.op, t.args, t.targets = "jmp", [], [t.targets[0]]
                    self.changed = True
                elif isinstance(c, (Const, SymAddr)):
                    taken = 0 if not isinstance(c, Const) or c.value else 1
                    self.retarget(b, t, [t.targets[taken]])
                elif isinstance(c, Instr) and c.op == "eq" and isinstance(c.args[1], Const) \
                        and c.args[1].value == 0:
                    # br (x == 0), T, F  ->  br x, F, T
                    t.args = [c.args[0]]
                    t.targets = [t.targets[1], t.targets[0]]
                    self.changed = True
                elif isinstance(c, Instr) and c.op == "ne" and isinstance(c.args[1], Const) \
                        and c.args[1].value == 0:
                    t.args = [c.args[0]]
                    self.changed = True
                elif isinstance(c, Instr) and c.op == "phi":
                    # while (n--): test n - 1 != -1, so n dies at the decrement
                    for u in self.users.get(c, ()):
                        if (u.op == "add" and u.args[0] is c and isinstance(u.args[1], Const)
                                and u.block is b and u in b.instrs):
                            cmp = Instr("ne", [u, Const(u.args[1].value)])
                            b.insert(len(b.instrs) - 1, cmp)
                            t.args = [cmp]
                            self.changed = True
                            break
            elif t.op == "switch":
                c = t.args[0]
                if isinstance(c, Const):
                    dest = t.targets[0]
                    for cv, blk in zip(t.cases, t.targets[1:]):
                        if cv == c.value:
                            dest = blk
                            break
                    self.retarget(b, t, [dest])
                elif not t.cases:
                    self.retarget(b, t, [t.targets[0]])
        if self.changed:
            remove_unreachable(f)
        return self.changed

    def retarget(self, b, t, targets):
        old = set(t.targets)
        t.op, t.args, t.targets, t.cases = "jmp", [], targets, None
        for s in old - set(targets):
            for p in s.phis():
                keep = [(v, blk) for v, blk in zip(p.args, p.incoming) if blk is not b]
                p.args = [v for v, _ in keep]
                p.incoming = [blk for _, blk in keep]
        self.changed = True


def simplify(func):
    return Simplifier(func).run()


# --------------------------------------------------------------------------
# Global value numbering (pure instructions, dominator-scoped)


def _key(i):
    args = list(i.args)
    if i.op in COMMUTATIVE:
        args.sort(key=lambda v: (type(v).__name__, getattr(v, "value", 0), id(v)))
    return (i.op, tuple(args))


def gvn(func):
    dom = DomTree(func)
    mapping = {}
    table = {}
    changed = False

    def res(v):
        while v in mapping:
            v = mapping[v]
        return v
    stack = [(dom.rpo[0], False, None)]
    while stack:
        b, done, added = stack.pop()
        if done:
            for k in added:
                del table[k]
            continue
        added = []
        for i in list(b.instrs):
            i.args = [res(a) for a in i.args]
            if i.op not in PURE or i.op == "copy":
                continue
            k = _key(i)
            prev = table.get(k)
            if prev is not None:
                mapping[i] = prev
                b.instrs.remove(i)
                changed = True
            else:
                table[k] = i
                added.append(k)
        stack.append((b, True, added))
        for c in reversed(dom.children[b]):
            stack.append((c, False, None))
    func.replace_uses(mapping)
    return changed


# --------------------------------------------------------------------------
# Redundant loads within a block


def _base(addr):
    """(object, offset) for an address, where object is a Slot, a symbol name
    or None for an unknown pointer."""
    off = 0
    while isinstance(addr, Instr) and addr.op == "add" and isinstance(addr.args[1], Const):
        off += addr.args[1].signed
        addr = addr.args[0]
    if isinstance(addr, Slot):
        return ("slot", addr), off
    if isinstance(addr, SymAddr):
        return ("sym", addr.name), off + addr.offset
    return ("ptr", addr), off


def _may_alias(a1, s1, a2, s2):
    (k1, o1), off1 = _base(a1)
    (k2, o2), off2 = _base(a2)
    if k1 != "ptr" and k2 != "ptr":
        if (k1, o1) != (k2, o2):
            return False
        return off1 < off2 + s2 and off2 < off1 + s1
    if k1 == "ptr" and k2 == "ptr" and o1 is o2:
        return off1 < off2 + s2 and off2 < off1 + s1
    return True


def load_cse(func):
    changed = False
    mapping = {}
    for b in func.blocks:
        avail = {}          # (addr, size, signed) -> value
        for i in list(b.instrs):
            i.args = [mapping.get(a, a) for a in i.args]
            if i.op == "load":
                if i.volatile:
                    continue
                k = (i.args[0], i.size, i.signed)
                if k in avail:
                    mapping[i] = avail[k]
                    b.instrs.remove(i)
                    changed = True
                else:
                    avail[k] = i
            elif i.op == "store":
                addr = i.args[1]
                for k in list(avail):
                    if _may_alias(k[0], k[1], addr, i.size):
                        del avail[k]
                if i.size == 4 and not i.volatile:
                    avail[(addr, 4, False)] = i.args[0]
            elif i.op in ("call", "memcpy"):
                avail.clear()
    func.replace_uses(mapping)
    return changed


# --------------------------------------------------------------------------
# Dead code


def dce(func):
    live = set()
    work = []
    for i in func.instructions():
        if i.has_side_effects:
            live.add(i)
            work.append(i)
    while work:
        i = work.pop()
        for a in i.args:
            if isinstance(a, Instr) and a not in live:
                live.add(a)
                work.append(a)
    changed = False
    for b in func.blocks:
        n = len(b.instrs)
        b.instrs = [i for i in b.instrs if i in live]
        changed |= len(b.instrs) != n
    return changed


# --------------------------------------------------------------------------
# Control flow cleanup


def cleanup_cfg(func):
    changed = remove_unreachable(func)
    progress = True
    while progress:
        progress = False
        func.compute_preds()
        # skip blocks that only jump elsewhere
        for b in func.blocks[1:]:
            if len(b.instrs) != 1 or b.instrs[0].op != "jmp":
                continue
            dest = b.instrs[0].targets[0]
            if dest is b:
                continue
            dphis = dest.phis()
            if dphis and any(p in dest.preds for p in b.preds):
                continue
            for p in b.preds:
                t = p.terminator
                t.targets = [dest if x is b else x for x in t.targets]
            for ph in dphis:
                v = ph.args[ph.incoming.index(b)]
                k = ph.incoming.index(b)
                del ph.args[k]
                del ph.incoming[k]
                for p in b.preds:
                    ph.args.append(v)
                    ph.incoming.append(p)
            if b.preds:
                progress = changed = True
                func.compute_preds()
        if remove_unreachable(func):
            progress = changed = True
        func.compute_preds()
        # merge a block into its only predecessor
        for b in list(func.blocks[1:]):
            if len(b.preds) != 1:
                continue
            p = b.preds[0]
            t = p.terminator
            if p is b or t.op != "jmp":
                continue
            mapping = {}
            for ph in b.phis():
                mapping[ph] = ph.args[0]
            p.instrs.pop()
            for i in b.instrs:
                if i.op == "phi":
                    continue
                p.append(i)
            for s in set(b.succs):
                for ph in s.phis():
                    ph.incoming = [p if x is b else x for x in ph.incoming]
            b.instrs = []
            func.blocks.remove(b)
            func.replace_uses(mapping)
            func.compute_preds()
            progress = changed = True
    # a br whose targets coincide
    for b in func.blocks:
        t = b.terminator
        if t.op == "br" and t.targets[0] is t.targets[1]:
            t.op, t.args, t.targets = "jmp", [], [t.targets[0]]
            changed = True
    func.compute_preds()
    return changed


# --------------------------------------------------------------------------
# Loop-invariant code motion


def make_preheader(func, h, body):
    """A block that is the loop's only entry and jumps straight to the
    header, made if needed. None if the loop can't have one."""
    outside = [p for p in h.preds if p not in body]
    if len(outside) != 1 or h is func.entry:
        return None
    p = outside[0]
    t = p.terminator
    if t.op == "jmp":
        return p
    if t.op not in ("br", "switch"):
        return None
    pre = func.new_block("preheader")
    func.blocks.remove(pre)
    func.blocks.insert(func.blocks.index(h), pre)
    pre.append(Instr("jmp", [], targets=[h]))
    t.targets = [pre if x is h else x for x in t.targets]
    for ph in h.phis():
        ph.incoming = [pre if x is p else x for x in ph.incoming]
    func.compute_preds()
    return pre


def hoistable(i):
    if i.op not in PURE or i.op in ("vastart", "copy"):
        return False
    if i.op in ("divs", "divu", "rems", "remu"):
        d = i.args[1]
        return isinstance(d, Const) and d.value != 0     # dividing by zero traps
    return True


def licm(func):
    dom = DomTree(func)
    loops = natural_loops(dom)
    changed = False
    # inner loops first, so code can move out level by level
    for h, body in sorted(loops.items(), key=lambda kv: len(kv[1])):
        pre = make_preheader(func, h, body)
        if pre is None:
            continue
        # a new preheader is inside the loops around this one: what moves
        # into it can only move further out with them
        for h2, body2 in loops.items():
            if h in body2 and h2 is not h:
                body2.add(pre)
        defined_inside = {i for b in body for i in b.instrs}
        moved = False
        for b in dom.rpo:
            if b not in body:
                continue
            for i in list(b.instrs):
                if not hoistable(i):
                    continue
                if any(isinstance(a, Instr) and a in defined_inside for a in i.args):
                    continue
                b.instrs.remove(i)
                pre.insert(len(pre.instrs) - 1, i)
                defined_inside.discard(i)
                moved = changed = True
        if moved:
            dom = DomTree(func)
    return changed


# --------------------------------------------------------------------------
# Strength reduction of induction variables


UNSIGNED_CMP = {"lt": "ltu", "le": "leu", "gt": "gtu", "ge": "geu", "ltu": "ltu", "leu": "leu",
                "gtu": "gtu", "geu": "geu", "eq": "eq", "ne": "ne"}


def scaled_iv(v, p):
    """If v is p * k (p itself, a shift or a multiply by a constant),
    return k."""
    if v is p:
        return 1
    if isinstance(v, Instr) and v.args and v.args[0] is p and isinstance(v.args[-1], Const):
        if v.op == "shl" and v.args[1].value < 31:
            return 1 << v.args[1].value
        if v.op == "mul":
            return v.args[1].signed
    return None


def lockstep_pointer(h, p, step, pre, latch, users, inside):
    """Another header phi of the loop that is a pointer used for memory
    accesses and moves by k * step whenever p moves by step. Returns
    (q, q_next, base, k) with base = q's start minus p's start times k,
    or None."""
    if not isinstance(step, int) or step <= 0:
        return None
    p0 = p.args[p.incoming.index(pre)]
    for q in h.phis():
        if q is p:
            continue
        qn = q.args[q.incoming.index(latch)]
        if not (isinstance(qn, Instr) and qn.op == "add" and qn.args[0] is q
                and isinstance(qn.args[1], Const)):
            continue
        qstep = qn.args[1].signed
        if qstep <= 0 or qstep % step:
            continue
        k = qstep // step

        def addr_use(v, depth=0):
            for u in users.get(v, []):
                if (u.op == "load" and u.args[0] is v) or (u.op == "store" and u.args[1] is v):
                    return True
                if depth < 1 and u.op == "add" and u in inside and isinstance(u.args[1], Const) \
                        and addr_use(u, depth + 1):
                    return True
            return False
        if not addr_use(q):
            continue
        q0 = q.args[q.incoming.index(pre)]
        off = Instr("mul", [p0, Const(k)])
        base = Instr("sub", [q0, off])
        pre.insert(len(pre.instrs) - 1, off)
        pre.insert(len(pre.instrs) - 1, base)
        return q, qn, base, k
    return None


def strength_reduce(func):
    """For a loop counter p (a header phi stepped by a constant) and an
    address base + p * k with base invariant in the loop, keep a pointer
    that starts at base + init * k and steps by step * k. When the counter
    is then only used to end the loop, compare the pointer against
    base + limit * k instead and let the counter go."""
    dom = DomTree(func)
    loops = natural_loops(dom)
    changed = False
    for h, body in sorted(loops.items(), key=lambda kv: len(kv[1])):
        pre = make_preheader(func, h, body)
        if pre is None:
            continue
        latches = [b for b in h.preds if b in body]
        if len(latches) != 1 or len(h.preds) != 2:
            continue
        latch = latches[0]
        users = func.users()
        inside = {i for b in body for i in b.instrs}

        def invariant(v):
            return not (isinstance(v, Instr) and v in inside)
        for p in list(h.phis()):
            init = p.args[p.incoming.index(pre)]
            nxt = p.args[p.incoming.index(latch)]
            if not (isinstance(nxt, Instr) and nxt.op == "add" and nxt.args[0] is p
                    and invariant(nxt.args[1]) and nxt in inside):
                continue
            step = nxt.args[1].signed if isinstance(nxt.args[1], Const) else nxt.args[1]
            # base + p * k inside the loop (base invariant): addresses, and
            # multiplies (an add per iteration is cheaper than a MUL)
            cands = []
            for u in users.get(p, []):
                if u.op in ("shl", "mul") and u in inside and scaled_iv(u, p):
                    for a in users.get(u, []):
                        if a.op == "add" and a in inside and u in a.args:
                            base = a.args[1] if a.args[0] is u else a.args[0]
                            cands.append((a, base, scaled_iv(u, p)))
                    if u.op == "mul":
                        cands.append((u, Const(0), scaled_iv(u, p)))
                elif u.op == "add" and u in inside and u is not nxt:
                    base = u.args[1] if u.args[0] is p else u.args[0]
                    cands.append((u, base, 1))
            # (base + p * k) + inv, with inv invariant too: one candidate
            # with base + inv as its base (a[k][j] in a loop over k)
            for a, base, k in list(cands):
                for u in users.get(a, []):
                    if u.op == "add" and u in inside and a in u.args:
                        other = u.args[1] if u.args[0] is a else u.args[0]
                        if other is not a and invariant(other) and not isinstance(other, Const):
                            cands.append((u, (base, other), k))
            reduced = {}
            for a, base, k in cands:
                if isinstance(base, tuple):
                    if not all(invariant(x) for x in base):
                        continue
                elif base is p or not invariant(base) or k is None:
                    continue
                if k is None:
                    continue
                if k == 1 and isinstance(base, Const):
                    continue        # p + c: addressing modes take the offset for free
                is_addr = any((x.op == "load" and x.args[0] is a) or
                              (x.op == "store" and x.args[1] is a and x.args[0] is not a)
                              for x in users.get(a, []))
                if not is_addr and a.op != "mul" and not any(
                        isinstance(t, Instr) and t.op == "mul" for t in a.args):
                    continue
                key = (tuple(id(x) for x in base) if isinstance(base, tuple) else id(base), k)
                if key not in reduced:
                    if isinstance(base, tuple):
                        b2 = Instr("add", list(base))
                        pre.insert(len(pre.instrs) - 1, b2)
                        base = b2
                    q = Instr("phi", [], incoming=[])
                    h.insert(0, q)
                    off = Instr("mul", [init, Const(k)])
                    start = Instr("add", [base, off])
                    pre.insert(len(pre.instrs) - 1, off)
                    pre.insert(len(pre.instrs) - 1, start)
                    if isinstance(step, int):
                        stride = Const(step * k)
                    else:
                        stride = Instr("mul", [step, Const(k)])
                        pre.insert(len(pre.instrs) - 1, stride)
                    qn = Instr("add", [q, stride])
                    nb = nxt.block
                    nb.insert(nb.instrs.index(nxt) + 1, qn)
                    q.args = [start, qn]
                    q.incoming = [pre, latch]
                    reduced[key] = [q, qn, base, k, False]
                reduced[key][4] |= is_addr
                func.replace_uses({a: reduced[key][0]})
                changed = True
            # linear function test replacement: if the counter only ends
            # the loop, test a pointer that moves in step with it instead
            dce(func)
            users = func.users()
            if any(u is not nxt for u in users.get(p, [])):
                continue
            nu = [u for u in users.get(nxt, []) if u is not p]
            if len(nu) != 1 or nu[0].op not in UNSIGNED_CMP:
                continue
            cmp = nu[0]
            lim = cmp.args[1] if cmp.args[0] is nxt else cmp.args[0]
            if lim is nxt or not invariant(lim) or step == 0:
                continue
            if not isinstance(step, int) and cmp.op not in ("lt", "le", "ltu", "leu"):
                continue            # the direction of an unknown step: only counting up
            # only an address walk is known not to wrap around
            walks = [r for r in reduced.values() if r[4] and r[3] > 0]
            if walks:
                q, qn, base, k, _ = walks[0]
            else:
                w = lockstep_pointer(h, p, step, pre, latch, users, inside)
                if w is None:
                    continue
                q, qn, base, k = w
            off = Instr("mul", [lim, Const(k)])
            end = Instr("add", [base, off])
            pre.insert(len(pre.instrs) - 1, off)
            pre.insert(len(pre.instrs) - 1, end)
            op = UNSIGNED_CMP[cmp.op]
            cmp.op = op
            cmp.args = [qn, end] if cmp.args[0] is nxt else [end, qn]
    return changed


# --------------------------------------------------------------------------
# Sinking


def sink(func):
    """Move a step like p + 1 down past the last use of p in its block
    (but not past its own first use), so p dies at the step and the two
    can share a register instead of needing a copy on the loop's back
    edge. Only single-operand instructions move: sinking a whole
    expression tree below its leaves would only raise register pressure."""
    for b in func.blocks:
        instrs = b.instrs
        k = len(instrs) - 2
        while k >= 0:
            i = instrs[k]
            regs = [a for a in i.args if isinstance(a, (Instr, Param))]
            if i.op in PURE and i.op not in ("phi", "vastart") and len(regs) == 1:
                x = regs[0]
                last_x = None
                for n in range(k + 1, len(instrs)):
                    if i in instrs[n].args:
                        break
                    if x in instrs[n].args:
                        last_x = n
                if last_x is not None and last_x < len(instrs) - 1:
                    instrs.pop(k)
                    instrs.insert(last_x, i)
            k -= 1


# --------------------------------------------------------------------------
# Constants in registers across loops


def hoist_constants(func, free_imm):
    """A constant that an instruction in a loop can't take as a cheap
    immediate (free_imm(op, value) says, per target) is loaded into a
    register before the loop instead. Runs last: the simplifier would fold
    the copies away again."""
    loops = natural_loops(DomTree(func))
    for h, body in sorted(loops.items(), key=lambda kv: len(kv[1])):
        if any(i.op == "call" for b in body for i in b.instrs):
            continue        # across a call the constant would need a callee-saved register
        pre = make_preheader(func, h, body)
        if pre is None:
            continue
        made = {}

        def reg_for(c):
            key = (type(c).__name__, getattr(c, "value", None), getattr(c, "name", None),
                   getattr(c, "offset", None))
            if key not in made:
                cp = Instr("copy", [c])
                pre.insert(len(pre.instrs) - 1, cp)
                made[key] = cp
            return made[key]
        # in block order: body is a set, and the order of the copies shapes
        # the code (iterating the set would depend on memory addresses)
        for b in [b for b in func.blocks if b in body]:
            for i in b.instrs:
                op = i.op
                if op == "store":
                    v = i.args[0]
                    if isinstance(v, SymAddr) or (isinstance(v, Const) and v.value):
                        i.args[0] = reg_for(v)
                elif op in CMPOPS or op in BINOPS:
                    for k, v in enumerate(i.args):
                        if k == 1 and op in ("shl", "shr", "sar", "rotr") and isinstance(v, Const):
                            continue
                        if op in ("add", "sub"):
                            continue        # displacements and LEA take any constant
                        if isinstance(v, (Const, SymAddr)) and not free_imm(op, v):
                            i.args[k] = reg_for(v)


# --------------------------------------------------------------------------


def optimize(func, level=1, verify=False, free_imm=None):
    from .cfg import verify as check
    cleanup_cfg(func)
    mem2reg(func)
    if verify:
        check(func)
    if level <= 0:
        return
    loop_passes = [licm, strength_reduce, None]
    for loop_pass in loop_passes:
        for _ in range(20):
            changed = False
            for p in (simplify, gvn, load_cse, simplify, dce, cleanup_cfg):
                changed |= bool(p(func))
                if verify:
                    check(func)
            if not changed:
                break
        if loop_pass is not None:
            loop_pass(func)
            if verify:
                check(func)
    if free_imm is not None:
        hoist_constants(func, free_imm)
        cleanup_cfg(func)
        if verify:
            check(func)
    sink(func)
    if verify:
        check(func)
