"""mem2reg: promote stack slots that are only loaded and stored into SSA
values (Cytron et al.: phis at the iterated dominance frontier, then a
renaming walk over the dominator tree).

A slot is promotable when every use is a load or store *through* it (its
address never escapes), none is volatile, and all accesses have the same
size. Narrow slots (char, short) keep their C semantics: the stored value is
truncated and re-extended the way the slot's loads read it.
"""

from .ir import Instr, Slot, Undef
from .cfg import DomTree, remove_unreachable


def promotable_slots(func):
    info = {s: {"sizes": set(), "kinds": set(), "ok": s.size in (1, 2, 4)} for s in func.slots}
    for i in func.instructions():
        for n, a in enumerate(i.args):
            if not isinstance(a, Slot):
                continue
            d = info[a]
            if i.op == "load" and n == 0 and not i.volatile:
                d["sizes"].add(i.size)
                d["kinds"].add((i.size, i.signed))
            elif i.op == "store" and n == 1 and not i.volatile:
                d["sizes"].add(i.size)
            else:
                d["ok"] = False
    out = []
    for s, d in info.items():
        if d["ok"] and len(d["sizes"]) <= 1 and len(d["kinds"]) <= 1:
            if not d["sizes"] or d["sizes"] == {s.size}:
                out.append(s)
    return out, info


EXTEND = {(1, False): "zext8", (1, True): "sext8", (2, False): "zext16", (2, True): "sext16"}


def mem2reg(func):
    remove_unreachable(func)
    slots, info = promotable_slots(func)
    if not slots:
        return False
    promo = set(slots)
    dom = DomTree(func)
    df = dom.frontiers()

    # phi placement
    phi_slot = {}
    for s in slots:
        defs = {i.block for i in func.instructions() if i.op == "store" and i.args[1] is s}
        work = list(defs)
        has_phi = set()
        while work:
            b = work.pop()
            for f in df.get(b, ()):
                if f in has_phi:
                    continue
                has_phi.add(f)
                p = Instr("phi", [], incoming=[])
                f.insert(0, p)
                phi_slot[p] = s
                if f not in defs:
                    work.append(f)

    # how narrow slots are read back
    ext = {}
    for s in slots:
        kinds = info[s]["kinds"]
        if s.size < 4 and kinds:
            ext[s] = EXTEND[next(iter(kinds))]

    replace = {}
    stacks = {s: [Undef] for s in slots}

    def visit(b):
        pushed = []
        new = []
        for i in b.instrs:
            if i.op == "phi" and i in phi_slot:
                s = phi_slot[i]
                stacks[s].append(i)
                pushed.append(s)
                new.append(i)
            elif i.op == "load" and i.args[0] in promo:
                replace[i] = stacks[i.args[0]][-1]
            elif i.op == "store" and i.args[1] in promo:
                s = i.args[1]
                v = i.args[0]
                if s in ext:
                    e = Instr(ext[s], [v])
                    e.block = b
                    new.append(e)
                    v = e
                stacks[s].append(v)
                pushed.append(s)
            else:
                new.append(i)
        b.instrs = new
        for succ in dict.fromkeys(b.succs):
            for p in succ.phis():
                if p in phi_slot:
                    p.args.append(stacks[phi_slot[p]][-1])
                    p.incoming.append(b)
        return pushed

    # iterative DFS over the dominator tree
    stack = [(dom.rpo[0], None)]
    while stack:
        b, pushed = stack.pop()
        if pushed is not None:
            for s in pushed:
                stacks[s].pop()
            continue
        pushed = visit(b)
        stack.append((b, pushed))
        for c in reversed(dom.children[b]):
            stack.append((c, None))

    func.replace_uses(replace)
    func.slots = [s for s in func.slots if s not in promo]
    return True
