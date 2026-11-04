"""A small two-pass 6502 assembler, for the m6502 workload's program.

    img = assemble(text, {"REPS": 4})    # -> Assembly: 64 KB image, symbols

The syntax is the usual one:

    NAME = expr                 a constant
    label:                      a label; @name is local to the last label
            LDA #<table         immediate (< low byte, > high byte)
            STA ptr             zero page or absolute, whichever fits
            LDA (ptr),Y         (zp),Y; also (zp,X), (abs) for JMP
            LDA table,X         zp,X or abs,X; also ,Y
            ASL A               the accumulator (or just ASL)
            .org $F000          where the next bytes go
            .byte 1, "text", 0  bytes and strings
            .word label         16-bit little-endian words
            .res 16             reserve bytes: move on without writing

Expressions have numbers ($hex, %binary, decimal, 'c'), symbols, `*` for
the current address, unary - ~ < >, and binary * / % + - << >> & ^ |
with C's precedence. A zero-page form is used when the operand's value is
known in the first pass and below 256, so zero-page variables are defined
before the code that uses them; a forward reference takes the absolute
form in both passes.

The opcode table here is written out by mnemonic and mode; cpu6502.py,
the reference emulator, decodes opcodes from their bit fields instead, and
its self-test checks that the two agree.
"""

import re

# mnemonic -> {mode: opcode}. Modes: imp (implied or the accumulator),
# imm, zp, zpx, zpy, abs, abx, aby, ind, izx (zp,X), izy (zp),Y, rel.
OPCODES = {
    "ADC": {"imm": 0x69, "zp": 0x65, "zpx": 0x75, "abs": 0x6D, "abx": 0x7D, "aby": 0x79, "izx": 0x61, "izy": 0x71},
    "AND": {"imm": 0x29, "zp": 0x25, "zpx": 0x35, "abs": 0x2D, "abx": 0x3D, "aby": 0x39, "izx": 0x21, "izy": 0x31},
    "ASL": {"imp": 0x0A, "zp": 0x06, "zpx": 0x16, "abs": 0x0E, "abx": 0x1E},
    "BCC": {"rel": 0x90}, "BCS": {"rel": 0xB0}, "BEQ": {"rel": 0xF0}, "BMI": {"rel": 0x30},
    "BNE": {"rel": 0xD0}, "BPL": {"rel": 0x10}, "BVC": {"rel": 0x50}, "BVS": {"rel": 0x70},
    "BIT": {"zp": 0x24, "abs": 0x2C},
    "BRK": {"imp": 0x00},
    "CLC": {"imp": 0x18}, "CLD": {"imp": 0xD8}, "CLI": {"imp": 0x58}, "CLV": {"imp": 0xB8},
    "CMP": {"imm": 0xC9, "zp": 0xC5, "zpx": 0xD5, "abs": 0xCD, "abx": 0xDD, "aby": 0xD9, "izx": 0xC1, "izy": 0xD1},
    "CPX": {"imm": 0xE0, "zp": 0xE4, "abs": 0xEC},
    "CPY": {"imm": 0xC0, "zp": 0xC4, "abs": 0xCC},
    "DEC": {"zp": 0xC6, "zpx": 0xD6, "abs": 0xCE, "abx": 0xDE},
    "DEX": {"imp": 0xCA}, "DEY": {"imp": 0x88},
    "EOR": {"imm": 0x49, "zp": 0x45, "zpx": 0x55, "abs": 0x4D, "abx": 0x5D, "aby": 0x59, "izx": 0x41, "izy": 0x51},
    "INC": {"zp": 0xE6, "zpx": 0xF6, "abs": 0xEE, "abx": 0xFE},
    "INX": {"imp": 0xE8}, "INY": {"imp": 0xC8},
    "JMP": {"abs": 0x4C, "ind": 0x6C},
    "JSR": {"abs": 0x20},
    "LDA": {"imm": 0xA9, "zp": 0xA5, "zpx": 0xB5, "abs": 0xAD, "abx": 0xBD, "aby": 0xB9, "izx": 0xA1, "izy": 0xB1},
    "LDX": {"imm": 0xA2, "zp": 0xA6, "zpy": 0xB6, "abs": 0xAE, "aby": 0xBE},
    "LDY": {"imm": 0xA0, "zp": 0xA4, "zpx": 0xB4, "abs": 0xAC, "abx": 0xBC},
    "LSR": {"imp": 0x4A, "zp": 0x46, "zpx": 0x56, "abs": 0x4E, "abx": 0x5E},
    "NOP": {"imp": 0xEA},
    "ORA": {"imm": 0x09, "zp": 0x05, "zpx": 0x15, "abs": 0x0D, "abx": 0x1D, "aby": 0x19, "izx": 0x01, "izy": 0x11},
    "PHA": {"imp": 0x48}, "PHP": {"imp": 0x08}, "PLA": {"imp": 0x68}, "PLP": {"imp": 0x28},
    "ROL": {"imp": 0x2A, "zp": 0x26, "zpx": 0x36, "abs": 0x2E, "abx": 0x3E},
    "ROR": {"imp": 0x6A, "zp": 0x66, "zpx": 0x76, "abs": 0x6E, "abx": 0x7E},
    "RTI": {"imp": 0x40}, "RTS": {"imp": 0x60},
    "SBC": {"imm": 0xE9, "zp": 0xE5, "zpx": 0xF5, "abs": 0xED, "abx": 0xFD, "aby": 0xF9, "izx": 0xE1, "izy": 0xF1},
    "SEC": {"imp": 0x38}, "SED": {"imp": 0xF8}, "SEI": {"imp": 0x78},
    "STA": {"zp": 0x85, "zpx": 0x95, "abs": 0x8D, "abx": 0x9D, "aby": 0x99, "izx": 0x81, "izy": 0x91},
    "STX": {"zp": 0x86, "zpy": 0x96, "abs": 0x8E},
    "STY": {"zp": 0x84, "zpx": 0x94, "abs": 0x8C},
    "TAX": {"imp": 0xAA}, "TAY": {"imp": 0xA8}, "TSX": {"imp": 0xBA},
    "TXA": {"imp": 0x8A}, "TXS": {"imp": 0x9A}, "TYA": {"imp": 0x98},
}

