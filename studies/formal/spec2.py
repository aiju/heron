"""The specification language for instruction sets: parser, checker and
interpreter.

RFC 0038, Part II, describes the language; v1b.isa is draft 1b written in
it. A specification is checked when it is loaded (types and widths,
effects, arguments, exhaustive matches, that every path of a function
returns) and then runs on a machine state whose values are known (ints,
bools) or symbolic (z3 terms).

On symbolic values the interpreter never forks: a statement under a
condition it can't decide runs under a *guard*, so a state change becomes
`if guard then new else old`, and one pass gives the next state for every
path at once. A fault or trap turns the guard off for the rest of the
instruction, and is entered at the end.

    spec = load("v1b.isa")
    st = State(spec, regs={...}, mems={...})
    run = spec.step(st)      # run.fault, run.fault_g, run.assumptions, ...
"""

import os
import re

import z3

HERE = os.path.dirname(os.path.abspath(__file__))


class SpecError(Exception):
    """A mistake in the specification (or in using it)."""


class Unspecified(Exception):
    """A run on known values reached an `assume` that doesn't hold: what
    happens next is outside the specification."""


# ================================================================ values
#
# uN values are Bits: a width and an int or a z3 bit-vector term. bool
# values are Python bools or z3 Booleans. An enum value is Bits as wide as
# its variants need; a record is a dict of its fields.

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
    if z3.is_bv_value(x):
        return Bits(w, x.as_long())
    return Bits(w, x)


def term(v):
    """A uN value as a z3 bit-vector term."""
    if isinstance(v.x, int):
        return z3.BitVecVal(v.x, v.w)
    return v.x


def guard(v):
    """A bool value as a Python bool or z3 Boolean (an int or a 1-bit
    value counts as one, for the tools' convenience)."""
    if isinstance(v, (bool, z3.BoolRef)):
        return v
    if isinstance(v, int):
        return v != 0
    if isinstance(v, Bits):
        return v.x != 0 if v.known else v.x == z3.BitVecVal(1, v.w)
    raise SpecError(f"not a condition: {v!r}")


def boolterm(b):
    return z3.BoolVal(b) if isinstance(b, bool) else b


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


def ite(c, a, b):
    """if c then a else b, for every kind of value."""
    if c is True:
        return a
    if c is False:
        return b
    if a is None:                    # no value: only on a path that has faulted
        return b
    if b is None:
        return a
    if isinstance(a, dict):
        return {k: ite(c, a[k], b[k]) for k in a}
    if isinstance(a, (bool, z3.BoolRef)):
        if isinstance(a, bool) and isinstance(b, bool) and a == b:
            return a
        return decided(z3.If(c, boolterm(a), boolterm(b)))
    if a.known and b.known and a.x == b.x:
        return a
    return mk(a.w, z3.If(c, term(a), term(b)))


def _signed(x, w):
    return x - (1 << w) if x >> (w - 1) else x


