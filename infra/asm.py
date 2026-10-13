"""ISA-independent assembler core.

The core handles everything that doesn't depend on the instruction set:
lexing, expressions, labels (including local `.labels`), directives,
includes, and multi-pass size relaxation. Instructions are handed to the
ISA module's `assemble(mnemonic, operands, ctx)` hook, which returns a
list of 16-bit words (parcels).

Size relaxation: an ISA hook may choose between a short and a long
encoding. In the first pass unknown symbols evaluate to 0 (optimistic,
so short forms get picked); whenever a statement grows it is marked
"sticky long" and never shrinks again, so passes always converge.

Object files (`relocatable=True`, `asm -c`): each section (`.text`,
`.data`, `.bss`, `.section NAME`) has its own location counter starting at
0, and the linker places it. A section that uses `.org` is absolute
instead. Addresses the linker fills in are relocations: when an ISA hook
evaluates such an operand, `ctx.value` (an address used as a number) and
`ctx.target` (a PC-relative target) return a stand-in value that makes the
hook pick a form with a 16-bit field (a 32-bit one for symbols declared
`.far`), and the hook names the field with `ctx.fix`. An operand the hook
doesn't fix is an error, so ISAs without relocation support (draft 0)
still assemble absolute code. Labels outside `.org` sections are exported
unless the file lists its exports with `.global` (or hides a label with
`.local`).
"""

import os
import re

from . import obj as O

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


class RelValue:
    """A data directive's value that the linker fills in: base + value."""
    __slots__ = ("value", "base")

    def __init__(self, value, base):
        self.value, self.base = value, base


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


class RegRange:
    """'r8-r11' register range operand (SAVE/RESTORE)."""
    __slots__ = ("a", "b")

    def __init__(self, a, b):
        self.a, self.b = a, b


class Imm:
    """'#expr' immediate operand."""
    __slots__ = ("expr",)

    def __init__(self, expr):
        self.expr = expr


class Mem:
    """'[base + disp]' memory operand.

    base and index are Regs or None, disp an expr or None. The rest is only
    used by ISAs with richer addressing (draft 1b): an optional size keyword
    ('byte', 'half' or 'word' before the bracket), the scale of the index
    register ('[r1 + r2*4]'), and auto-increment ('[r1]+') or auto-decrement
    ('-[r1]').
    """
    __slots__ = ("base", "disp", "index", "scale", "size", "postinc", "predec")

    def __init__(self, base, disp, index=None, scale=1, size=None, postinc=False, predec=False):
        self.base, self.disp = base, disp
        self.index, self.scale = index, scale
        self.size, self.postinc, self.predec = size, postinc, predec

    def plain(self):
        """True for the draft 0 forms: [base + disp] without the extras."""
        return self.index is None and self.size is None and not self.postinc and not self.predec


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


REP_NEAR = 0x4000      # stand-in for an address the linker fills in: fits 16 bits
REP_FAR = 0x45678      # ... for a .far symbol: needs 32 bits
REP_PC = 0x1000        # stand-in distance to a branch target in another section