# The operand's size in bytes, by mode
SIZE = {"imp": 0, "imm": 1, "zp": 1, "zpx": 1, "zpy": 1, "abs": 2, "abx": 2,
        "aby": 2, "ind": 2, "izx": 1, "izy": 1, "rel": 1}


class AsmError(Exception):
    pass


# ---- expressions ------------------------------------------------------------

_TOKEN = re.compile(r"""\s*(?:
    (?P<hex>\$[0-9A-Fa-f]+) | (?P<bin>%[01]+) | (?P<dec>[0-9]+) |
    (?P<chr>'(?:\\.|[^'\\])') | (?P<id>@?[A-Za-z_][A-Za-z0-9_@]*) |
    (?P<op><<|>>|[-+*/%&|^~<>()])
)""", re.X)

# binary operators, by precedence (lowest first), as C has them
_BINARY = [("|",), ("^",), ("&",), ("<<", ">>"), ("+", "-"), ("*", "/", "%")]


def _tokens(s):
    out, i = [], 0
    s = s.rstrip()
    while i < len(s):
        m = _TOKEN.match(s, i)
        if not m or m.end() == i:
            raise AsmError(f"can't read {s[i:]!r}")
        i = m.end()
        kind = m.lastgroup
        t = m.group(kind)
        if kind == "hex":
            out.append(("num", int(t[1:], 16)))
        elif kind == "bin":
            out.append(("num", int(t[1:], 2)))
        elif kind == "dec":
            out.append(("num", int(t)))
        elif kind == "chr":
            c = t[1:-1]
            out.append(("num", ord(c[1]) if c[0] == "\\" else ord(c)))
        else:
            out.append((kind, t))
    return out


