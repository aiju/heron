"""What one-parcel forms of a field access would save in a draft 1b run.

The simulator counts executions per (instruction address, timing key).
A scan decodes each executed instruction from the run's memory and keeps
the word accesses at [R + d], d = 4..60 and a multiple of 4: the ones a
fixed-base mode [rT + 4R] makes one parcel when R is rT. What each would
save is the timing model's cycles for its key less those for the same
key one parcel shorter, so a scan answers, from one baseline run, what
any choice of rT, or of another short form, would save.

Runs can be added and subtracted (a program's run less its start-up),
and limited to some addresses (the nucleus without its user programs).
"""

from collections import Counter, defaultdict

from heron import native

CONFIGS = ["D32-separate", "D32-wide"]
EA_KINDS = ("ld", "st", "op", "lea", "jmpm", "callm")
OPNAME = {1: "MOV", 2: "ST", 3: "LEA", 4: "ADD", 5: "SUB", 6: "CMP", 7: "AND", 8: "OR",
          9: "XOR", 0xB: "JMP"}
FIELDS = range(4, 61, 4)
BRANCH_NZ = (0, 1, 4, 5)        # Bcc on EQ, NE, MI, PL

_cycles = {}


def cycles(key, config):
    k = (key, config)
    if k not in _cycles:
        _cycles[k] = native.v1.cycles(key, config)
    return _cycles[k]


def sext16(v):
    return v - 0x10000 if v & 0x8000 else v


class Scan:
    def __init__(self):
        self.instr = 0
        self.cycles = Counter()            # config -> cycles
        # (base, disp, op) -> Counter: n, and cycles saved by config
        self.fields = defaultdict(Counter)
        # absolute 16-bit word addresses -> n (two parcels each now)
        self.abs16 = Counter()

    def add(self, pc_keys, parcel, weight=1, pcs=None):
        """pc_keys: [(pc, key, count)]; parcel(addr): the 16-bit parcel
        there; weight: -1 subtracts; pcs: only these addresses count."""
        for pc, key, count in pc_keys:
            if pcs is not None and pc not in pcs:
                continue
            count *= weight
            self.instr += count
            for c in CONFIGS:
                self.cycles[c] += count * cycles(key, c)
            if pc is None or key[2] not in EA_KINDS or key[0] != 2:
                continue
            w = parcel(pc)
            op, mode, r = w >> 12, (w >> 4) & 15, w & 15
            if op not in OPNAME:
                continue
            if mode == 0xF and r == 4:
                self.abs16[sext16(parcel(pc + 2)) & 0xFFFFFFFF] += count
            if mode != 3 or key[3] != "rd":
                continue
            d = sext16(parcel(pc + 2))
            if d not in FIELDS:
                continue
            short = (1,) + tuple(key[1:])
            f = self.fields[(r, d, OPNAME[op])]
            f["n"] += count
            nxt = parcel(pc + 4)
            if op == 1 and nxt >> 12 == 0xE and (nxt >> 8) & 15 in BRANCH_NZ:
                # a load whose flags a branch reads: draft 2's MOVS
                f["flags"] += count
            for c in CONFIGS:
                f[c] += count * (cycles(key, c) - cycles(short, c))
        return self

    def add_machine(self, m, weight=1, pcs=None):
        """Add a machine's run (a Machine32, or the native machine)."""
        nm = getattr(m, "_m", m)
        return self.add(nm.pc_keys(), nm.parcel, weight, pcs)

    def saves(self, bases=None, disps=FIELDS, ops=None):
        """Counter of n and cycles saved (by config) by a one-parcel form
        for the accesses with base in `bases` (None: any), displacement in
        `disps`, operation in `ops` (None: any)."""
        out = Counter()
        for (r, d, op), f in self.fields.items():
            if (bases is None or r in bases) and d in disps and (ops is None or op in ops):
                out.update(f)
        return out

    def by_base(self, config="D32-separate"):
        """Counter of base register -> cycles a fixed rT there would save."""
        out = Counter()
        for (r, d, op), f in self.fields.items():
            out[r] += f[config]
        return out

    def ops(self, base):
        """Counter of operation -> accesses, for one base; 'MOVS' counts
        the loads a branch on N or Z follows directly (in 1b, MOV sets
        them; in draft 2 these would be MOVS), and 'MOV' the rest."""
        out = Counter()
        for (r, d, op), f in self.fields.items():
            if r == base:
                out[op] += f["n"] - f["flags"]
                if f["flags"]:
                    out["MOVS"] += f["flags"]
        return out

    def pct(self, saved, config):
        """saved cycles as a percentage of this scan's cycles"""
        return 100 * saved[config] / self.cycles[config] if self.cycles[config] else 0.0
