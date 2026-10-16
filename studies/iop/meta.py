"""The metacompiler: the IOP's Forth source into the dictionary image the
microcode copies into the SRAM at reset (RFC 0027, 6.7).

**The dictionary** is cells from 1 (0 ends the chain of headers). A
word's header:

    link        the previous header, 0 for the first
    count       the name's length (bits 0-5) and flags: 0x8000 IMMEDIATE,
                0x4000 CONSTANT (compiled inline as `lit n`), 0x2000
                HIDDEN (being defined)
    name        a cell a character
    xt          the word's execution token: a colon definition's body (the
                next cell), or a primitive's microaddress, bit 15 set

A thread is cells: xts, and the inline operands of `lit`, the branches and
the strings. `branch` and the others take the address of the cell to go
on at. A constant's or a variable's body is `lit n exit`, so that it can
be executed, and it compiles inline as `lit n`. A `create`d word's body is
`lit a exit 0`, its data at a, four cells on; `does>` makes the last two
cells `branch` to its code.

**The source** is ordinary Forth. While metacompiling, outside a colon
definition, the metacompiler interprets a small host language: numbers,
`constant` `2constant` `variable` `2variable` `create` `,` `allot` `user`
`immediate` `'` `here`, arithmetic, and the names in layout.py, which it
knows as numbers, with the microcode's labels as `U.name` and the
registers' numbers as `R.name` (a task's) and `J.name` (a job's). Inside one it compiles: the target's words, numbers as
literals, and its own versions of the control words (`if` ... `then`,
`begin` ... `until`, `do` ... `loop` and `leave`, `."`, `s"`, `abort"`,
`[char]`, `[']`, `literal`, `[` `]`, `postpone`, `recurse`, `does>`). The
target defines its own control words for its own compiler; the
metacompiler never runs target code.

Numbers: decimal, or `$` hex, `%` binary, `#` decimal; a leading `-`; a
trailing `.` makes a double, two cells (low, high).
"""

import re

from . import layout

IMMEDIATE = 0x8000
CONSTANT = 0x4000
HIDDEN = 0x2000
LEN_MASK = 0x3F


class MetaError(Exception):
    pass


class Word:
    def __init__(self, name, hdr, xt, flags=0):
        self.name = name
        self.hdr = hdr
        self.xt = xt
        self.flags = flags


