r"""The IOP's microassembler: RFC 0027's notation (6.2), one line a
microinstruction, into the 48-bit words of 3.3 (the field table is in
studies/iop/sim/src/micro.rs; FIELDS below is the same).

A line is a label (`name:`), then clauses separated by `|`, then an
optional comment after `;`:

    next:   ip, X <- ip + 1
            F <- [X] | X <- F | dispatch nest      ; a primitive, or a colon definition
            nop

A `|` starts a new clause only where what follows is one (an assignment,
or a keyword); elsewhere it is OR.

**The ALU clause,** `dests <- expr`. The expression is a 74181 function of
one source, A, which is R in the first half, and AC, B:

- the source: a register (`ip`), memory at X (`[X]`), a constant (`#12`,
  `#name`, `#(expr)`), bus read data (`BA`) or a device on T (`io`, `sr`,
  `swap`, `ev0`-`ev2`, `pg0`, `pg1`, `ttab`, `d6`, `d7`);
- the functions, spelt with `A` for the source and `AC`: `A`, `A + AC`,
  `A - AC`, `A + 1`, `A - 1`, `A + A`, `A & AC`, `A | AC`, `A ^ AC`, `~A`,
  `AC`, `~AC`, `0`, `-1`, `A & ~AC`, `(A & AC) - 1` and the rest of the
  chip's 48 (see FUNCTIONS);
- `F` alone keeps the last result: HOLD.

The destinations: registers and `[X]` are written back in the second half
(WB), so the SRAM's address must be that register's, or X when the source
is memory; `AC`, `X`, `BANK`, `AH0`, `AH1`, `LC` and `CTRL` are loaded at
E2 (one of them); `F` names the result without storing it. A second ALU
clause whose expression is `F` adds its destinations to the first:
`F <- [X] | X <- F` is RFC 0027's "F <- [X]; X <- F".

**T moves:** `AB <- BA`, `AB <- F`, `AB <- dev`, `dev <- BA`, `dev <- F`.

**Bus transfers:** `rd.h AH0`, `wr.b0 AH1`, `rd.b1 AH0`, `rdl.h AH0` (the
locked read, kept): the address is the ALU's source.

**Sequencing:** `goto L`, `if C goto L`, `ifnot C goto L`, `dispatch L` (to
F if F's bit 15 is set, else to L), `goto F` (to F), `if C goto F else L`,
and `count` (count LC without branching). Conditions: `carry`, `F15`, `lc`
(LC not done, and count), `attn`, `bell`.

**Others:** `nop`; `task` (the TASK bit); `NEXT`, the inner interpreter's
step, three lines, with the clauses after it on the line as the last
one's, the delay slot: `NEXT | sp <- sp + 1`.

**Constants** are Python expressions over layout.py's names, the labels
and the registers' numbers.

**Directives:** `.equ name expr`, `.reg name n`, `.org expr`, `.prim
name`, which makes the next line a Forth primitive by that name, and
`.macro name params` ... `.endm`: a use `name args` stands for the lines,
`\param` for its argument and `\@` for a number of the use's own.

REG is shared by a register and a device: a line that names both must
name a register whose number REG can be for that device too.
"""

import re

from . import layout

FIELDS = {
    "K": (0, 16), "REG": (16, 6), "RS": (22, 2), "ALU": (24, 6), "WB": (30, 1), "LD": (31, 3),
    "BUS": (34, 2), "SEG": (36, 1), "SZ": (37, 2), "T": (39, 3), "SEQ": (42, 2), "COND": (44, 3),
    "TASK": (47, 1),
}

RS_REG, RS_MEM, RS_K, RS_T = range(4)
LD = {"AC": 1, "X": 2, "BANK": 3, "AH0": 4, "AH1": 5, "LC": 6, "CTRL": 7}
T_AB_BA, T_AB_F, T_AB_DEV, T_DEV_BA, T_DEV_F, T_FROM_DEV = 1, 2, 3, 4, 5, 6
CONDS = {"always": 0, "carry": 1, "F15": 2, "lc": 3, "attn": 4, "bell": 5}

