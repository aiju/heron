"""SSA intermediate representation.

A Module holds functions and global data. A Function is a list of basic
blocks; the first is the entry. Every value is a 32-bit word: the IR has
no other register type (yet). Memory accesses carry their own size.

Values:
    Const(v)        a 32-bit constant (stored unsigned, printed signed)
    SymAddr(n, o)   the address of global symbol n, plus o
    Param(i)        the i-th parameter of the function
    Slot            a stack slot of the function; its value is its address
    Undef           an unspecified value (reading an uninitialised local)
    Instr           the result of an instruction

Instructions (`%x = op args`):
    binary          add sub mul divs divu rems remu and or xor shl shr sar
    compare         eq ne lt le gt ge ltu leu gtu geu      -> 0 or 1
    unary           neg not sext8 sext16 zext8 zext16 copy
    load            load.SIZE addr  (SIZE = u8 s8 u16 s16 32), volatile flag
    store           store.SIZE value, addr
    memcpy          memcpy dst, src (size, align attributes)
    call            call callee, args...  (callee is a SymAddr or a value)
    vastart         the address of the first variadic argument
    phi             phi [v, block], ...
Terminators:
    jmp B | br c, T, F (c != 0 goes to T) | ret [v] | switch v, default, cases
    | unreachable

Shifts take the count modulo 32. Division by zero is undefined.
"""

M32 = 0xFFFFFFFF

BINOPS = ("add", "sub", "mul", "divs", "divu", "rems", "remu",
          "and", "or", "xor", "shl", "shr", "sar")
CMPOPS = ("eq", "ne", "lt", "le", "gt", "ge", "ltu", "leu", "gtu", "geu")
UNOPS = ("neg", "not", "sext8", "sext16", "zext8", "zext16", "copy")
COMMUTATIVE = frozenset(("add", "mul", "and", "or", "xor", "eq", "ne"))
TERMINATORS = frozenset(("jmp", "br", "ret", "switch", "unreachable"))
PURE = frozenset(BINOPS + CMPOPS + UNOPS + ("vastart",))
SIDE_EFFECTS = frozenset(("store", "call", "memcpy")) | TERMINATORS

# compare op -> the op with its operands swapped, and its negation
CMP_SWAP = {"eq": "eq", "ne": "ne", "lt": "gt", "le": "ge", "gt": "lt", "ge": "le",
            "ltu": "gtu", "leu": "geu", "gtu": "ltu", "geu": "leu"}
CMP_NEG = {"eq": "ne", "ne": "eq", "lt": "ge", "le": "gt", "gt": "le", "ge": "lt",
           "ltu": "geu", "leu": "gtu", "gtu": "leu", "geu": "ltu"}

LOAD_KINDS = {"u8": (1, False), "s8": (1, True), "u16": (2, False), "s16": (2, True),
              "32": (4, False)}


def s32(x):
    x &= M32
    return x - (1 << 32) if x & 0x80000000 else x


# --------------------------------------------------------------------------
# Values


class Value:
    __slots__ = ()

    def is_const(self, v=None):
        return False


class Const(Value):
    __slots__ = ("value",)

    def __init__(self, value):
        self.value = value & M32

    @property
    def signed(self):
        return s32(self.value)

    def is_const(self, v=None):
        return v is None or self.value == (v & M32)

    def __eq__(self, other):
        return isinstance(other, Const) and other.value == self.value

    def __hash__(self):
        return hash(("c", self.value))

    def __str__(self):
        return str(self.signed)

    __repr__ = __str__


class SymAddr(Value):
    __slots__ = ("name", "offset")

    def __init__(self, name, offset=0):
        self.name = name
        self.offset = s32(offset)

    def __eq__(self, other):
        return isinstance(other, SymAddr) and (other.name, other.offset) == (self.name, self.offset)

    def __hash__(self):
        return hash(("s", self.name, self.offset))

    def __str__(self):
        if self.offset:
            return f"@{self.name}{self.offset:+d}"
        return f"@{self.name}"

    __repr__ = __str__


class _Undef(Value):
    __slots__ = ()

    def __str__(self):
        return "undef"

    __repr__ = __str__


Undef = _Undef()


class Param(Value):
    __slots__ = ("index", "name")

    def __init__(self, index, name=None):
        self.index = index
        self.name = name

    def __str__(self):
        return f"%{self.name or 'arg'}.{self.index}" if self.name else f"%arg{self.index}"

    __repr__ = __str__


class Slot(Value):
    """A stack slot. Its value is its address."""
    __slots__ = ("size", "align", "name", "id")

    def __init__(self, size, align, name=None, id=0):
        self.size = size
        self.align = align
        self.name = name
        self.id = id

    def __str__(self):
        return f"$slot{self.id}" + (f".{self.name}" if self.name else "")

    __repr__ = __str__


