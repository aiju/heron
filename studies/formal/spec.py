"""The specification language for instruction sets: parser and interpreter.

RFC 0038, Part II, describes the language; v1b.isa is draft 1b written in it.

The interpreter runs a specification's `step()` on a machine state whose
values are known (ints) or symbolic (z3 bit-vectors). It never forks: a
statement under a condition it can't decide runs under a *guard*, so a
state change becomes `if guard then new else old`, and one pass gives
the next state for every case at once. A fault or trap turns the guard
off for the rest of the instruction and is entered at the end.

    spec = load("v1b.isa")
    st = State(spec, regs={...}, mem=ConcreteMemory(...))
    out = spec.step(st)      # out.fault (None, or (vector, return address))
"""

import os
import re

import z3

HERE = os.path.dirname(os.path.abspath(__file__))


class SpecError(Exception):
    """A mistake in the specification (or in using it)."""


class Unspecified(Exception):
    """A concrete run reached an `assume` that doesn't hold: what happens
    next is outside the specification."""


# ================================================================ values
#
# A value is an int (a number from the text, not yet given a width) or a
# Bits: a width and an int or a z3 term. A 1-bit Bits may hold a z3
# Boolean, which is what conditions are.

class Bits:
    __slots__ = ("w", "x")

    def __init__(self, w, x):
        self.w, self.x = w, x

    def __repr__(self):
        return f"Bits({self.w}, {self.x})"

    @property
    def known(self):
        return isinstance(self.x, int)


def mk(w, x):
    if isinstance(x, int):
        return Bits(w, x & ((1 << w) - 1))
    if isinstance(x, z3.BoolRef):
        if z3.is_true(x):
            return Bits(1, 1)
        if z3.is_false(x):
            return Bits(1, 0)
        return Bits(1, x)
    if z3.is_bv_value(x):
        return Bits(w, x.as_long())
    return Bits(w, x)


def term(v, w=None):
    """A value as a z3 bit-vector term."""
    if isinstance(v, int):
        if w is None:
            raise SpecError("a number needs a width here")
        return z3.BitVecVal(v & ((1 << w) - 1), w)
    if isinstance(v.x, int):
        return z3.BitVecVal(v.x, v.w)
    if isinstance(v.x, z3.BoolRef):
        return z3.If(v.x, z3.BitVecVal(1, 1), z3.BitVecVal(0, 1))
    return v.x


def guard(v):
    """A condition (a 1-bit value or a number) as a Python bool or z3 Boolean."""
    if isinstance(v, int):
        return v != 0
    if v.w != 1:
        raise SpecError(f"a condition must be one bit, not {v.w}")
    if isinstance(v.x, int):
        return v.x != 0
    if isinstance(v.x, z3.BoolRef):
        return v.x
    return v.x == z3.BitVecVal(1, 1)


def g_and(a, b):
    if a is False or b is False:
        return False
    if a is True:
        return b
    if b is True:
        return a
    return z3.And(a, b)


def g_or(a, b):
    if a is True or b is True:
        return True
    if a is False:
        return b
    if b is False:
        return a
    return z3.Or(a, b)


def g_not(a):
    if isinstance(a, bool):
        return not a
    return z3.Not(a)


def decided(c):
    """A condition simplified, as a Python bool if it is constant."""
    if isinstance(c, bool):
        return c
    c = z3.simplify(c)
    if z3.is_true(c):
        return True
    if z3.is_false(c):
        return False
    return c


def sized(v, w):
    """v as a Bits of width w (a number takes it; a Bits must have it)."""
    if isinstance(v, int):
        return mk(w, v)
    if v.w != w:
        raise SpecError(f"width {v.w} where {w} is wanted")
    return v


def ite(c, a, b):
    """if c then a else b, for values and tuples of values."""
    if c is True:
        return a
    if c is False:
        return b
    if a is None:                    # no value: only on a path that has faulted
        return b
    if b is None:
        return a
    if isinstance(a, tuple):
        return tuple(ite(c, x, y) for x, y in zip(a, b))
    if isinstance(a, int) and isinstance(b, int):
        if a == b:
            return a
        a, b = mk(32, a), mk(32, b)
    w = a.w if isinstance(a, Bits) else b.w
    a, b = sized(a, w), sized(b, w)
    if a.known and b.known and a.x == b.x:
        return a
    if w == 1 and (isinstance(a.x, z3.BoolRef) or isinstance(b.x, z3.BoolRef)):
        return mk(1, z3.If(c, guard(a) if not a.known else z3.BoolVal(bool(a.x)),
                           guard(b) if not b.known else z3.BoolVal(bool(b.x))))
    return mk(w, z3.If(c, term(a), term(b)))


def _unify(a, b):
    if isinstance(a, int) and isinstance(b, int):
        return a, b, None
    if isinstance(a, int):
        return mk(b.w, a), b, b.w
    if isinstance(b, int):
        return a, mk(a.w, b), a.w
    if a.w != b.w:
        raise SpecError(f"widths differ: {a.w} and {b.w}")
    return a, b, a.w