# Devices on T: name -> (device, register or None when REG's low bits are free)
DEVICES = {
    "io": (0, None), "sr": (1, None), "swap": (2, None),
    "ev0": (3, 0), "ev1": (3, 1), "ev2": (3, 2),
    "pg0": (4, 0), "pg1": (4, 1),
    "ttab": (5, None), "d6": (6, None), "d7": (7, None),
}


def _functions():
    """{spelling: (S, M, cin)} for the 74181, A the source and B AC. Logic
    first, so that a function both can do is the logic one."""
    logic = {
        0b0000: ["~A"], 0b0001: ["~(A|B)", "~A&~B"], 0b0010: ["~A&B", "B&~A"], 0b0011: ["0"],
        0b0100: ["~(A&B)", "~A|~B"], 0b0101: ["~B"], 0b0110: ["A^B", "B^A"], 0b0111: ["A&~B", "~B&A"],
        0b1000: ["~A|B", "B|~A"], 0b1001: ["~(A^B)", "A^~B", "~A^B"], 0b1010: ["B"], 0b1011: ["A&B", "B&A"],
        0b1100: ["-1"], 0b1101: ["A|~B", "~B|A"], 0b1110: ["A|B", "B|A"], 0b1111: ["A"],
    }
    arith = {
        (0b0000, 0): ["A+0"], (0b0000, 1): ["A+1"],
        (0b0001, 0): ["(A|B)+0"], (0b0001, 1): ["(A|B)+1"],
        (0b0010, 0): ["(A|~B)+0"], (0b0010, 1): ["(A|~B)+1"],
        (0b0011, 0): ["-1+0"], (0b0011, 1): ["-1+1"],
        (0b0100, 0): ["A+(A&~B)"], (0b0100, 1): ["A+(A&~B)+1"],
        (0b0101, 0): ["(A|B)+(A&~B)"], (0b0101, 1): ["(A|B)+(A&~B)+1"],
        (0b0110, 0): ["A-B-1"], (0b0110, 1): ["A-B"],
        (0b0111, 0): ["(A&~B)-1"], (0b0111, 1): ["(A&~B)-1+1"],
        (0b1000, 0): ["A+(A&B)"], (0b1000, 1): ["A+(A&B)+1"],
        (0b1001, 0): ["A+B", "B+A"], (0b1001, 1): ["A+B+1", "B+A+1"],
        (0b1010, 0): ["(A|~B)+(A&B)"], (0b1010, 1): ["(A|~B)+(A&B)+1"],
        (0b1011, 0): ["(A&B)-1", "(B&A)-1"], (0b1011, 1): ["(A&B)-1+1"],
        (0b1100, 0): ["A+A", "2*A"], (0b1100, 1): ["A+A+1"],
        (0b1101, 0): ["(A|B)+A"], (0b1101, 1): ["(A|B)+A+1"],
        (0b1110, 0): ["(A|~B)+A"], (0b1110, 1): ["(A|~B)+A+1"],
        (0b1111, 0): ["A-1"], (0b1111, 1): ["A-1+1"],
    }
    out = {}
    for s, names in logic.items():
        for n in names:
            out[n] = (s, 1, 1 if s == 0 else 0)     # NOT A with the carry in: 0 is HOLD
    for (s, c), names in arith.items():
        for n in names:
            out.setdefault(n, (s, 0, c))
    return out


FUNCTIONS = _functions()
HOLD = (0, 1, 0)


class AsmError(Exception):
    pass


def encode(f):
    """A microinstruction's word from its field values."""
    w = 0
    for name, v in f.items():
        shift, width = FIELDS[name]
        if not 0 <= v < 1 << width:
            raise AsmError(f"{name} = {v} doesn't fit in {width} bits")
        w |= v << (shift)
    return w


def alu_field(s, m, cin):
    """The ALU field: S0-S3, M stored inverted, the carry in."""
    return s | (0 if m else 16) | (32 if cin else 0)