class Ctx:
    def __init__(self, asm, stmt):
        self.asm = asm
        self.stmt = stmt
        self.pc = stmt.addr
        self.pending = []       # operands that need a relocation (object files)
        self.fixed = set()
        self.relocs = []        # (offset, kind, base, addend)

    @property
    def abs_pc(self):
        """True if ctx.pc is the final address (not an offset in a section
        the linker will place)."""
        return self.stmt.section is None

    @property
    def final(self):
        return self.asm.final_pass

    @property
    def long(self):
        """True once this statement has been forced to its long form."""
        return self.stmt.sticky_long

    @property
    def min_words(self):
        """Once a statement has grown, its encoding may never get shorter
        again (so the passes converge): ISAs with several sizes pick a form
        of at least this many words."""
        return self.stmt.size // 2 if self.stmt.sticky_long else 0

    def value(self, expr):
        """Evaluate an expression used as a number (an immediate, an
        absolute address, a displacement). Returns (value, known)."""
        if not self.asm.relocatable:
            try:
                return eval_expr(expr, self.asm.symbols, self.pc), True
            except Unresolved as u:
                if self.asm.final_pass:
                    raise AsmError(f"undefined symbol {u.args[0]}")
                return 0, False
        r = self._rel(expr)
        if r is None:
            return 0, False
        v, base = r
        if base is None:
            return v, True
        self.pending.append(expr)
        return (REP_FAR if self.asm.is_far(base) else REP_NEAR) + v, True

    def target(self, expr):
        """Evaluate a branch target or other PC-relative operand: the
        address, comparable with ctx.pc. Returns (value, known)."""
        if not self.asm.relocatable:
            return self.value(expr)
        r = self._rel(expr)
        if r is None:
            return 0, False
        v, base = r
        direct = self.asm.direct(base, self.stmt.section)
        if direct is not None:
            return v + direct, True
        self.pending.append(expr)
        return self.pc + REP_PC, True

    def fix(self, index, kind, expr, base=None):
        """Parcel `index` of the encoding holds expr (kind: a relocation kind
        from heron.infra.obj; for the PC-relative kinds, `base` is the address the
        CPU adds the field to). Records a relocation when the linker has to
        fill the field in; does nothing for assembly-time constants."""
        if not self.asm.relocatable or not self.asm.final_pass:
            self.fixed.add(id(expr))
            return
        v, b = self._rel(expr)
        field = self.pc + 2 * index
        if kind in (O.PC16, O.PC16H):
            if self.asm.direct(b, self.stmt.section) is not None:
                self.fixed.add(id(expr))
                return
            v -= base - field
        elif b is None:
            self.fixed.add(id(expr))
            return
        self.relocs.append((field, kind, b, v))
        self.fixed.add(id(expr))

    def _rel(self, expr):
        try:
            return self.asm.eval_rel(expr, self.pc, self.stmt.section)
        except Unresolved as u:
            if self.asm.final_pass:
                raise AsmError(f"undefined symbol {u.args[0]}")
            return None

    def check_fixed(self):
        for e in self.pending:
            if id(e) not in self.fixed:
                names = sorted(symbols_in(e))
                raise AsmError(f"the linker fills in the address of {', '.join(names) or 'this'}, "
                               "but this operand can't hold it")

    def error(self, msg):
        raise AsmError(msg)

    def warn(self, msg):
        if self.asm.final_pass:
            self.asm.warnings.append(f"{self.stmt.where[0]}:{self.stmt.where[1]}: {msg}")


# --------------------------------------------------------------------------
# Statements


class Stmt:
    __slots__ = ("where", "text", "kind", "name", "operands", "addr", "size",
                 "words", "data", "sticky_long", "scope", "label", "seckey", "section",
                 "relocs", "toplevel")

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
        self.seckey = None    # the section (object files)
        self.section = None   # ... if the linker places it, else None (addr is final)
        self.relocs = []
        self.toplevel = False


def symbols_in(e):
    if e[0] == "sym":
        return {e[1]}
    out = set()
    for x in e[1:]:
        if isinstance(x, tuple):
            out |= symbols_in(x)
    return out


SECTION_DIRS = {".text": ".text", ".data": ".data", ".bss": ".bss"}
NOBITS_PREFIXES = (".bss", ".farbss")


def is_nobits(section):
    return any(section == p or section.startswith(p + ".") for p in NOBITS_PREFIXES)


