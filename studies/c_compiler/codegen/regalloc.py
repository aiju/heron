"""Graph-colouring register allocation with iterated register coalescing
(George and Appel, 1996; the version in Appel's "Modern Compiler
Implementation"), with spilling to stack slots and rematerialisation of
constants.

Both draft 1 ISAs are two-address, so the instruction selector writes
`a = b + c` as `COPY a, b; ADD a, c`. Coalescing removes the copy whenever
b dies there, which is what makes the code look hand-written.
"""

from .mir import PHYS, VReg, MInstr, Mem, Frame, SP, is_alloc, liveness

INF = 1 << 30


class Allocator:
    def __init__(self, mf, target):
        self.mf = mf
        self.target = target
        self.colors = target.ALLOC_ORDER
        self.K = len(self.colors)

    def run(self):
        for _ in range(50):
            spilled = self.color_graph()
            if not spilled:
                break
            self.rewrite(spilled)
        else:
            raise RuntimeError(f"{self.mf.name}: register allocation didn't converge")
        self.mf.assign = {n: c for n, c in self.color.items() if isinstance(n, VReg)}

    # ---- graph -----------------------------------------------------------

    def add_edge(self, u, v):
        if u is v or (u, v) in self.adj_set:
            return
        self.adj_set.add((u, v))
        self.adj_set.add((v, u))
        if not u.is_phys:
            self.adj_list[u].add(v)
            self.degree[u] += 1
        if not v.is_phys:
            self.adj_list[v].add(u)
            self.degree[v] += 1

    def node(self, n):
        if n not in self.degree:
            self.degree[n] = INF if n.is_phys else 0
            self.adj_list[n] = set()
            self.move_list[n] = set()
            self.cost[n] = 0
            if not n.is_phys:
                self.initial.add(n)

    def build(self):
        mf = self.mf
        self.adj_set = set()
        self.adj_list = {}
        self.degree = {}
        self.move_list = {}
        self.cost = {}
        self.initial = set()
        self.worklist_moves = set()
        self.moves = {}
        self.move_order = {}        # moves are taken in a fixed order, so output is reproducible
        live_in, live_out = liveness(mf)
        for b in mf.blocks:
            w = 10 ** min(b.loop_depth, 5)
            live = set(live_out[b])
            for r in live:
                self.node(r)
            for i in reversed(b.instrs):
                uses = [r for r in i.uses if is_alloc(r)]
                defs = [r for r in i.defs if is_alloc(r)]
                for r in uses + defs:
                    self.node(r)
                    self.cost[r] += w
                if i.is_copy and len(uses) == 1 and len(defs) == 1:
                    live.discard(uses[0])
                    self.moves[i] = (defs[0], uses[0])
                    self.move_order[i] = len(self.move_order)
                    self.move_list[defs[0]].add(i)
                    self.move_list[uses[0]].add(i)
                    self.worklist_moves.add(i)
                live.update(defs)
                for d in defs:
                    for l in live:
                        self.add_edge(l, d)
                live.difference_update(defs)
                live.update(uses)

    # ---- the IRC main loop ----------------------------------------------

    def color_graph(self):
        self.build()
        K = self.K
        self.simplify_wl, self.freeze_wl, self.spill_wl = set(), set(), set()
        self.spilled, self.coalesced, self.colored = set(), set(), set()
        self.select_stack = []
        self.in_stack = set()
        self.coalesced_moves, self.constrained_moves, self.frozen_moves = set(), set(), set()
        self.active_moves = set()
        self.alias = {}
        self.color = {p: p for p in PHYS[1:15]}
        for n in sorted(self.initial, key=lambda r: r.id):
            if self.degree[n] >= K:
                self.spill_wl.add(n)
            elif self.move_related(n):
                self.freeze_wl.add(n)
            else:
                self.simplify_wl.add(n)
        while True:
            if self.simplify_wl:
                self.simplify()
            elif self.worklist_moves:
                self.coalesce()
            elif self.freeze_wl:
                self.freeze()
            elif self.spill_wl:
                self.select_spill()
            else:
                break
        self.assign_colors()
        return self.spilled

    def adjacent(self, n):
        return [m for m in self.adj_list[n] if m not in self.in_stack and m not in self.coalesced]

    def node_moves(self, n):
        return [m for m in self.move_list[n] if m in self.active_moves or m in self.worklist_moves]

    def move_related(self, n):
        return any(m in self.active_moves or m in self.worklist_moves for m in self.move_list[n])

    def pop(self, s):
        x = min(s, key=lambda r: r.id)
        s.remove(x)
        return x

    def simplify(self):
        n = self.pop(self.simplify_wl)
        self.select_stack.append(n)
        self.in_stack.add(n)
        for m in self.adjacent(n):
            self.decrement_degree(m)

    def decrement_degree(self, m):
        if m.is_phys:
            return
        d = self.degree[m]
        self.degree[m] = d - 1
        if d == self.K:
            self.enable_moves([m] + self.adjacent(m))
            self.spill_wl.discard(m)
            if self.move_related(m):
                self.freeze_wl.add(m)
            else:
                self.simplify_wl.add(m)

    def enable_moves(self, nodes):
        for n in nodes:
            for m in self.node_moves(n):
                if m in self.active_moves:
                    self.active_moves.remove(m)
                    self.worklist_moves.add(m)

    def get_alias(self, n):
        while n in self.coalesced:
            n = self.alias[n]
        return n

    def add_worklist(self, u):
        if not u.is_phys and not self.move_related(u) and self.degree[u] < self.K:
            self.freeze_wl.discard(u)
            self.simplify_wl.add(u)

    def ok(self, t, r):
        return t.is_phys or self.degree[t] < self.K or (t, r) in self.adj_set

    def conservative(self, nodes):
        k = 0
        for n in nodes:
            if self.degree[n] >= self.K:
                k += 1
        return k < self.K

    def coalesce(self):
        m = min(self.worklist_moves, key=self.move_order.__getitem__)
        self.worklist_moves.remove(m)
        x, y = self.moves[m]
        x, y = self.get_alias(x), self.get_alias(y)
        if y.is_phys:
            u, v = y, x
        else:
            u, v = x, y
        if u is v:
            self.coalesced_moves.add(m)
            self.add_worklist(u)
        elif v.is_phys or (u, v) in self.adj_set:
            self.constrained_moves.add(m)
            self.add_worklist(u)
            self.add_worklist(v)
        elif (u.is_phys and all(self.ok(t, u) for t in self.adjacent(v))) or \
                (not u.is_phys and self.conservative(set(self.adjacent(u)) | set(self.adjacent(v)))):
            self.coalesced_moves.add(m)
            self.combine(u, v)
            self.add_worklist(u)
        else:
            self.active_moves.add(m)

    def combine(self, u, v):
        if v in self.freeze_wl:
            self.freeze_wl.remove(v)
        else:
            self.spill_wl.discard(v)
        self.coalesced.add(v)
        self.alias[v] = u
        self.move_list[u] |= self.move_list[v]
        if not u.is_phys and v.no_spill:
            u.no_spill = True
        self.enable_moves([v])
        for t in self.adjacent(v):
            self.add_edge(t, u)
            self.decrement_degree(t)
        if not u.is_phys and self.degree[u] >= self.K and u in self.freeze_wl:
            self.freeze_wl.remove(u)
            self.spill_wl.add(u)

    def freeze(self):
        u = self.pop(self.freeze_wl)
        self.simplify_wl.add(u)
        self.freeze_moves(u)

    def freeze_moves(self, u):
        for m in self.node_moves(u):
            x, y = self.moves[m]
            if self.get_alias(y) is self.get_alias(u):
                v = self.get_alias(x)
            else:
                v = self.get_alias(y)
            self.active_moves.discard(m)
            self.worklist_moves.discard(m)
            self.frozen_moves.add(m)
            if not v.is_phys and not self.node_moves(v) and self.degree[v] < self.K:
                self.freeze_wl.discard(v)
                self.simplify_wl.add(v)

    def select_spill(self):
        def score(n):
            if n.no_spill:
                return INF
            c = self.cost[n]
            if n.remat is not None:
                c *= 0.5
            return c / max(1, self.degree[n])
        m = min(self.spill_wl, key=lambda n: (score(n), n.id))
        self.spill_wl.remove(m)
        self.simplify_wl.add(m)
        self.freeze_moves(m)

    def assign_colors(self):
        color = self.color
        while self.select_stack:
            n = self.select_stack.pop()
            self.in_stack.discard(n)
            ok = list(self.colors)
            taken = set()
            for w in self.adj_list[n]:
                a = self.get_alias(w)
                if a.is_phys or a in self.colored:
                    taken.add(color[a])
            ok = [c for c in ok if c not in taken]
            if not ok:
                self.spilled.add(n)
                continue
            self.colored.add(n)
            color[n] = self.choose(n, ok)
        for n in self.coalesced:
            a = self.get_alias(n)
            if a in color:
                color[n] = color[a]

    def choose(self, n, ok):
        """Prefer the colour of a register n is copied to or from."""
        for m in sorted(self.move_list[n], key=self.move_order.__getitem__):
            x, y = self.moves[m]
            for other in (x, y):
                o = self.get_alias(other)
                if o is n:
                    continue
                c = self.color.get(o) if (o.is_phys or o in self.colored) else None
                if c is not None and c in ok:
                    return c
        return ok[0]

    # ---- spilling ----------------------------------------------------------

    def rewrite(self, spilled):
        mf = self.mf
        slots = {}
        remat = {}
        for v in sorted(spilled, key=lambda r: r.id):
            if v.remat is not None:
                remat[v] = v.remat
            else:
                slots[v] = mf.spills
                mf.spills += 1
        for b in mf.blocks:
            out = []
            for i in b.instrs:
                if any(d in remat for d in i.defs) and i.remat_of in remat:
                    continue            # the constant is recomputed at each use
                before, after = [], []
                for v in [r for r in dict.fromkeys(i.uses + i.defs) if r in slots or r in remat]:
                    t = VReg()
                    t.no_spill = True
                    if v in remat:
                        if v in i.uses:
                            src = remat[v]
                            c = MInstr(src.op, [t] + src.ops[1:], defs=[t], uses=[], flags=src.flags)
                            # a temporary that lives for one instruction: spilling
                            # it again would gain nothing (and never converge)
                            before.append(c)
                        if v in i.defs:
                            raise RuntimeError("rematerialised register is redefined")
                    else:
                        slot = Mem(SP, frame=Frame("spill", slots[v]))
                        if v in i.uses:
                            before.append(self.target.spill_load(t, slot))
                        if v in i.defs:
                            after.append(self.target.spill_store(t, slot))
                    i.replace_reg(v, t)
                out.extend(before)
                out.append(i)
                out.extend(after)
            b.instrs = out