TOKEN = re.compile(r"\s*(\[X\]|#-?[\w.]+|<-|[A-Za-z_][\w.]*|0x[0-9a-fA-F]+|\d+|[-+&|^~()*,])")


def tokens(s):
    """An expression's tokens; a constant `#(...)` is one, parentheses
    and all."""
    out, pos = [], 0
    s = s.rstrip()
    while pos < len(s):
        while s[pos].isspace():
            pos += 1
        if s.startswith("#(", pos):
            depth, end = 0, pos + 1
            while end < len(s):
                depth += {"(": 1, ")": -1}.get(s[end], 0)
                end += 1
                if depth == 0:
                    break
            if depth:
                raise AsmError(f"unbalanced parentheses in {s[pos:]!r}")
            out.append(s[pos:end])
            pos = end
            continue
        m = TOKEN.match(s, pos)
        if not m:
            raise AsmError(f"can't read {s[pos:]!r}")
        out.append(m.group(1))
        pos = m.end()
    return out


CLAUSE_START = re.compile(r"\s*(goto|if|ifnot|dispatch|nop|count|task|rdl?\.|wr\.|NEXT\b)")


def clauses(s):
    """A line's clauses: split at each `|` that starts a new clause (an
    assignment or a keyword), so that `|` is still OR inside an
    expression."""
    out = []
    for part in s.split("|"):
        if out and "<-" not in part and not CLAUSE_START.match(part):
            out[-1] += "|" + part
        else:
            out.append(part)
    return [c.strip() for c in out]


class Line:
    """One microinstruction being assembled."""

    def __init__(self, src, where):
        self.src = src
        self.where = where
        self.f = {}
        self.k = None            # (expr text) for K
        self.reg = None          # register number named
        self.dev = None          # (device, fixed register or None)
        self.label = None
        self.prim = None


