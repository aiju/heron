"""The instruction profiles: what they record about small programs whose
answers are known, the hardware shadow against the whole RTL machine, and
the database."""

import os
import sqlite3
import tempfile
import unittest

from heron.infra import asm as asmcore
from heron.infra import isas
from heron.studies.v1_isa.sim32 import Machine32
from heron.studies.v1_isa.testing import metadata, program_paths
from heron.studies.v1b_hw import rtl_native
from heron.studies.v1b_profile import collect as C
from heron.studies.v1b_profile import traces

ISA = isas.get("v1b")

FLOW = """
start:  MOV  sp, #0x8000
        MOV  r1, #5
        MOV  r2, #3             ; never read
        MOV  r2, #4
        ADD  r1, r2             ; its flags are never read
        CMP  r1, #9
        BEQ  ok
        HALT
ok:     MOV  r3, #10
loop:   DEC  r3, r3
        BNE  loop
        BSR  f
        HALT
f:      MOV  r4, r3
        RET
"""

# the MOV at `patch` becomes MOV r1, #7 (0x1117) after its first run
SELF_MODIFYING = """
start:  MOV  r5, #2
patch:  MOV  r1, #1
        DEC  r5, r5
        BEQ  done
        MOV  r2, #0x1117
        LEA  r6, [patch]
        ST   r2, half [r6]
        BRA  patch
done:   HALT
"""


def profile(src):
    img = asmcore.assemble_text(ISA, src)
    m = Machine32(ISA, img)
    C.attach(m)
    m.run(max_cycles=1_000_000)
    res = C.results(m)
    return m, res, C.rows(res, C.Symbols.of(img), ISA)


def by_text(tables):
    """{disassembly: insn row as a dict}"""
    cols = ["id", "code", "pc", "phys", "version", "class", "count", "hw_cycles", "hw_unknown",
            "hw_min", "hw_max", *C.MODEL, "taken", "irqs", "traps", "reg_defs", "reg_defs_used",
            "n_defs", "n_used", "z_defs", "z_used", "c_defs", "c_used", "v_defs", "v_used"]
    out = {}
    for r in tables["insn"]:
        d = dict(zip(cols, r))
        out[r[1][4]] = d
    return out


