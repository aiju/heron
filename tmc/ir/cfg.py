"""Control-flow analyses: orderings, dominators, dominance frontiers, loops,
and the IR verifier."""

from .ir import Instr, Param, Slot, Const, SymAddr, Undef


def reverse_postorder(func):
    """Blocks reachable from the entry, in reverse postorder."""
    seen = set()
    post = []
    stack = [(func.entry, iter(func.entry.succs))]
    seen.add(func.entry)
    while stack:
        b, it = stack[-1]
        nxt = next(it, None)
        if nxt is None:
            stack.pop()
            post.append(b)
        elif nxt not in seen:
            seen.add(nxt)
            stack.append((nxt, iter(nxt.succs)))
    post.reverse()
    return post


def remove_unreachable(func):
    """Drop blocks the entry can't reach. Returns True if any were removed."""
    live = set(reverse_postorder(func))
    if len(live) == len(func.blocks):
        return False
    dead = [b for b in func.blocks if b not in live]
    func.blocks = [b for b in func.blocks if b in live]
    for b in func.blocks:
        for p in b.phis():
            keep = [(v, blk) for v, blk in zip(p.args, p.incoming) if blk in live]
            p.args = [v for v, _ in keep]
            p.incoming = [blk for _, blk in keep]
    for b in dead:
        b.instrs = []
    func.compute_preds()
    return True


class DomTree:
    """Immediate dominators by Cooper, Harvey and Kennedy's iterative algorithm."""

    def __init__(self, func):
        func.compute_preds()
        self.rpo = reverse_postorder(func)
        order = {b: n for n, b in enumerate(self.rpo)}
        self.order = order
        idom = {func.entry: func.entry}
        changed = True
        while changed:
            changed = False
            for b in self.rpo[1:]:
                new = None
                for p in b.preds:
                    if p not in idom:
                        continue
                    if new is None:
                        new = p
                    else:
                        new = self._intersect(p, new, idom, order)
                if new is not None and idom.get(b) is not new:
                    idom[b] = new
                    changed = True
        self.idom = idom
        self.children = {b: [] for b in self.rpo}
        for b in self.rpo[1:]:
            self.children[idom[b]].append(b)
        # pre/post numbers for O(1) dominance queries
        self.pre, self.post = {}, {}
        n = 0
        stack = [(func.entry, False)]
        while stack:
            b, done = stack.pop()
            if done:
                self.post[b] = n
                n += 1
                continue
            self.pre[b] = n
            n += 1
            stack.append((b, True))
            for c in reversed(self.children[b]):
                stack.append((c, False))

    @staticmethod
    def _intersect(a, b, idom, order):
        while a is not b:
            while order[a] > order[b]:
                a = idom[a]
            while order[b] > order[a]:
                b = idom[b]
        return a

    def dominates(self, a, b):
        return self.pre[a] <= self.pre[b] and self.post[b] <= self.post[a]

    def frontiers(self):
        df = {b: set() for b in self.rpo}
        for b in self.rpo:
            preds = [p for p in b.preds if p in self.idom]
            if len(preds) >= 2:
                for p in preds:
                    r = p
                    while r is not self.idom[b]:
                        df[r].add(b)
                        r = self.idom[r]
        return df

    def preorder(self):
        out = []
        stack = [self.rpo[0]]
        while stack:
            b = stack.pop()
            out.append(b)
            stack.extend(reversed(self.children[b]))
        return out


def natural_loops(dom):
    """header -> set of blocks, for every loop (back edges to the same header
    merged)."""
    loops = {}
    for b in dom.rpo:
        for h in b.succs:
            if h in dom.pre and dom.dominates(h, b):
                body = loops.setdefault(h, {h})
                work = [b]
                while work:
                    x = work.pop()
                    if x in body:
                        continue
                    body.add(x)
                    work.extend(p for p in x.preds if p in dom.pre)
    return loops