class Assembler:
    def __init__(self):
        self.symbols = {k: v for k, v in vars(layout).items()
                        if isinstance(v, int) and not k.startswith("_")}
        self.regs = {**layout.REGS, **layout.JOB_REGS, **layout.NAT_REGS}
        self.lines = []          # (address, Line)
        self.prims = {}          # Forth name -> address
        self.labels = {}
        self.pc = 0
        self.pending_prim = None
        self.prim_at = {}
        self.used = set()
        self.macros = {}
        self.uses = 0

    # ---- expressions

    def value(self, text, where, labels_ok=True):
        text = text.strip()
        env = {**self.regs, **self.symbols}
        if labels_ok:
            env.update(self.labels)
        try:
            v = eval(text, {"__builtins__": {}}, env)
        except NameError as e:
            raise AsmError(f"{where}: unknown name in {text!r}: {e}") from None
        except Exception as e:
            raise AsmError(f"{where}: bad expression {text!r}: {e}") from None
        return int(v)

    # ---- the source

    def assemble(self, text, name="<microcode>"):
        """First pass over a source file: macros expanded, lines placed,
        labels defined."""
        for where, raw in self.expand([(f"{name}:{n}", raw) for n, raw in enumerate(text.split("\n"), 1)]):
            line = raw.split(";", 1)[0].rstrip()
            if not line.strip():
                continue
            m = re.match(r"\s*([A-Za-z_][\w.]*):(.*)$", line)
            label = None
            if m:
                label, line = m.group(1), m.group(2)
            if label:
                if label in self.labels:
                    raise AsmError(f"{where}: {label} defined twice")
                self.labels[label] = self.pc
            s = line.strip()
            if not s:
                continue
            if s.startswith("."):
                self.directive(s, where)
                continue
            cs = clauses(s)
            if cs[0] == "NEXT":
                expansion = ["ip, X <- ip + 1", "F <- [X] | X <- F | dispatch nest",
                             " | ".join(cs[1:]) or "nop"]
                for i, e in enumerate(expansion):
                    self.place(e, raw if i == 0 else f"    (NEXT) {e}", where)
                continue
            self.place(s, raw, where)

    def expand(self, lines):
        r"""Macros: `.macro name p1 p2 ...` to `.endm` defines one; a line
        `[label:] name a1 a2 ...` uses it, `\p1` in its body standing for
        a1, and `\@` for a number of the use's own, for labels."""
        out = []
        i = 0
        while i < len(lines):
            where, raw = lines[i]
            code = raw.split(";", 1)[0].strip()
            if code.startswith(".macro"):
                parts = code.split()
                body = []
                i += 1
                while i < len(lines) and lines[i][1].split(";", 1)[0].strip() != ".endm":
                    body.append(lines[i][1])
                    i += 1
                if i == len(lines):
                    raise AsmError(f"{where}: .macro without .endm")
                self.macros[parts[1]] = (parts[2:], body)
                i += 1
                continue
            m = re.match(r"\s*(?:([A-Za-z_][\w.]*):)?\s*([A-Za-z_][\w.]*)\b(.*)$", code)
            if m and m.group(2) in self.macros:
                params, body = self.macros[m.group(2)]
                args = m.group(3).split()
                if len(args) != len(params):
                    raise AsmError(f"{where}: {m.group(2)} takes {len(params)} arguments")
                self.uses += 1
                expanded = []
                for b in body:
                    for p, a in sorted(zip(params, args), key=lambda x: -len(x[0])):
                        b = b.replace("\\" + p, a)
                    expanded.append((f"{where} ({m.group(2)})", b.replace("\\@", str(self.uses))))
                if m.group(1):
                    expanded.insert(0, (where, m.group(1) + ":"))
                lines[i + 1:i + 1] = expanded
                i += 1
                continue
            out.append((where, raw))
            i += 1
        return out

    def directive(self, s, where):
        parts = s.split(None, 2)
        d = parts[0]
        if d == ".equ":
            self.symbols[parts[1]] = self.value(parts[2], where)
        elif d == ".reg":
            self.regs[parts[1]] = self.value(parts[2], where)
        elif d == ".org":
            self.pc = self.value(" ".join(parts[1:]), where, labels_ok=False)
        elif d == ".prim":
            self.pending_prim = parts[1]
        else:
            raise AsmError(f"{where}: unknown directive {d}")

    def place(self, text, raw, where):
        ln = Line(text, where)
        ln.raw = raw
        if self.pending_prim is not None:
            if self.pending_prim in self.prims:
                raise AsmError(f"{where}: primitive {self.pending_prim} defined twice")
            if self.pc < 0x8000:
                raise AsmError(f"{where}: primitive {self.pending_prim} below 0x8000")
            self.prims[self.pending_prim] = self.pc
            self.prim_at[self.pc] = self.pending_prim
            self.pending_prim = None
        if self.pc in self.used:
            raise AsmError(f"{where}: address {self.pc:04X} used twice")
        self.used.add(self.pc)
        self.lines.append((self.pc, ln))
        self.pc += 1

    # ---- the second pass

    def link(self):
        """Encode every line: {address: word}."""
        words = {}
        for addr, ln in self.lines:
            try:
                words[addr] = self.encode_line(ln)
            except AsmError as e:
                raise AsmError(f"{ln.where}: {e} in {ln.src!r}") from None
        return words

    def set_k(self, ln, v):
        v &= 0xFFFF
        if ln.k is not None and ln.k != v:
            raise AsmError(f"K is needed for both {ln.k:#x} and {v:#x}")
        ln.k = v

    def name_reg(self, ln, name):
        r = self.regs[name]
        if ln.reg is not None and ln.reg != r:
            raise AsmError(f"two registers, {ln.reg} and {r}")
        ln.reg = r

    def name_dev(self, ln, name):
        d = DEVICES[name]
        if ln.dev is not None and ln.dev != d:
            raise AsmError(f"two devices on T: {ln.dev} and {d}")
        ln.dev = d

    def encode_line(self, ln):
        f = {}
        alu_clauses = []
        for c in clauses(ln.src):
            if not c or c == "nop":
                continue
            if c == "task":
                f["TASK"] = 1
                continue
            if c == "count":
                self.set_field(f, "COND", CONDS["lc"])
                continue
            m = re.match(r"(rdl?|wr)\.(b0|b1|h|w)\s+(AH[01])$", c)
            if m:
                self.set_field(f, "BUS", {"rd": 1, "wr": 2, "rdl": 3}[m.group(1)])
                self.set_field(f, "SZ", {"b0": 0, "b1": 1, "h": 2, "w": 3}[m.group(2)])
                self.set_field(f, "SEG", int(m.group(3)[2]))
                continue
            if self.seq_clause(ln, f, c):
                continue
            if "<-" in c:
                dests, expr = c.split("<-", 1)
                dests = [d.strip() for d in dests.split(",")]
                expr = expr.strip()
                if dests[0] == "AB" or dests[0] in DEVICES:
                    self.t_move(ln, f, dests, expr)
                else:
                    alu_clauses.append((dests, expr))
                continue
            raise AsmError(f"can't read {c!r}")
        self.alu(ln, f, alu_clauses)
        if ln.k is not None:
            f["K"] = ln.k
        reg = self.resolve_reg(ln)
        if reg is not None:
            f["REG"] = reg
        return encode(f)

    def set_field(self, f, name, v):
        if name in f and f[name] != v:
            raise AsmError(f"{name} set twice")
        f[name] = v

    def seq_clause(self, ln, f, c):
        m = re.match(r"goto\s+F$", c)
        if m:
            self.set_field(f, "SEQ", 3)
            self.set_field(f, "COND", 0)
            return True
        m = re.match(r"if\s+(!?)(\w+)\s+goto\s+F\s+else\s+(.+)$", c)
        if m:
            if m.group(1):
                raise AsmError("to F needs the condition itself")
            self.set_field(f, "SEQ", 3)
            self.set_field(f, "COND", CONDS[m.group(2)])
            self.set_k(ln, self.value(m.group(3), ln.where))
            return True
        m = re.match(r"goto\s+(.+)$", c)
        if m:
            self.set_field(f, "SEQ", 1)
            self.set_field(f, "COND", 0)
            self.set_k(ln, self.value(m.group(1), ln.where))
            return True
        m = re.match(r"(if|ifnot)\s+(!?)(\w+)\s+goto\s+(.+)$", c)
        if m:
            neg = (m.group(1) == "ifnot") != bool(m.group(2))
            if m.group(3) not in CONDS:
                raise AsmError(f"no condition {m.group(3)}")
            self.set_field(f, "SEQ", 2 if neg else 1)
            self.set_field(f, "COND", CONDS[m.group(3)])
            self.set_k(ln, self.value(m.group(4), ln.where))
            return True
        m = re.match(r"dispatch\s+(.+)$", c)
        if m:
            self.set_field(f, "SEQ", 3)
            self.set_field(f, "COND", CONDS["F15"])
            self.set_k(ln, self.value(m.group(1), ln.where))
            return True
        return False

    def t_move(self, ln, f, dests, expr):
        if len(dests) != 1:
            raise AsmError("a T move has one destination")
        d = dests[0]
        if d == "AB":
            if expr == "BA":
                t = T_AB_BA
            elif expr == "F":
                t = T_AB_F
            elif expr in DEVICES:
                t = T_AB_DEV
                self.name_dev(ln, expr)
            else:
                raise AsmError(f"AB can't take {expr}")
        else:
            self.name_dev(ln, d)
            if expr == "BA":
                t = T_DEV_BA
            elif expr == "F":
                t = T_DEV_F
            else:
                raise AsmError(f"a device can't take {expr}")
        self.set_field(f, "T", t)

    def alu(self, ln, f, clauses):
        main = [c for c in clauses if c[1] != "F"]
        routed = [d for c in clauses if c[1] == "F" for d in c[0]]
        if len(main) > 1:
            raise AsmError("two ALU operations")
        dests = routed + (main[0][0] if main else [])
        rs = None
        if main:
            rs, fn = self.expression(ln, f, main[0][1])
            s, m, cin = fn
        elif clauses:
            s, m, cin = HOLD
        else:
            return
        f["ALU"] = alu_field(s, m, cin)
        wb = [d for d in dests if d == "[X]" or d in self.regs]
        ld = [d for d in dests if d in LD]
        bad = [d for d in dests if d not in LD and d != "F" and d not in wb]
        if bad:
            raise AsmError(f"can't write {bad[0]}")
        if len(wb) > 1:
            raise AsmError("two write-backs")
        if len(ld) > 1:
            raise AsmError("two loads")
        if ld:
            f["LD"] = LD[ld[0]]
        if wb:
            f["WB"] = 1
            if wb[0] == "[X]":
                if rs not in (None, RS_MEM):
                    raise AsmError("[X] written back, but the source isn't memory")
                rs = RS_MEM
            else:
                if rs == RS_MEM:
                    raise AsmError(f"{wb[0]} written back, but the SRAM's address is X")
                self.name_reg(ln, wb[0])
        if rs is not None:
            f["RS"] = rs

    def expression(self, ln, f, expr):
        """The source's RS and the function (S, M, cin)."""
        toks = tokens(expr)
        src = None
        norm = []
        for t in toks:
            if t == "AC":
                norm.append("B")
                continue
            if t in ("[X]", "BA") or t.startswith("#") or t in self.regs or t in DEVICES:
                if src is not None and src != t:
                    raise AsmError(f"two sources, {src} and {t}")
                src = t
                norm.append("A")
                continue
            norm.append(t)
        key = "".join(norm)
        if key not in FUNCTIONS:
            raise AsmError(f"the 74181 can't do {expr!r} ({key})")
        rs = None
        if src is None:
            pass
        elif src == "[X]":
            rs = RS_MEM
        elif src == "BA":
            rs = RS_T
            if f.get("T") == T_FROM_DEV:
                raise AsmError("BA and a device on R")
        elif src.startswith("#"):
            rs = RS_K
            self.set_k(ln, self.value(src[1:], ln.where))
        elif src in self.regs:
            rs = RS_REG
            self.name_reg(ln, src)
        else:
            rs = RS_T
            self.name_dev(ln, src)
            self.set_field(f, "T", T_FROM_DEV)
        return rs, FUNCTIONS[key]

    def resolve_reg(self, ln):
        if ln.dev is None:
            return ln.reg
        d, r = ln.dev
        if r is None:
            if ln.reg is None:
                return d << 3
            if ln.reg >> 3 != d:
                raise AsmError(f"register {ln.reg} can't share REG with device {d}")
            return ln.reg
        want = d << 3 | r
        if ln.reg is not None and ln.reg != want:
            raise AsmError(f"register {ln.reg} can't share REG with device {d} register {r}")
        return want


