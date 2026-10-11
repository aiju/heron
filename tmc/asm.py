"""ISA-independent assembler core.

The core handles everything that doesn't depend on the instruction set:
lexing, expressions, labels (including local `.labels`), directives,
includes, and multi-pass size relaxation. Instructions are handed to the
ISA module's `assemble(mnemonic, operands, ctx)` hook, which returns a
list of 16-bit words.

Size relaxation: an ISA hook may choose between a short and a long
encoding. In the first pass unknown symbols evaluate to 0 (optimistic,
so short forms get picked); whenever a statement grows it is marked
"sticky long" and never shrinks again, so passes always converge.
"""

import os
import re

# --------------------------------------------------------------------------
# Errors


class AsmError(Exception):
    def __init__(self, msg, where=None):
        super().__init__(msg)
        self.msg = msg
        self.where = where

    def __str__(self):
        if self.where:
            return f"{self.where[0]}:{self.where[1]}: {self.msg}"
        return self.msg


class Unresolved(Exception):
    """Raised during evaluation when a symbol isn't defined (yet)."""


# --------------------------------------------------------------------------
# Lexer

TOKEN_RE = re.compile(r"""
    (?P<ws>\s+)
  | (?P<str>"(?:[^"\\]|\\.)*")
  | (?P<chr>'(?:[^'\\]|\\.)')
  | (?P<num>0[xX][0-9a-fA-F_]+|0[bB][01_]+|[0-9][0-9_]*)
  | (?P<id>[A-Za-z_.][A-Za-z0-9_.]*)
  | (?P<op><<|>>|[-+*/%&|^~!()\[\],#:=$])
""", re.VERBOSE)

ESCAPES = {"n": 10, "r": 13, "t": 9, "0": 0, "\\": 92, "'": 39, '"': 34, "e": 27}


def unescape(body):
    out = []
    i = 0
    while i < len(body):
        ch = body[i]
        if ch == "\\" and i + 1 < len(body):
            nxt = body[i + 1]
            if nxt == "x":
                out.append(int(body[i + 2:i + 4], 16))
                i += 4
                continue
            if nxt not in ESCAPES:
                raise AsmError(f"unknown escape \\{nxt}")
            out.append(ESCAPES[nxt])
            i += 2
        else:
            out.append(ord(ch))
            i += 1
    return out


def tokenize(text):
    """Turn one source line (comment already stripped) into tokens.

    Tokens are (kind, value) tuples: ('num', int), ('id', str),
    ('str', list-of-bytes), ('op', str).
    """
    toks = []
    pos = 0
    while pos < len(text):
        m = TOKEN_RE.match(text, pos)
        if not m:
            raise AsmError(f"unexpected character {text[pos]!r}")
        pos = m.end()
        kind = m.lastgroup
        val = m.group(kind)
        if kind == "ws":
            continue
        if kind == "num":
            v = val.replace("_", "")
            toks.append(("num", int(v, 0) if v[:2].lower() in ("0x", "0b") else int(v, 10)))
        elif kind == "chr":
            toks.append(("num", unescape(val[1:-1])[0]))
        elif kind == "str":
            toks.append(("str", unescape(val[1:-1])))
        else:
            toks.append((kind, val))
    return toks


def strip_comment(line):
    """Remove a ';' comment, respecting string and char literals."""
    quote = None
    i = 0
    while i < len(line):
        ch = line[i]
        if quote:
            if ch == "\\":
                i += 2
                continue
            if ch == quote:
                quote = None
        elif ch in "\"'":
            quote = ch
        elif ch == ";":
            return line[:i]
        i += 1
    return line


def split_operands(toks):
    """Split a token list on top-level commas."""
    out, cur, depth = [], [], 0
    for t in toks:
        if t == ("op", "(") or t == ("op", "["):
            depth += 1
        elif t == ("op", ")") or t == ("op", "]"):
            depth -= 1
        if t == ("op", ",") and depth == 0:
            out.append(cur)
            cur = []
        else:
            cur.append(t)
    if cur or out:
        out.append(cur)
    return out


# --------------------------------------------------------------------------
# Expressions
#
# Parsed into small tuple trees: ('num', v), ('sym', name), ('pc',),
# ('un', op, x), ('bin', op, a, b), ('call', fname, x).