class Flow(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.m, cls.res, cls.t = profile(FLOW)
        cls.insn = by_text(cls.t)

    def test_counts_and_hardware_costs(self):
        i = self.insn
        self.assertEqual(self.res["mismatches"], 0)
        self.assertEqual(i["DEC r3, r3"]["count"], 10)
        # hardware.md's table: MOV #q 1, ADD 2, branches 2, BSR and RET 5
        self.assertEqual(i["MOV r1, #5"]["hw_cycles"], 1)
        self.assertEqual(i["ADD r1, r2"]["hw_cycles"], 2)
        self.assertEqual(i["BNE loop"]["hw_cycles"], 20)
        self.assertEqual(i["BSR f"]["hw_cycles"], 5)
        self.assertEqual(i["RET"]["hw_cycles"], 5)
        self.assertEqual(i["BNE loop"]["taken"], 9)
        self.assertEqual(i["BEQ ok"]["taken"], 1)

    def test_register_def_use(self):
        i = self.insn
        self.assertEqual((i["MOV r2, #3"]["reg_defs"], i["MOV r2, #3"]["reg_defs_used"]), (1, 0))
        self.assertEqual((i["MOV r2, #4"]["reg_defs"], i["MOV r2, #4"]["reg_defs_used"]), (1, 1))
        ids = {d["id"]: text for text, d in i.items()}
        pairs = {(ids[w], ids[r], reg): (n, dist) for w, r, reg, n, dist in self.t["reg_use"]}
        self.assertEqual(pairs[("MOV r1, #5", "ADD r1, r2", "r1")], (1, 3))
        self.assertEqual(pairs[("DEC r3, r3", "DEC r3, r3", "r3")], (9, 18))

    def test_flag_def_use(self):
        i = self.insn
        add = i["ADD r1, r2"]
        self.assertEqual((add["z_defs"], add["z_used"], add["c_defs"], add["c_used"]), (1, 0, 1, 0))
        self.assertEqual(i["CMP r1, #9"]["z_used"], 1)
        ids = {d["id"]: text for text, d in i.items()}
        flags = {(ids[w], ids[r]): (f, n) for w, r, f, n in self.t["flag_use"]}
        self.assertEqual(flags[("DEC r3, r3", "BNE loop")], ("Z", 10))

    def test_edges(self):
        ids = {d["id"]: text for text, d in self.insn.items()}
        edges = {(ids[s], dst_pc): (kind, fall, n) for s, dst_pc, _, kind, fall, n in self.t["edge"]}
        loop = self.insn["DEC r3, r3"]["pc"]
        self.assertEqual(edges[("BNE loop", loop)], ("next", 0, 9))
        # nothing ran after the last HALT
        self.assertFalse([e for e in edges if e[0] == "HALT"])

    def test_functions(self):
        funcs = {name: (calls, incl[:2]) for _, name, calls, *incl in self.t["func"]}
        # f: MOV (2 cycles) and RET (5)
        self.assertEqual(funcs["f"], (1, [2, 7]))


class Versions(unittest.TestCase):
    def test_changed_code_gets_a_version(self):
        _, res, t = profile(SELF_MODIFYING)
        rows = [(r[2], r[4], r[1][4], r[6]) for r in t["insn"]]
        patch = [r for r in rows if r[2].startswith("MOV r1")]
        self.assertEqual([(v, text, n) for _, v, text, n in patch],
                         [(0, "MOV r1, #1", 1), (1, "MOV r1, #7", 1)])
        self.assertEqual(patch[0][0], patch[1][0])


class Shadow(unittest.TestCase):
    """The shadow's cost of every instruction against the whole RTL
    machine's, from one opcode fetch to the next. The ends differ in how
    they're counted: the machine gives the reset routine the first
    instruction's fetch, and the shadow gives each instruction the next
    one's (the last HALT has none)."""

    def check(self, name):
        path = program_paths([name], "v1b")[0]
        meta = metadata(path)
        img = asmcore.assemble_file(ISA, path)
        m = Machine32(ISA, img, inp=meta["input"])
        C.attach(m)
        m.run(max_cycles=meta["max-cycles"])
        res = C.results(m)
        self.assertEqual((res["mismatches"], res["shadow_errors"], res["hw_unknown"]), (0, 0, 0))
        pcs = {row[0][0]: row[0][1] for row in res["insns"]}
        shadow = {}
        for idx, _, hw, n, _ in res["keys"]:
            shadow[pcs[idx]] = shadow.get(pcs[idx], 0) + hw * n
        whole = rtl_native.run(img, meta["input"])
        rtl = dict(whole.pc_cycles())
        self.assertEqual(sum(shadow.values()), whole.cycles)
        ends = {0, m.pc - 2}
        self.assertEqual({p: c for p, c in shadow.items() if p not in ends},
                         {p: c for p, c in rtl.items() if p not in ends})

    def test_life(self):
        self.check("life")

    def test_mandel(self):
        # multiplies take 16 or 32 steps, by their operands
        self.check("mandel")

    def test_vm(self):
        self.check("vm")


class Database(unittest.TestCase):
    def test_store_load_merge(self):
        d = tempfile.mkdtemp()
        a, b = os.path.join(d, "a.db"), os.path.join(d, "b.db")
        _, res, tables = profile(FLOW)
        row = dict(name="test/flow", study="test", program="flow", isa="v1b", **C.totals(res))
        db = C.Database(a)
        db.store(row, tables)
        db.store(row, tables)                   # replaces it
        self.assertEqual(db.names(), ["test/flow"])
        loaded = db.load("test/flow")
        db.close()
        other = C.Database(b)
        other.store(*loaded)
        other.prune()
        other.close()
        con = sqlite3.connect(b)
        n, hw = con.execute("SELECT SUM(count), SUM(hw_cycles) FROM insns").fetchone()
        self.assertEqual(n, row["instructions"])
        self.assertEqual(hw, row["hw_cycles"])
        mix = dict(con.execute("SELECT kind, count FROM mix"))
        self.assertEqual(mix["Bcc"], 11)
        self.assertEqual(con.execute("SELECT COUNT(*) FROM code").fetchone()[0], len(tables["insn"]))
        con.close()


class Catalogue(unittest.TestCase):
    def test_names(self):
        ts = traces.all_traces()
        names = [t.name for t in ts]
        self.assertEqual(len(names), len(set(names)))
        studies = {t.study for t in ts}
        for s in ("v1_isa", "c_compiler", "lisp", "graphics", "kernel", "egret"):
            self.assertIn(s, studies)
        self.assertEqual([t.name for t in traces.select(["v1_isa/fib"])], ["v1_isa/fib"])
        self.assertTrue(all(t.name.endswith("/compiled") for t in traces.select(["lisp/*/compiled"])))


if __name__ == "__main__":
    unittest.main()