class _Expr:
    """An expression's value: a recursive-descent parser over its tokens.
    `lookup(name)` gives a symbol's value, or None if it isn't known yet;
    the result is None if anything in it isn't known."""

    def __init__(self, text, lookup, here):
        self.toks = _tokens(text)
        self.i = 0
        self.lookup = lookup
        self.here = here

    def value(self):
        v = self.binary(0)
        if self.i != len(self.toks):
            raise AsmError(f"unexpected {self.toks[self.i][1]!r}")
        return v

    def peek(self):
        return self.toks[self.i] if self.i < len(self.toks) else (None, None)

    def binary(self, level):
        if level == len(_BINARY):
            return self.unary()
        left = self.binary(level + 1)
        while self.peek()[0] == "op" and self.peek()[1] in _BINARY[level]:
            op = self.toks[self.i][1]
            self.i += 1
            right = self.binary(level + 1)
            if left is None or right is None:
                left = None
                continue
            if op in ("/", "%") and right == 0:
                raise AsmError("division by zero")
            left = {"|": left | right, "^": left ^ right, "&": left & right,
                    "<<": left << right, ">>": left >> right, "+": left + right,
                    "-": left - right, "*": left * right, "/": left // right,
                    "%": left % right}[op]
        return left

    def unary(self):
        kind, t = self.peek()
        if kind is None:
            raise AsmError("expression ends too soon")
        self.i += 1
        if kind == "num":
            return t
        if kind == "id":
            return self.lookup(t)
        if t == "*":
            return self.here
        if t == "(":
            v = self.binary(0)
            if self.peek() != ("op", ")"):
                raise AsmError("missing )")
            self.i += 1
            return v
        if t in "-~<>":
            v = self.unary()
            if v is None:
                return None
            return {"-": -v, "~": ~v, "<": v & 0xFF, ">": (v >> 8) & 0xFF}[t]
        raise AsmError(f"unexpected {t!r}")


# ---- the assembler ------------------------------------------------------------

def _split_args(s):
    """Split a directive's arguments at commas outside strings."""
    out, cur, quote = [], "", None
    for c in s:
        if quote:
            cur += c
            if c == quote:
                quote = None
        elif c in "\"'":
            quote = c
            cur += c
        elif c == ",":
            out.append(cur.strip())
            cur = ""
        else:
            cur += c
    if cur.strip():
        out.append(cur.strip())
    return out


def _strip_comment(line):
    quote = None
    for i, c in enumerate(line):
        if quote:
            if c == quote:
                quote = None
        elif c in "\"'":
            quote = c
        elif c == ";":
            return line[:i]
    return line


def _operand(text):
    """An operand's addressing-mode family and its expression: imp, imm,
    ind, izx, izy, idx-X, idx-Y or plain (zp, abs or rel, decided later)."""
    t = text.strip()
    u = t.upper().replace(" ", "")
    if t == "" or u == "A":
        return "imp", None
    if t.startswith("#"):
        return "imm", t[1:]
    if u.startswith("(") and u.endswith(",X)"):
        return "izx", t[1:t.upper().rindex(",")]
    if u.startswith("(") and u.endswith("),Y"):
        return "izy", t[1:t.rindex(")")]
    if u.endswith(",X") or u.endswith(",Y"):
        return "idx-" + u[-1], t[:t.rindex(",")]
    if u.startswith("(") and u.endswith(")"):
        return "paren", t
    return "plain", t


class Assembly:
    """The result: the 64 KB memory image, what was written, and symbols."""

    def __init__(self, mem, written, symbols):
        self.mem = mem
        self.written = written
        self.symbols = symbols

    def span(self):
        """The lowest and highest address written, plus one."""
        return min(self.written), max(self.written) + 1


