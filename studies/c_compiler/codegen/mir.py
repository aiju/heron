"""Machine IR: target instructions on virtual or physical registers.

An MInstr is a mnemonic with operands for printing, plus explicit lists of
the registers it defines and uses (the target's instruction selector fills
those in, including implicit ones like a call's clobbers). The register
allocator only looks at defs and uses; COPY instructions are the moves it
tries to coalesce away.
"""


class Reg:
    __slots__ = ()
    is_phys = False


class PReg(Reg):
    __slots__ = ("n",)
    is_phys = True

    def __init__(self, n):
        self.n = n

    def __repr__(self):
        return "sp" if self.n == 15 else f"r{self.n}"


PHYS = [PReg(n) for n in range(16)]
R0 = PHYS[0]
SP = PHYS[15]


class VReg(Reg):
    __slots__ = ("id", "no_spill", "remat")
    _next = 0

    def __init__(self):
        VReg._next += 1
        self.id = VReg._next
        self.no_spill = False
        self.remat = None          # an MInstr that can recompute it (a constant load)

    def __repr__(self):
        return f"v{self.id}"


class Imm:
    """#value, where value is an int or a symbol expression string."""
    __slots__ = ("value",)

    def __init__(self, value):
        self.value = value


class Frame:
    """A stack offset that's only known after register allocation.
    kind: 'local' (an IR slot), 'spill' (n), 'in' (incoming stack argument
    n), 'out' (outgoing argument n)."""
    __slots__ = ("kind", "key")

    def __init__(self, kind, key):
        self.kind = kind
        self.key = key


class Mem:
    """A memory operand. base and index are registers (or None); disp is an
    int; sym a symbol name added to disp; frame a Frame added to disp (base
    is then sp). size 1, 2 or 4 (draft 1b prints it, 1a puts it in the
    mnemonic)."""
    __slots__ = ("base", "index", "scale", "disp", "sym", "frame", "size", "postinc")

    def __init__(self, base=None, disp=0, sym=None, index=None, scale=1, frame=None, size=4,
                 postinc=False):
        self.base = base
        self.index = index
        self.scale = scale
        self.disp = disp
        self.sym = sym
        self.frame = frame
        self.size = size
        self.postinc = postinc

    def regs(self):
        out = []
        if self.base is not None:
            out.append(self.base)
        if self.index is not None:
            out.append(self.index)
        return out

    def copy(self, **kw):
        m = Mem(self.base, self.disp, self.sym, self.index, self.scale, self.frame, self.size,
                self.postinc)
        for k, v in kw.items():
            setattr(m, k, v)
        return m


class Label:
    """A branch target: a block, or a global symbol name."""
    __slots__ = ("target",)

    def __init__(self, target):
        self.target = target


class MInstr:
    __slots__ = ("op", "ops", "defs", "uses", "cond", "targets", "flags", "comment", "remat_of")

    def __init__(self, op, ops=(), defs=(), uses=(), cond=None, targets=None, flags=None):
        self.op = op            # mnemonic, or COPY / JMP / BCC / RET / CALL ...
        self.ops = list(ops)
        self.defs = list(defs)
        self.uses = list(uses)
        self.cond = cond        # BCC / SET: the condition name
        self.targets = targets  # control flow: list of MBlocks
        self.flags = flags      # 'nz': sets N and Z from its first operand (for the peepholes)
        self.comment = None
        self.remat_of = None

    @property
    def is_copy(self):
        return self.op == "COPY"

    def replace_reg(self, old, new, defs=True, uses=True):
        def sub(x):
            if x is old:
                return new
            if isinstance(x, Mem):
                if x.base is old or x.index is old:
                    m = x.copy()
                    if m.base is old:
                        m.base = new
                    if m.index is old:
                        m.index = new
                    return m
            return x
        self.ops = [sub(x) for x in self.ops]
        if defs:
            self.defs = [new if r is old else r for r in self.defs]
        if uses:
            self.uses = [new if r is old else r for r in self.uses]

    def __repr__(self):
        return f"{self.op} {self.ops} d={self.defs} u={self.uses}"


class MBlock:
    def __init__(self, ir_block, label):
        self.ir = ir_block
        self.label = label
        self.instrs = []
        self.succs = []
        self.preds = []
        self.loop_depth = ir_block.loop_depth if ir_block is not None else 0

    def __repr__(self):
        return self.label


class MFunction:
    def __init__(self, name, ir_func):
        self.name = name
        self.ir = ir_func
        self.blocks = []
        self.slots = {}         # IR Slot -> offset from the start of the locals area
        self.locals_size = 0
        self.out_args = 0       # words of outgoing stack arguments
        self.spills = 0         # spill slots (words)
        self.saved = None       # (first, last) callee-saved registers, or None
        self.frame_size = 0
        self.consts = []        # (label, list of block targets): jump tables
        self.assign = {}        # VReg -> PReg after allocation
        self.leaf = True

    def compute_preds(self):
        for b in self.blocks:
            b.preds = []
        for b in self.blocks:
            for s in b.succs:
                if b not in s.preds:
                    s.preds.append(b)

    # ---- frame -----------------------------------------------------------

    def layout_frame(self, nsaved):
        """Called after register allocation: from sp up, outgoing arguments,
        locals, spill slots; then the registers SAVE pushed, the return
        address and the caller's stack arguments."""
        self.locals_base = 4 * self.out_args
        self.spill_base = self.locals_base + self.locals_size
        size = self.spill_base + 4 * self.spills
        self.frame_size = (size + 3) & ~3
        self.nsaved = nsaved

    def frame_offset(self, fr):
        if fr.kind == "out":
            return 4 * fr.key
        if fr.kind == "local":
            return self.locals_base + self.slots[fr.key]
        if fr.kind == "spill":
            return self.spill_base + 4 * fr.key
        if fr.kind == "in":
            return self.frame_size + 4 * self.nsaved + 4 + 4 * fr.key
        raise ValueError(fr.kind)

    def local_offset_known(self, slot):
        """The offset of an IR slot from sp, which is fixed before register
        allocation (spill slots go above the locals)."""
        return 4 * self.out_args + self.slots[slot]


# --------------------------------------------------------------------------
# Liveness


def is_alloc(r):
    """Registers the allocator cares about: virtual ones and r1-r14."""
    return not r.is_phys or 1 <= r.n <= 14


def liveness(mf):
    """Returns (live_in, live_out) dicts of sets per block."""
    mf.compute_preds()
    use, defs = {}, {}
    for b in mf.blocks:
        u, d = set(), set()
        for i in b.instrs:
            for r in i.uses:
                if is_alloc(r) and r not in d:
                    u.add(r)
            for r in i.defs:
                if is_alloc(r):
                    d.add(r)
        use[b], defs[b] = u, d
    live_in = {b: set() for b in mf.blocks}
    live_out = {b: set() for b in mf.blocks}
    changed = True
    order = list(reversed(mf.blocks))
    while changed:
        changed = False
        for b in order:
            out = set()
            for s in b.succs:
                out |= live_in[s]
            inn = use[b] | (out - defs[b])
            if out != live_out[b] or inn != live_in[b]:
                live_out[b] = out
                live_in[b] = inn
                changed = True
    return live_in, live_out
