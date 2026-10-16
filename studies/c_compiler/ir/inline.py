"""Inlining: a call to a small function of the same translation unit
becomes a copy of its body.

`inline_module` runs after every function has been optimised once, so a
callee's size is what it compiles to. A call is inlined when the callee is
defined in the module, isn't variadic, doesn't call itself and has at most
INLINE_SIZE instructions (phis and jumps not counted) and no loop: what a
call to a loop costs is small next to the loop. The callers that
changed are optimised again by the driver, and a static function that
nothing refers to any more is dropped.
"""

from .ir import Instr, Param, Slot, SymAddr, Undef
from .cfg import DomTree, natural_loops

INLINE_SIZE = 16


def size(f):
    return sum(1 for i in f.instructions() if i.op not in ("phi", "jmp"))


def inlinable(f):
    if f.variadic or not f.blocks or f.entry.preds or size(f) > INLINE_SIZE:
        return False
    if natural_loops(DomTree(f)):
        return False
    for i in f.instructions():
        if i.op == "vastart":
            return False
        if i.op == "call" and isinstance(i.args[0], SymAddr) and i.args[0].name == f.name:
            return False
    return True


def inline_call(caller, call, callee):
    """Replace call (in caller) by a copy of callee's body."""
    b = call.block
    k = b.instrs.index(call)
    # the instructions after the call go to a block of their own
    cont = caller.new_block("inl.cont")
    cont.instrs = []
    for i in b.instrs[k + 1:]:
        cont.append(i)
    del b.instrs[k:]
    for s in set(cont.succs):
        for ph in s.phis():
            ph.incoming = [cont if x is b else x for x in ph.incoming]
    # the callee's blocks, values and slots, renamed
    vmap = {p: a for p, a in zip(callee.params, call.args[1:])}
    for s in callee.slots:
        vmap[s] = caller.new_slot(s.size, s.align, s.name)
    bmap = {cb: caller.new_block("inl." + (cb.hint or "b")) for cb in callee.blocks}
    rets = []
    for cb in callee.blocks:
        nb = bmap[cb]
        for i in cb.instrs:
            ni = Instr(i.op, list(i.args), size=i.size, signed=i.signed, volatile=i.volatile,
                       align=i.align, incoming=[bmap[x] for x in i.incoming] if i.incoming else i.incoming,
                       targets=[bmap[x] for x in i.targets] if i.targets else i.targets,
                       cases=list(i.cases) if i.cases else i.cases, nfixed=i.nfixed, void=i.void)
            if i.op == "ret":
                rets.append((ni.args[0] if ni.args else Undef, nb))
                ni = Instr("jmp", [], targets=[cont])
            vmap[i] = ni
            nb.append(ni)
    for nb in bmap.values():
        for i in nb.instrs:
            i.args = [vmap.get(a, a) if isinstance(a, (Instr, Param, Slot)) else a for a in i.args]
    rets = [(vmap.get(v, v) if isinstance(v, (Instr, Param, Slot)) else v, blk) for v, blk in rets]
    b.append(Instr("jmp", [], targets=[bmap[callee.entry]]))
    # the call's value: what the copy returns
    if call.has_value:
        if len(rets) == 1:
            result = rets[0][0]
        else:
            result = Instr("phi", [v for v, _ in rets], incoming=[blk for _, blk in rets])
            cont.insert(0, result)
        caller.replace_uses({call: result})
    # keep the blocks in order: the copy right after the call, then the rest
    caller.blocks.remove(cont)
    for nb in bmap.values():
        caller.blocks.remove(nb)
    at = caller.blocks.index(b) + 1
    caller.blocks[at:at] = list(bmap.values()) + [cont]
    caller.compute_preds()


def inline_module(module):
    """Inline the small functions' calls throughout module. Returns the
    functions that changed."""
    funcs = {f.name: f for f in module.functions}
    small = {name for name, f in funcs.items() if inlinable(f)}
    changed = []
    for f in module.functions:
        done = False
        for b in list(f.blocks):
            for i in list(b.instrs):
                if (i.op == "call" and i.nfixed is None and isinstance(i.args[0], SymAddr)
                        and i.args[0].offset == 0 and i.args[0].name in small
                        and i.args[0].name != f.name
                        and len(i.args) - 1 == len(funcs[i.args[0].name].params)):
                    inline_call(f, i, funcs[i.args[0].name])
                    done = True
        if done:
            changed.append(f)
    # static functions nothing refers to any more
    used = set()
    for f in module.functions:
        for i in f.instructions():
            used.update(a.name for a in i.args if isinstance(a, SymAddr))
    for d in module.data:
        used.update(v.name for kind, v in d.items if kind == "word" and isinstance(v, SymAddr))
    module.functions = [f for f in module.functions if not f.static or f.name in used]
    return [f for f in changed if f in module.functions]