class Assembler:
    def __init__(self, isa, relocatable=False):
        self.isa = isa
        self.relocatable = relocatable
        self.symbols = {}
        self.final_pass = False
        self.warnings = []
        self.stmts = []
        self.reg_names = {k.lower(): v for k, v in isa.REGISTERS.items()}
        self.owner = {}       # symbol -> statement that defines it
        self.mem_top = getattr(isa, "MEM_TOP", 0x10000)
        # object files
        self.cur_section = ".text"      # while parsing
        self.abs_sections = set()       # sections that use .org
        self.sections = []              # in order of appearance
        self.sym_section = {}           # label -> section, if the linker places it
        self.equ_rel = {}               # name = relocatable expression: (value, base)
        self.defined = set()            # every name the file defines
        self.globals = set()
        self.locals = set()
        self.far = set()
        self.sec_align = {}

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
            st.toplevel = not name.startswith(".")
            st.seckey = self.cur_section
            self.defined.add(st.label)
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
            st.seckey = self.cur_section
            self.defined.add(mangle(toks[0][1], scope))
            self.stmts.append(st)
            return scope
        if toks[0][0] != "id":
            raise AsmError(f"expected mnemonic or directive, got {toks[0][1]!r}")
        name = toks[0][1].lower()
        st = Stmt(where, raw)
        st.scope = scope
        st.name = name
        ops = split_operands(toks[1:])
        if name in SECTION_DIRS or name == ".section":
            if name == ".section":
                if len(ops) != 1 or len(ops[0]) != 1 or ops[0][0][0] != "id":
                    raise AsmError(".section needs a name, like .section .text.main")
                name = ops[0][0][1]
            self.cur_section = SECTION_DIRS.get(name, name)
            if self.cur_section not in self.sections:
                self.sections.append(self.cur_section)
            return scope
        st.seckey = self.cur_section
        if name == ".org":
            self.abs_sections.add(self.cur_section)
        if name in (".global", ".globl", ".extern", ".far", ".local"):
            names = []
            for o in ops:
                if len(o) != 1 or o[0][0] != "id" or o[0][1].startswith("."):
                    raise AsmError(f"{name} takes a list of symbol names")
                names.append(o[0][1])
            {".global": self.globals, ".globl": self.globals, ".extern": set(),
             ".far": self.far, ".local": self.locals}[name].update(names)
            return scope
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
        if len(toks) == 3 and self.reg(toks[0]) and toks[1] == ("op", "-") and self.reg(toks[2]):
            return RegRange(self.reg(toks[0]), self.reg(toks[2]))
        if toks[0] == ("op", "#"):
            return Imm(parse_expr(toks[1:], scope))
        size = None
        if (len(toks) > 1 and toks[0][0] == "id" and toks[0][1].lower() in ("byte", "half", "word")
                and toks[1] in (("op", "["), ("op", "-"))):
            size = toks[0][1].lower()
            toks = toks[1:]
        predec = postinc = False
        if len(toks) > 1 and toks[0] == ("op", "-") and toks[1] == ("op", "["):
            predec = True
            toks = toks[1:]
        if len(toks) > 1 and toks[-1] == ("op", "+") and toks[-2] == ("op", "]") and toks[0] == ("op", "["):
            postinc = True
            toks = toks[:-1]
        if toks[0] == ("op", "["):
            if toks[-1] != ("op", "]"):
                raise AsmError("missing ']'")
            m = self.parse_mem(toks[1:-1], scope)
            m.size, m.predec, m.postinc = size, predec, postinc
            if (predec or postinc) and (m.base is None or m.index is not None or m.disp is not None):
                raise AsmError("auto-increment and auto-decrement need a plain [register]")
            return m
        if size or predec:
            raise AsmError("expected [...] after the size or '-'")
        if len(toks) == 1 and toks[0][0] == "str":
            return Str(toks[0][1])
        for t in toks:
            if self.reg(t):
                raise AsmError(f"unexpected register in expression: {t[1]}")
        return Expr(parse_expr(toks, scope))

    def parse_mem(self, inner, scope):
        """Parse the inside of [...]: terms joined by + and -, each a register,
        'reg*scale' (an index), or part of the displacement expression."""
        terms, cur, depth = [], [], 0
        sign = "+"
        for t in inner:
            if t in (("op", "("),):
                depth += 1
            elif t == ("op", ")"):
                depth -= 1
            if depth == 0 and t in (("op", "+"), ("op", "-")) and cur:
                terms.append((sign, cur))
                sign, cur = t[1], []
            else:
                cur.append(t)
        if cur:
            terms.append((sign, cur))
        regs, disp = [], []
        for sign, tt in terms:
            r = self.reg(tt[0])
            if len(tt) == 1 and r:
                if sign != "+":
                    raise AsmError("a register can't be subtracted")
                regs.append((r, 1, False))
                continue
            scaled = None
            if len(tt) >= 3 and r and tt[1] == ("op", "*"):
                scaled = (r, tt[2:])
            elif len(tt) >= 3 and self.reg(tt[-1]) and tt[-2] == ("op", "*"):
                scaled = (self.reg(tt[-1]), tt[:-2])
            if scaled:
                if sign != "+":
                    raise AsmError("a register can't be subtracted")
                k = eval_expr(parse_expr(scaled[1], scope), {}, 0)
                regs.append((scaled[0], k, True))
                continue
            for t in tt:
                if self.reg(t):
                    raise AsmError(f"unexpected register in address expression: {t[1]}")
            if disp or sign == "-":
                disp.append(("op", sign))
            disp.extend(tt)
        base = index = None
        scale = 1
        if len(regs) > 2:
            raise AsmError("at most two registers in an address")
        plain = [r for r in regs if not r[2]]
        scaled = [r for r in regs if r[2]]
        if len(scaled) > 1:
            raise AsmError("only one register can be scaled")
        if scaled:
            index, scale = scaled[0][0], scaled[0][1]
            base = plain[0][0] if plain else None
        elif len(plain) == 2:
            base, index = plain[0][0], plain[1][0]
        elif plain:
            base = plain[0][0]
        return Mem(base, parse_expr(disp, scope) if disp else None, index, scale)

    # ---- passes ----------------------------------------------------------

    def dir_values(self, st, ops, pc, relocs=None):
        """Evaluate each operand of a data directive as an expression or
        string. With `relocs` (a list), an address the linker fills in comes
        back as RelValue(value, base), and is otherwise an error."""
        out = []
        for o in ops:
            if len(o) == 1 and o[0][0] == "str":
                out.append(bytes(o[0][1]))
                continue
            e = parse_expr(o, st.scope)
            try:
                if not self.relocatable:
                    out.append(eval_expr(e, self.symbols, pc))
                    continue
                v, base = self.eval_rel(e, pc, st.section)
            except Unresolved as u:
                if self.final_pass:
                    raise AsmError(f"undefined symbol {u.args[0]}")
                out.append(0)
                continue
            if base is None:
                out.append(v)
            elif relocs is None:
                raise AsmError(f"{st.name} needs a constant, not an address the linker fills in")
            else:
                out.append(RelValue(v, base))
        return out

    # ---- relocatable values (object files) --------------------------------

    def eval_rel(self, e, pc, section):
        """Evaluate an expression in an object file: returns (value, base),
        where base is None for a constant, or what the linker adds the value
        to: ('label', name), ('ext', name) or ('sec', section)."""
        kind = e[0]
        if kind == "num":
            return e[1], None
        if kind == "pc":
            return (pc, None) if section is None else (pc, ("sec", section))
        if kind == "sym":
            name = e[1]
            if name in self.equ_rel:
                return self.equ_rel[name]
            if name in self.symbols:
                if self.sym_section.get(name) is None:
                    return self.symbols[name], None
                return 0, ("label", name)
            if name in self.defined:
                raise Unresolved(name)
            return 0, ("ext", name)
        if kind in ("un", "call"):
            v, b = self.eval_rel(e[2], pc, section)
            if b is not None and not (kind == "un" and e[1] == "+"):
                raise AsmError(f"can't apply {e[1]} to an address the linker fills in")
            if kind == "call":
                return FUNCS[e[1]](v), None
            return {"-": -v, "~": ~v, "+": v, "!": int(not v)}[e[1]], b
        op = e[1]
        a, ba = self.eval_rel(e[2], pc, section)
        c, bc = self.eval_rel(e[3], pc, section)
        if ba is None and bc is None:
            return eval_expr(("bin", op, ("num", a), ("num", c)), {}, pc), None
        if op == "+" and (ba is None or bc is None):
            return a + c, ba or bc
        if op == "-" and bc is None:
            return a - c, ba
        if op == "-" and ba is not None:
            sa, sc = self.base_section(ba), self.base_section(bc)
            if sa is not None and sa == sc:
                return a + self.base_offset(ba) - c - self.base_offset(bc), None
            if ba == bc:
                return a - c, None
            raise AsmError("can't subtract addresses in different sections")
        raise AsmError(f"can't use {op} on an address the linker fills in")

    def base_section(self, base):
        if base[0] == "label":
            return self.sym_section.get(base[1])
        if base[0] == "sec":
            return base[1]
        return None

    def base_offset(self, base):
        return self.symbols[base[1]] if base[0] == "label" else 0

    def direct(self, base, section):
        """If an operand with this base can be encoded relative to the
        current statement without the linker (same section, or both
        absolute), the offset to add to its value; else None."""
        if base is None:
            return 0 if section is None else None
        if section is not None and self.base_section(base) == section:
            return self.base_offset(base)
        return None

    def is_far(self, base):
        return base[0] in ("label", "ext") and base[1] in self.far

    def run_directive(self, st, pc):
        n = st.name
        ops = st.operands
        st.data = b""
        if n == ".equ":
            name = mangle(ops[0][0][1], st.scope)
            self.define(name, st)
            e = parse_expr(ops[1], st.scope)
            try:
                if self.relocatable:
                    v, base = self.eval_rel(e, pc, st.section)
                    if base is None:
                        self.symbols[name] = v
                    else:
                        self.equ_rel[name] = (v, base)
                else:
                    self.symbols[name] = eval_expr(e, self.symbols, pc)
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
            if v <= 0:
                raise AsmError(".align needs a positive number")
            self.note_align(st, v)
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
        if n in (".word", ".half", ".long"):
            size = {".half": 2, ".long": 4}.get(n, getattr(self.isa, "WORD_BYTES", 2))
            if pc % size:
                raise AsmError(f"{n} at an address that isn't a multiple of {size} (missing .align?)")
            buf = bytearray()
            bits = 8 * size
            self.note_align(st, size)
            st.relocs = []
            for v in self.dir_values(st, ops, pc, relocs=st.relocs):
                if isinstance(v, bytes):
                    raise AsmError(f"{n} doesn't take strings")
                if isinstance(v, RelValue):
                    kind = {4: O.ABS32, 2: O.ABS16}.get(size)
                    if kind is None:
                        raise AsmError(f"{n} is too small for an address the linker fills in")
                    if self.direct(v.base, None) is None:
                        st.relocs.append((pc + len(buf), kind, v.base, v.value))
                    v = 0
                if self.final_pass and not -(1 << (bits - 1)) <= v < (1 << bits):
                    raise AsmError(f"{n} value {v} out of range")
                buf += (v & ((1 << bits) - 1)).to_bytes(size, "little")
            st.data = bytes(buf)
            return pc + len(buf)
        if n == ".title":
            return pc
        raise AsmError(f"unknown directive {n}")

    def define(self, sym, st):
        prev = self.owner.setdefault(sym, st)
        if prev is not st:
            raise AsmError(f"{sym} is already defined at {prev.where[0]}:{prev.where[1]}")

    def one_pass(self):
        pcs = {}                # location counter per section (one in an image)
        changed = False
        for st in self.stmts:
            key = st.seckey if self.relocatable else None
            if self.relocatable:
                st.section = None if key in self.abs_sections else key
            pc = pcs.get(key, 0)
            try:
                st.addr = pc
                if st.kind == "label":
                    self.define(st.label, st)
                    if self.symbols.get(st.label) != pc:
                        changed = True
                    self.symbols[st.label] = pc
                    if self.relocatable:
                        self.sym_section[st.label] = st.section
                elif st.kind == "dir":
                    if st.name == ".org":
                        st.addr = pc
                    pc = self.run_directive(st, pc)
                    if st.name == ".org":
                        st.addr = pc
                else:
                    if pc & 1:
                        raise AsmError("instruction at odd address (missing .align 2?)")
                    self.note_align(st, 2)
                    words, ctx = self.encode(st)
                    if len(words) * 2 < st.size and not self.final_pass:
                        # never shrink: keep the previous long form
                        st.sticky_long = True
                        words, ctx = self.encode(st)
                    if self.final_pass:
                        ctx.check_fixed()
                        st.relocs = ctx.relocs
                    if len(words) * 2 != st.size:
                        if st.size:
                            st.sticky_long = True
                        changed = True
                    st.size = len(words) * 2
                    st.words = words
                    pc += st.size
                if pc > self.mem_top and st.section is None:
                    raise AsmError("program runs past the end of memory")
            except AsmError as e:
                e.where = e.where or st.where
                raise
            pcs[key] = pc
        return changed

    def encode(self, st):
        ctx = Ctx(self, st)
        try:
            return self.isa.assemble(st.name, st.operands, ctx), ctx
        except AsmError:
            if ctx.pending:
                # the stand-in value for a linker-filled operand didn't fit
                ctx.check_fixed()
            raise

    def note_align(self, st, n):
        if self.relocatable and st.section is not None:
            self.sec_align[st.section] = max(self.sec_align.get(st.section, 1), n)

    def passes(self):
        for _ in range(20):
            if not self.one_pass():
                break
        else:
            raise AsmError("assembly did not converge")
        self.final_pass = True
        self.one_pass()

    def assemble(self):
        if self.relocatable:
            raise AsmError("use assemble_object() for an object file")
        self.passes()
        return self.image()

    def assemble_object(self, name="?"):
        """Assemble into an object file (heron.infra.obj.ObjectFile)."""
        if not self.relocatable:
            raise AsmError("this assembler makes images: create it with relocatable=True")
        self.passes()
        o = O.ObjectFile(self.isa.NAME, name=name)
        secs = {}               # relocatable section -> index (1-based)
        content = {}
        code = {}
        abs_mem = {}            # absolute sections: address -> (byte, section, is code)
        for st in self.stmts:
            key = st.seckey
            if st.kind == "insn":
                data = b"".join(((w & 0xFFFF).to_bytes(2, "little") for w in st.words))
            elif st.kind == "dir" and st.data:
                data = st.data
            else:
                if st.section is not None and st.section not in secs:
                    secs[st.section] = None
                continue
            if st.section is None:
                for i, b in enumerate(data):
                    abs_mem[st.addr + i] = (b, key, st.kind == "insn")
                continue
            secs[st.section] = None
            buf = content.setdefault(st.section, bytearray())
            if len(buf) < st.addr + len(data):
                buf.extend(bytes(st.addr + len(data) - len(buf)))
            buf[st.addr:st.addr + len(data)] = data
            if st.kind == "insn":
                code[st.section] = code.get(st.section, 0) + len(data)
                if is_nobits(st.section):
                    raise AsmError(f"instruction in {st.section}, which holds only zeros",
                                   st.where)
            elif is_nobits(st.section) and any(data):
                raise AsmError(f"{st.section} holds only zeros", st.where)
        # sizes come from the location counters (a section can end in .space)
        size = {}
        for st in self.stmts:
            if st.section is not None:
                end = st.addr + (st.size if st.kind == "insn" else len(st.data))
                size[st.section] = max(size.get(st.section, 0), end)
        for sec in secs:
            nb = is_nobits(sec)
            data = bytes(content.get(sec, b"")).ljust(size.get(sec, 0), b"\0")
            o.sections.append(O.Section(sec, O.SEC_NOBITS if nb else 0, 0, len(data),
                                        self.sec_align.get(sec, 1), b"" if nb else data,
                                        code.get(sec, 0)))
            secs[sec] = len(o.sections)
        # absolute sections: one per contiguous run of bytes
        abs_index = {}
        run = None
        for a in sorted(abs_mem):
            b, key, is_code = abs_mem[a]
            if run is None or a != run[0] + len(run[1]) or key != run[2]:
                run = [a, bytearray(), key, 0]
                o.sections.append(run)
            run[1].append(b)
            run[3] += is_code
        for k, r in enumerate(o.sections):
            if isinstance(r, list):
                o.sections[k] = O.Section(r[2], O.SEC_ABS, r[0], len(r[1]), 1, bytes(r[1]), r[3])
                abs_index[r[0]] = k + 1
        # symbols
        syms = {}

        def add(name, section, value, flags):
            syms[name] = len(o.symbols)
            o.symbols.append(O.Symbol(name, section, value, flags))
        for sec, k in secs.items():
            add(sec, k, 0, O.SYM_SECTION)
        exported = self.globals or {st.label for st in self.stmts
                                    if st.kind == "label" and st.toplevel}
        exported = exported - self.locals
        for name in self.globals:
            if name not in self.defined:
                raise AsmError(f".global {name}, but {name} isn't defined here (no need to "
                               "declare external symbols)")

        def flags(name):
            return ((O.SYM_GLOBAL if name in exported else 0)
                    | (O.SYM_FAR if name in self.far else 0))
        def abs_place(a):
            for k, sec in enumerate(o.sections):
                if sec.absolute and sec.addr <= a <= sec.addr + sec.size:
                    return k + 1, a - sec.addr
            return O.ABS, a
        for st in self.stmts:
            if st.kind == "label":
                if st.section is None:
                    add(st.label, *abs_place(self.symbols[st.label]), flags(st.label))
                else:
                    add(st.label, secs[st.section], self.symbols[st.label], flags(st.label))
            elif st.kind == "dir" and st.name == ".equ":
                name = mangle(st.operands[0][0][1], st.scope)
                if name in self.symbols:
                    add(name, O.ABS, self.symbols[name], flags(name) & ~O.SYM_GLOBAL
                        if name not in self.globals else flags(name))
                elif name in self.globals:
                    v, base = self.equ_rel[name]
                    if base[0] == "ext":
                        raise AsmError(f"can't export {name}: it's an external symbol plus "
                                       "a constant", st.where)
                    sec = self.base_section(base)
                    add(name, secs[sec], self.base_offset(base) + v, flags(name))

        def symbol_for(base):
            if base is None:
                if "*ABS*" not in syms:
                    add("*ABS*", O.ABS, 0, 0)
                return syms["*ABS*"]
            if base[0] == "sec":
                return syms[base[1]]
            name = base[1]
            if name not in syms:
                add(name, O.UNDEF, 0, O.SYM_GLOBAL | (O.SYM_FAR if name in self.far else 0))
            return syms[name]
        for st in self.stmts:
            for off, kind, base, addend in st.relocs:
                if st.section is None:
                    # an absolute section: find its run
                    k = max(a for a in abs_index if a <= off)
                    sec, where = abs_index[k], off - k
                else:
                    sec, where = secs[st.section], off
                o.relocs.append(O.Reloc(sec, where, kind, symbol_for(base), addend))
                # the field holds nothing until the linker fills it in
                target = o.sections[sec - 1]
                if not target.nobits:
                    data = bytearray(target.data)
                    data[where:where + O.RELOC_SIZE[kind]] = bytes(O.RELOC_SIZE[kind])
                    target.data = bytes(data)
        return o

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
                lines.append(f"{'':20} {text}")
                continue
            st = body[0]
            if st.kind == "insn":
                hexw = " ".join(f"{w:04X}" for w in st.words)
                lines.append(f"{st.addr:04X}  {hexw:<14} {text}")
            else:
                d = st.data[:4]
                hexb = " ".join(f"{b:02X}" for b in d) + (" …" if len(st.data) > 4 else "")
                lines.append(f"{st.addr:04X}  {hexb:<14} {text}")
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