BINARY_PREC = [
    ["|"], ["^"], ["&"], ["<<", ">>"], ["+", "-"], ["*", "/", "%"],
]

FUNCS = {
    "lo": lambda x: x & 0xFF,              # low byte
    "hi": lambda x: (x >> 8) & 0xFF,       # high byte
    "lo16": lambda x: x & 0xFFFF,          # low word of a 32-bit constant
    "hi16": lambda x: (x >> 16) & 0xFFFF,  # high word of a 32-bit constant
}


class ExprParser:
    def __init__(self, toks, scope):
        self.toks = toks
        self.i = 0
        self.scope = scope  # current global label, for local-label mangling

    def peek(self):
        return self.toks[self.i] if self.i < len(self.toks) else (None, None)

    def take(self):
        t = self.peek()
        self.i += 1
        return t

    def parse(self):
        e = self.binary(0)
        if self.i != len(self.toks):
            raise AsmError(f"junk after expression: {self.toks[self.i][1]!r}")
        return e

    def binary(self, level):
        if level == len(BINARY_PREC):
            return self.unary()
        left = self.binary(level + 1)
        while self.peek()[0] == "op" and self.peek()[1] in BINARY_PREC[level]:
            op = self.take()[1]
            right = self.binary(level + 1)
            left = ("bin", op, left, right)
        return left

    def unary(self):
        k, v = self.peek()
        if k == "op" and v in ("-", "~", "+", "!"):
            self.take()
            return ("un", v, self.unary())
        return self.atom()

    def atom(self):
        k, v = self.take()
        if k == "num":
            return ("num", v)
        if k == "op" and v == "$":
            return ("pc",)
        if k == "op" and v == "(":
            e = self.binary(0)
            if self.take() != ("op", ")"):
                raise AsmError("missing ')'")
            return e
        if k == "id":
            if v.lower() in FUNCS and self.peek() == ("op", "("):
                self.take()
                e = self.binary(0)
                if self.take() != ("op", ")"):
                    raise AsmError("missing ')'")
                return ("call", v.lower(), e)
            return ("sym", mangle(v, self.scope))
        if k is None:
            raise AsmError("expression expected")
        raise AsmError(f"unexpected {v!r} in expression")


def mangle(name, scope):
    if name.startswith(".") and len(name) > 1:
        return (scope or "") + name
    return name


def parse_expr(toks, scope):
    return ExprParser(toks, scope).parse()


def eval_expr(e, symbols, pc):
    kind = e[0]
    if kind == "num":
        return e[1]
    if kind == "pc":
        return pc
    if kind == "sym":
        if e[1] not in symbols:
            raise Unresolved(e[1])
        return symbols[e[1]]
    if kind == "un":
        x = eval_expr(e[2], symbols, pc)
        return {"-": -x, "~": ~x, "+": x, "!": int(not x)}[e[1]]
    if kind == "call":
        return FUNCS[e[1]](eval_expr(e[2], symbols, pc))
    a = eval_expr(e[2], symbols, pc)
    b = eval_expr(e[3], symbols, pc)
    op = e[1]
    if op == "+": return a + b
    if op == "-": return a - b
    if op == "*": return a * b
    if op == "/":
        if b == 0:
            raise AsmError("division by zero")
        return int(a / b)
    if op == "%":
        if b == 0:
            raise AsmError("division by zero")
        return a % b
    if op == "<<": return a << b
    if op == ">>": return a >> b
    if op == "&": return a & b
    if op == "|": return a | b
    if op == "^": return a ^ b
    raise AsmError(f"bad operator {op}")


# --------------------------------------------------------------------------
# Operands handed to the ISA hook


class Reg:
    __slots__ = ("n", "name")

    def __init__(self, n, name):
        self.n, self.name = n, name

    def __repr__(self):
        return f"Reg({self.name})"


class Imm:
    """'#expr' immediate operand."""
    __slots__ = ("expr",)

    def __init__(self, expr):
        self.expr = expr


class Mem:
    """'[base + disp]' memory operand; base is a Reg or None, disp an expr or None."""
    __slots__ = ("base", "disp")

    def __init__(self, base, disp):
        self.base, self.disp = base, disp


class Expr:
    """Bare expression operand (branch target, address)."""
    __slots__ = ("expr",)

    def __init__(self, expr):
        self.expr = expr


class Str:
    __slots__ = ("data",)

    def __init__(self, data):
        self.data = data