def compute_loop_depth(func, dom=None):
    """Set block.loop_depth: the number of natural loops that contain the
    block (a loop with several back edges counts once)."""
    dom = dom or DomTree(func)
    for b in func.blocks:
        b.loop_depth = 0
    for body in natural_loops(dom).values():
        for b in body:
            b.loop_depth += 1
    return dom


def split_critical_edges(func):
    """Put a block on every edge from a block with several successors to a
    block with several predecessors (phi copies need somewhere to go)."""
    func.compute_preds()
    for b in list(func.blocks):
        t = b.terminator
        if t is None or not t.targets or len(set(t.targets)) < 2:
            continue
        for n, s in enumerate(t.targets):
            if len(s.preds) < 2:
                continue
            mid = func.new_block("crit")
            j = Instr("jmp", [], targets=[s])
            mid.append(j)
            # every edge b -> s through this slot gets the same new block
            for k in range(n, len(t.targets)):
                if t.targets[k] is s:
                    t.targets[k] = mid
            for p in s.phis():
                p.incoming = [mid if blk is b else blk for blk in p.incoming]
    func.compute_preds()


class VerifyError(Exception):
    pass


def verify(func):
    """Check structural invariants and that definitions dominate uses."""
    func.compute_preds()
    blocks = set(func.blocks)
    defined_in = {}
    params = set(func.params)
    slots = set(func.slots)
    for b in func.blocks:
        if not b.instrs or not b.instrs[-1].is_terminator:
            raise VerifyError(f"{func.name}: block {b.name} has no terminator")
        seen_non_phi = False
        for n, i in enumerate(b.instrs):
            if i.block is not b:
                raise VerifyError(f"{func.name}: {i.op} in {b.name} has the wrong block")
            if i.is_terminator and n != len(b.instrs) - 1:
                raise VerifyError(f"{func.name}: terminator in the middle of {b.name}")
            if i.op == "phi":
                if seen_non_phi:
                    raise VerifyError(f"{func.name}: phi after other instructions in {b.name}")
                if sorted(id(x) for x in i.incoming) != sorted(id(x) for x in b.preds):
                    raise VerifyError(f"{func.name}: phi in {b.name} has incoming "
                                      f"{[x.name for x in i.incoming]} but preds "
                                      f"{[x.name for x in b.preds]}")
            else:
                seen_non_phi = True
            for t in (i.targets or []):
                if t not in blocks:
                    raise VerifyError(f"{func.name}: {b.name} branches to a removed block")
            defined_in[i] = (b, n)
    dom = DomTree(func)
    for b in func.blocks:
        if b not in dom.pre:
            continue
        for n, i in enumerate(b.instrs):
            for k, a in enumerate(i.args):
                if isinstance(a, Instr):
                    if a not in defined_in:
                        raise VerifyError(f"{func.name}: {i.op} in {b.name} uses a deleted value ({a.op})")
                    db, dn = defined_in[a]
                    if i.op == "phi":
                        ub = i.incoming[k]
                        if ub not in dom.pre:
                            continue
                        if not dom.dominates(db, ub):
                            raise VerifyError(f"{func.name}: phi operand {a.op} doesn't dominate edge "
                                              f"{ub.name} -> {b.name}")
                    elif db is b:
                        if dn >= n:
                            raise VerifyError(f"{func.name}: {i.op} uses {a.op} before its definition in {b.name}")
                    elif not dom.dominates(db, b):
                        raise VerifyError(f"{func.name}: {a.op} in {db.name} doesn't dominate its use "
                                          f"({i.op}) in {b.name}")
                elif isinstance(a, Param):
                    if a not in params:
                        raise VerifyError(f"{func.name}: foreign parameter")
                elif isinstance(a, Slot):
                    if a not in slots:
                        raise VerifyError(f"{func.name}: foreign stack slot")
                elif not (isinstance(a, (Const, SymAddr)) or a is Undef):
                    raise VerifyError(f"{func.name}: bad operand {a!r}")
