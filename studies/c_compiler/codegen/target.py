"""The parts of code generation that every target shares: walking the IR,
deciding which values can be folded into the instructions that use them,
the calling convention, phi copies, switch lowering, the stack frame, the
peepholes and the assembly text. codegen.v1a, v1b and v2 subclass Target
with their instruction selection.

Calling convention (draft 1's, RFC 0004): arguments in r1-r4, the rest on the
stack; result in r1; r1-r7 caller-saved, r8-r14 callee-saved; sp is r15.
On draft 1 r0 reads as zero; on draft 2 it's a general register, and
caller-saved. Calls to variadic functions pass every argument on the stack.
The caller reserves the outgoing argument area at the bottom of its frame,
so sp doesn't move inside a function body.

With a link register (LINK: r7 on draft 2), calls leave the return
address in it instead of pushing it. The allocator treats it like a
callee-saved register: a function that calls, or that needs the register,
saves it with the others (SAVE r7-rN) or pushes it; a leaf that doesn't
returns through it.
"""

from heron.studies.c_compiler.ir import ir as I
from heron.studies.c_compiler.ir.ir import Instr, Const, SymAddr, Param, Slot, Undef, PURE, s32
from heron.studies.c_compiler.ir.cfg import compute_loop_depth, reverse_postorder
from .mir import PHYS, R0, SP, VReg, Imm, Mem, Frame, Label, MInstr, MBlock, MFunction, liveness
from .regalloc import Allocator

ARG_REGS = PHYS[1:5]

COND = {"eq": "EQ", "ne": "NE", "lt": "LT", "le": "LE", "gt": "GT", "ge": "GE",
        "ltu": "LO", "leu": "LS", "gtu": "HI", "geu": "HS"}
INVERT = {"EQ": "NE", "NE": "EQ", "LT": "GE", "GE": "LT", "LE": "GT", "GT": "LE",
          "LO": "HS", "HS": "LO", "LS": "HI", "HI": "LS", "MI": "PL", "PL": "MI",
          "VS": "VC", "VC": "VS"}
SWAP = {"EQ": "EQ", "NE": "NE", "LT": "GT", "GT": "LT", "LE": "GE", "GE": "LE",
        "LO": "HI", "HI": "LO", "LS": "HS", "HS": "LS"}


def split_critical_edges(func):
    """Put a block on every edge from a block with several successors to a
    block with phis and several predecessors (the phi copies need somewhere
    to go), right after its predecessor (so the copies in it don't need an
    extra jump)."""
    func.compute_preds()
    order = []
    for b in list(func.blocks):
        order.append(b)
        t = b.terminator
        if t is None or not t.targets or len(set(t.targets)) < 2:
            continue
        seen = {}
        for n, s in enumerate(t.targets):
            if len(s.preds) < 2 or not s.phis():
                continue
            if s in seen:
                t.targets[n] = seen[s]
                continue
            mid = func.new_block("edge")
            func.blocks.remove(mid)
            mid.append(Instr("jmp", [], targets=[s]))
            seen[s] = mid
            t.targets[n] = mid
            for p in s.phis():
                p.incoming = [mid if blk is b else blk for blk in p.incoming]
            order.append(mid)
    func.blocks = order
    func.compute_preds()