class Instr(Value):
    __slots__ = ("op", "args", "block", "id",
                 "size", "signed", "volatile", "align",   # load/store/memcpy
                 "incoming",                        # phi: blocks, parallel to args
                 "targets",                         # jmp/br/switch successors
                 "cases",                           # switch: list of case values (ints)
                 "nfixed", "void")                  # call: fixed args of a variadic callee, no result

    def __init__(self, op, args=(), **kw):
        self.op = op
        self.args = list(args)
        self.block = None
        self.id = 0
        self.size = kw.get("size", 4)
        self.signed = kw.get("signed", False)
        self.volatile = kw.get("volatile", False)
        self.align = kw.get("align", 4)
        self.incoming = kw.get("incoming", None)
        self.targets = kw.get("targets", None)
        self.cases = kw.get("cases", None)
        self.nfixed = kw.get("nfixed", None)
        self.void = kw.get("void", False)

    @property
    def is_terminator(self):
        return self.op in TERMINATORS

    @property
    def has_value(self):
        if self.op in ("store", "memcpy") or self.op in TERMINATORS:
            return False
        if self.op == "call":
            return not self.void
        return True

    @property
    def has_side_effects(self):
        return self.op in SIDE_EFFECTS or (self.op == "load" and self.volatile)

    def load_kind(self):
        return f"{'s' if self.signed else 'u'}{8 * self.size}" if self.size < 4 else "32"

    def __str__(self):
        return f"%{self.id}"

    __repr__ = __str__


# --------------------------------------------------------------------------
# Blocks, functions, modules


class Block:
    __slots__ = ("id", "hint", "instrs", "preds", "func", "loop_depth")

    def __init__(self, func, id, hint=""):
        self.func = func
        self.id = id
        self.hint = hint
        self.instrs = []
        self.preds = []
        self.loop_depth = 0

    @property
    def name(self):
        return f"b{self.id}" + (f".{self.hint}" if self.hint else "")

    @property
    def terminator(self):
        if self.instrs and self.instrs[-1].is_terminator:
            return self.instrs[-1]
        return None

    @property
    def succs(self):
        t = self.terminator
        return list(t.targets) if t is not None and t.targets else []

    def phis(self):
        out = []
        for i in self.instrs:
            if i.op != "phi":
                break
            out.append(i)
        return out

    def first_non_phi(self):
        for n, i in enumerate(self.instrs):
            if i.op != "phi":
                return n
        return len(self.instrs)

    def insert(self, pos, instr):
        instr.block = self
        self.instrs.insert(pos, instr)

    def append(self, instr):
        instr.block = self
        self.instrs.append(instr)

    def __str__(self):
        return self.name

    __repr__ = __str__


class Function:
    def __init__(self, name, nparams, variadic=False, returns=True, static=False, param_names=None):
        self.name = name
        names = param_names or [None] * nparams
        self.params = [Param(i, names[i]) for i in range(nparams)]
        self.variadic = variadic
        self.returns = returns
        self.static = static
        self.blocks = []
        self.slots = []
        self._next_block = 0
        self._next_slot = 0

    @property
    def entry(self):
        return self.blocks[0]

    def new_block(self, hint=""):
        b = Block(self, self._next_block, hint)
        self._next_block += 1
        self.blocks.append(b)
        return b

    def new_slot(self, size, align, name=None):
        s = Slot(size, align, name, self._next_slot)
        self._next_slot += 1
        self.slots.append(s)
        return s

    def instructions(self):
        for b in self.blocks:
            yield from b.instrs

    def compute_preds(self):
        for b in self.blocks:
            b.preds = []
        for b in self.blocks:
            for s in b.succs:
                if b not in s.preds:
                    s.preds.append(b)

    def renumber(self):
        n = 0
        for b in self.blocks:
            for i in b.instrs:
                if i.has_value:
                    n += 1
                    i.id = n
                else:
                    i.id = 0

    def use_counts(self):
        """value -> number of uses (by instruction operands, counting phis)."""
        counts = {}
        for i in self.instructions():
            for a in i.args:
                if isinstance(a, (Instr, Param, Slot)):
                    counts[a] = counts.get(a, 0) + 1
        return counts

    def users(self):
        """value -> list of instructions that use it."""
        out = {}
        for i in self.instructions():
            for a in i.args:
                if isinstance(a, (Instr, Param, Slot)):
                    lst = out.setdefault(a, [])
                    if not lst or lst[-1] is not i:
                        lst.append(i)
        return out

    def replace_uses(self, mapping):
        """Replace operands everywhere by mapping (old value -> new value),
        following chains."""
        if not mapping:
            return

        def res(v):
            seen = 0
            while v in mapping:
                v = mapping[v]
                seen += 1
                if seen > 10000:
                    raise RuntimeError("cycle in replacement map")
            return v
        for i in self.instructions():
            i.args = [res(a) if isinstance(a, (Instr, Param, Slot)) else a for a in i.args]

    def __str__(self):
        return format_function(self)