_ARITH = {
    "+": (lambda a, b: a + b, lambda a, b: a + b),
    "-": (lambda a, b: a - b, lambda a, b: a - b),
    "*": (lambda a, b: a * b, lambda a, b: a * b),
    "&": (lambda a, b: a & b, lambda a, b: a & b),
    "|": (lambda a, b: a | b, lambda a, b: a | b),
    "^": (lambda a, b: a ^ b, lambda a, b: a ^ b),
    "/": (lambda a, b: a // b if b else (1 << 64) - 1, z3.UDiv),
    "%": (lambda a, b: a % b if b else a, z3.URem),
}
_CMP = {
    "==": (lambda a, b: a == b, lambda a, b: a == b),
    "!=": (lambda a, b: a != b, lambda a, b: a != b),
    "<": (lambda a, b: a < b, z3.ULT), "<=": (lambda a, b: a <= b, z3.ULE),
    ">": (lambda a, b: a > b, z3.UGT), ">=": (lambda a, b: a >= b, z3.UGE),
}


def _bool_bits(a, b, op):
    """&, |, ^ on two 1-bit values kept as Booleans."""
    ga, gb = guard(a), guard(b)
    f = {"&": z3.And, "|": z3.Or, "^": z3.Xor}[op]
    ga = z3.BoolVal(ga) if isinstance(ga, bool) else ga
    gb = z3.BoolVal(gb) if isinstance(gb, bool) else gb
    return mk(1, f(ga, gb))


def binop(op, a, b):
    if op in ("<<", ">>"):
        return shift(op, a, b)
    if op == "++":
        if isinstance(a, int) or isinstance(b, int):
            raise SpecError("++ needs values with widths")
        if a.known and b.known:
            return mk(a.w + b.w, (a.x << b.w) | b.x)
        return mk(a.w + b.w, z3.Concat(term(a), term(b)))
    a, b, w = _unify(a, b)
    if op in _CMP:
        if w is None:
            return int(_CMP[op][0](a, b))
        if a.known and b.known:
            return mk(1, int(_CMP[op][0](a.x, b.x)))
        return mk(1, _CMP[op][1](term(a), term(b)))
    if op not in _ARITH:
        raise SpecError(f"unknown operator {op}")
    if w is None:
        if op in ("/", "%"):
            return a // b if op == "/" else a % b
        return _ARITH[op][0](a, b)
    if a.known and b.known:
        if op in ("/", "%") and b.x == 0:
            return mk(w, (1 << w) - 1 if op == "/" else a.x)     # as SMT-LIB
        return mk(w, _ARITH[op][0](a.x, b.x))
    if w == 1 and op in ("&", "|", "^"):
        return _bool_bits(a, b, op)
    return mk(w, _ARITH[op][1](term(a), term(b)))


def shift(op, a, n):
    if isinstance(a, int):
        if not isinstance(n, int):
            raise SpecError("shifting a number by a value: give the number a width")
        return a << n if op == "<<" else a >> n
    w = a.w
    if isinstance(n, int):
        if a.known:
            return mk(w, a.x << n if op == "<<" else a.x >> n)
        if n >= w:
            return mk(w, 0)
        return mk(w, term(a) << n if op == "<<" else z3.LShR(term(a), n))
    if a.known and n.known:
        return mk(w, a.x << n.x if op == "<<" else a.x >> n.x)
    # widen both, shift, and cut back
    ww = max(w, n.w)
    x = z3.ZeroExt(ww - w, term(a)) if ww > w else term(a)
    s = z3.ZeroExt(ww - n.w, term(n)) if ww > n.w else term(n)
    r = x << s if op == "<<" else z3.LShR(x, s)
    return mk(w, z3.Extract(w - 1, 0, r) if ww > w else r)


def unop(op, a):
    if op == "not":
        g = guard(a)
        return int(not g) if isinstance(g, bool) else mk(1, z3.Not(g))
    if isinstance(a, int):
        return ~a if op == "~" else -a
    if a.known:
        return mk(a.w, ~a.x if op == "~" else -a.x)
    if a.w == 1 and isinstance(a.x, z3.BoolRef) and op == "~":
        return mk(1, z3.Not(a.x))
    return mk(a.w, ~term(a) if op == "~" else -term(a))


def extract(a, hi, lo):
    if hi < lo:
        raise SpecError(f"slice [{hi}:{lo}]")
    w = hi - lo + 1
    if isinstance(a, int):
        return mk(w, a >> lo)
    if hi >= a.w:
        raise SpecError(f"slice [{hi}:{lo}] of a {a.w}-bit value")
    if a.known:
        return mk(w, a.x >> lo)
    if a.w == 1:
        return a
    return mk(w, z3.simplify(z3.Extract(hi, lo, term(a))))


def bit_at(a, i):
    """a[i] for a value index i."""
    if isinstance(i, int):
        return extract(a, i, i)
    if i.known:
        return extract(a, i.x, i.x)
    return extract(shift(">>", a, i), 0, 0)


def zext(a, w=32):
    if isinstance(a, int):
        return mk(w, a)
    if a.w > w:
        raise SpecError(f"zext of {a.w} bits to {w}")
    if a.known:
        return mk(w, a.x)
    return mk(w, z3.ZeroExt(w - a.w, term(a)) if w > a.w else term(a))


def sext(a, w=32):
    if isinstance(a, int):
        return mk(w, a)
    if a.w > w:
        raise SpecError(f"sext of {a.w} bits to {w}")
    if a.known:
        x = a.x - (1 << a.w) if a.x >> (a.w - 1) else a.x
        return mk(w, x)
    return mk(w, z3.SignExt(w - a.w, term(a)) if w > a.w else term(a))


def _signed(x, w):
    return x - (1 << w) if x >> (w - 1) else x


def asr(a, n):
    n = sized(n, a.w) if isinstance(n, int) else zext(n, a.w) if n.w < a.w else n
    if a.known and n.known:
        return mk(a.w, _signed(a.x, a.w) >> min(n.x, a.w))
    return mk(a.w, term(a) >> term(n))


def ror(a, n):
    n = sized(n, a.w) if isinstance(n, int) else zext(n, a.w) if n.w < a.w else n
    if a.known and n.known:
        k = n.x % a.w
        return mk(a.w, (a.x >> k) | (a.x << (a.w - k)))
    return mk(a.w, z3.RotateRight(term(a), term(n)))


def sdiv(a, b):
    a, b, w = _unify(a, b)
    if a.known and b.known:
        if b.x == 0:
            raise SpecError("sdiv by zero")
        x, y = _signed(a.x, w), _signed(b.x, w)
        q = abs(x) // abs(y)
        return mk(w, q if (x < 0) == (y < 0) else -q)
    return mk(w, term(a) / term(b))


def srem(a, b):
    a, b, w = _unify(a, b)
    if a.known and b.known:
        if b.x == 0:
            raise SpecError("srem by zero")
        x, y = _signed(a.x, w), _signed(b.x, w)
        r = abs(x) % abs(y)
        return mk(w, r if x >= 0 else -r)
    return mk(w, z3.SRem(term(a), term(b)))


BUILTINS = {
    "zext": zext, "sext": sext, "asr": asr, "ror": ror, "sdiv": sdiv, "srem": srem,
}


# ================================================================ lexer

KEYWORDS = {"register", "hardwired", "flag", "memory", "const", "fn", "instruction",
            "let", "if", "elif", "else", "for", "in", "case", "return", "fault", "trap",
            "halt", "assume", "decode", "and", "or", "not", "then", "when", "pass"}
OPS = [":=", "==", "!=", "<=", ">=", "<<", ">>", "++", "..", "->",
       "+", "-", "*", "/", "%", "&", "|", "^", "~", "<", ">", "(", ")", "[", "]",
       ",", ":", "="]
_TOKEN = re.compile(r"""
    (?P<ws>[ \t]+) | (?P<comment>\#.*) |
    (?P<num>0[xX][0-9a-fA-F_]+|0[bB][01_]+|[0-9][0-9_]*) |
    (?P<name>[A-Za-z_][A-Za-z0-9_]*) | (?P<str>"[^"]*") |
    (?P<op>""" + "|".join(re.escape(o) for o in OPS) + ")", re.X)
_INSN = re.compile(r'^instruction\s+("[^"]*")\s+([01a-z\- ]+?)\s*(?:when\s+(.*?))?\s*:\s*(.*)$')


class Tok:
    __slots__ = ("kind", "val", "line")

    def __init__(self, kind, val, line):
        self.kind, self.val, self.line = kind, val, line

    def __repr__(self):
        return f"{self.kind}:{self.val!r}@{self.line}"


def _lex_line(text, lineno, toks):
    pos = 0
    while pos < len(text):
        m = _TOKEN.match(text, pos)
        if not m:
            raise SpecError(f"line {lineno}: can't read {text[pos:pos + 20]!r}")
        pos = m.end()
        k = m.lastgroup
        if k in ("ws", "comment"):
            continue
        v = m.group()
        if k == "num":
            toks.append(Tok("num", int(v.replace("_", ""), 0), lineno))
        elif k == "name":
            toks.append(Tok("kw" if v in KEYWORDS else "name", v, lineno))
        elif k == "str":
            toks.append(Tok("str", v[1:-1], lineno))
        else:
            toks.append(Tok("op", v, lineno))


def lex(src):
    toks, indents = [], [0]
    for lineno, raw in enumerate(src.split("\n"), 1):
        line = raw.rstrip()
        stripped = line.lstrip()
        if not stripped or stripped.startswith("#"):
            continue
        ind = len(line) - len(stripped)
        if ind > indents[-1]:
            indents.append(ind)
            toks.append(Tok("indent", None, lineno))
        while ind < indents[-1]:
            indents.pop()
            toks.append(Tok("dedent", None, lineno))
        if ind != indents[-1]:
            raise SpecError(f"line {lineno}: indentation doesn't match")
        m = _INSN.match(stripped)
        if m:
            toks.append(Tok("kw", "instruction", lineno))
            toks.append(Tok("str", m.group(1)[1:-1], lineno))
            toks.append(Tok("pattern", m.group(2), lineno))
            if m.group(3):
                toks.append(Tok("kw", "when", lineno))
                _lex_line(m.group(3), lineno, toks)
            toks.append(Tok("op", ":", lineno))
            _lex_line(m.group(4), lineno, toks)
        else:
            _lex_line(stripped, lineno, toks)
        toks.append(Tok("nl", None, lineno))
    while len(indents) > 1:
        indents.pop()
        toks.append(Tok("dedent", None, 0))
    toks.append(Tok("eof", None, 0))
    return toks


# ================================================================ parser
#
# The tree is tuples: statements ("let", names, expr), ("set", target,
# expr), ("if", [(cond, block)...], else_block), ("for", name, lo, hi,
# block), ("case", expr, [(values or None, block)...]), ("return", expr),
# ("fault", expr), ("trap", expr), ("halt",), ("assume", expr, why),
# ("decode", expr, else_block), ("expr", expr); expressions ("num", n),
# ("name", s), ("index", base, i), ("slice", base, hi, lo), ("call", name,
# args), ("bin", op, a, b), ("un", op, a), ("ite", c, a, b), ("tuple", xs).

BINARY = [["or"], ["and"], None, ["==", "!=", "<", "<=", ">", ">="], ["|"], ["^"], ["&"],
          ["++"], ["<<", ">>"], ["+", "-"], ["*", "/", "%"]]


class Parser:
    def __init__(self, toks):
        self.toks, self.i = toks, 0

    def peek(self, k=0):
        return self.toks[self.i + k]

    def next(self):
        t = self.toks[self.i]
        self.i += 1
        return t

    def at(self, kind, val=None):
        t = self.peek()
        return t.kind == kind and (val is None or t.val == val)

    def accept(self, kind, val=None):
        if self.at(kind, val):
            return self.next()
        return None

    def expect(self, kind, val=None):
        t = self.next()
        if t.kind != kind or (val is not None and t.val != val):
            want = val if val is not None else kind
            raise SpecError(f"line {t.line}: expected {want}, found {t.val if t.val is not None else t.kind}")
        return t

    # ---- top level

    def spec(self, spec):
        while not self.at("eof"):
            if self.accept("nl"):
                continue
            t = self.expect("kw")
            getattr(self, "decl_" + t.val)(spec, t)

    def decl_register(self, spec, t):
        name = self.expect("name").val
        count = None
        if self.accept("op", "["):
            count = self.expect("num").val
            self.expect("op", "]")
        self.expect("op", ":")
        width = self.expect("num").val
        self.expect("nl")
        spec.declare(name, ("reg", count, width), t.line)

    def decl_hardwired(self, spec, t):
        name = self.expect("name").val
        self.expect("op", "[")
        idx = self.expect("num").val
        self.expect("op", "]")
        self.expect("op", "=")
        val = self.expect("num").val
        self.expect("nl")
        spec.hardwired[(name, idx)] = val

    def decl_flag(self, spec, t):
        while not self.at("nl"):
            spec.declare(self.expect("name").val, ("reg", None, 1), t.line)
        self.expect("nl")

    def decl_memory(self, spec, t):
        name = self.expect("name").val
        self.expect("op", ":")
        aw = self.expect("num").val
        self.expect("op", "->")
        dw = self.expect("num").val
        self.expect("nl")
        spec.declare(name, ("mem", aw, dw), t.line)

    def decl_const(self, spec, t):
        name = self.expect("name").val
        self.expect("op", "=")
        e = self.expr()
        self.expect("nl")
        spec.declare(name, ("const", e), t.line)

    def decl_fn(self, spec, t):
        name = self.expect("name").val
        self.expect("op", "(")
        params = []
        while not self.accept("op", ")"):
            params.append(self.expect("name").val)
            if not self.at("op", ")"):
                self.expect("op", ",")
        self.expect("op", ":")
        spec.declare(name, ("fn", params, self.block()), t.line)

    def decl_instruction(self, spec, t):
        syntax = self.expect("str").val
        pat = self.expect("pattern").val
        when = None
        if self.accept("kw", "when"):
            when = self.expr()
        self.expect("op", ":")
        spec.instructions.append(Instruction(syntax, pat, when, self.block(), t.line))

    # ---- statements

    def block(self):
        if self.accept("nl"):
            self.expect("indent")
            out = []
            while not self.accept("dedent"):
                out.append(self.statement())
            return out
        st = self.simple()
        self.expect("nl")
        return [st]

    def statement(self):
        t = self.peek()
        if t.kind == "kw" and t.val in ("if", "for", "case", "decode"):
            self.next()
            return getattr(self, "st_" + t.val)(t)
        st = self.simple()
        self.expect("nl")
        return st

    def simple(self):
        t = self.peek()
        if t.kind == "kw":
            if t.val == "let":
                self.next()
                if self.accept("op", "("):
                    names = [self.expect("name").val]
                    while self.accept("op", ","):
                        names.append(self.expect("name").val)
                    self.expect("op", ")")
                else:
                    names = self.expect("name").val
                self.expect("op", "=")
                return ("let", names, self.expr(), t.line)
            if t.val in ("return", "fault", "trap"):
                self.next()
                return (t.val, self.expr(), t.line)
            if t.val in ("halt", "pass"):
                self.next()
                return (t.val, t.line)
            if t.val == "assume":
                self.next()
                e = self.expr()
                why = self.expect("str").val
                return ("assume", e, why, t.line)
        e = self.expr()
        if self.accept("op", ":="):
            if e[0] not in ("name", "index"):
                raise SpecError(f"line {t.line}: can't assign to that")
            return ("set", e, self.expr(), t.line)
        return ("expr", e, t.line)

    def st_if(self, t):
        arms = [(self.expr(), self.colon_block())]
        els = None
        while True:
            if self.accept("kw", "elif"):
                arms.append((self.expr(), self.colon_block()))
            elif self.accept("kw", "else"):
                els = self.colon_block()
                break
            else:
                break
        return ("if", arms, els, t.line)

    def colon_block(self):
        self.expect("op", ":")
        return self.block()

    def st_for(self, t):
        name = self.expect("name").val
        self.expect("kw", "in")
        lo = self.expr()
        self.expect("op", "..")
        hi = self.expr()
        return ("for", name, lo, hi, self.colon_block(), t.line)

    def st_case(self, t):
        e = self.expr()
        self.expect("op", ":")
        self.expect("nl")
        self.expect("indent")
        arms = []
        while not self.accept("dedent"):
            if self.accept("kw", "else"):
                vals = None
            else:
                vals = [self.expr_no_ternary()]
                while self.accept("op", ","):
                    vals.append(self.expr_no_ternary())
            arms.append((vals, self.colon_block()))
        return ("case", e, arms, t.line)

    def st_decode(self, t):
        e = self.expr()
        return ("decode", e, self.colon_block(), t.line)

    # ---- expressions

    def expr(self):
        if self.accept("kw", "if"):
            c = self.expr()
            self.expect("kw", "then")
            a = self.expr()
            self.expect("kw", "else")
            b = self.expr()
            return ("ite", c, a, b)
        return self.binary(0)

    def expr_no_ternary(self):
        return self.binary(0)

    def binary(self, level):
        if level == len(BINARY):
            return self.unary()
        ops = BINARY[level]
        if ops is None:                          # `not`
            if self.accept("kw", "not"):
                return ("un", "not", self.binary(level))
            return self.binary(level + 1)
        a = self.binary(level + 1)
        while True:
            t = self.peek()
            if (t.kind == "op" or t.kind == "kw") and t.val in ops:
                self.next()
                a = ("bin", t.val, a, self.binary(level + 1))
            else:
                return a

    def unary(self):
        if self.accept("op", "~"):
            return ("un", "~", self.unary())
        if self.accept("op", "-"):
            return ("un", "-", self.unary())
        return self.postfix(self.atom())

    def postfix(self, e):
        while True:
            if self.accept("op", "["):
                i = self.expr()
                if self.accept("op", ":"):
                    lo = self.expr()
                    self.expect("op", "]")
                    e = ("slice", e, i, lo)
                else:
                    self.expect("op", "]")
                    e = ("index", e, i)
            elif self.at("op", "(") and e[0] == "name":
                self.next()
                args = []
                while not self.accept("op", ")"):
                    args.append(self.expr())
                    if not self.at("op", ")"):
                        self.expect("op", ",")
                e = ("call", e[1], args)
            else:
                return e

    def atom(self):
        t = self.next()
        if t.kind == "num":
            return ("num", t.val)
        if t.kind == "name":
            return ("name", t.val)
        if t.kind == "op" and t.val == "(":
            e = self.expr()
            if self.accept("op", ","):
                xs = [e, self.expr()]
                while self.accept("op", ","):
                    xs.append(self.expr())
                self.expect("op", ")")
                return ("tuple", xs)
            self.expect("op", ")")
            return e
        raise SpecError(f"line {t.line}: unexpected {t.val if t.val is not None else t.kind}")


# ================================================================ the specification

class Instruction:
    def __init__(self, syntax, pattern, when, body, line):
        self.syntax, self.when, self.body, self.line = syntax, when, body, line
        bits = pattern.replace(" ", "")
        self.width = len(bits)
        self.mask = self.value = 0
        self.fields = {}            # name -> (hi, lo)
        for i, ch in enumerate(bits):
            pos = self.width - 1 - i
            if ch in "01":
                self.mask |= 1 << pos
                self.value |= int(ch) << pos
            elif ch != "-":
                if ch in self.fields:
                    hi, lo = self.fields[ch]
                    if lo != pos + 1:
                        raise SpecError(f"line {line}: field {ch} isn't contiguous")
                    self.fields[ch] = (hi, pos)
                else:
                    self.fields[ch] = (pos, pos)
        self.pattern = pattern

    @property
    def name(self):
        return self.syntax.split()[0] if self.syntax else ""

    def matches(self, w):
        return w & self.mask == self.value


class Spec:
    def __init__(self, src, name="spec"):
        self.name = name
        self.decls = {}
        self.hardwired = {}
        self.instructions = []
        self.lines = {}
        Parser(lex(src)).spec(self)
        self._consts = {}
        for need in ("step", "enter"):
            if need not in self.decls or self.decls[need][0] != "fn":
                raise SpecError(f"a specification needs fn {need}")

    def declare(self, name, d, line):
        if name in self.decls:
            raise SpecError(f"line {line}: {name} declared twice")
        if name in BUILTINS:
            raise SpecError(f"line {line}: {name} is a built-in")
        self.decls[name] = d
        self.lines[name] = line

    @property
    def registers(self):
        return {n: d[1:] for n, d in self.decls.items() if d[0] == "reg"}

    @property
    def memories(self):
        return {n: d[1:] for n, d in self.decls.items() if d[0] == "mem"}

    def const(self, name):
        if name not in self._consts:
            self._consts[name] = Run(self, None).eval(self.decls[name][1], {})
        return self._consts[name]

    def step(self, state, record=False):
        """Run one instruction on `state` (changed in place). Returns the Run:
        its fault (vector, return address, guard), assumptions and halt. With
        `record`, run.record lists every decision it met (Run.note)."""
        run = Run(self, state)
        if record:
            run.record = []
        run.step()
        return run


class State:
    """A machine's state: registers by name (a list for an array), each a
    Bits; memories by name, each an object with read(addr) -> Bits and
    write(addr, value, guard) (ConcreteMemory, or the caller's). An array
    register may be such an object too; it then keeps the hardwired
    entries itself."""

    def __init__(self, spec, regs, mems):
        self.spec = spec
        self.regs = dict(regs)
        self.mems = dict(mems)
        for name, (count, width) in spec.registers.items():
            if name not in self.regs:
                raise SpecError(f"no value for register {name}")
            v = self.regs[name]
            if count is None:
                self.regs[name] = sized(v, width)
            elif not isinstance(v, list):
                continue
            else:
                if len(v) != count:
                    raise SpecError(f"{name} has {count} entries, not {len(v)}")
                self.regs[name] = [sized(x, width) for x in v]
            for (n, i), val in spec.hardwired.items():
                if n == name:
                    self.regs[name][i] = mk(width, val)

    def copy(self):
        st = State.__new__(State)
        st.spec = self.spec
        st.regs = {k: list(v) if isinstance(v, list) else v for k, v in self.regs.items()}
        if any(not isinstance(v, (list, Bits)) for v in st.regs.values()):
            raise SpecError("can't copy a state with a register array object")
        st.mems = dict(self.mems)
        return st


class ConcreteMemory:
    """A memory with known contents: a dict (missing entries read as
    `default`), changed in place."""

    def __init__(self, aw, dw, data=None, default=0):
        self.aw, self.dw = aw, dw
        self.data = data if data is not None else {}
        self.default = default

    def read(self, a):
        if not a.known:
            raise SpecError("a symbolic address into a memory with known contents")
        return mk(self.dw, self.data.get(a.x, self.default))

    def write(self, a, v, g):
        if g is False:
            return
        if g is not True or not a.known or not v.known:
            raise SpecError("a symbolic write into a memory with known contents")
        self.data[a.x] = v.x


class _Dead(Exception):
    """Every path through a statement has faulted: abandon the statement."""


class Run:
    """One execution of the specification (see the module's docstring)."""

    def __init__(self, spec, state):
        self.spec, self.st = spec, state
        self.g = True
        self.fault_g = False
        self.fault = None            # (vector, return address) as values
        self.assumptions = []        # (guard => condition as z3 Boolean, why)
        self.halt_g = False
        self.double_fault = False
        self.start_pc = None
        self.matched = None          # the instruction decoded, if known
        self.record = None           # [(site, guard of one outcome, of the other)]

    # ---- the instruction

    def step(self):
        self.start_pc = self.st.regs.get("pc")
        try:
            self.call("step", [])
        except _Dead:
            pass
        if self.fault_g is not False:
            vec, ret = self.fault
            g, fg = self.g, self.fault_g
            self.g, self.fault_g, self.fault = fg, False, None
            try:
                self.call("enter", [vec, ret])
            except _Dead:
                pass
            if self.fault_g is not False:
                # a fault while entering one: the specification's assumptions exclude it
                self.double_fault = self.fault_g
            self.fault_g, self.fault = fg, (vec, ret)
            self.g = g_or(g, self.g)

    def raise_fault(self, vec, ret):
        if self.g is False:
            return
        if self.fault is None:
            self.fault = (vec, ret)
        else:
            self.fault = (ite(self.g, vec, self.fault[0]), ite(self.g, ret, self.fault[1]))
        self.fault_g = g_or(self.fault_g, self.g)
        self.g = False

    # ---- statements

    def note(self, site, c):
        """A decision met under the current guard: `site` says where (a
        statement's line and what it decides), `c` the condition. Recorded,
        if asked, as the guards under which each outcome happens: on known
        values, which outcome; on symbolic ones, terms a solver can aim at."""
        if self.record is not None:
            self.record.append((site, g_and(self.g, c), g_and(self.g, g_not(c))))

    def block(self, stmts, env):
        for st in stmts:
            if self.g is False:
                return
            try:
                getattr(self, "s_" + st[0])(st, env)
            except _Dead:
                return

    def s_let(self, st, env):
        v = self.eval(st[2], env)
        names = st[1]
        if isinstance(names, list):
            if not isinstance(v, tuple) or len(v) != len(names):
                raise SpecError(f"line {st[3]}: {len(names)} names for {v!r}")
            for n, x in zip(names, v):
                self.bind(env, n, x)
        else:
            self.bind(env, names, v)

    def bind(self, env, name, v):
        if name in env and self.g is not True:
            env[name] = ite(self.g, v, env[name])
        else:
            env[name] = v

    def s_set(self, st, env):
        target, v = st[1], self.eval(st[2], env)
        if target[0] == "name":
            name = target[1]
            if name in env:
                self.bind(env, name, v)
                return
            d = self.spec.decls.get(name)
            if d is None or d[0] != "reg" or d[1] is not None:
                raise SpecError(f"line {st[3]}: can't assign to {name}")
            v = sized(v, d[2])
            if d[2] == 1:
                self.note(("set", st[3], name), guard(v))
            self.st.regs[name] = ite(self.g, v, self.st.regs[name])
            return
        base, idx = target[1], self.eval(target[2], env)
        if base[0] != "name":
            raise SpecError(f"line {st[3]}: can't assign to that")
        name = base[1]
        d = self.spec.decls.get(name)
        if d is None:
            raise SpecError(f"line {st[3]}: unknown {name}")
        if d[0] == "mem":
            self.st.mems[name].write(sized(idx, d[1]), sized(v, d[2]), self.g)
            return
        if d[0] != "reg" or d[1] is None:
            raise SpecError(f"line {st[3]}: can't index {name}")
        v = sized(v, d[2])
        regs = self.st.regs[name]
        if not isinstance(regs, list):
            regs.write(idx, v, self.g)
            return
        if isinstance(idx, int) or idx.known:
            i = idx if isinstance(idx, int) else idx.x
            if (name, i) not in self.spec.hardwired:
                regs[i] = ite(self.g, v, regs[i])
            return
        for i in range(d[1]):
            if (name, i) in self.spec.hardwired:
                continue
            gi = g_and(self.g, guard(binop("==", idx, i)))
            regs[i] = ite(gi, v, regs[i])

    def s_if(self, st, env):
        rest, out = self.g, False
        seen = []
        for cond, blk in st[1]:
            self.g = rest
            c = decided(guard(self.eval(cond, env)))
            rest = self.g                       # (a call in the condition may fault)
            self.note(("branch", st[3], len(seen)), c)
            seen.append(None)
            self.g = g_and(rest, c)
            if self.g is not False:
                self.block(blk, env)
            out = g_or(out, self.g)
            rest = g_and(rest, g_not(c))
            if rest is False:
                break
        if rest is not False:
            self.g = rest
            if st[2] is not None:
                self.block(st[2], env)
            out = g_or(out, self.g)
        self.g = out

    def s_for(self, st, env):
        lo, hi = self.eval(st[2], env), self.eval(st[3], env)
        name, blk = st[1], st[4]
        lo_k = lo if isinstance(lo, int) else lo.x if lo.known else None
        hi_k = hi if isinstance(hi, int) else hi.x if hi.known else None
        if lo_k is not None and hi_k is not None:
            for i in range(lo_k, hi_k + 1):
                if self.g is False:
                    return
                env[name] = i
                self.block(blk, env)
            return
        # symbolic bounds: every value the bounds' width allows, guarded
        w = max(x.w for x in (lo, hi) if isinstance(x, Bits))
        if w > 6:
            raise SpecError(f"line {st[5]}: a loop over {w}-bit bounds")
        for i in range(1 << w):
            inside = g_and(guard(binop("<=", lo, i)), guard(binop("<=", i, hi)))
            g0 = self.g
            self.g = g_and(g0, inside)
            if self.g is not False:
                env[name] = i
                self.block(blk, env)
            self.g = g_or(self.g, g_and(g0, g_not(inside)))

    def s_case(self, st, env):
        v = self.eval(st[1], env)
        arms = []
        for vals, blk in st[2]:
            if vals is None:
                arms.append((None, blk))
            else:
                c = None
                for x in vals:
                    e = ("bin", "==", ("value", v), x)
                    c = e if c is None else ("bin", "or", c, e)
                arms.append((c, blk))
        els = None
        if arms and arms[-1][0] is None:
            els = arms.pop()[1]
        self.s_if(("if", arms, els, st[3]), env)

    def s_return(self, st, env):
        v = self.eval(st[1], env)
        r = env.get("$ret")
        env["$ret"] = v if r is None else ite(self.g, v, r)
        self.g = False

    def s_fault(self, st, env):
        self.note(("fault", st[2]), True)
        self.raise_fault(self.eval(st[1], env), self.start_pc)

    def s_trap(self, st, env):
        self.note(("trap", st[2]), True)
        self.raise_fault(self.eval(st[1], env), self.st.regs["pc"])

    def s_pass(self, st, env):
        pass

    def s_halt(self, st, env):
        self.note(("halt", st[1]), True)
        self.halt_g = g_or(self.halt_g, self.g)

    def s_assume(self, st, env):
        c = guard(self.eval(st[1], env))
        self.note(("assume", st[3]), c)
        if c is True:
            return
        if c is False and self.g is True:
            raise Unspecified(st[2])
        if isinstance(c, bool):
            c = z3.BoolVal(c)
        g = self.g if not isinstance(self.g, bool) else z3.BoolVal(self.g)
        self.assumptions.append((z3.Implies(g, c), st[2]))

    def s_expr(self, st, env):
        self.eval(st[1], env)

    def s_decode(self, st, env):
        p = self.eval(st[1], env)
        g0 = self.g
        rest, out = g0, False
        for ins in self.spec.instructions:
            if isinstance(p, int) or p.known:
                w = p if isinstance(p, int) else p.x
                m = ins.matches(w)
            else:
                m = decided(guard(binop("==", binop("&", p, ins.mask), ins.value)))
            if m is False:
                continue
            fields = {f: extract(p, hi, lo) for f, (hi, lo) in ins.fields.items()}
            if ins.when is not None:
                m = g_and(m, guard(self.eval(ins.when, dict(fields))))
            self.g = g_and(rest, m)
            if self.g is not False:
                if self.g is True:
                    self.matched = ins
                self.block(ins.body, dict(fields))
                out = g_or(out, self.g)
            rest = g_and(rest, g_not(m))
            if rest is False:
                break
        if rest is not False:
            self.g = rest
            self.block(st[2], env)
            out = g_or(out, self.g)
        self.g = out

    # ---- expressions

    def eval(self, e, env):
        k = e[0]
        if k == "num":
            return e[1]
        if k == "value":
            return e[1]
        if k == "name":
            return self.name(e[1], env)
        if k == "bin":
            op = e[1]
            if op in ("and", "or"):
                a = self.eval(e[2], env)
                ga = guard(a)
                if ga is (op == "or"):         # decided by the left side
                    return int(ga)
                # the right side runs only where the left doesn't decide:
                # under that guard, so that what it notes is what a run on
                # known values would note
                g0 = self.g
                rhs = ga if op == "and" else g_not(ga)
                self.g = g_and(g0, rhs)
                b = self.eval(e[3], env) if self.g is not False else 0
                self.g = g_or(g_and(g0, g_not(rhs)), self.g)
                gb = guard(b)
                if isinstance(ga, bool) and isinstance(gb, bool):
                    return int(ga and gb) if op == "and" else int(ga or gb)
                f = g_and if op == "and" else g_or
                r = f(ga, gb)
                return int(r) if isinstance(r, bool) else mk(1, r)
            return binop(op, self.eval(e[2], env), self.eval(e[3], env))
        if k == "un":
            return unop(e[1], self.eval(e[2], env))
        if k == "ite":
            c = guard(self.eval(e[1], env))
            if c is True:
                return self.eval(e[2], env)
            if c is False:
                return self.eval(e[3], env)
            return ite(c, self.eval(e[2], env), self.eval(e[3], env))
        if k == "tuple":
            return tuple(self.eval(x, env) for x in e[1])
        if k == "slice":
            a = self.eval(e[1], env)
            hi, lo = self.eval(e[2], env), self.eval(e[3], env)
            if not isinstance(hi, int) or not isinstance(lo, int):
                raise SpecError("slice bounds must be numbers")
            return extract(a, hi, lo)
        if k == "index":
            base = e[1]
            if base[0] == "name" and base[1] not in env:
                d = self.spec.decls.get(base[1])
                if d is not None and d[0] == "reg" and d[1] is not None:
                    return self.reg_at(base[1], self.eval(e[2], env))
                if d is not None and d[0] == "mem":
                    return self.st.mems[base[1]].read(sized(self.eval(e[2], env), d[1]))
            return bit_at(self.eval(base, env), self.eval(e[2], env))
        if k == "call":
            args = [self.eval(a, env) for a in e[2]]
            if e[1] in BUILTINS:
                return BUILTINS[e[1]](*args)
            return self.call(e[1], args)
        raise SpecError(f"can't evaluate {k}")

    def name(self, n, env):
        if n in env:
            return env[n]
        d = self.spec.decls.get(n)
        if d is None:
            raise SpecError(f"unknown name {n}")
        if d[0] == "const":
            return self.spec.const(n)
        if d[0] == "reg" and d[1] is None:
            return self.st.regs[n]
        raise SpecError(f"{n} isn't a value")

    def reg_at(self, name, idx):
        regs = self.st.regs[name]
        if not isinstance(regs, list):
            return regs.read(idx)
        if isinstance(idx, int) or idx.known:
            return regs[idx if isinstance(idx, int) else idx.x]
        out = regs[0]
        for i in range(1, len(regs)):
            out = ite(guard(binop("==", idx, i)), regs[i], out)
        return out

    def call(self, name, args):
        d = self.spec.decls.get(name)
        if d is None or d[0] != "fn":
            raise SpecError(f"unknown function {name}")
        params, body = d[1], d[2]
        if len(args) != len(params):
            raise SpecError(f"{name} takes {len(params)} arguments, not {len(args)}")
        if self.g is False:
            raise _Dead
        env = dict(zip(params, args))
        env["$ret"] = None
        g0 = self.g
        self.block(body, env)
        self.g = g_and(g0, g_not(self.fault_g)) if self.fault_g is not False else g0
        if self.g is False:
            raise _Dead
        return env["$ret"]


def load(name):
    """A specification in this folder, by file name."""
    path = name if os.path.isabs(name) else os.path.join(HERE, name)
    with open(path) as f:
        return Spec(f.read(), os.path.basename(path))