# --------------------------------------------------------------------------
# Assembly context passed to the ISA hook


class Ctx:
    def __init__(self, asm, stmt):
        self.asm = asm
        self.stmt = stmt
        self.pc = stmt.addr

    @property
    def final(self):
        return self.asm.final_pass

    @property
    def long(self):
        """True once this statement has been forced to its long form."""
        return self.stmt.sticky_long

    def value(self, expr):
        """Evaluate an expression. Returns (value, known)."""
        try:
            return eval_expr(expr, self.asm.symbols, self.pc), True
        except Unresolved as u:
            if self.asm.final_pass:
                raise AsmError(f"undefined symbol {u.args[0]}")
            return 0, False

    def error(self, msg):
        raise AsmError(msg)

    def warn(self, msg):
        if self.asm.final_pass:
            self.asm.warnings.append(f"{self.stmt.where[0]}:{self.stmt.where[1]}: {msg}")


# --------------------------------------------------------------------------
# Statements


class Stmt:
    __slots__ = ("where", "text", "kind", "name", "operands", "addr", "size",
                 "words", "data", "sticky_long", "scope", "label")

    def __init__(self, where, text):
        self.where = where
        self.text = text
        self.kind = None      # 'insn', 'dir', 'label-only'
        self.name = None
        self.operands = []
        self.addr = 0
        self.size = 0
        self.words = []
        self.data = b""
        self.sticky_long = False
        self.scope = None
        self.label = None