class Target:
    FOLD_LOADS = True       # loads can be operands of other instructions
    ALLOC_ORDER = PHYS[1:15]
    CALLER_SAVED = PHYS[1:8]     # what a call clobbers
    ZERO = R0               # a register that reads as zero, or None
    COUNT_DOWN = False      # loops that only count, counted down to zero (ir.passes.count_down)
    LINK = None             # the link register, if calls leave the return address in one
    SMALL_ADD = (-16, 15)        # add constants that fit the one-parcel form

    def __init__(self, symname=None, near=None):
        self.symname = symname or (lambda n: "_" + n)
        self.near = near or (lambda name, off=0: False)

    # ======================================================================
    # Driver

    def compile_function(self, f):
        split_critical_edges(f)
        compute_loop_depth(f)
        self.f = f
        mf = self.mf = MFunction(self.symname(f.name), f, self.ALLOC_ORDER)
        # locals: fixed offsets (spill slots go above them)
        off = 0
        for s in f.slots:
            a = max(1, min(s.align, 4))
            off = (off + a - 1) // a * a
            mf.slots[s] = off
            off += s.size
        mf.locals_size = (off + 3) & ~3
        # outgoing stack arguments
        for i in f.instructions():
            if i.op == "call":
                n = len(i.args) - 1
                if i.nfixed is not None:
                    mf.out_args = max(mf.out_args, n)
                elif n > 4:
                    mf.out_args = max(mf.out_args, n - 4)
                mf.leaf = False
            elif i.op == "memcpy" and i.size > self.INLINE_COPY:
                mf.leaf = False
                mf.out_args = max(mf.out_args, 0)
        self.isel()
        Allocator(mf, self).run()
        self.finish()
        return self.emit_text()

    # ======================================================================
    # Instruction selection: framework

    def isel(self):
        f, mf = self.f, self.mf
        rpo = reverse_postorder(f)
        self.users = f.users()
        self.ucount = f.use_counts()
        self.vregs = {}
        self.mblocks = {}
        for b in f.blocks:
            mb = MBlock(b, f".b{b.id}")
            self.mblocks[b] = mb
        mf.blocks = [self.mblocks[b] for b in f.blocks]
        for b in f.blocks:
            for p in b.phis():
                self.vregs[p] = VReg()
        # parameters
        self.blk = self.mblocks[f.entry]
        nreg = 0 if f.variadic else 4
        for k, p in enumerate(f.params):
            v = VReg()
            self.vregs[p] = v
            if k < nreg:
                self.emit("COPY", [v, ARG_REGS[k]], defs=[v], uses=[ARG_REGS[k]])
            else:
                self.load_word(v, Mem(SP, frame=Frame("in", k - nreg)))
        for b in rpo:
            self.select_block(b)
        self.compute_succs()

    def compute_succs(self):
        for mb in self.mf.blocks:
            succs = []
            for i in mb.instrs:
                for t in i.targets or ():
                    if t not in succs:
                        succs.append(t)
            mb.succs = succs

    def select_block(self, b):
        self.blk = self.mblocks[b]
        self.cur = b
        self.pos = {i: n for n, i in enumerate(b.instrs)}
        self.analyse_block(b)
        for i in b.instrs:
            if i.op == "phi" or i in self.foldable or i in self.absorbed:
                continue
            if i in self.vregs and i.op != "phi":
                continue
            self.select(i)

    def analyse_block(self, b):
        """Find the values that can be computed where they're used: one use,
        in this block, and (for loads) no store, call or volatile access
        between the load and where its user ends up being emitted."""
        self.foldable = set()
        self.absorbed = {}       # add instruction -> the memory access that does it
        self.postinc = {}        # memory access -> add instruction
        instrs = b.instrs
        side = [n for n, i in enumerate(instrs)
                if i.op in ("store", "call", "memcpy") or (i.op == "load" and i.volatile)]
        ep = {}
        for n in range(len(instrs) - 1, -1, -1):
            i = instrs[n]
            ep[i] = n
            if not i.has_value or i.op in ("phi", "call"):
                continue
            us = self.users.get(i, [])
            if self.ucount.get(i, 0) != 1 or len(us) != 1:
                continue
            u = us[0]
            if u.block is not b or u.op == "phi":
                continue
            end = ep[u]
            if i.op == "load":
                if not self.FOLD_LOADS or any(n < k < end for k in side):
                    continue
            elif i.op not in PURE:
                continue
            if i.op == "vastart":
                continue
            self.foldable.add(i)
            ep[i] = end
        # base + constant used only as the address of a few accesses in this
        # block: fold it into each of them rather than computing it once
        for n, i in enumerate(instrs):
            if (i.op != "add" or i in self.foldable or not isinstance(i.args[1], Const)
                    or isinstance(i.args[0], Instr) and i.args[0] in self.foldable):
                continue
            us = self.users.get(i, [])
            if not 2 <= self.ucount.get(i, 0) <= self.MULTI_FOLD or len(us) != self.ucount[i]:
                continue
            if all(u.block is b and ((u.op == "load" and u.args[0] is i) or
                                     (u.op == "store" and u.args[1] is i and u.args[0] is not i))
                   for u in us):
                self.foldable.add(i)
                ep[i] = min(ep[u] for u in us)
        self.ep = ep
        self.find_postinc(b)

    MULTI_FOLD = 3

    def find_postinc(self, b):
        """Overridden by targets with auto-increment addressing."""

    def select(self, i):
        if i.op in I.BINOPS:
            return self.sel_binop(i)
        if i.op in I.CMPOPS:
            return self.sel_setcc(i)
        if i.op in I.UNOPS:
            return self.sel_unop(i)
        m = getattr(self, "sel_" + i.op)
        return m(i)

    def emit(self, op, ops=(), defs=(), uses=(), **kw):
        """Append an instruction; the registers of memory operands are added
        to its uses (and an auto-incremented base to its defs too)."""
        defs = list(defs)
        uses = list(uses)
        for x in ops:
            if isinstance(x, Mem):
                uses.extend(x.regs())
                if x.postinc:
                    defs.append(x.base)
        mi = MInstr(op, ops, defs, uses, **kw)
        self.blk.instrs.append(mi)
        return mi

    def def_reg(self, i):
        v = self.vregs.get(i)
        if v is None:
            v = self.vregs[i] = VReg()
        return v

    def reg(self, v):
        """A register holding IR value v (emitting it here if it's a folded
        value that a pattern didn't absorb)."""
        if isinstance(v, (Instr, Param)):
            r = self.vregs.get(v)
            if r is not None:
                return r
            if isinstance(v, Instr) and v in self.foldable:
                self.select(v)
                return self.vregs[v]
            if isinstance(v, Instr) and v in self.absorbed:
                raise AssertionError("use of an absorbed increment before its access")
            raise AssertionError(f"value {v} ({getattr(v, 'op', '?')}) used before it's computed")
        if isinstance(v, Const):
            if v.value == 0 and self.ZERO is not None:
                return self.ZERO
            return self.const_reg(v.value)
        if isinstance(v, SymAddr):
            return self.const_reg(self.sym_expr(v))
        if isinstance(v, Slot):
            t = VReg()
            self.emit("LEA", [t, Mem(SP, frame=Frame("local", v))], defs=[t])
            return t
        if v is Undef:
            return self.ZERO if self.ZERO is not None else self.const_reg(0)
        raise AssertionError(v)

    def const_reg(self, value):
        t = VReg()
        mi = self.emit("MOV", [t, Imm(value)], defs=[t], flags="nz")
        t.remat = mi
        mi.remat_of = t
        return t

    def sym_expr(self, s):
        name = self.symname(s.name)
        if s.offset:
            return f"{name}{s.offset:+d}"
        return name

    def copy(self, dst, src):
        if dst is src:
            return
        self.emit("COPY", [dst, src], defs=[dst], uses=[src], flags="nz")

    def is_folded(self, v, op=None):
        return isinstance(v, Instr) and v in self.foldable and (op is None or v.op in op)

    def divmod_partner(self, i):
        """The quotient for a remainder (or the reverse) of the same operands
        in this block, not computed yet: one divide gives both."""
        want = {"divs": "rems", "rems": "divs", "divu": "remu", "remu": "divu"}[i.op]
        for j in self.cur.instrs:
            if j.op == want and j.args[0] is i.args[0] and j.args[1] is i.args[1] \
                    and j not in self.vregs:
                return j
        return None

    def prefer_second(self, a, b, i):
        """For a commutative two-address operation on a and b: should the
        result start as a copy of b rather than a? Yes if only b dies here
        (the copy then coalesces away), or if both do and b was computed
        later (it's likelier to sit in the register the result wants)."""
        # an accumulator (x = x + y around a loop): start from the phi the
        # result goes back into, so phi, operand and result share a register
        for u in self.users.get(i, ()):
            if u.op == "phi":
                if u is a:
                    return False
                if u is b:
                    return True
        da, db = self.dies_here(a, i), self.dies_here(b, i)
        if da != db:
            return db
        pa = self.pos.get(a, -1) if isinstance(a, Instr) else -1
        pb = self.pos.get(b, -1) if isinstance(b, Instr) else -1
        return db and pb > pa

    def dies_here(self, v, i):
        """True if instruction i is the last use of v (all uses in this
        block, i the last of them)."""
        if not isinstance(v, (Instr, Param)):
            return True
        us = self.users.get(v, [])
        if any(u.block is not self.cur or u.op == "phi" for u in us):
            return False
        p = self.ep.get(i, self.pos.get(i, 0))
        return all(self.ep.get(u, self.pos.get(u, 0)) <= p for u in us)

    # ======================================================================
    # Control flow

    def sel_jmp(self, i):
        target = i.targets[0]
        self.phi_copies(self.cur, target)
        self.emit("JMP", [Label(self.mblocks[target])], targets=[self.mblocks[target]])

    def phi_copies(self, pred, succ):
        """Parallel copy of succ's phi arguments for the edge from pred."""
        moves = []
        consts = []
        for p in succ.phis():
            v = p.args[p.incoming.index(pred)]
            dst = self.vregs[p]
            if v is Undef:
                continue
            if isinstance(v, (Instr, Param)):
                src = self.reg(v)
                if src is not dst:
                    moves.append([dst, src])
            else:
                consts.append((dst, v))
        while moves:
            srcs = {id(s) for _, s in moves}
            ready = [m for m in moves if id(m[0]) not in srcs]
            if ready:
                d, s = ready[0]
                self.copy(d, s)
                moves.remove(ready[0])
                continue
            # a cycle: save one destination's current value first
            d, s = moves[0]
            t = VReg()
            self.copy(t, d)
            for m in moves:
                if m[1] is d:
                    m[1] = t
        for d, v in consts:
            self.load_value(d, v)

    def sel_br(self, i):
        t, f = i.targets
        c = i.args[0]
        mt, mf_ = self.mblocks[t], self.mblocks[f]
        if t is f:
            self.emit("JMP", [Label(mt)], targets=[mt])
            return
        if isinstance(c, (Const, SymAddr)):
            dest = mt if (not isinstance(c, Const) or c.value) else mf_
            self.emit("JMP", [Label(dest)], targets=[dest])
            return
        cc = self.condition(c)
        self.emit("BCC", [Label(mt)], cond=cc, targets=[mt])
        self.emit("JMP", [Label(mf_)], targets=[mf_])

    def condition(self, c):
        """Set the flags for a branch on value c != 0; returns the condition."""
        if self.is_folded(c, I.CMPOPS):
            return self.compare(c.op, c.args[0], c.args[1])
        if self.is_folded(c, ("and",)):
            return self.test(c.args[0], c.args[1])
        r = self.reg(c)
        self.emit("CMP", [r, Imm(0)], uses=[r], flags="cmp")
        return "NE"

    def sel_setcc(self, i):
        cc = self.compare(i.op, i.args[0], i.args[1])
        d = self.def_reg(i)
        self.emit("SET" + cc, [d], defs=[d])

    def sel_ret(self, i):
        uses = []
        if i.args and self.f.returns:
            v = i.args[0]
            if v is not Undef:
                self.load_value(PHYS[1], v)
            uses = [PHYS[1]]
        self.emit("RET", [], uses=uses)

    def sel_unreachable(self, i):
        self.emit("HALT", [])

    def sel_switch(self, i):
        v = i.args[0]
        default = self.mblocks[i.targets[0]]
        cases = sorted(zip([s32(c) for c in i.cases], [self.mblocks[t] for t in i.targets[1:]]))
        r = self.reg(v)
        if not cases:
            self.emit("JMP", [Label(default)], targets=[default])
            return
        lo, hi = cases[0][0], cases[-1][0]
        span = hi - lo + 1
        if len(cases) >= 4 and span <= 3 * len(cases) and span <= 1024:
            table = [default] * span
            for c, blk in cases:
                table[c - lo] = blk
            label = f"{self.mf.name}_jt{len(self.mf.consts)}"
            self.mf.consts.append((label, table))
            self.jump_table(r, lo, span, label, default, table)
            return
        self.switch_tree(r, cases, default)

    def switch_tree(self, r, cases, default):
        if len(cases) <= 4:
            for c, blk in cases:
                self.emit("CMP", [r, Imm(c)], uses=[r], flags="cmp")
                self.emit("BCC", [Label(blk)], cond="EQ", targets=[blk])
            self.emit("JMP", [Label(default)], targets=[default])
            return
        mid = len(cases) // 2
        c, blk = cases[mid]
        hi_blk = MBlock(None, self.new_label())
        hi_blk.loop_depth = self.blk.loop_depth
        self.mf.blocks.insert(self.mf.blocks.index(self.blk) + 1, hi_blk)
        self.emit("CMP", [r, Imm(c)], uses=[r], flags="cmp")
        self.emit("BCC", [Label(blk)], cond="EQ", targets=[blk])
        self.emit("BCC", [Label(hi_blk)], cond="GT", targets=[hi_blk])
        lo_blk = MBlock(None, self.new_label())
        lo_blk.loop_depth = self.blk.loop_depth
        self.mf.blocks.insert(self.mf.blocks.index(hi_blk), lo_blk)
        self.emit("JMP", [Label(lo_blk)], targets=[lo_blk])
        cur = self.blk
        self.blk = lo_blk
        self.switch_tree(r, cases[:mid], default)
        self.blk = hi_blk
        self.switch_tree(r, cases[mid + 1:], default)
        self.blk = cur

    # ======================================================================
    # Calls

    def sel_call(self, i):
        callee = i.args[0]
        args = i.args[1:]
        nreg = 0 if i.nfixed is not None else 4
        regs = []
        for k, a in enumerate(args):
            if k < nreg:
                regs.append(self.reg(a))
            else:
                self.store_word(a, Mem(SP, frame=Frame("out", k - nreg)))
        target = self.call_target(callee)
        uses = []
        for k, r in enumerate(regs):
            self.copy(ARG_REGS[k], r)
            uses.append(ARG_REGS[k])
        self.emit_call(target, uses)
        if len(args) <= nreg:
            self.blk.instrs[-1].comment = "tail-ok"
        if not i.void:
            d = self.def_reg(i)
            self.copy(d, PHYS[1])

    def call_target(self, callee):
        if isinstance(callee, SymAddr) and callee.offset == 0:
            return Label(self.symname(callee.name))
        return self.reg(callee)

    def emit_call(self, target, uses):
        if isinstance(target, Label):
            self.emit("BSR", [target], defs=list(self.CALLER_SAVED), uses=uses)
        else:
            self.emit("CALL", [target], defs=list(self.CALLER_SAVED), uses=uses + [target])

    def new_label(self):
        self.label_count = getattr(self, "label_count", 0) + 1
        return f".s{self.label_count}"

    def call_runtime(self, name, args, result=None):
        for k, a in enumerate(args):
            self.copy(ARG_REGS[k], a)
        self.emit("BSR", [Label(self.symname(name))], defs=list(self.CALLER_SAVED),
                  uses=list(ARG_REGS[:len(args)]))
        if result is not None:
            self.copy(result, PHYS[1])

    def sel_vastart(self, i):
        d = self.def_reg(i)
        self.emit("LEA", [d, Mem(SP, frame=Frame("in", len(self.f.params)))], defs=[d])

    # ======================================================================
    # Block copies

    INLINE_COPY = 64

    def sel_memcpy(self, i):
        dst, src = i.args
        size, align = i.size, i.align
        if size > self.INLINE_COPY:
            self.call_runtime("memcpy", [self.reg(dst), self.reg(src), self.reg(Const(size))])
            return
        self.inline_copy(self.reg(dst), self.reg(src), size, align)

    # ======================================================================
    # After allocation

    def finish(self):
        mf = self.mf
        assign = mf.assign
        for b in mf.blocks:
            for i in b.instrs:
                for r in set(i.defs + i.uses):
                    if isinstance(r, VReg):
                        i.replace_reg(r, assign[r])
                for x in i.ops:
                    if isinstance(x, Mem):
                        for r in x.regs():
                            assert r.is_phys
        used = set()
        for b in mf.blocks:
            for i in b.instrs:
                if i.op in ("BSR", "CALL"):
                    continue
                for r in i.defs:
                    if r.is_phys and 8 <= r.n <= 14:
                        used.add(r.n)
                    if r is self.LINK:
                        mf.link_used = True
        mf.saved = (min(used), max(used)) if used else None
        nsaved = mf.saved[1] - mf.saved[0] + 1 if mf.saved else 0
        mf.layout_frame(nsaved)
        for b in mf.blocks:
            b.instrs = [i for i in b.instrs if not (i.is_copy and i.ops[0] is i.ops[1])]
        self.peephole()
        self.thread_jumps()
        self.tail_calls()
        if self.LINK is not None:
            # a function whose only calls are tail calls is a leaf: the
            # link register survives until the jump
            mf.leaf = mf.leaf or not any(i.op in ("BSR", "CALL") for b in mf.blocks
                                         for i in b.instrs)
            # the return address stays on the stack (in the saved link
            # register) unless this is a leaf that leaves the register alone
            mf.ret_words = int(self.saves_link())
            if mf.saved and self.saves_link():
                mf.saved = (self.LINK.n + 1, mf.saved[1])     # SAVE r7-rN takes them all
                mf.nsaved = mf.saved[1] - mf.saved[0] + 1

    def tail_calls(self):
        """A call followed by a return becomes a jump (TAIL), unless the
        callee might see this frame's locals or takes stack arguments."""
        if self.mf.locals_size:
            return
        for b in self.mf.blocks:
            out = []
            for i in b.instrs:
                if i.op == "RET" and out and out[-1].op == "BSR" and out[-1].comment == "tail-ok":
                    out[-1] = MInstr("TAIL", [out[-1].ops[0]])
                    continue
                out.append(i)
            b.instrs = out

    def retarget(self, i, mapping):
        if not i.targets:
            return
        new = [mapping(t) for t in i.targets]
        if any(a is not b for a, b in zip(new, i.targets)):
            i.targets = new
            if i.op in ("JMP", "BCC"):
                i.ops = [Label(new[0])]

    def thread_jumps(self):
        """Branches to a block that only jumps on go straight to the end of
        the chain; jumps to a short return block become a copy of it; then
        unreachable blocks go."""
        mf = self.mf

        def final(b):
            seen = set()
            while len(b.instrs) == 1 and b.instrs[0].op == "JMP" and b not in seen:
                seen.add(b)
                b = b.instrs[0].targets[0]
            return b
        for b in mf.blocks:
            for i in b.instrs:
                self.retarget(i, final)
        mf.consts = [(label, [final(t) for t in table]) for label, table in mf.consts]
        for b in mf.blocks:
            if b.instrs and b.instrs[-1].op == "JMP":
                t = b.instrs[-1].targets[0]
                if t is not b and t.instrs and t.instrs[-1].op == "RET" and len(t.instrs) <= 2 \
                        and all(not i.targets for i in t.instrs):
                    b.instrs[-1:] = [MInstr(i.op, list(i.ops), list(i.defs), list(i.uses),
                                            flags=i.flags) for i in t.instrs]
        self.compute_succs()
        live = set()
        work = [mf.blocks[0]]
        for _, table in mf.consts:
            work.extend(table)
        while work:
            b = work.pop()
            if b in live:
                continue
            live.add(b)
            work.extend(b.succs)
        mf.blocks = [b for b in mf.blocks if b in live]

    # After CMP r, #c, these conditions only depend on N and Z of r itself
    # (with c = 0, V is 0, so GE is "not N"; r > -1 is r >= 0).
    NZ_CONDS = {0: {"EQ": "EQ", "NE": "NE", "MI": "MI", "PL": "PL", "GE": "PL", "LT": "MI"},
                -1: {"GT": "PL", "LE": "MI"}}

    IMM_OPS = ()        # mnemonics whose second operand may be an immediate instead

    def fold_constants(self):
        """MOV rt, #c; OP rd, rt  ->  OP rd, #c, when rt dies there (left
        over from constants rematerialised by the register allocator)."""
        is_alloc = self.mf.is_alloc
        live_in, live_out = liveness(self.mf)
        for b in self.mf.blocks:
            live = set(live_out[b])
            after = []
            for i in reversed(b.instrs):
                after.append(set(live))
                live -= set(r for r in i.defs if is_alloc(r))
                live |= set(r for r in i.uses if is_alloc(r))
            after.reverse()
            out = []
            for k, i in enumerate(b.instrs):
                prev = out[-1] if out else None
                if (prev is not None and prev.op == "MOV" and len(prev.ops) == 2
                        and isinstance(prev.ops[1], Imm) and i.op in self.IMM_OPS
                        and len(i.ops) == 2 and i.ops[1] is prev.ops[0]
                        and i.ops[0] is not prev.ops[0] and prev.ops[0] not in after[k]):
                    t = prev.ops[0]
                    out[-1] = MInstr(i.op, [i.ops[0], prev.ops[1]], i.defs,
                                     [r for r in i.uses if r is not t], flags=i.flags)
                    continue
                out.append(i)
            b.instrs = out

    def peephole(self):
        """Target-independent clean-ups on the allocated code."""
        mf = self.mf
        self.fold_constants()
        for b in mf.blocks:
            out = []
            for k, i in enumerate(b.instrs):
                # drop CMP r, #c when the previous instruction set N and Z
                # from r and only the conditions above are tested
                if (i.op == "CMP" and len(i.ops) == 2 and isinstance(i.ops[1], Imm)
                        and i.ops[1].value in self.NZ_CONDS and out and out[-1].flags == "nz"
                        and out[-1].ops and out[-1].ops[0] is i.ops[0]):
                    users = self.flag_users(b, k)
                    conds = self.NZ_CONDS[i.ops[1].value]
                    if users is not None and all(self.cond_of(u) in conds for u in users):
                        for u in users:
                            self.set_cond(u, conds[self.cond_of(u)])
                        continue
                out.append(i)
            b.instrs = out

    @staticmethod
    def cond_of(i):
        return i.cond if i.op == "BCC" else i.op[3:]

    @staticmethod
    def set_cond(i, cc):
        if i.op == "BCC":
            i.cond = cc
        else:
            i.op = "SET" + cc

    def flag_users(self, b, k):
        """The branches and SETs that read the flags set by instruction k of
        block b, or None if they might be read further on."""
        out = []
        for i in b.instrs[k + 1:]:
            if i.op == "BCC" or i.op.startswith("SET"):
                out.append(i)
                continue
            if i.op in ("JMP", "RET") or i.flags in ("cmp", "nz") or i.op in ("BSR", "CALL"):
                return out
            return None
        return out

    # ======================================================================
    # Assembly text

    def fmt(self, x):
        if x.__class__.__name__ == "PReg":
            return "sp" if x.n == 15 else f"r{x.n}"
        if isinstance(x, Imm):
            return f"#{x.value}"
        if isinstance(x, Label):
            t = x.target
            return t if isinstance(t, str) else t.label
        if isinstance(x, Mem):
            return self.fmt_mem(x)
        if isinstance(x, str):
            return x
        raise AssertionError(x)

    def mem_disp(self, m):
        d = m.disp
        if m.frame is not None:
            d += self.mf.frame_offset(m.frame)
        return d

    def emit_text(self):
        mf = self.mf
        lines = [f"{mf.name}:"]
        lines += self.prologue()
        blocks = mf.blocks
        targets = set()
        for b in blocks:
            for i in b.instrs:
                for t in i.targets or ():
                    targets.add(t)
        body = []
        for n, b in enumerate(blocks):
            nxt = blocks[n + 1] if n + 1 < len(blocks) else None
            instrs = list(b.instrs)
            # Bcc T; JMP F with T next: B!cc F
            if (len(instrs) >= 2 and instrs[-1].op == "JMP" and instrs[-2].op == "BCC"
                    and instrs[-2].targets[0] is nxt):
                bc, j = instrs[-2], instrs[-1]
                instrs[-2:] = [MInstr("BCC", [Label(j.targets[0])], cond=INVERT[bc.cond],
                                      targets=j.targets)]
            if instrs and instrs[-1].op == "JMP" and instrs[-1].targets and instrs[-1].targets[0] is nxt:
                instrs = instrs[:-1]
            body.append((b, instrs))
        self.final_layout(body)
        # labels only where needed
        used_labels = set()
        for b, instrs in body:
            for i in instrs:
                for t in i.targets or ():
                    used_labels.add(t)
        for _, table in mf.consts:
            used_labels.update(table)
        for b, instrs in body:
            if b in used_labels:
                lines.append(f"{b.label}:")
            for i in instrs:
                if i.op == "TAIL":
                    lines += self.epilogue(tail=True) + [f"        BRA  {self.fmt(i.ops[0])}"]
                    continue
                lines += self.format_instr(i)
        for label, table in mf.consts:
            lines.append("        .align 4")
            lines.append(f"{label}:")
            for t in table:
                lines.append(f"        .word {mf.name}{t.label}")
        return "\n".join(lines) + "\n"

    def final_layout(self, body):
        """Last changes, with the blocks in their final order: body is
        [(block, instructions)]."""

    def format_instr(self, i):
        op = i.op
        if op == "RET":
            return self.epilogue() + self.return_instr()
        if op == "COPY":
            return [f"        MOV  {self.fmt(i.ops[0])}, {self.fmt(i.ops[1])}"]
        if op == "JMP":
            return [f"        BRA  {self.fmt(i.ops[0])}"]
        if op == "BCC":
            return [f"        B{i.cond}  {self.fmt(i.ops[0])}"]
        if op.startswith("SET"):
            return [f"        {op} {self.fmt(i.ops[0])}"]
        args = ", ".join(self.fmt(x) for x in i.ops)
        return [f"        {op:<4} {args}".rstrip()]

    def saves_link(self):
        return self.LINK is not None and (not self.mf.leaf or self.mf.link_used)

    def prologue(self):
        mf = self.mf
        out = []
        if self.saves_link():
            # the return address goes below the callee-saved registers, so
            # one SAVE takes both; without them, a push
            if mf.saved:
                out.append(f"        SAVE r{self.LINK.n}-r{mf.saved[1]}")
            else:
                out.append(self.push(self.LINK))
        elif mf.saved:
            out.append(f"        SAVE r{mf.saved[0]}-r{mf.saved[1]}")
        if mf.frame_size:
            out += self.adjust_sp(-mf.frame_size)
        return out

    def epilogue(self, tail=False):
        """Unwind the frame. Before a return, with a link register saved and
        nothing else, return_instr pops the return address itself; before a
        tail call it goes back into the link register."""
        mf = self.mf
        out = []
        if mf.frame_size:
            out += self.adjust_sp(mf.frame_size)
        if self.saves_link():
            if mf.saved:
                out.append(f"        RESTORE r{self.LINK.n}-r{mf.saved[1]}")
            elif tail:
                out.append(f"        MOV  r{self.LINK.n}, [sp]+")
        elif mf.saved:
            out.append(f"        RESTORE r{mf.saved[0]}-r{mf.saved[1]}")
        return out

    def push(self, r):
        return f"        ST   {self.fmt(r)}, -[sp]"

    def return_instr(self):
        if self.saves_link() and not self.mf.saved:
            return ["        JMP  [sp]+"]
        return ["        RET"]