def assemble(text, defines=None, name="program"):
    symbols = {k: int(v) for k, v in (defines or {}).items()}
    lines = text.split("\n")
    modes = {}                  # line number -> mode chosen in the first pass

    for final in (False, True):
        mem = bytearray(0x10000)
        written = set()
        pc = 0
        scope = ""

        def where(n):
            return f"{name}:{n + 1}"

        for n, raw in enumerate(lines):
            line = _strip_comment(raw).strip()
            try:
                def lookup(sym):
                    if sym.startswith("@"):
                        sym = scope + sym
                    if sym in symbols:
                        return symbols[sym]
                    if final:
                        raise AsmError(f"undefined symbol {sym}")
                    return None

                def value(expr):
                    return _Expr(expr, lookup, pc).value()

                def emit(*bs):
                    nonlocal pc
                    for b in bs:
                        if pc > 0xFFFF:
                            raise AsmError("past the end of memory")
                        mem[pc] = b & 0xFF
                        written.add(pc)
                        pc += 1

                # constants
                m = re.match(r"([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.+)$", line)
                if m:
                    v = value(m.group(2))
                    if v is not None:
                        symbols[m.group(1)] = v
                    continue
                # labels
                m = re.match(r"(@?[A-Za-z_][A-Za-z0-9_]*):\s*(.*)$", line)
                if m:
                    label = m.group(1)
                    if label.startswith("@"):
                        label = scope + label
                    else:
                        scope = label
                    if not final and label in symbols:
                        raise AsmError(f"{label} is defined twice")
                    symbols[label] = pc
                    line = m.group(2)
                if not line:
                    continue
                parts = line.split(None, 1)
                op = parts[0]
                arg = parts[1] if len(parts) > 1 else ""
                if op.startswith("."):
                    d = op.lower()
                    if d == ".org":
                        pc = value(arg)
                        if pc is None:
                            raise AsmError(".org needs a known address")
                    elif d == ".res":
                        k = value(arg)
                        if k is None:
                            raise AsmError(".res needs a known size")
                        pc += k
                    elif d in (".byte", ".word"):
                        for a in _split_args(arg):
                            if a.startswith('"'):
                                if d == ".word":
                                    raise AsmError(".word doesn't take strings")
                                emit(*a[1:-1].encode("latin-1"))
                                continue
                            v = value(a) or 0
                            if d == ".byte":
                                if final and not -128 <= v <= 255:
                                    raise AsmError(f"{v} doesn't fit a byte")
                                emit(v)
                            else:
                                emit(v, v >> 8)
                    else:
                        raise AsmError(f"unknown directive {op}")
                    continue
                emit(*_instruction(op.upper(), arg, n, modes, final, value, pc))
            except AsmError as e:
                raise AsmError(f"{where(n)}: {e}") from None
    return Assembly(mem, written, symbols)


def _instruction(mn, arg, n, modes, final, value, pc):
    """An instruction's bytes; in the first pass, chooses its mode."""
    if mn not in OPCODES:
        raise AsmError(f"unknown instruction {mn}")
    table = OPCODES[mn]
    family, expr = _operand(arg)
    v = value(expr) if expr is not None else None
    if family == "paren":
        if "ind" in table:
            family, expr = "ind", expr[1:-1]
            v = value(expr)
        else:
            family = "plain"
    if n in modes:
        mode = modes[n]
    else:
        short = v is not None and 0 <= v < 256
        if family in ("imp", "imm", "izx", "izy", "ind"):
            mode = family
        elif "rel" in table:
            mode = "rel"
        elif family == "plain":
            mode = "zp" if short and "zp" in table else "abs"
        else:
            r = family[-1].lower()
            mode = f"zp{r}" if short and f"zp{r}" in table else f"ab{r}"
        modes[n] = mode
    if mode not in table:
        raise AsmError(f"{mn} has no {mode} mode")
    if not final:
        return [0] * (1 + SIZE[mode])
    if mode == "rel":
        d = v - (pc + 2)
        if not -128 <= d <= 127:
            raise AsmError(f"branch out of reach ({d})")
        return [table[mode], d & 0xFF]
    size = SIZE[mode]
    if size == 1 and not (0 <= v < 256 or mode == "imm" and -128 <= v < 0):
        raise AsmError(f"{v} doesn't fit a byte")
    if size == 2 and not 0 <= v < 0x10000:
        raise AsmError(f"{v} isn't an address")
    return [table[mode]] + [(v >> (8 * k)) & 0xFF for k in range(size)]