class Assembler:
    def __init__(self, isa):
        self.isa = isa
        self.symbols = {}
        self.final_pass = False
        self.warnings = []
        self.stmts = []
        self.reg_names = {k.lower(): v for k, v in isa.REGISTERS.items()}
        self.owner = {}       # symbol -> statement that defines it

    # ---- parsing ---------------------------------------------------------

    def load(self, path, text=None, seen=None):
        seen = seen if seen is not None else set()
        path = os.path.abspath(path)
        if path in seen:
            raise AsmError(f"recursive include of {path}")
        seen = seen | {path}
        if text is None:
            with open(path) as f:
                text = f.read()
        scope = self.stmts[-1].scope if self.stmts else None
        for lineno, raw in enumerate(text.splitlines(), 1):
            rel = os.path.relpath(path)
            where = (path if rel.startswith("..") else rel, lineno)
            try:
                scope = self.parse_line(raw, where, scope, path, seen)
            except AsmError as e:
                e.where = e.where or where
                raise

    def parse_line(self, raw, where, scope, path, seen):
        line = strip_comment(raw)
        toks = tokenize(line)
        if not toks:
            return scope
        # labels: "name:" possibly several on one line
        while len(toks) >= 2 and toks[0][0] == "id" and toks[1] == ("op", ":"):
            name = toks[0][1]
            if not name.startswith("."):
                scope = name
            st = Stmt(where, raw)
            st.kind = "label"
            st.label = mangle(name, scope)
            st.scope = scope
            self.stmts.append(st)
            toks = toks[2:]
        if not toks:
            return scope
        # "name = expr" / "name .equ expr"
        if len(toks) >= 2 and toks[0][0] == "id" and toks[1] == ("op", "="):
            st = Stmt(where, raw)
            st.kind = "dir"
            st.name = ".equ"
            st.scope = scope
            st.operands = [[toks[0]], toks[2:]]
            self.stmts.append(st)
            return scope
        if toks[0][0] != "id":
            raise AsmError(f"expected mnemonic or directive, got {toks[0][1]!r}")
        name = toks[0][1].lower()
        st = Stmt(where, raw)
        st.scope = scope
        st.name = name
        ops = split_operands(toks[1:])
        if name == ".include":
            if len(ops) != 1 or ops[0][0][0] != "str":
                raise AsmError(".include needs a quoted file name")
            inc = bytes(ops[0][0][1]).decode()
            inc_path = os.path.join(os.path.dirname(path), inc)
            self.load(inc_path, seen=seen)
            return self.stmts[-1].scope if self.stmts else scope
        if name.startswith("."):
            st.kind = "dir"
            st.operands = ops
        else:
            st.kind = "insn"
            st.operands = [self.parse_operand(o, scope) for o in ops]
        self.stmts.append(st)
        return scope

    def reg(self, tok):
        if tok[0] == "id" and tok[1].lower() in self.reg_names:
            return Reg(self.reg_names[tok[1].lower()], tok[1].lower())
        return None

    def parse_operand(self, toks, scope):
        if not toks:
            raise AsmError("empty operand")
        if len(toks) == 1 and self.reg(toks[0]):
            return self.reg(toks[0])
        if toks[0] == ("op", "#"):
            return Imm(parse_expr(toks[1:], scope))
        if toks[0] == ("op", "["):
            if toks[-1] != ("op", "]"):
                raise AsmError("missing ']'")
            inner = toks[1:-1]
            regs = [i for i, t in enumerate(inner) if self.reg(t)]
            base, disp = None, None
            if len(regs) > 1:
                raise AsmError("register + register addressing doesn't exist: add the registers "
                               "first, or use [label + reg] for a static array")
            if regs and regs[0] == 0:
                base = self.reg(inner[0])
                rest = inner[1:]
                if rest:
                    if rest[0] not in (("op", "+"), ("op", "-")):
                        raise AsmError("expected + or - after base register")
                    disp = parse_expr(rest if rest[0] == ("op", "-") else rest[1:], scope)
            elif regs and regs[0] == len(inner) - 1 and len(inner) >= 3 and inner[-2] == ("op", "+"):
                base = self.reg(inner[-1])
                disp = parse_expr(inner[:-2], scope)
            elif regs:
                raise AsmError("register must come first, or last after '+', inside [...]")
            else:
                disp = parse_expr(inner, scope) if inner else None
            return Mem(base, disp)
        if len(toks) == 1 and toks[0][0] == "str":
            return Str(toks[0][1])
        for t in toks:
            if self.reg(t):
                raise AsmError(f"unexpected register in expression: {t[1]}")
        return Expr(parse_expr(toks, scope))

    # ---- passes ----------------------------------------------------------

    def dir_values(self, st, ops, pc):
        """Evaluate each operand of a data directive as an expression or string."""
        out = []
        for o in ops:
            if len(o) == 1 and o[0][0] == "str":
                out.append(bytes(o[0][1]))
            else:
                e = parse_expr(o, st.scope)
                try:
                    out.append(eval_expr(e, self.symbols, pc))
                except Unresolved as u:
                    if self.final_pass:
                        raise AsmError(f"undefined symbol {u.args[0]}")
                    out.append(0)
        return out

    def run_directive(self, st, pc):
        n = st.name
        ops = st.operands
        st.data = b""
        if n == ".equ":
            name = ops[0][0][1]
            self.define(mangle(name, st.scope), st)
            e = parse_expr(ops[1], st.scope)
            try:
                self.symbols[mangle(name, st.scope)] = eval_expr(e, self.symbols, pc)
            except Unresolved as u:
                if self.final_pass:
                    raise AsmError(f"undefined symbol {u.args[0]}")
            return pc
        if n == ".org":
            (v,) = self.dir_values(st, ops, pc)
            if v < pc and self.final_pass:
                self.warnings.append(f"{st.where[0]}:{st.where[1]}: .org moves backwards")
            return v
        if n == ".align":
            (v,) = self.dir_values(st, ops, pc)
            pad = (-pc) % v
            st.data = bytes(pad)
            return pc + pad
        if n in (".space", ".fill"):
            vals = self.dir_values(st, ops, pc)
            count = vals[0]
            fill = vals[1] if len(vals) > 1 else 0
            st.data = bytes([fill & 0xFF]) * count
            return pc + count
        if n == ".byte":
            buf = bytearray()
            for v in self.dir_values(st, ops, pc):
                if isinstance(v, bytes):
                    buf += v
                else:
                    if self.final_pass and not -128 <= v <= 255:
                        raise AsmError(f".byte value {v} out of range")
                    buf.append(v & 0xFF)
            st.data = bytes(buf)
            return pc + len(buf)
        if n in (".ascii", ".asciz"):
            buf = bytearray()
            for v in self.dir_values(st, ops, pc):
                if not isinstance(v, bytes):
                    raise AsmError(f"{n} needs strings")
                buf += v
            if n == ".asciz":
                buf.append(0)
            st.data = bytes(buf)
            return pc + len(buf)
        if n == ".word":
            if pc & 1:
                raise AsmError(".word at odd address")
            buf = bytearray()
            for v in self.dir_values(st, ops, pc):
                if isinstance(v, bytes):
                    raise AsmError(".word doesn't take strings")
                if self.final_pass and not -32768 <= v <= 65535:
                    raise AsmError(f".word value {v} out of range")
                buf += (v & 0xFFFF).to_bytes(2, "little")
            st.data = bytes(buf)
            return pc + len(buf)
        if n in (".global", ".globl", ".title"):
            return pc
        raise AsmError(f"unknown directive {n}")

    def define(self, sym, st):
        prev = self.owner.setdefault(sym, st)
        if prev is not st:
            raise AsmError(f"{sym} is already defined at {prev.where[0]}:{prev.where[1]}")

    def one_pass(self):
        pc = 0
        changed = False
        for st in self.stmts:
            try:
                st.addr = pc
                if st.kind == "label":
                    self.define(st.label, st)
                    if self.symbols.get(st.label) != pc:
                        changed = True
                    self.symbols[st.label] = pc
                elif st.kind == "dir":
                    if st.name == ".org":
                        st.addr = pc
                    pc = self.run_directive(st, pc)
                    if st.name == ".org":
                        st.addr = pc
                else:
                    if pc & 1:
                        raise AsmError("instruction at odd address (missing .align 2?)")
                    words = self.isa.assemble(st.name, st.operands, Ctx(self, st))
                    if len(words) * 2 < st.size and not self.final_pass:
                        # never shrink: keep the previous long form
                        st.sticky_long = True
                        words = self.isa.assemble(st.name, st.operands, Ctx(self, st))
                    if len(words) * 2 != st.size:
                        if st.size:
                            st.sticky_long = True
                        changed = True
                    st.size = len(words) * 2
                    st.words = words
                    pc += st.size
                if pc > 0x10000:
                    raise AsmError("program runs past the end of memory")
            except AsmError as e:
                e.where = e.where or st.where
                raise
        return changed

    def assemble(self):
        for _ in range(20):
            if not self.one_pass():
                break
        else:
            raise AsmError("assembly did not converge")
        self.final_pass = True
        self.one_pass()
        return self.image()

    def image(self):
        mem = {}
        for st in self.stmts:
            if st.kind == "insn":
                for i, w in enumerate(st.words):
                    mem[st.addr + 2 * i] = w & 0xFF
                    mem[st.addr + 2 * i + 1] = (w >> 8) & 0xFF
            elif st.kind == "dir" and st.data:
                for i, b in enumerate(st.data):
                    mem[st.addr + i] = b
        return Image(mem, self.symbols, self.stmts)