class GlobalData:
    """A global object. items: list of
        ('bytes', bytes) | ('zero', n) | ('byte', v) | ('half', v) | ('word', v)
    where v is an int or a SymAddr (for 'word')."""

    def __init__(self, name, size, align, items=None, static=False, readonly=False):
        self.name = name
        self.size = size
        self.align = align
        self.items = items if items is not None else [("zero", size)]
        self.static = static
        self.readonly = readonly


class Module:
    def __init__(self):
        self.functions = []
        self.data = []

    def function(self, name):
        for f in self.functions:
            if f.name == name:
                return f
        return None

    def __str__(self):
        out = []
        for d in self.data:
            out.append(format_data(d))
        for f in self.functions:
            out.append(format_function(f))
        return "\n".join(out)


# --------------------------------------------------------------------------
# Builder


class Builder:
    """Appends instructions to a current block."""

    def __init__(self, func):
        self.func = func
        self.block = None

    def set_block(self, b):
        self.block = b

    @property
    def terminated(self):
        return self.block is None or self.block.terminator is not None

    def emit(self, op, args=(), **kw):
        i = Instr(op, args, **kw)
        self.block.append(i)
        return i

    def binop(self, op, a, b):
        return self.emit(op, [a, b])

    def unop(self, op, a):
        return self.emit(op, [a])

    def load(self, addr, size=4, signed=False, volatile=False):
        return self.emit("load", [addr], size=size, signed=signed and size < 4, volatile=volatile)

    def store(self, value, addr, size=4, volatile=False):
        return self.emit("store", [value, addr], size=size, volatile=volatile)

    def memcpy(self, dst, src, size, align):
        return self.emit("memcpy", [dst, src], size=size, align=align)

    def call(self, callee, args, void=False, nfixed=None):
        return self.emit("call", [callee] + list(args), void=void, nfixed=nfixed)

    def phi(self, block=None):
        b = block or self.block
        i = Instr("phi", [], incoming=[])
        b.insert(b.first_non_phi(), i)
        return i

    def jmp(self, target):
        return self.emit("jmp", [], targets=[target])

    def br(self, cond, t, f):
        return self.emit("br", [cond], targets=[t, f])

    def ret(self, value=None):
        return self.emit("ret", [] if value is None else [value])

    def switch(self, value, default, cases):
        """cases: list of (int, block)."""
        return self.emit("switch", [value], targets=[default] + [b for _, b in cases],
                         cases=[c & M32 for c, _ in cases])

    def unreachable(self):
        return self.emit("unreachable", [], targets=[])


# --------------------------------------------------------------------------
# Printing


def _fmt_val(v):
    return str(v)


def format_instr(i):
    a = ", ".join(_fmt_val(x) for x in i.args)
    if i.op == "phi":
        a = ", ".join(f"[{_fmt_val(v)}, {b.name}]" for v, b in zip(i.args, i.incoming))
        return f"%{i.id} = phi {a}"
    if i.op == "load":
        return f"%{i.id} = load.{i.load_kind()}{' volatile' if i.volatile else ''} {a}"
    if i.op == "store":
        return f"store.{8 * i.size}{' volatile' if i.volatile else ''} {a}"
    if i.op == "memcpy":
        return f"memcpy {a}, size {i.size}, align {i.align}"
    if i.op == "jmp":
        return f"jmp {i.targets[0].name}"
    if i.op == "br":
        return f"br {a}, {i.targets[0].name}, {i.targets[1].name}"
    if i.op == "switch":
        cs = ", ".join(f"{s32(c)}: {b.name}" for c, b in zip(i.cases, i.targets[1:]))
        return f"switch {a}, default {i.targets[0].name} [{cs}]"
    if i.op in ("ret", "unreachable"):
        return f"{i.op} {a}".rstrip()
    if i.op == "call":
        extra = f" (variadic after {i.nfixed})" if i.nfixed is not None else ""
        args = ", ".join(_fmt_val(x) for x in i.args[1:])
        call = f"call {_fmt_val(i.args[0])}({args}){extra}"
        return call if i.void else f"%{i.id} = {call}"
    return f"%{i.id} = {i.op} {a}".rstrip()


def format_function(f):
    f.renumber()
    params = ", ".join(str(p) for p in f.params) + (", ..." if f.variadic else "")
    head = f"{'static ' if f.static else ''}func {f.name}({params})"
    out = [head + " {"]
    for s in f.slots:
        out.append(f"  {s} = slot size {s.size}, align {s.align}")
    for b in f.blocks:
        preds = ", ".join(p.name for p in b.preds)
        out.append(f"{b.name}:" + (f"                ; preds {preds}" if preds else ""))
        for i in b.instrs:
            out.append("  " + format_instr(i))
    out.append("}")
    return "\n".join(out) + "\n"


def format_data(d):
    items = []
    for it in d.items:
        if it[0] == "bytes":
            items.append(repr(bytes(it[1])))
        else:
            items.append(f"{it[0]} {it[1]}")
    flags = ("static " if d.static else "") + ("const " if d.readonly else "")
    return f"{flags}data @{d.name} size {d.size}, align {d.align} = {{{'; '.join(items)}}}"
