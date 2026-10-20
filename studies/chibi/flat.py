"""The flat control store: the routines (routines2.py) compiled into
µPC's 8K words (ucode2.py has the sequencer).

The routines are written as blocks of microinstructions, a block for each
(page, N, opcode), where a jump goes to a label or step of its block or to
a step of another page's, a word with N <- s or N <- z goes on in the
block of the new N, and the decode enters page 0's block of the opcode's
N = d; or as named linear routines (page 3's entries, reset's, the copper,
ODT), with labels of their own. compile():

- follows every block's control flow from its entries to its states (a
  state: a block's step or a routine's word);
- merges the states that do the same, with the same successors (the
  partition's refinement of a minimal automaton), so that what's the same
  in every N's block, or in every opcode's, is one word;
- makes each dispatch a 16-way branch (SEQ MW: N <- s on s, N <- z on z,
  and the decode's N = d on d, in the entry's word, after that word's work
  when it's the same for every d);
- lays the words out: the interrupt's entry at 0x000-0x0FF, each opcode's
  at 0x100 + the opcode, the tasks' (the copper's and the device task's)
  within their 128 words at TASK_BASE, a conditional jump's two targets as a pair (JT, JT ^ 1), a
  branch's 16 at a multiple of 16; a word wanted in two places is copied,
  as every word gives its next address.
"""

from collections import defaultdict

from . import ucode2 as uc

TRUE = uc.COND_CODE["TRUE"]


class Node:
    __slots__ = ("word", "kind", "cond", "task", "src", "succ", "halt", "region", "nochk",
                 "name")

    def __init__(self, word, kind, succ, cond=0, task=False, src=0, halt=False, region="main",
                 nochk=False, name=""):
        self.word, self.kind, self.succ = word, kind, succ
        self.cond, self.task, self.src, self.halt = cond, task, src, halt
        self.region, self.nochk, self.name = region, nochk, name


class Graph:
    """The states, from the routines' generators: {state: (word fields,
    kind, cond, task, src, successors, halt, nochk)}."""

    def __init__(self, block, routines, task_routines=("copper", "device")):
        self.block = block              # (page, n, op) -> [ops]
        self.routines = routines        # name -> [ops]
        self.task_routines = set(task_routines)
        self._blocks, self._labels = {}, {}
        self.states = {}

    # ---- the generators' lists, labels merged into their microinstructions

    def ops(self, key):
        if key not in self._blocks:
            if key[0] == "l":
                raw = self.routines[key[1]]()
            else:
                raw = self.block(*key[1:])
            ops, labels = [], {}
            pending = []
            for op in raw:
                if set(op) == {"_label"}:
                    pending.append(op["_label"])
                    continue
                names = pending + ([op["_label"]] if "_label" in op else [])
                pending = []
                for nm in names:
                    assert nm not in labels, (key, nm)
                    labels[nm] = len(ops)
                ops.append(op)
            assert not pending, (key, "a label at the end")
            self._blocks[key], self._labels[key] = ops, labels
        return self._blocks[key], self._labels[key]

    def target(self, state, op):
        """The state a jump of `op` (in `state`) goes to."""
        g = op["_goto"]
        if "_routine" in op:
            key = ("l", op["_routine"])
            _, labels = self.ops(key)
            return ("l", op["_routine"], labels[g] if isinstance(g, str) else g)
        if state[0] == "l":
            if op.get("_page") == 3:
                _, labels = self.ops(("l", "p3"))
                return ("l", "p3", labels[g] if isinstance(g, str) else g)
            assert "_page" not in op, (state, "a routine's jump to a page")
            _, labels = self.ops(state[:2])
            return state[:2] + (labels[g] if isinstance(g, str) else g,)
        _, page, n, opc, _ = state
        if op.get("_page") == 3:
            _, labels = self.ops(("l", "p3"))
            return ("l", "p3", labels[g] if isinstance(g, str) else g)
        tpage = op.get("_page", page)
        if isinstance(g, str):
            assert tpage == page, (state, g)
            _, labels = self.ops(("b", page, n, opc))
            return ("b", page, n, opc, labels[g])
        return ("b", tpage, n, opc, g)

    def state(self, st):
        """(fields, kind, cond, task, src, successors, halt, nochk) of a state."""
        key = st[:2] if st[0] == "l" else st[:4]
        ops, _ = self.ops(key)
        i = st[-1]
        if i >= len(ops):
            raise IndexError(f"{st}: past the block's end")
        op = ops[i]
        word = uc.hw_fields(op)
        halt = bool(op.get("HALT"))
        seq, cnd, irn = op.get("SEQ", uc.SEQ_NEXT), op.get("CND", 0), op.get("IRN", 0)
        task = seq == uc.SEQ_JUMPT
        nxt = st[:-1] + (i + 1,)
        in_task = st[0] == "l" and st[1] in self.task_routines
        if seq == uc.SEQ_END:
            return word, ("tend" if in_task else "end"), 0, False, 0, (), halt, \
                bool(op.get("_nochk"))
        if seq == uc.SEQ_NEXT:
            assert irn not in (uc.IRN_NS, uc.IRN_IDX) or st[0] == "l", (st, "a dispatch falling through")
            return word, "jump", TRUE, False, 0, (nxt,), halt, False
        tgt = self.target(st, op)
        c, inv = cnd & 15, cnd >> 4
        if irn in (uc.IRN_NS, uc.IRN_IDX) and st[0] == "b":
            assert c == TRUE and not inv, (st, "a conditional dispatch")
            src = uc.MW_S if irn == uc.IRN_NS else uc.MW_Z
            _, tpage, _, opc, step = tgt
            return word, "mw", 0, False, src, tuple(("b", tpage, v, opc, step) for v in range(16)), \
                halt, False
        if c == TRUE:
            return word, "jump", TRUE, task, 0, ((nxt if inv else tgt),), halt, False
        t_true, t_false = (nxt, tgt) if inv else (tgt, nxt)
        return word, "cond", c, task, 0, (t_true, t_false), halt, False

    def explore(self, roots):
        todo = list(roots)
        while todo:
            st = todo.pop()
            if st in self.states:
                continue
            try:
                s = self.state(st)
            except Exception as e:          # an unwritten block: it stops the machine
                if not isinstance(e, (IndexError,)) and type(e).__name__ != "Unimplemented":
                    raise
                s = (uc.hw_fields({}), "stop", 0, False, 0, (), True, False)
            self.states[st] = s
            todo.extend(s[5])