class Image:
    """Result of assembly: sparse byte map plus symbols and a listing."""

    def __init__(self, mem, symbols, stmts):
        self.mem = mem
        self.symbols = symbols
        self.stmts = stmts

    def to_bytes(self, size=0x10000):
        buf = bytearray(size)
        for a, b in self.mem.items():
            buf[a] = b
        return bytes(buf)

    def extent(self):
        if not self.mem:
            return 0, 0
        return min(self.mem), max(self.mem) + 1

    def code_bytes(self):
        return sum(st.size for st in self.stmts if st.kind == "insn")

    def listing(self):
        lines = []
        groups = []
        for st in self.stmts:
            if groups and groups[-1][0] == st.where:
                groups[-1][1].append(st)
            else:
                groups.append((st.where, [st]))
        for where, sts in groups:
            text = sts[-1].text.rstrip()
            body = [st for st in sts if st.kind == "insn" or (st.kind == "dir" and st.data)]
            if not body:
                lines.append(f"{'':16} {text}")
                continue
            st = body[0]
            if st.kind == "insn":
                hexw = " ".join(f"{w:04X}" for w in st.words)
                lines.append(f"{st.addr:04X}  {hexw:<10} {text}")
            else:
                d = st.data[:4]
                hexb = " ".join(f"{b:02X}" for b in d) + (" …" if len(st.data) > 4 else "")
                lines.append(f"{st.addr:04X}  {hexb:<10} {text}")
        return "\n".join(lines) + "\n"


def assemble_file(isa, path):
    a = Assembler(isa)
    a.load(path)
    img = a.assemble()
    img.warnings = a.warnings
    return img


def assemble_text(isa, text, name="<string>"):
    a = Assembler(isa)
    a.load(name, text=text)
    img = a.assemble()
    img.warnings = a.warnings
    return img