class Meta:
    def __init__(self, prims, labels=None):
        self.mem = [0] * layout.DICT_END
        self.here = 1           # a header's link of 0 ends the chain, so none is at 0
        self.latest = 0
        self.words = {}
        self.host = {k: v for k, v in vars(layout).items() if isinstance(v, int) and not k.startswith("_")}
        for name, addr in (labels or {}).items():
            self.host[f"U.{name}"] = addr
        for name, r in layout.REGS.items():
            self.host[f"R.{name}"] = r
        for name, r in layout.JOB_REGS.items():
            self.host[f"J.{name}"] = r
        self.stack = []
        self.user_next = layout.USER_FIRST
        self.state = False
        self.cur = None
        self.ctl = []           # control-flow stack while compiling
        self.leaves = None
        self.where = "?"
        self.names = {}          # address -> word name, for the debugger
        for name, addr in prims.items():
            self.header(name)
            self.comma(addr)
            self.words[name].xt = addr

    # ---- the target's memory

    def comma(self, v):
        if self.here >= layout.DICT_END:
            raise MetaError("the dictionary is full")
        self.mem[self.here] = v & 0xFFFF
        self.here += 1

    def header(self, name, flags=0):
        if len(name) > LEN_MASK:
            raise MetaError(f"{self.where}: name too long: {name}")
        hdr = self.here
        self.comma(self.latest)
        self.comma(len(name) | flags)
        for c in name:
            self.comma(ord(c))
        self.latest = hdr
        w = Word(name, hdr, None, flags)
        self.words[name] = w
        return w

    def xt_cell(self, w):
        """The header's last cell, the xt: here + 1 for a body that follows."""
        w.xt = self.here + 1
        self.comma(w.xt)
        self.names[w.xt] = w.name

    def set_flag(self, w, flag, on=True):
        a = w.hdr + 1
        self.mem[a] = (self.mem[a] | flag) if on else (self.mem[a] & ~flag)
        w.flags = self.mem[a]

    def word(self, name):
        if name not in self.words:
            raise MetaError(f"{self.where}: no word {name}")
        return self.words[name]

    def xt(self, name):
        return self.word(name).xt

    def compile_xt(self, name):
        self.comma(self.xt(name))

    def lit(self, v):
        self.compile_xt("lit")
        self.comma(v)

    # ---- numbers

    def number(self, tok):
        """A number: [value] or [low, high] for a double, or None."""
        s = tok
        base = 10
        neg = False
        if s.startswith("-") and len(s) > 1:
            neg, s = True, s[1:]
        if s[:1] in "$%#" and len(s) > 1:
            base = {"$": 16, "%": 2, "#": 10}[s[0]]
            s = s[1:]
        if s.startswith("-") and len(s) > 1 and not neg:
            neg, s = True, s[1:]
        double = s.endswith(".") and len(s) > 1
        if double:
            s = s[:-1]
        try:
            v = int(s, base)
        except ValueError:
            return None
        if neg:
            v = -v
        if double:
            v &= 0xFFFFFFFF
            return [v & 0xFFFF, v >> 16]
        return [v & 0xFFFF]

    # ---- the source

    def compile(self, text, name="<forth>"):
        self.text = text
        self.src = name
        self.pos = 0
        self.line, self.counted = 1, 0
        while True:
            tok = self.token()
            if tok is None:
                break
            if self.state:
                self.compile_token(tok)
            else:
                self.interpret_token(tok)
        if self.state:
            raise MetaError(f"{name}: ends inside the definition of {self.cur.name}")

    def raw(self):
        """The next blank-delimited token as it is, or None at the end."""
        m = re.compile(r"\s*(\S+)").match(self.text, self.pos)
        if not m:
            return None
        self.pos = m.end()
        self.line += self.text.count("\n", self.counted, m.start(1))
        self.counted = m.start(1)
        self.where = f"{self.src}:{self.line}"
        return m.group(1)

    def token(self):
        """The next token with comments skipped, and a string word with
        its string as one: ('."', 'text')."""
        while True:
            tok = self.raw()
            if tok == "\\":
                nl = self.text.find("\n", self.pos)
                self.pos = len(self.text) if nl < 0 else nl
                continue
            if tok == "(":
                end = self.text.find(")", self.pos)
                if end < 0:
                    raise MetaError(f"{self.where}: ( without )")
                self.pos = end + 1
                continue
            if tok in ('."', 's"', 'abort"', '.('):
                close = ")" if tok == ".(" else '"'
                end = self.text.find(close, self.pos + 1)
                if end < 0:
                    raise MetaError(f"{self.where}: {tok} without its end")
                text = self.text[self.pos + 1:end]
                self.pos = end + 1
                if tok == ".(":
                    continue
                return (tok, text)
            return tok

    def next_token(self):
        tok = self.raw()
        if tok is None:
            raise MetaError(f"{self.where}: the source ends too soon")
        return tok

    def pop(self):
        if not self.stack:
            raise MetaError(f"{self.where}: the host's stack is empty")
        return self.stack.pop()

    # ---- interpreting, on the host

    def interpret_token(self, tok):
        if isinstance(tok, tuple):
            raise MetaError(f"{self.where}: {tok[0]} outside a definition")
        bin_ops = {"+": lambda a, b: a + b, "-": lambda a, b: a - b, "*": lambda a, b: a * b,
                   "/": lambda a, b: a // b, "and": lambda a, b: a & b, "or": lambda a, b: a | b,
                   "lshift": lambda a, b: a << b, "rshift": lambda a, b: a >> b}
        if tok in bin_ops:
            b, a = self.pop(), self.pop()
            self.stack.append(bin_ops[tok](a, b) & 0xFFFF)
        elif tok == "negate":
            self.stack.append(-self.pop() & 0xFFFF)
        elif tok == "invert":
            self.stack.append(~self.pop() & 0xFFFF)
        elif tok == ":":
            name = self.next_token()
            self.cur = self.header(name, HIDDEN)
            self.xt_cell(self.cur)
            self.state = True
            self.ctl = []
        elif tok == "]":
            self.state = True
        elif tok == "immediate":
            self.set_flag(self.words[self.latest_name()], IMMEDIATE)
        elif tok == "constant":
            self.constant(self.next_token(), self.pop())
        elif tok == "2constant":
            hi, lo = self.pop(), self.pop()
            w = self.header(self.next_token(), CONSTANT)
            self.xt_cell(w)
            self.lit(lo)
            self.lit(hi)
            self.compile_xt("exit")
        elif tok == "variable":
            self.variable(self.next_token(), 1)
        elif tok == "2variable":
            self.variable(self.next_token(), 2)
        elif tok == "create":
            self.create(self.next_token())
        elif tok == ",":
            self.comma(self.pop())
        elif tok == "allot":
            for _ in range(self.pop()):
                self.comma(0)
        elif tok == "here":
            self.stack.append(self.here)
        elif tok == "cells":
            pass
        elif tok == "!":
            a = self.pop()
            self.mem[a] = self.pop()
        elif tok == "user":
            name = self.next_token()
            w = self.header(name)
            self.xt_cell(w)
            self.compile_xt("(user)")
            self.comma(self.user_next)
            self.compile_xt("exit")
            self.user_next += 1
            if self.user_next > 64:
                raise MetaError(f"{self.where}: too many user variables")
        elif tok == "'":
            self.stack.append(self.xt(self.next_token()))
        elif tok in self.host:
            self.stack.append(self.host[tok] & 0xFFFF)
        elif tok in self.words and self.words[tok].flags & CONSTANT:
            xt = self.words[tok].xt
            self.stack.append(self.mem[xt + 1])
            if self.mem[xt + 2] == self.xt("lit"):
                self.stack.append(self.mem[xt + 3])
        else:
            n = self.number(tok)
            if n is None:
                raise MetaError(f"{self.where}: can't interpret {tok} while metacompiling")
            self.stack.extend(n)

    def latest_name(self):
        for name, w in self.words.items():
            if w.hdr == self.latest:
                return name
        raise MetaError("no words")

    def constant(self, name, v):
        w = self.header(name, CONSTANT)
        self.xt_cell(w)
        self.lit(v)
        self.compile_xt("exit")

    def variable(self, name, cells):
        w = self.header(name, CONSTANT)
        self.xt_cell(w)
        self.lit(self.here + 3)
        self.compile_xt("exit")
        for _ in range(cells):
            self.comma(0)

    def create(self, name):
        w = self.header(name)
        self.xt_cell(w)
        self.lit(self.here + 4)
        self.compile_xt("exit")
        self.comma(0)

    # ---- compiling a colon definition

    def compile_token(self, tok):
        if isinstance(tok, tuple):
            kind, text = tok
            self.compile_xt({'."': '(.")', 's"': '(s")', 'abort"': '(abort")'}[kind])
            self.comma(len(text))
            for c in text:
                self.comma(ord(c))
            return
        special = getattr(self, "c_" + {
            ";": "semi", "if": "if", "else": "else", "then": "then", "begin": "begin",
            "until": "until", "again": "again", "while": "while", "repeat": "repeat",
            "do": "do", "?do": "qdo", "loop": "loop", "+loop": "ploop", "leave": "leave",
            "[char]": "char", "[']": "tick", "literal": "literal", "[": "lbrac",
            "postpone": "postpone", "recurse": "recurse", "does>": "does",
        }.get(tok, "_none"), None)
        if special:
            special()
            return
        if tok in self.words:
            w = self.words[tok]
            if w.flags & CONSTANT:
                self.lit(self.mem[w.xt + 1])
                if self.mem[w.xt + 2] == self.xt("lit"):     # a 2constant
                    self.lit(self.mem[w.xt + 3])
            else:
                self.comma(w.xt)
            return
        if tok in self.host:
            self.lit(self.host[tok])
            return
        n = self.number(tok)
        if n is None:
            raise MetaError(f"{self.where}: no word {tok}")
        for v in n:
            self.lit(v)

    def c_semi(self):
        if self.ctl:
            raise MetaError(f"{self.where}: {self.cur.name} ends with its control flow open: {self.ctl}")
        self.compile_xt("exit")
        self.set_flag(self.cur, HIDDEN, False)
        self.state = False

    def branch(self, name, to=0):
        self.compile_xt(name)
        self.comma(to)
        return self.here - 1

    def c_if(self):
        self.ctl.append(("if", self.branch("0branch")))

    def c_else(self):
        kind, a = self.ctl.pop()
        if kind != "if":
            raise MetaError(f"{self.where}: else without if")
        self.ctl.append(("if", self.branch("branch")))
        self.mem[a] = self.here

    def c_then(self):
        kind, a = self.ctl.pop()
        if kind != "if":
            raise MetaError(f"{self.where}: then without if")
        self.mem[a] = self.here

    def c_begin(self):
        self.ctl.append(("begin", self.here))

    def c_until(self):
        kind, a = self.ctl.pop()
        if kind != "begin":
            raise MetaError(f"{self.where}: until without begin")
        self.branch("0branch", a)

    def c_again(self):
        kind, a = self.ctl.pop()
        if kind != "begin":
            raise MetaError(f"{self.where}: again without begin")
        self.branch("branch", a)

    def c_while(self):
        self.ctl.insert(len(self.ctl) - 1, ("if", self.branch("0branch")))

    def c_repeat(self):
        self.c_again()
        self.c_then()

    def c_do(self):
        self.compile_xt("(do)")
        self.ctl.append(("do", self.here, self.leaves))
        self.leaves = []

    def c_qdo(self):
        self.compile_xt("(?do)")
        self.ctl.append(("do", self.here + 1, self.leaves))
        self.leaves = [self.here]
        self.comma(0)

    def c_leave(self):
        if self.leaves is None:
            raise MetaError(f"{self.where}: leave outside a loop")
        self.compile_xt("unloop")
        self.leaves.append(self.branch("branch"))

    def end_loop(self, prim):
        kind, a, outer = self.ctl.pop()
        if kind != "do":
            raise MetaError(f"{self.where}: loop without do")
        self.branch(prim, a)
        for c in self.leaves:
            self.mem[c] = self.here
        self.leaves = outer

    def c_loop(self):
        self.end_loop("(loop)")

    def c_ploop(self):
        self.end_loop("(+loop)")

    def c_char(self):
        self.lit(ord(self.next_token()[0]))

    def c_tick(self):
        self.lit(self.xt(self.next_token()))

    def c_literal(self):
        self.lit(self.pop())

    def c_lbrac(self):
        self.state = False

    def c_postpone(self):
        w = self.word(self.next_token())
        if w.flags & IMMEDIATE:
            self.comma(w.xt)
        else:
            self.lit(w.xt)
            self.compile_xt(",")

    def c_recurse(self):
        self.comma(self.cur.xt)

    def c_does(self):
        self.compile_xt("(does>)")

    # ---- the end

    def finish(self, cold="cold"):
        """Set the dictionary's own variables to where it ends: `dp` and
        `latest`. Returns the image's cells."""
        for v, val in (("dp", None), ("latest", None)):
            if v not in self.words:
                raise MetaError(f"the source has no variable {v}")
        self.mem[self.mem[self.xt("dp") + 1]] = self.here
        self.mem[self.mem[self.xt("latest") + 1]] = self.latest
        self.cold = self.xt(cold)
        return self.mem[:self.here]


def metacompile(sources, prims, labels=None):
    """[(name, text)] into a Meta, finished."""
    m = Meta(prims, labels)
    for name, text in sources:
        m.compile(text, name)
    m.image = m.finish()
    return m