class Microcode:
    """An assembled microcode: words, labels, the primitives, a listing."""

    def __init__(self, asm, words):
        self.words = words
        self.labels = asm.labels
        self.prims = asm.prims
        self.symbols = asm.symbols
        self.lines = asm.lines

    def rom(self):
        """The words as one list, 0 to the highest used address."""
        top = max(self.words) + 1
        return [self.words.get(a, 0) for a in range(top)]

    def rom_bytes(self):
        """The six ROMs' contents interleaved: each word as 6 bytes,
        little-endian."""
        return b"".join(w.to_bytes(6, "little") for w in self.rom())

    def listing(self):
        out = []
        for a, ln in sorted(self.lines, key=lambda x: x[0]):
            out.append(f"{a:04X}  {self.words[a]:012X}  {ln.raw.rstrip()}")
        return "\n".join(out)

    def where(self, addr):
        """The label or primitive at or before a microaddress, and the
        offset."""
        best = None
        named = list(self.labels.items()) + [(f"[{n}]", a) for n, a in self.prims.items()]
        for name, a in named:
            if a <= addr and (best is None or a > best[1]):
                best = (name, a)
        return f"{best[0]}+{addr - best[1]}" if best else f"{addr:04X}"


def assemble(sources):
    """Assemble [(name, text)]: a Microcode."""
    asm = Assembler()
    for name, text in sources:
        asm.assemble(text, name)
    return Microcode(asm, asm.link())