def _bits_op(op, a, b):
    w = a.w
    if a.known and b.known:
        x, y = a.x, b.x
        if op in ("/", "%") and y == 0:
            raise SpecError(f"{op} by zero")
        return mk(w, {"+": x + y, "-": x - y, "*": x * y, "&": x & y, "|": x | y, "^": x ^ y,
                      "/": x // y if y else 0, "%": x % y if y else 0}[op])
    ta, tb = term(a), term(b)
    return mk(w, {"+": lambda: ta + tb, "-": lambda: ta - tb, "*": lambda: ta * tb,
                  "&": lambda: ta & tb, "|": lambda: ta | tb, "^": lambda: ta ^ tb,
                  "/": lambda: z3.UDiv(ta, tb), "%": lambda: z3.URem(ta, tb)}[op]())


def _compare(op, a, b):
    if isinstance(a, (bool, z3.BoolRef)):
        if isinstance(a, bool) and isinstance(b, bool):
            return (a == b) if op == "==" else (a != b)
        x, y = boolterm(a), boolterm(b)
        return decided(x == y if op == "==" else x != y)
    if a.known and b.known:
        x, y = a.x, b.x
        return {"==": x == y, "!=": x != y, "<": x < y, "<=": x <= y, ">": x > y, ">=": x >= y}[op]
    ta, tb = term(a), term(b)
    return {"==": lambda: ta == tb, "!=": lambda: ta != tb, "<": lambda: z3.ULT(ta, tb),
            "<=": lambda: z3.ULE(ta, tb), ">": lambda: z3.UGT(ta, tb),
            ">=": lambda: z3.UGE(ta, tb)}[op]()


def _shift(op, a, n):
    w = a.w
    if a.known and n.known:
        return mk(w, a.x << n.x if op == "<<" else a.x >> n.x)
    ww = max(w, n.w)
    x = z3.ZeroExt(ww - w, term(a)) if ww > w else term(a)
    s = z3.ZeroExt(ww - n.w, term(n)) if ww > n.w else term(n)
    r = x << s if op == "<<" else z3.LShR(x, s)
    return mk(w, z3.Extract(w - 1, 0, r) if ww > w else r)


def _extract(a, hi, lo):
    w = hi - lo + 1
    if a.known:
        return mk(w, a.x >> lo)
    if lo == 0 and hi == a.w - 1:
        return a
    return mk(w, z3.simplify(z3.Extract(hi, lo, term(a))))


def _bit_at(a, i):
    if i.known:
        return _extract(a, i.x, i.x)
    return _extract(_shift(">>", a, i), 0, 0)


def _ext(a, w, signed):
    if a.known:
        return mk(w, _signed(a.x, a.w) if signed else a.x)
    if w == a.w:
        return a
    return mk(w, (z3.SignExt if signed else z3.ZeroExt)(w - a.w, term(a)))


def _asr(a, n):
    n = _ext(n, a.w, False) if n.w < a.w else n
    if a.known and n.known:
        return mk(a.w, _signed(a.x, a.w) >> min(n.x, a.w))
    return mk(a.w, term(a) >> term(n))


def _ror(a, n):
    n = _ext(n, a.w, False) if n.w < a.w else n
    if a.known and n.known:
        k = n.x % a.w
        return mk(a.w, (a.x >> k) | (a.x << (a.w - k)))
    return mk(a.w, z3.RotateRight(term(a), term(n)))


def _sdiv(a, b):
    if a.known and b.known:
        if b.x == 0:
            raise SpecError("sdiv by zero")
        x, y = _signed(a.x, a.w), _signed(b.x, b.w)
        q = abs(x) // abs(y)
        return mk(a.w, q if (x < 0) == (y < 0) else -q)
    return mk(a.w, term(a) / term(b))


def _srem(a, b):
    if a.known and b.known:
        if b.x == 0:
            raise SpecError("srem by zero")
        x, y = _signed(a.x, a.w), _signed(b.x, b.w)
        r = abs(x) % abs(y)
        return mk(a.w, r if x >= 0 else -r)
    return mk(a.w, z3.SRem(term(a), term(b)))


def _bit(b):
    if isinstance(b, bool):
        return Bits(1, int(b))
    return mk(1, z3.If(b, z3.BitVecVal(1, 1), z3.BitVecVal(0, 1)))


def _bool(x):
    return guard(x)


# ================================================================ types

class T:
    """A type: uN ('bits', N), bool, an enum or a record (by name)."""
    __slots__ = ("kind", "n", "name")

    def __init__(self, kind, n=0, name=None):
        self.kind, self.n, self.name = kind, n, name

    def __eq__(self, o):
        return isinstance(o, T) and (self.kind, self.n, self.name) == (o.kind, o.n, o.name)

    def __hash__(self):
        return hash((self.kind, self.n, self.name))

    def __repr__(self):
        return {"bits": f"u{self.n}", "bool": "bool"}.get(self.kind, self.name or self.kind)


BOOL = T("bool")
CONST = T("const")          # a number not yet given a type


def U(n):
    return T("bits", n)


# ================================================================ lexer

KEYWORDS = {"register", "hardwired", "flag", "memory", "const", "enum", "record", "fn", "proc",
            "instruction", "when", "let", "var", "if", "else", "for", "in", "match", "return",
            "fault", "trap", "halt", "assume", "decode", "true", "false"}
OPS = ["..=", ":=", "==", "!=", "<=", ">=", "<<", ">>", "++", "->", "=>", "&&", "||",
       "+", "-", "*", "/", "%", "&", "|", "^", "~", "!", "<", ">", "(", ")", "[", "]", "{", "}",
       ",", ":", "=", ".", "@", ";"]
_TOKEN = re.compile(r"""
    (?P<ws>[ \t\r]+) | (?P<nl>\n) | (?P<comment>//[^\n]*) |
    (?P<sized>[0-9]+'[hbd][0-9a-fA-F_]+) |
    (?P<num>0x[0-9a-fA-F_]+|0b[01_]+|[0-9][0-9_]*) |
    (?P<name>[A-Za-z_][A-Za-z0-9_]*) | (?P<str>"[^"\n]*") |
    (?P<op>""" + "|".join(re.escape(o) for o in OPS) + ")", re.X)
_PATTERN = re.compile(r"\s+([01a-z\- ]+?)\s*(?=when\b|\{)")
# a line ending in one of these goes on: no statement ends there
_GOES_ON = {"(", "[", "{", ",", ":", "=", ":=", "->", "=>", "&&", "||", "+", "-", "*", "/", "%",
            "&", "|", "^", "~", "!", "<", ">", "<=", ">=", "==", "!=", "<<", ">>", "++", "..=",
            ".", "@"}


class Tok:
    __slots__ = ("kind", "val", "line")

    def __init__(self, kind, val, line):
        self.kind, self.val, self.line = kind, val, line

    def __repr__(self):
        return f"{self.kind}:{self.val!r}@{self.line}"


def lex(src):
    toks, pos, line, depth = [], 0, 1, 0
    while pos < len(src):
        m = _TOKEN.match(src, pos)
        if not m:
            raise SpecError(f"line {line}: can't read {src[pos:pos + 20]!r}")
        pos = m.end()
        k, v = m.lastgroup, m.group()
        if k in ("ws", "comment"):
            continue
        if k == "nl":
            line += 1
            if depth == 0 and toks and toks[-1].kind != "nl" and toks[-1].val not in _GOES_ON:
                toks.append(Tok("nl", None, line - 1))
            continue
        if k == "num":
            toks.append(Tok("num", (int(v.replace("_", ""), 0), None), line))
        elif k == "sized":
            w, digits = v.split("'")
            base = {"h": 16, "b": 2, "d": 10}[digits[0]]
            try:
                x = int(digits[1:].replace("_", ""), base)
            except ValueError:
                raise SpecError(f"line {line}: can't read {v}")
            w = int(w)
            if not 1 <= w <= 128 or x >> w:
                raise SpecError(f"line {line}: {v} doesn't fit {w} bits")
            toks.append(Tok("num", (x, w), line))
        elif k == "name":
            toks.append(Tok("kw" if v in KEYWORDS else "name", v, line))
        elif k == "str":
            toks.append(Tok("str", v[1:-1], line))
            if len(toks) >= 2 and toks[-2].val == "instruction":
                pm = _PATTERN.match(src, pos)
                if not pm:
                    raise SpecError(f"line {line}: an instruction needs an encoding")
                toks.append(Tok("pattern", pm.group(1), line))
                pos = pm.end()
        else:
            if v in ("(", "["):
                depth += 1
            elif v in (")", "]"):
                depth -= 1
            toks.append(Tok("op", v, line))
    toks.append(Tok("nl", None, line))
    toks.append(Tok("eof", None, line))
    return toks


# ================================================================ syntax tree

class N:
    """A node: its kind, its parts (attributes), its line, and (filled in by
    the checker) its type."""

    def __init__(self, kind, line, **kw):
        self.kind, self.line, self.type = kind, line, None
        self.paren = False
        self.__dict__.update(kw)

    def __repr__(self):
        return f"N({self.kind}@{self.line})"


class Param:
    def __init__(self, name, type_):
        self.name, self.type = name, type_


class Func:
    def __init__(self, name, params, result, body, proc, line):
        self.name, self.params, self.result = name, params, result
        self.body, self.proc, self.line = body, proc, line


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

    def matches(self, w):
        return w & self.mask == self.value


# ================================================================ parser

BINARY = [["||"], ["&&"], ["==", "!=", "<", "<=", ">", ">="], ["|"], ["^"], ["&"], ["++"],
          ["<<", ">>"], ["+", "-"], ["*", "/", "%"]]
PATTERN_LEVEL = 4               # a match pattern is above |, which separates patterns
_GROUP = {"||": "logic", "&&": "logic", "==": "cmp", "!=": "cmp", "<": "cmp", "<=": "cmp",
          ">": "cmp", ">=": "cmp", "+": "arith", "-": "arith", "*": "arith", "/": "arith",
          "%": "arith"}


def _mixes(outer, inner):
    """Whether two operators, one an operand of the other, need parentheses
    to be read safely: && with ||, a comparison of a comparison, and any two
    different operators among the bitwise ones, shifts, ++ and arithmetic
    (but arithmetic among itself reads as in school)."""
    go, gi = _GROUP.get(outer, outer), _GROUP.get(inner, inner)
    if "cmp" in (go, gi):
        return go == gi
    if "logic" in (go, gi):
        return go == gi and outer != inner
    if outer == inner or go == gi == "arith":
        return False
    return True


class Parser:
    def __init__(self, toks):
        self.toks, self.i = toks, 0
        self.no_record = False

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
        return self.next() if self.at(kind, val) else None

    def expect(self, kind, val=None):
        t = self.next()
        if t.kind != kind or (val is not None and t.val != val):
            want = val if val is not None else kind
            got = t.val if t.val is not None else ("end of line" if t.kind == "nl" else t.kind)
            raise SpecError(f"line {t.line}: expected {want}, found {got}")
        return t

    def skip_nl(self):
        while self.accept("nl"):
            pass

    def end(self):
        """A statement ends at a line's end, a ;, the } of its block or the ,
        after a match arm."""
        if not (self.accept("nl") or self.accept("op", ";") or self.at("op", "}")
                or self.at("op", ",")):
            t = self.peek()
            raise SpecError(f"line {t.line}: expected the end of the statement, found {t.val}")

    # ---- declarations

    def spec(self, spec):
        self.skip_nl()
        while not self.at("eof"):
            t = self.expect("kw")
            fn = getattr(self, "d_" + t.val, None)
            if fn is None:
                raise SpecError(f"line {t.line}: {t.val} can't start a declaration")
            fn(spec, t)
            self.skip_nl()

    def type_(self):
        t = self.next()
        if t.kind == "name" and t.val == "bool":
            return BOOL
        if t.kind == "name":
            m = re.fullmatch(r"u([1-9][0-9]*)", t.val)
            if m:
                n = int(m.group(1))
                if n > 128:
                    raise SpecError(f"line {t.line}: u{n} is too wide")
                return U(n)
            return T("named", name=t.val)
        raise SpecError(f"line {t.line}: expected a type, found {t.val}")

    def plain(self):
        """A plain (unsized) number, where a count or index is wanted."""
        t = self.expect("num")
        if t.val[1] is not None:
            raise SpecError(f"line {t.line}: a plain number here")
        return t.val[0]

    def d_register(self, spec, t):
        name = self.expect("name").val
        count = None
        if self.accept("op", "["):
            count = self.plain()
            self.expect("op", "]")
        self.expect("op", ":")
        spec.declare(name, ("reg", count, self.type_()), t.line)
        self.end()

    def d_hardwired(self, spec, t):
        name = self.expect("name").val
        self.expect("op", "[")
        idx = self.plain()
        self.expect("op", "]")
        self.expect("op", "=")
        spec.hardwired[(name, idx)] = self.plain()
        self.end()

    def d_flag(self, spec, t):
        spec.declare(self.expect("name").val, ("reg", None, BOOL), t.line)
        while self.accept("op", ","):
            spec.declare(self.expect("name").val, ("reg", None, BOOL), t.line)
        self.end()

    def d_memory(self, spec, t):
        name = self.expect("name").val
        self.expect("op", "[")
        at = self.type_()
        self.expect("op", "]")
        self.expect("op", ":")
        spec.declare(name, ("mem", at, self.type_()), t.line)
        self.end()

    def d_const(self, spec, t):
        name = self.expect("name").val
        ty = self.type_() if self.accept("op", ":") else None
        self.expect("op", "=")
        spec.declare(name, ("const", ty, self.expr()), t.line)
        self.end()

    def d_enum(self, spec, t):
        name = self.expect("name").val
        self.expect("op", "{")
        self.skip_nl()
        vs = []
        while not self.accept("op", "}"):
            vs.append(self.expect("name").val)
            if not self.accept("op", ","):
                self.skip_nl()
                self.expect("op", "}")
                break
            self.skip_nl()
        if len(set(vs)) != len(vs) or not vs:
            raise SpecError(f"line {t.line}: enum {name}'s variants")
        spec.declare(name, ("enum", vs), t.line)
        self.end()

    def d_record(self, spec, t):
        name = self.expect("name").val
        self.expect("op", "{")
        self.skip_nl()
        fields = {}
        while not self.accept("op", "}"):
            f = self.expect("name").val
            self.expect("op", ":")
            if f in fields:
                raise SpecError(f"line {t.line}: field {f} twice")
            fields[f] = self.type_()
            if not self.accept("op", ","):
                self.skip_nl()
                self.expect("op", "}")
                break
            self.skip_nl()
        spec.declare(name, ("record", fields), t.line)
        self.end()

    def _func(self, spec, t, proc):
        name = self.expect("name").val
        self.expect("op", "(")
        params = []
        while not self.accept("op", ")"):
            p = self.expect("name").val
            self.expect("op", ":")
            params.append(Param(p, self.type_()))
            if not self.at("op", ")"):
                self.expect("op", ",")
        result = None
        if self.accept("op", "->"):
            result = self.type_()
        if not proc and result is None:
            raise SpecError(f"line {t.line}: fn {name} must give a value (a proc needn't)")
        spec.declare(name, ("fn", Func(name, params, result, self.block(), proc, t.line)), t.line)
        self.end()

    def d_fn(self, spec, t):
        self._func(spec, t, False)

    def d_proc(self, spec, t):
        self._func(spec, t, True)

    def d_instruction(self, spec, t):
        syntax = self.expect("str").val
        pat = self.expect("pattern").val
        when = self.head() if self.accept("kw", "when") else None
        spec.instructions.append(Instruction(syntax, pat, when, self.block(), t.line))
        self.end()

    # ---- statements

    def block(self):
        self.expect("op", "{")
        self.skip_nl()
        out = []
        while not self.accept("op", "}"):
            out.append(self.statement())
            self.skip_nl()
        return out

    def statement(self):
        t = self.peek()
        if t.kind == "kw":
            fn = getattr(self, "s_" + t.val, None)
            if fn is not None:
                self.next()
                return fn(t)
        e = self.expr()
        if self.accept("op", ":="):
            if not (e.kind in ("name", "state") or e.kind == "index" and e.a.kind == "state"):
                raise SpecError(f"line {t.line}: can't assign to that")
            st = N("assign", t.line, target=e, value=self.expr())
        else:
            st = N("call_st", t.line, call=e)
        self.end()
        return st

    def s_let(self, t, mutable=False):
        name = self.expect("name").val
        ty = self.type_() if self.accept("op", ":") else None
        self.expect("op", "=")
        st = N("let", t.line, name=name, decl=ty, value=self.expr(), mutable=mutable)
        self.end()
        return st

    def s_var(self, t):
        return self.s_let(t, mutable=True)

    def s_if(self, t):
        arms = [(self.head(), self.block())]
        els = None
        while self.at("kw", "else"):
            self.next()
            if self.accept("kw", "if"):
                arms.append((self.head(), self.block()))
            else:
                els = self.block()
                break
        self.end()
        return N("if", t.line, arms=arms, els=els)

    def s_for(self, t):
        name = self.expect("name").val
        ty = self.type_() if self.accept("op", ":") else None
        self.expect("kw", "in")
        lo = self.head()
        self.expect("op", "..=")
        hi = self.head()
        st = N("for", t.line, name=name, decl=ty, lo=lo, hi=hi, body=self.block())
        self.end()
        return st

    def s_match(self, t):
        e = self.head()
        arms = self.arms(statement=True)
        self.end()
        return N("match_st", t.line, subject=e, arms=arms)

    def arms(self, statement):
        """{ pattern | pattern => body, ... }: (patterns or None for _, body)."""
        self.expect("op", "{")
        self.skip_nl()
        out = []
        while not self.accept("op", "}"):
            line = self.peek().line
            if self.accept("name", "_"):
                pats = None
            else:
                pats = [self.binary(PATTERN_LEVEL)]
                while self.accept("op", "|"):
                    pats.append(self.binary(PATTERN_LEVEL))
            self.expect("op", "=>")
            if statement:
                if self.at("op", "{"):
                    body = self.block()
                    self.end()
                else:
                    body = [self.statement()]
            else:
                body = self.expr()
            out.append((pats, body, line))
            self.accept("op", ",")
            self.skip_nl()
        return out

    def s_return(self, t):
        if self.at("nl") or self.at("op", "}") or self.at("op", ";") or self.at("op", ","):
            st = N("return", t.line, value=None)
        else:
            st = N("return", t.line, value=self.expr())
        self.end()
        return st

    def s_fault(self, t):
        st = N("fault", t.line, value=self.expr())
        self.end()
        return st

    def s_trap(self, t):
        st = N("trap", t.line, value=self.expr())
        self.end()
        return st

    def s_halt(self, t):
        self.end()
        return N("halt", t.line)

    def s_assume(self, t):
        c = self.expr()
        self.expect("op", ",")
        st = N("assume", t.line, cond=c, why=self.expect("str").val)
        self.end()
        return st

    def s_decode(self, t):
        e = self.head()
        self.expect("kw", "else")
        st = N("decode", t.line, value=e, els=self.block())
        self.end()
        return st

    # ---- expressions

    def expr(self):
        return self.binary(0)

    def head(self):
        """The expression before a block's {: an if's or match's subject, a
        loop's bounds, a when. A record literal there would read as the
        block, so it needs parentheses."""
        return self.nested(True)

    def nested(self, head):
        old, self.no_record = self.no_record, head
        try:
            return self.expr()
        finally:
            self.no_record = old

    def binary(self, level):
        if level == len(BINARY):
            return self.unary()
        a = self.binary(level + 1)
        while True:
            t = self.peek()
            if t.kind == "op" and t.val in BINARY[level]:
                self.next()
                a = N("bin", t.line, op=t.val, a=a, b=self.binary(level + 1))
                for x in (a.a, a.b):
                    if x.kind == "bin" and not x.paren and _mixes(t.val, x.op):
                        raise SpecError(f"line {t.line}: {x.op} and {t.val} together need "
                                        "parentheses, to say which goes first")
            else:
                return a

    def unary(self):
        t = self.peek()
        if t.kind == "op" and t.val in ("~", "!", "-"):
            self.next()
            return N("un", t.line, op=t.val, a=self.unary())
        return self.postfix(self.atom())

    def postfix(self, e):
        while True:
            t = self.peek()
            if self.accept("op", "["):
                i = self.nested(False)
                if self.accept("op", ":"):
                    lo = self.nested(False)
                    self.expect("op", "]")
                    e = N("slice", t.line, a=e, hi=i, lo=lo)
                else:
                    self.expect("op", "]")
                    e = N("index", t.line, a=e, i=i)
            elif self.accept("op", "."):
                e = N("dot", t.line, a=e, field=self.expect("name").val)
            else:
                return e

    def atom(self):
        t = self.next()
        if t.kind == "num":
            return N("num", t.line, value=t.val[0], width=t.val[1])
        if t.kind == "kw" and t.val in ("true", "false"):
            return N("boolean", t.line, value=t.val == "true")
        if t.kind == "kw" and t.val == "match":
            e = self.head()
            return N("match", t.line, subject=e, arms=self.arms(statement=False))
        if t.kind == "op" and t.val == "@":
            return N("state", t.line, name=self.expect("name").val)
        if t.kind == "name":
            if self.at("op", "("):
                self.next()
                pos, named = [], {}
                while not self.accept("op", ")"):
                    if self.peek().kind == "name" and self.peek(1).val == ":":
                        n = self.next().val
                        self.next()
                        if n in named:
                            raise SpecError(f"line {t.line}: argument {n} twice")
                        named[n] = self.nested(False)
                    else:
                        if named:
                            raise SpecError(f"line {t.line}: a positional argument after a named one")
                        pos.append(self.nested(False))
                    if not self.at("op", ")"):
                        self.expect("op", ",")
                return N("call", t.line, name=t.val, pos=pos, named=named)
            if self.at("op", "{") and not self.no_record:
                # Record { field: value, ... }: a record's name starts with a capital
                save = self.i
                self.next()
                self.skip_nl()
                if self.peek().kind == "name" and self.peek(1).val == ":" or self.at("op", "}"):
                    fields = {}
                    while not self.accept("op", "}"):
                        f = self.expect("name").val
                        self.expect("op", ":")
                        if f in fields:
                            raise SpecError(f"line {t.line}: field {f} twice")
                        fields[f] = self.nested(False)
                        if not self.accept("op", ","):
                            self.skip_nl()
                            self.expect("op", "}")
                            break
                        self.skip_nl()
                    return N("record", t.line, name=t.val, fields=fields)
                self.i = save
            return N("name", t.line, name=t.val)
        if t.kind == "op" and t.val == "(":
            e = self.nested(False)
            self.expect("op", ")")
            e.paren = True
            return e
        raise SpecError(f"line {t.line}: unexpected {t.val if t.val is not None else 'end of line'}")


# ================================================================ the checker

BUILTINS = {"zext", "sext", "asr", "ror", "sdiv", "srem", "bit", "bool"}


class Checker:
    """Types every expression (node.type), and checks the rules of RFC 0038,
    Part II: widths, effects, arguments, matches, returns, names."""

    def __init__(self, spec):
        self.spec = spec

    def err(self, node, msg):
        raise SpecError(f"line {node.line}: {msg}")

    def resolve(self, ty, line):
        if ty is None or ty.kind != "named":
            return ty
        d = self.spec.decls.get(ty.name)
        if d is None or d[0] not in ("enum", "record"):
            raise SpecError(f"line {line}: no type {ty.name}")
        return T(d[0], name=ty.name)

    def run(self):
        sp = self.spec
        for name, d in list(sp.decls.items()):
            line = sp.lines[name]
            if d[0] == "reg":
                sp.decls[name] = ("reg", d[1], self.resolve(d[2], line))
            elif d[0] == "mem":
                sp.decls[name] = ("mem", self.resolve(d[1], line), self.resolve(d[2], line))
            elif d[0] == "record":
                sp.decls[name] = ("record", {f: self.resolve(t, line) for f, t in d[1].items()})
            elif d[0] == "fn":
                f = d[1]
                for p in f.params:
                    p.type = self.resolve(p.type, f.line)
                f.result = self.resolve(f.result, f.line)
        for name, d in sp.decls.items():
            if d[0] == "const":
                ty = self.resolve(d[1], sp.lines[name])
                ty = self.expect(d[2], ty, {}, None)
                if ty == CONST:
                    self.err(d[2], f"const {name}: give it a type, or its value a size (32'd...)")
                sp.decls[name] = ("const", ty, d[2])
                if not self.constant(d[2]):
                    self.err(d[2], f"const {name} must be a constant expression")
        for (name, i), v in sp.hardwired.items():
            d = sp.decls.get(name)
            if d is None or d[0] != "reg" or d[1] is None or not 0 <= i < d[1]:
                raise SpecError(f"hardwired {name}[{i}] isn't a register")
            self.fits(v, d[2], None)
        for name, d in sp.decls.items():
            if d[0] == "fn":
                self.func(d[1])
        for ins in sp.instructions:
            scope = {f: (U(hi - lo + 1), False) for f, (hi, lo) in ins.fields.items()}
            for f in scope:
                if f in sp.decls:
                    raise SpecError(f"line {ins.line}: field {f} is a global name")
            if ins.when is not None:
                self.expect(ins.when, BOOL, [scope], None)
                self.pure(ins.when)
            self.block(ins.body, [dict(scope)], Func(ins.syntax, [], None, ins.body, True, ins.line))
        if "step" not in sp.decls or not sp.decls["step"][1].proc:
            raise SpecError("a specification needs proc step()")
        if "enter" not in sp.decls or not sp.decls["enter"][1].proc:
            raise SpecError("a specification needs proc enter(vector, ret)")

    def constant(self, e):
        if e.kind == "num" or e.kind == "boolean":
            return True
        if e.kind == "name":
            d = self.spec.decls.get(e.name)
            return d is not None and d[0] == "const"
        if e.kind == "bin":
            return self.constant(e.a) and self.constant(e.b)
        if e.kind == "un":
            return self.constant(e.a)
        return e.kind == "dot" and e.type is not None and e.type.kind == "enum"

    def pure(self, e):
        """A `when` condition reads nothing but the fields and constants."""
        if e.kind in ("state", "state_index"):
            self.err(e, "a when condition can't read state")
        for v in e.__dict__.values():
            if isinstance(v, N):
                self.pure(v)

    # ---- functions and statements

    def func(self, f):
        scope = {}
        for p in f.params:
            if p.name in self.spec.decls:
                raise SpecError(f"line {f.line}: parameter {p.name} is a global name")
            if p.name in scope:
                raise SpecError(f"line {f.line}: parameter {p.name} twice")
            scope[p.name] = (p.type, False)
        self.block(f.body, [scope], f)
        if f.result is not None and not self.ends(f.body):
            raise SpecError(f"line {f.line}: {f.name} can end without returning a value")

    def ends(self, stmts):
        """Whether a block never falls off its end: it returns or faults on
        every path."""
        if not stmts:
            return False
        s = stmts[-1]
        if s.kind in ("return", "fault", "trap"):
            return True
        if s.kind == "if":
            return s.els is not None and all(self.ends(b) for _, b in s.arms) and self.ends(s.els)
        if s.kind == "match_st":
            return all(self.ends(b) for _, b, _ in s.arms)
        return False

    def lookup(self, scopes, name):
        for sc in reversed(scopes):
            if name in sc:
                return sc[name]
        return None

    def declare(self, scopes, name, ty, mutable, node):
        if name in self.spec.decls or name in BUILTINS:
            self.err(node, f"{name} is a global name")
        if self.lookup(scopes, name) is not None:
            self.err(node, f"{name} is already a name here (no shadowing)")
        scopes[-1][name] = (ty, mutable)

    def block(self, stmts, scopes, f):
        scopes = scopes + [{}]
        for st in stmts:
            self.stmt(st, scopes, f)

    def effects(self, node, f, what):
        if f is None:
            self.err(node, f"{what} in a constant")
        if not f.proc:
            self.err(node, f"{what} in fn {f.name}: only a proc may do that")

    def stmt(self, st, scopes, f):
        k = st.kind
        if k == "let":
            ty = self.resolve(st.decl, st.line)
            t = self.top(st.value, ty, scopes, f)
            self.declare(scopes, st.name, t, st.mutable, st)
        elif k == "assign":
            tg = st.target
            if tg.kind == "index" and not self.state_index(tg):
                self.err(st, f"can't assign to one bit of @{tg.a.name}")
            if tg.kind == "name":
                v = self.lookup(scopes, tg.name)
                if v is None and tg.name in self.spec.decls:
                    self.err(st, f"{tg.name} is state: write @{tg.name}")
                if v is None:
                    self.err(st, f"no name {tg.name}")
                if not v[1]:
                    self.err(st, f"{tg.name} is a let: it can't change (make it a var)")
                self.top(st.value, v[0], scopes, f)
            else:
                self.effects(st, f, "changing state")
                d = self.spec.decls.get(tg.name)
                if d is None or d[0] not in ("reg", "mem"):
                    self.err(st, f"no register or memory {tg.name}")
                if tg.kind == "state_index":
                    if d[0] == "reg" and d[1] is None:
                        self.err(st, f"{tg.name} isn't an array")
                    at = d[1] if d[0] == "mem" else self.index_type(d[1])
                    self.expect(tg.i, at, scopes, f)
                    self.top(st.value, d[2], scopes, f)
                else:
                    if d[0] != "reg" or d[1] is not None:
                        self.err(st, f"{tg.name} needs an index")
                    self.top(st.value, d[2], scopes, f)
        elif k == "if":
            for c, b in st.arms:
                self.expect(c, BOOL, scopes, f)
                self.block(b, scopes, f)
            if st.els is not None:
                self.block(st.els, scopes, f)
        elif k == "for":
            ty = self.resolve(st.decl, st.line)
            lt = self.infer_pair(st.lo, st.hi, ty, scopes, f)
            if lt.kind != "bits":
                self.err(st, "a loop runs over uN values")
            st.var_type = lt
            inner = scopes + [{}]
            self.declare(inner, st.name, lt, False, st)
            self.block(st.body, inner, f)
        elif k == "match_st":
            t = self.expr(st.subject, None, scopes, f)
            self.match_arms(st, t, scopes, f, statement=True)
        elif k == "return":
            if f.result is None:
                if st.value is not None:
                    self.err(st, f"{f.name} gives no value")
            else:
                if st.value is None:
                    self.err(st, f"{f.name} must give a {f.result}")
                self.top(st.value, f.result, scopes, f)
        elif k in ("fault", "trap"):
            self.effects(st, f, k)
            self.expect(st.value, self.vector_type(), scopes, f)
        elif k == "halt":
            self.effects(st, f, "halt")
        elif k == "assume":
            self.effects(st, f, "assume")
            self.expect(st.cond, BOOL, scopes, f)
        elif k == "decode":
            self.effects(st, f, "decode")
            t = self.expr(st.value, None, scopes, f)
            widths = {i.width for i in self.spec.instructions}
            if t != U(max(widths)) or len(widths) != 1:
                self.err(st, f"decode takes a u{max(widths)}, as the encodings are")
            self.block(st.els, scopes, f)
        elif k == "call_st":
            c = st.call
            if c.kind != "call":
                self.err(st, "a statement must be a call, an assignment or a keyword")
            t = self.call(c, scopes, f, top=True)
            callee = self.spec.decls.get(c.name)
            if c.name in BUILTINS or not callee[1].proc:
                self.err(st, f"{c.name}'s value is thrown away (a fn only gives a value)")
            if t is not None:
                self.err(st, f"{c.name}'s value is thrown away (name it with let)")
        else:
            self.err(st, f"unknown statement {k}")

    def state_index(self, e):
        """@r[i] or @mem[a]: an index node on an array register or a memory
        becomes an access (state_index); on anything else it is a bit."""
        if e.a.kind != "state":
            return False
        d = self.spec.decls.get(e.a.name)
        if d is None or not (d[0] == "mem" or d[0] == "reg" and d[1] is not None):
            return False
        e.kind, e.name = "state_index", e.a.name
        return True

    def vector_type(self):
        return self.spec.decls["enter"][1].params[0].type if "enter" in self.spec.decls else U(32)

    def index_type(self, count):
        n = max(1, (count - 1).bit_length())
        return U(n)

    def top(self, e, want, scopes, f):
        """An expression that may be a whole proc call (the right side of a
        let, an assignment or a return)."""
        if e.kind == "call" and e.name not in BUILTINS:
            t = self.call(e, scopes, f, top=True)
            if t is None:
                self.err(e, f"{e.name} gives no value")
            if want is not None and t != want:
                self.err(e, f"{e.name} gives a {t}, not a {want}")
            return t
        return self.expect(e, want, scopes, f)

    def match_arms(self, node, t, scopes, f, statement, want=None):
        seen, covered, results = set(), False, []
        for i, (pats, body, line) in enumerate(node.arms):
            if covered:
                raise SpecError(f"line {line}: an arm after `_` (or after every value)")
            if pats is None:
                covered = True
            else:
                for p in pats:
                    self.expect(p, t, scopes, f)
                    if not self.constant(p):
                        self.err(p, "a match pattern is a constant")
                    v = self.const_value(p, t)
                    if v in seen:
                        self.err(p, "a value matched twice")
                    seen.add(v)
            if statement:
                self.block(body, scopes, f)
            else:
                results.append(self.expect(body, None, scopes, f))
            if not covered and self.all_values(t, seen):
                covered = True
        if not covered:
            self.err(node, f"the match doesn't cover every {t} (add `_`)")
        node.exhaustive_at = len(node.arms) - 1
        if not statement:
            types = {r for r in results if r != CONST}
            if len(types) > 1:
                self.err(node, f"the arms give different types: {types}")
            if not types and (want is None or want.kind != "bits"):
                self.err(node, "the arms are all bare numbers: give one a type")
            t = types.pop() if types else want
            for (_, body, _) in node.arms:
                self.expect(body, t, scopes, f)
            return t
        return None

    def all_values(self, t, seen):
        if t.kind == "bool":
            return seen >= {True, False}
        if t.kind == "enum":
            return len(seen) == len(self.spec.decls[t.name][1])
        if t.kind == "bits" and t.n <= 12:
            return len(seen) == 1 << t.n
        return False

    def const_value(self, e, t):
        """A constant expression's value (int, bool, or enum index)."""
        v = Run(self.spec, None).eval(e, {})
        if isinstance(v, Bits):
            return v.x
        return v

    # ---- expressions

    def expect(self, e, want, scopes, f):
        t = self.expr(e, want, scopes, f)
        if want is not None and t != want:
            if t == CONST:
                self.fits_node(e, want)
                self.settle(e, want)
                return want
            self.err(e, f"a {t} where a {want} is wanted")
        if t == CONST and want is None:
            return CONST
        return t

    def settle(self, e, t):
        """Give a constant expression (numbers only) its type."""
        if e.kind == "num" and e.width is not None:
            return
        e.type = t
        if e.kind == "bin" and e.op not in ("==", "!=", "<", "<=", ">", ">=", "&&", "||"):
            if e.op in ("<<", ">>"):
                self.settle(e.a, t)
            else:
                self.settle(e.a, t)
                self.settle(e.b, t)
        elif e.kind == "un":
            self.settle(e.a, t)

    def number(self, e):
        """The exact value of a constant expression of numbers."""
        if e.kind == "num":
            return e.value
        if e.kind == "un":
            a = self.number(e.a)
            return {"-": -a, "~": ~a}[e.op]
        if e.kind == "bin":
            a, b = self.number(e.a), self.number(e.b)
            return {"+": a + b, "-": a - b, "*": a * b, "&": a & b, "|": a | b, "^": a ^ b,
                    "<<": a << b, ">>": a >> b, "/": a // b if b else 0, "%": a % b if b else 0}[e.op]
        if e.kind == "name":
            return None
        self.err(e, "not a number")

    def fits_node(self, e, t):
        if t.kind != "bits":
            self.err(e, f"a number where a {t} is wanted")
        v = self.number(e)
        if v is not None:
            self.fits(v, t, e)

    def fits(self, v, t, node):
        if not -(1 << (t.n - 1)) <= v < (1 << t.n):
            msg = f"{v:#x} doesn't fit a {t}"
            if node is None:
                raise SpecError(msg)
            self.err(node, msg)

    def infer_pair(self, a, b, want, scopes, f):
        """The common type of two operands, a number taking the other's."""
        ta = self.expr(a, None, scopes, f)
        tb = self.expr(b, None, scopes, f)
        if ta == CONST and tb == CONST:
            if want is None:
                self.err(a, "two bare numbers: give one a type")
            self.expect(a, want, scopes, f)
            self.expect(b, want, scopes, f)
            return want
        if ta == CONST:
            self.expect(a, tb, scopes, f)
            return tb
        if tb == CONST:
            self.expect(b, ta, scopes, f)
            return ta
        if ta != tb:
            self.err(a, f"a {ta} and a {tb}")
        if want is not None and ta != want:
            self.err(a, f"a {ta} where a {want} is wanted")
        return ta

    def expr(self, e, want, scopes, f):
        t = self._expr(e, want, scopes, f)
        e.type = t
        return t

    def _expr(self, e, want, scopes, f):
        k = e.kind
        sp = self.spec
        if k == "num":
            return CONST if e.width is None else U(e.width)
        if k == "boolean":
            return BOOL
        if k == "name":
            v = self.lookup(scopes, e.name) if scopes else None
            if v is not None:
                return v[0]
            d = sp.decls.get(e.name)
            if d is None:
                self.err(e, f"no name {e.name}")
            if d[0] == "const":
                return d[1]
            if d[0] in ("reg", "mem"):
                self.err(e, f"{e.name} is state: write @{e.name}")
            self.err(e, f"{e.name} isn't a value")
        if k == "state":
            d = sp.decls.get(e.name)
            if d is None or d[0] != "reg" or d[1] is not None:
                self.err(e, f"no register {e.name}" if d is None else f"{e.name} needs an index")
            return d[2]
        if k == "state_index":
            d = sp.decls.get(e.name)
            if d is None or d[0] not in ("reg", "mem") or (d[0] == "reg" and d[1] is None):
                self.err(e, f"no array register or memory {e.name}")
            at = d[1] if d[0] == "mem" else self.index_type(d[1])
            self.expect(e.i, at, scopes, f)
            return d[2]
        if k == "dot":
            if e.a.kind == "name" and e.a.name in sp.decls and sp.decls[e.a.name][0] == "enum" \
                    and self.lookup(scopes or [], e.a.name) is None:
                vs = sp.decls[e.a.name][1]
                if e.field not in vs:
                    self.err(e, f"{e.a.name} has no {e.field}")
                e.enum_index = vs.index(e.field)
                return T("enum", name=e.a.name)
            t = self.expr(e.a, None, scopes, f)
            if t.kind != "record":
                self.err(e, f"a {t} has no fields")
            fields = sp.decls[t.name][1]
            if e.field not in fields:
                self.err(e, f"{t.name} has no field {e.field}")
            return fields[e.field]
        if k == "record":
            d = sp.decls.get(e.name)
            if d is None or d[0] != "record":
                self.err(e, f"no record {e.name}")
            if set(e.fields) != set(d[1]):
                missing = set(d[1]) - set(e.fields)
                extra = set(e.fields) - set(d[1])
                self.err(e, f"{e.name} needs exactly its fields" +
                         (f" (missing {', '.join(sorted(missing))})" if missing else "") +
                         (f" (no field {', '.join(sorted(extra))})" if extra else ""))
            for fn, v in e.fields.items():
                self.expect(v, d[1][fn], scopes, f)
            return T("record", name=e.name)
        if k == "un":
            if e.op == "!":
                self.expect(e.a, BOOL, scopes, f)
                return BOOL
            t = self.expr(e.a, want if want is not None and want.kind == "bits" else None, scopes, f)
            if t == CONST:
                return CONST
            if t.kind != "bits":
                self.err(e, f"{e.op} on a {t}")
            return t
        if k == "bin":
            op = e.op
            if op in ("&&", "||"):
                self.expect(e.a, BOOL, scopes, f)
                self.expect(e.b, BOOL, scopes, f)
                return BOOL
            if op in ("==", "!="):
                t = self.infer_pair(e.a, e.b, None, scopes, f)
                return BOOL
            if op in ("<", "<=", ">", ">="):
                t = self.infer_pair(e.a, e.b, None, scopes, f)
                if t.kind != "bits":
                    self.err(e, f"{op} compares uN values, not {t}")
                return BOOL
            if op == "++":
                ta = self.expr(e.a, None, scopes, f)
                tb = self.expr(e.b, None, scopes, f)
                if ta.kind != "bits" or tb.kind != "bits":
                    self.err(e, "++ joins uN values (a bare number has no width)")
                return U(ta.n + tb.n)
            if op in ("<<", ">>"):
                ta = self.expr(e.a, want if want is not None and want.kind == "bits" else None,
                              scopes, f)
                tb = self.expr(e.b, None, scopes, f)
                if tb == CONST:
                    n = self.number(e.b)
                    if n is None or n < 0:
                        self.err(e, "a shift count is a uN value or a number")
                    if ta != CONST and n >= ta.n:
                        self.err(e, f"shifting a {ta} by {n} leaves nothing")
                    self.settle(e.b, U(max(1, n.bit_length())))
                elif tb.kind != "bits":
                    self.err(e, "a shift count is a uN value")
                if ta == CONST:
                    if want is None or want.kind != "bits":
                        if tb == CONST:
                            return CONST
                        self.err(e, "shifting a bare number: give it a type")
                    self.expect(e.a, want, scopes, f)
                    return want
                if ta.kind != "bits":
                    self.err(e, f"shifting a {ta}")
                return ta
            # arithmetic and bitwise
            ta = self.expr(e.a, None, scopes, f)
            tb = self.expr(e.b, None, scopes, f)
            if ta == CONST and tb == CONST:
                return CONST
            t = self.infer_pair(e.a, e.b, None, scopes, f)
            if t.kind != "bits":
                self.err(e, f"{op} on a {t}")
            return t
        if k == "index" and self.state_index(e):
            return self._expr(e, want, scopes, f)
        if k == "index":
            t = self.expr(e.a, None, scopes, f)
            if t.kind != "bits":
                self.err(e, f"bit select on a {t}")
            ti = self.expr(e.i, None, scopes, f)
            if ti == CONST:
                i = self.number(e.i)
                if i is None or not 0 <= i < t.n:
                    self.err(e, f"bit {i} of a {t}")
                self.settle(e.i, U(max(1, t.n.bit_length())))
            elif ti.kind != "bits":
                self.err(e, "a bit index is a uN value")
            return U(1)
        if k == "slice":
            t = self.expr(e.a, None, scopes, f)
            if t.kind != "bits":
                self.err(e, f"slice of a {t}")
            hi, lo = self.number(e.hi), self.number(e.lo)
            if hi is None or lo is None or not 0 <= lo <= hi < t.n:
                self.err(e, f"slice [{hi}:{lo}] of a {t}")
            e.hi_v, e.lo_v = hi, lo
            return U(hi - lo + 1)
        if k == "match":
            t = self.expr(e.subject, None, scopes, f)
            return self.match_arms(e, t, scopes, f, statement=False, want=want)
        if k == "call":
            return self.call(e, scopes, f, top=False)
        self.err(e, f"unknown expression {k}")

    def call(self, e, scopes, f, top):
        sp = self.spec
        if e.name in BUILTINS:
            return self.builtin(e, scopes, f)
        d = sp.decls.get(e.name)
        if d is None or d[0] != "fn":
            self.err(e, f"no fn or proc {e.name}")
        g = d[1]
        if g.proc:
            self.effects(e, f, f"calling proc {g.name}")
            if not top:
                self.err(e, f"proc {g.name} inside an expression: call it on its own "
                         "(let x = ...), so the order of what it does is plain")
        ps = g.params
        if len(e.pos) + len(e.named) != len(ps):
            self.err(e, f"{g.name} takes {len(ps)} arguments")
        types = [p.type for p in ps]
        if e.pos and len(set(types)) != len(types):
            self.err(e, f"{g.name} has parameters of the same type: name its arguments "
                     f"({', '.join(p.name + ': ...' for p in ps)})")
        e.order = []
        for i, a in enumerate(e.pos):
            self.expect(a, ps[i].type, scopes, f)
            e.order.append(a)
        rest = ps[len(e.pos):]
        for p in rest:
            if p.name not in e.named:
                self.err(e, f"{g.name}: no argument {p.name}")
            self.expect(e.named[p.name], p.type, scopes, f)
            e.order.append(e.named[p.name])
        for n in e.named:
            if n not in {p.name for p in ps}:
                self.err(e, f"{g.name} has no parameter {n}")
        return g.result

    def builtin(self, e, scopes, f):
        n, args = e.name, e.pos
        if e.named:
            self.err(e, f"{n} takes positional arguments")
        if n in ("zext", "sext"):
            if len(args) != 2:
                self.err(e, f"{n}(x, width)")
            t = self.expr(args[0], None, scopes, f)
            if t.kind != "bits":
                self.err(e, f"{n} of a {t}")
            w = self.number(args[1])
            if w is None or not t.n <= w <= 128:
                self.err(e, f"{n} of a {t} to {w} bits")
            e.width = w
            return U(w)
        if n in ("asr", "ror"):
            if len(args) != 2:
                self.err(e, f"{n}(x, count)")
            t = self.expr(args[0], None, scopes, f)
            if t.kind != "bits":
                self.err(e, f"{n} of a {t}")
            tc = self.expr(args[1], None, scopes, f)
            if tc == CONST:
                self.expect(args[1], t, scopes, f)
            elif tc.kind != "bits":
                self.err(e, "a count is a uN value")
            return t
        if n in ("sdiv", "srem"):
            if len(args) != 2:
                self.err(e, f"{n}(a, b)")
            return self.infer_pair(args[0], args[1], None, scopes, f)
        if n == "bit":
            if len(args) != 1:
                self.err(e, "bit(b)")
            self.expect(args[0], BOOL, scopes, f)
            return U(1)
        if n == "bool":
            if len(args) != 1:
                self.err(e, "bool(x)")
            self.expect(args[0], U(1), scopes, f)
            return BOOL
        self.err(e, f"no builtin {n}")


# ================================================================ the specification

class Spec:
    def __init__(self, src, name="spec"):
        self.name = name
        self.decls = {}
        self.hardwired = {}
        self.instructions = []
        self.lines = {}
        Parser(lex(src)).spec(self)
        Checker(self).run()
        self._consts = {}

    def declare(self, name, d, line):
        if name in self.decls:
            raise SpecError(f"line {line}: {name} declared twice")
        if name in BUILTINS:
            raise SpecError(f"line {line}: {name} is a builtin")
        self.decls[name] = d
        self.lines[name] = line

    @property
    def registers(self):
        return {n: (d[1], d[2]) for n, d in self.decls.items() if d[0] == "reg"}

    def const(self, name):
        if name not in self._consts:
            self._consts[name] = Run(self, None).eval(self.decls[name][2], {})
        return self._consts[name]

    def step(self, state, record=False):
        """Run one instruction on `state` (changed in place). Returns the Run:
        its fault (vector, return address), fault guard, assumptions and
        halt. With `record`, run.record lists every decision it met."""
        run = Run(self, state)
        if record:
            run.record = []
        run.step()
        return run

    def when_holds(self, ins, w):
        """Whether instruction ins's `when` takes a known parcel w."""
        if ins.when is None:
            return True
        fields = {f: mk(hi - lo + 1, w >> lo) for f, (hi, lo) in ins.fields.items()}
        return guard(Run(self, None).eval(ins.when, fields)) is True

    def decisions(self):
        """Every decision in the text, as Run.note names it, with the
        outcomes it can have: {(site, outcome)}."""
        out = set()

        def walk(stmts):
            for st in stmts:
                visit(st)

        def visit(n):
            if not isinstance(n, N):
                return
            k = n.kind
            if k == "if":
                for i, (c, b) in enumerate(n.arms):
                    out.update({(("branch", n.line, i), True), (("branch", n.line, i), False)})
                    visit(c)
                    walk(b)
                if n.els:
                    walk(n.els)
                return
            if k in ("match_st", "match"):
                visit(n.subject)
                for i, (pats, body, _) in enumerate(n.arms):
                    out.add((("branch", n.line, i), True))
                    if i < n.exhaustive_at:
                        out.add((("branch", n.line, i), False))
                    if k == "match_st":
                        walk(body)
                    else:
                        visit(body)
                return
            if k == "assign" and n.target.kind == "state" and n.value.type == BOOL:
                site = ("set", n.line, n.target.name)
                if n.value.kind == "boolean":
                    out.add((site, n.value.value))
                else:
                    out.update({(site, True), (site, False)})
            elif k in ("fault", "trap"):
                out.add(((k, n.line), True))
            elif k == "halt":
                out.add((("halt", n.line), True))
            for v in n.__dict__.values():
                if isinstance(v, N):
                    visit(v)
                elif isinstance(v, list):
                    for x in v:
                        if isinstance(x, N):
                            visit(x)
                elif isinstance(v, dict):
                    for x in v.values():
                        if isinstance(x, N):
                            visit(x)
            if k == "for":
                walk(n.body)
            if k == "decode":
                walk(n.els)
        for d in self.decls.values():
            if d[0] == "fn":
                walk(d[1].body)
        for ins in self.instructions:
            walk(ins.body)
        return out


class State:
    """A machine's state: registers by name (uN as Bits, flags as bool; an
    array as a list, or an object with read(index) and write(index, value,
    guard), which then keeps the hardwired entries itself); memories by
    name, objects with read(address) and write(address, value, guard)."""

    def __init__(self, spec, regs, mems):
        self.spec = spec
        self.regs = dict(regs)
        self.mems = dict(mems)
        for name, (count, ty) in spec.registers.items():
            if name not in self.regs:
                raise SpecError(f"no value for register {name}")
            v = self.regs[name]
            if count is not None and isinstance(v, list):
                if len(v) != count:
                    raise SpecError(f"{name} has {count} entries, not {len(v)}")
                for (n, i), val in spec.hardwired.items():
                    if n == name:
                        v[i] = mk(ty.n, val)


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
        self.fault = None            # (vector, return address)
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
            self.call_func("step", [])
        except _Dead:
            pass
        if self.fault_g is not False:
            vec, ret = self.fault
            g, fg = self.g, self.fault_g
            self.g, self.fault_g, self.fault = fg, False, None
            try:
                self.call_func("enter", [vec, ret])
            except _Dead:
                pass
            if self.fault_g is not False:
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

    def note(self, site, c):
        """A decision met under the current guard: `site` says where (a
        statement's line and what it decides), `c` the condition. Recorded,
        if asked, as the guards under which each outcome happens."""
        if self.record is not None:
            self.record.append((site, g_and(self.g, c), g_and(self.g, g_not(c))))

    # ---- statements

    def block(self, stmts, env):
        env = env.child()
        for st in stmts:
            if self.g is False:
                return
            try:
                getattr(self, "s_" + st.kind)(st, env)
            except _Dead:
                return

    def s_let(self, st, env):
        env.define(st.name, self.eval(st.value, env))

    def s_assign(self, st, env):
        v = self.eval(st.value, env)
        if self.g is False:
            return
        tg = st.target
        if tg.kind == "name":
            env.set(tg.name, v, self.g)
            return
        d = self.spec.decls[tg.name]
        if tg.kind == "state":
            if d[2] == BOOL:
                self.note(("set", st.line, tg.name), v)
            self.st.regs[tg.name] = ite(self.g, v, self.st.regs[tg.name])
            return
        idx = self.eval(tg.i, env)
        if d[0] == "mem":
            self.st.mems[tg.name].write(idx, v, self.g)
            return
        regs = self.st.regs[tg.name]
        if not isinstance(regs, list):
            regs.write(idx, v, self.g)
            return
        if idx.known:
            if (tg.name, idx.x) not in self.spec.hardwired:
                regs[idx.x] = ite(self.g, v, regs[idx.x])
            return
        for i in range(d[1]):
            if (tg.name, i) in self.spec.hardwired:
                continue
            regs[i] = ite(g_and(self.g, _compare("==", idx, mk(idx.w, i))), v, regs[i])

    def s_if(self, st, env):
        rest, out = self.g, False
        for k, (cond, blk) in enumerate(st.arms):
            self.g = rest
            c = decided(self.eval(cond, env))
            rest = self.g
            self.note(("branch", st.line, k), c)
            self.g = g_and(rest, c)
            if self.g is not False:
                self.block(blk, env)
            out = g_or(out, self.g)
            rest = g_and(rest, g_not(c))
            if rest is False:
                break
        if rest is not False:
            self.g = rest
            if st.els is not None:
                self.block(st.els, env)
            out = g_or(out, self.g)
        self.g = out

    def arm_conds(self, node, v, env):
        """Each arm's condition (the subject equals one of its patterns), the
        arm the match must take when reached being True."""
        out = []
        for i, (pats, body, _) in enumerate(node.arms):
            if pats is None or i == node.exhaustive_at:
                out.append(True)
                continue
            c = False
            for p in pats:
                c = g_or(c, _compare("==", v, self.eval(p, env)))
            out.append(decided(c))
        return out

    def s_match_st(self, st, env):
        v = self.eval(st.subject, env)
        rest, out = self.g, False
        for k, c in enumerate(self.arm_conds(st, v, env)):
            self.g = rest
            self.note(("branch", st.line, k), c)
            self.g = g_and(rest, c)
            if self.g is not False:
                self.block(st.arms[k][1], env)
            out = g_or(out, self.g)
            rest = g_and(rest, g_not(c))
            if rest is False:
                break
        self.g = out

    def s_for(self, st, env):
        lo, hi = self.eval(st.lo, env), self.eval(st.hi, env)
        w = st.var_type.n
        if lo.known and hi.known:
            for i in range(lo.x, hi.x + 1):
                if self.g is False:
                    return
                inner = env.child()
                inner.define(st.name, mk(w, i))
                self.block(st.body, inner)
            return
        if w > 6:
            raise SpecError(f"line {st.line}: a loop over u{w} bounds that aren't known")
        for i in range(1 << w):
            iv = mk(w, i)
            inside = g_and(_compare("<=", lo, iv), _compare("<=", iv, hi))
            g0 = self.g
            self.g = g_and(g0, inside)
            if self.g is not False:
                inner = env.child()
                inner.define(st.name, iv)
                self.block(st.body, inner)
            self.g = g_or(self.g, g_and(g0, g_not(inside)))

    def s_return(self, st, env):
        v = self.eval(st.value, env) if st.value is not None else None
        if self.g is False:
            return
        r = env.ret
        env.frame["$ret"] = v if r is None else ite(self.g, v, r)
        self.g = False

    def s_fault(self, st, env):
        self.note(("fault", st.line), True)
        self.raise_fault(self.eval(st.value, env), self.start_pc)

    def s_trap(self, st, env):
        self.note(("trap", st.line), True)
        self.raise_fault(self.eval(st.value, env), self.st.regs["pc"])

    def s_halt(self, st, env):
        self.note(("halt", st.line), True)
        self.halt_g = g_or(self.halt_g, self.g)

    def s_assume(self, st, env):
        c = decided(self.eval(st.cond, env))
        self.note(("assume", st.line), c)
        if c is True:
            return
        if c is False and self.g is True:
            raise Unspecified(st.why)
        self.assumptions.append((z3.Implies(boolterm(self.g), boolterm(c)), st.why))

    def s_call_st(self, st, env):
        self.eval(st.call, env)

    def s_decode(self, st, env):
        p = self.eval(st.value, env)
        rest, out = self.g, False
        for ins in self.spec.instructions:
            if p.known:
                m = ins.matches(p.x)
            else:
                m = decided(_compare("==", _bits_op("&", p, mk(p.w, ins.mask)), mk(p.w, ins.value)))
            if m is False:
                continue
            fields = Env(None)
            for f, (hi, lo) in ins.fields.items():
                fields.define(f, _extract(p, hi, lo))
            if ins.when is not None:
                m = g_and(m, decided(self.eval(ins.when, fields)))
            self.g = g_and(rest, m)
            if self.g is not False:
                if self.g is True:
                    self.matched = ins
                self.block(ins.body, fields)
                out = g_or(out, self.g)
            rest = g_and(rest, g_not(m))
            if rest is False:
                break
        if rest is not False:
            self.g = rest
            self.block(st.els, env)
            out = g_or(out, self.g)
        self.g = out

    # ---- expressions

    def eval(self, e, env):
        k = e.kind
        if k == "num":
            t = e.type
            if t is None or t.kind != "bits":
                raise SpecError(f"line {e.line}: a number with no type")
            return mk(t.n, e.value)
        if k == "boolean":
            return e.value
        if k == "name":
            v = env.get(e.name) if env is not None else None
            if v is not None:
                return v
            return self.spec.const(e.name)
        if k == "state":
            return self.st.regs[e.name]
        if k == "state_index":
            d = self.spec.decls[e.name]
            idx = self.eval(e.i, env)
            if d[0] == "mem":
                return self.st.mems[e.name].read(idx)
            regs = self.st.regs[e.name]
            if not isinstance(regs, list):
                return regs.read(idx)
            if idx.known:
                return regs[idx.x]
            out = regs[0]
            for i in range(1, len(regs)):
                out = ite(_compare("==", idx, mk(idx.w, i)), regs[i], out)
            return out
        if k == "dot":
            if e.type.kind == "enum" and hasattr(e, "enum_index"):
                return mk(self.enum_width(e.type), e.enum_index)
            return self.eval(e.a, env)[e.field]
        if k == "record":
            return {f: self.eval(v, env) for f, v in e.fields.items()}
        if k == "un":
            a = self.eval(e.a, env)
            if e.op == "!":
                return g_not(a)
            if a.known:
                return mk(a.w, ~a.x if e.op == "~" else -a.x)
            return mk(a.w, ~term(a) if e.op == "~" else -term(a))
        if k == "bin":
            return self.binary(e, env)
        if k == "index":
            return _bit_at(self.eval(e.a, env), self.eval(e.i, env))
        if k == "slice":
            return _extract(self.eval(e.a, env), e.hi_v, e.lo_v)
        if k == "match":
            # each arm is worked out under its own guard, so that what it
            # notes is what a run on known values would note; the patterns
            # differ, so at most one arm's condition holds
            v = self.eval(e.subject, env)
            g0 = rest = self.g
            vals = []
            for i, c in enumerate(self.arm_conds(e, v, env)):
                self.g = rest
                self.note(("branch", e.line, i), c)
                self.g = g_and(rest, c)
                if self.g is not False:
                    vals.append((c, self.eval(e.arms[i][1], env)))
                rest = g_and(rest, g_not(c))
                if rest is False:
                    break
            self.g = g0
            out = None
            for c, val in reversed(vals):
                out = val if out is None else ite(c, val, out)
            return out
        if k == "call":
            return self.call(e, env)
        raise SpecError(f"line {e.line}: can't evaluate {k}")

    def binary(self, e, env):
        op = e.op
        if op in ("&&", "||"):
            a = decided(self.eval(e.a, env))
            if a is (op == "||"):
                return a
            # the right side runs only where the left doesn't decide: under
            # that guard, so that what it notes is what a run on known
            # values would note
            g0 = self.g
            rhs = a if op == "&&" else g_not(a)
            self.g = g_and(g0, rhs)
            b = self.eval(e.b, env) if self.g is not False else False
            self.g = g_or(g_and(g0, g_not(rhs)), self.g)
            f = g_and if op == "&&" else g_or
            return decided(f(a, b))
        a, b = self.eval(e.a, env), self.eval(e.b, env)
        if op in ("==", "!=", "<", "<=", ">", ">="):
            return _compare(op, a, b)
        if op == "++":
            if a.known and b.known:
                return mk(a.w + b.w, (a.x << b.w) | b.x)
            return mk(a.w + b.w, z3.Concat(term(a), term(b)))
        if op in ("<<", ">>"):
            return _shift(op, a, b)
        return _bits_op(op, a, b)

    def enum_width(self, t):
        n = len(self.spec.decls[t.name][1])
        return max(1, (n - 1).bit_length())

    def call(self, e, env):
        if e.name in BUILTINS:
            n = e.name
            if n in ("zext", "sext"):          # the width is the checker's
                return _ext(self.eval(e.pos[0], env), e.width, n == "sext")
            args = [self.eval(a, env) for a in e.pos]
            if n == "asr":
                return _asr(*args)
            if n == "ror":
                return _ror(*args)
            if n == "sdiv":
                return _sdiv(*args)
            if n == "srem":
                return _srem(*args)
            if n == "bit":
                return _bit(args[0])
            return _bool(args[0])
        args = [self.eval(a, env) for a in e.order]
        return self.call_func(e.name, args)

    def call_func(self, name, args):
        g = self.spec.decls[name][1]
        if self.g is False:
            raise _Dead
        env = Env(None)
        for p, a in zip(g.params, args):
            env.define(p.name, a)
        env.frame["$ret"] = None
        g0 = self.g
        self.block(g.body, env)
        self.g = g_and(g0, g_not(self.fault_g)) if self.fault_g is not False else g0
        if self.g is False:
            raise _Dead
        return env.frame["$ret"]


class Env:
    """Local names: a chain of blocks within one function's frame."""

    def __init__(self, parent):
        self.parent = parent
        self.vars = {}
        self.frame = parent.frame if parent is not None else {}

    def child(self):
        return Env(self)

    @property
    def ret(self):
        return self.frame.get("$ret")

    def define(self, name, v):
        self.vars[name] = v

    def get(self, name):
        e = self
        while e is not None:
            if name in e.vars:
                return e.vars[name]
            e = e.parent
        return None

    def set(self, name, v, g):
        e = self
        while e is not None:
            if name in e.vars:
                e.vars[name] = v if g is True else ite(g, v, e.vars[name])
                return
            e = e.parent
        raise SpecError(f"no name {name}")


def load(name):
    """A specification in this folder, by file name."""
    path = name if os.path.isabs(name) else os.path.join(HERE, name)
    with open(path) as f:
        return Spec(f.read(), os.path.basename(path))