def minimise(states, region):
    """{state: class}: states that do the same with the same successors
    share a class."""
    keys = {}
    cls = {}
    for st, (word, kind, cond, task, src, succ, halt, nochk) in states.items():
        k = (tuple(sorted(word.items())), kind, cond, task, src, halt, nochk, region(st))
        cls[st] = keys.setdefault(k, len(keys))
    n = len(keys)
    while True:
        keys = {}
        new = {}
        for st, s in states.items():
            k = (cls[st], tuple(cls[t] for t in s[5]))
            new[st] = keys.setdefault(k, len(keys))
        if len(keys) == n:
            return new
        cls, n = new, len(keys)


class Layout:
    def __init__(self):
        self.mem = [None] * uc.CS_WORDS
        self.canon = {}
        self.queue = []
        self.ptr = {"main": [0x200, 0x200, 0x200], "task": [uc.TASK_BASE] * 3}
        self.end = {"main": uc.TASK_BASE, "task": uc.CS_WORDS}

    def put(self, node, a):
        assert self.mem[a] is None, (hex(a), node.name)
        self.mem[a] = node
        if node not in self.canon:
            self.canon[node] = a
            self.queue.append(node)

    def free(self, region, size):
        """The first free run of `size` words at a multiple of size."""
        k = {1: 0, 2: 1, 16: 2}[size]
        a = self.ptr[region][k]
        a = -(-a // size) * size
        while any(self.mem[a + i] is not None for i in range(size)):
            a += size
        if a + size > self.end[region]:
            raise RuntimeError(f"the control store's {region} region is full")
        self.ptr[region][k] = a
        return a

    def at(self, node):
        """node's address, placing it if it has none."""
        if node not in self.canon:
            self.put(node, self.free(node.region, 1))
        return self.canon[node]

    def pair(self, n0, n1, region):
        """An even address P with n0 at P and n1 at P + 1."""
        for x, y, off in ((n0, n1, 0), (n1, n0, 1)):
            a = self.canon.get(x)
            if a is not None and a & 1 == off:
                b = a ^ 1
                if self.mem[b] is y:
                    return a & ~1
                if self.mem[b] is None and (b >= 0x200 or region == "task"):
                    self.put(y, b)
                    return a & ~1
        p = self.free(region, 2)
        self.put(n0, p)
        self.put(n1, p + 1)
        return p


def compile_store(block, routines, ops_range=range(256)):
    """(the words' nodes by address, {node: (SEQ, CND, JT)}, the entries)."""
    g = Graph(block, routines)
    entries = {op: [("b", 0, d, op, 0) for d in range(16)] for op in ops_range}
    roots = [("l", "p3", 0), ("l", "copper", 0), ("l", "device", 0)] + \
        [s for v in entries.values() for s in v]
    g.explore(roots)

    def region(st):
        return "task" if st[0] == "l" and st[1] in g.task_routines else "main"
    cls = minimise(g.states, region)
    nodes = {}
    for st, c in cls.items():
        if c not in nodes:
            word, kind, cond, task, src, succ, halt, nochk = g.states[st]
            nodes[c] = Node(word, kind, succ, cond, task, src, halt, region(st), nochk,
                            name="/".join(str(x) for x in st))
    for nd in nodes.values():
        nd.succ = tuple(nodes[cls[t]] for t in nd.succ)
    entry = {}
    for op, sts in entries.items():
        cs = [nodes[cls[s]] for s in sts]
        if all(c is cs[0] for c in cs):
            entry[op] = cs[0]
            continue
        same = all(c.word == cs[0].word and c.kind == "jump" and not c.task and not c.halt
                   for c in cs)
        if same:            # the entry's word is every d's: the branch after it
            entry[op] = Node(cs[0].word, "mw", tuple(c.succ[0] for c in cs), src=uc.MW_D,
                             name=f"entry {op:02X}")
        else:
            entry[op] = Node(uc.hw_fields({}), "mw", tuple(cs), src=uc.MW_D,
                             name=f"entry {op:02X} (a branch)")
    lay = Layout()
    irq = nodes[cls[("l", "p3", 0)]]
    for a in range(uc.ENTRY_BASE):
        lay.put(irq, a)
    for op, nd in entry.items():
        lay.put(nd, uc.ENTRY_BASE + op)
    lay.put(nodes[cls[("l", "copper", 0)]], uc.COPPER_BASE)
    lay.put(nodes[cls[("l", "device", 0)]], uc.DEVICE_BASE)
    seqenc = {}
    while lay.queue:
        nd = lay.queue.pop(0)
        seq = uc.HSEQ_JUMPT if nd.task else uc.HSEQ_JUMP
        if nd.kind in ("end", "tend"):
            seqenc[nd] = (uc.HSEQ_END, 0, uc.NOCHK if nd.nochk else 0)
        elif nd.kind == "stop":
            seqenc[nd] = None           # filled with a jump to itself below
        elif nd.kind == "jump":
            seqenc[nd] = (seq, TRUE, lay.at(nd.succ[0]) ^ 1)
        elif nd.kind == "cond":
            t_true, t_false = nd.succ
            if t_true is t_false:
                seqenc[nd] = (seq, TRUE, lay.at(t_true) ^ 1)
            else:
                seqenc[nd] = (seq, nd.cond, lay.pair(t_false, t_true, nd.region))
        elif nd.kind == "mw":
            b = lay.free(nd.region, 16)
            for k, t in enumerate(nd.succ):
                lay.put(t, b + k)
            seqenc[nd] = (uc.HSEQ_MW, nd.src, b)
        else:
            raise ValueError(nd.kind)
    for nd, e in seqenc.items():
        if e is None:
            seqenc[nd] = (uc.HSEQ_JUMP, TRUE, lay.canon[nd] ^ 1)
    return lay, seqenc, entry, nodes


class ControlStore:
    """The flat store: `words` (packed, by address), `where` (a state each
    word came from), `halt` (the addresses of the stopped machine's word),
    `missing` (the opcodes not written, whose blocks stop the machine),
    `untimed` (the words without their ticks in the timing analysis's
    table, given the longest)."""

    def __init__(self, block, routines, ticks):
        lay, seqenc, entry, nodes = compile_store(block, routines)
        mask = uc.untimed_mask()
        self.words = [0] * uc.CS_WORDS
        self.where = [""] * uc.CS_WORDS
        self.halt = set()
        self.untimed = set()
        self.used = 0
        self.distinct = set()
        stop = None
        for a, nd in enumerate(lay.mem):
            if nd is None:
                continue
            self.used += 1
            if nd.halt:
                self.halt.add(a)
                stop = stop if stop is not None else lay.canon[nd]
            seq, cnd, jt = seqenc[nd]
            f = dict(nd.word, SEQ=seq, CND=cnd, JT=jt)
            two = bool(f.get("HLEN"))
            raw = uc.pack(f)
            t = ticks.get((raw & ~mask, two))
            if t is None:
                self.untimed.add((raw & ~mask, two))
                t = (4, 3 if two else 0)
            f.update(LEN=t[0] - 1, HLEN=t[1])
            self.words[a] = uc.pack(f)
            self.where[a] = nd.name
            self.distinct.add(raw & ~mask)
        hang = uc.pack(dict(uc.hw_fields({}), SEQ=uc.HSEQ_JUMP, CND=TRUE,
                            JT=(stop if stop is not None else 0) ^ 1))
        for a in range(uc.CS_WORDS):
            if lay.mem[a] is None:
                self.words[a] = hang
        self.distinct = len(self.distinct)
        self.entry = entry
        self.missing = {}
