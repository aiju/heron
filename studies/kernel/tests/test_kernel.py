"""The kernel study: v1bs's system extensions (report 0020's appendix) on the
simulator, the nucleus's scenarios on every register-bank variant, the
small routines, and the page statistics."""

import unittest

from heron.infra import asm as asmcore
from heron.infra import isas
from heron.studies.kernel import bench, build, micro
from heron.studies.v1_isa.sim32 import Machine32

import heron.studies.kernel  # noqa: F401  (registers v1bs)

# A supervisor for the tests: user code at virtual 0 (physical 0x1000) in
# context 1, a stack page at virtual 0x1000 (physical 0x2000), a read-only
# page at virtual 0x3000, and the user's program at the end (assembled at
# 0x1000, run at 0: no PC-relative jumps out of it). Traps leave what the
# test wants in r9-r12 and halt.
SUPERVISOR = """
        .org 0x00
        JMP  start
        .org 0x08
        JMP  stop
        .org 0x0C
        JMP  swi
        .org 0x1C
        JMP  stop
        .org 0x20
        JMP  fault
        .org 0x40
start:  MOV  sp, #0x800
        MOV  r1, #SYSCTL
        MTSR sysctl, r1
        MOV  r1, #3
        MTSR bank, r1
        MOV  r1, #1
        MTSR ctx, r1
        MOV  r1, #0x1000
        MTSR mapa, r1
        MOV  r1, #0x1007
        MTSR mapd, r1
        MOV  r1, #0x2003
        MTSR mapd, r1
        MOV  r1, #0x1003        ; virtual 0x3000: read-only, physical 0x4000
        MTSR mapa, r1
        MOV  r1, #0x4001
        MTSR mapd, r1
        MOV  r1, #0x2000
        MTUR sp, r1
        MOV  r1, #0x77
        MTUR r9, r1             ; the user starts with r9 = 0x77
        ST   r0, -[sp]
        MOV  r1, #FLAGS
        ST   r1, -[sp]
        RTI
swi:    MFSR r9, fsr            ; (r9-r12 are the nucleus's with banks)
        MFUR r10, r1
        MFUR r11, r9
        MFSR r12, flags
        HALT
fault:  MFSR r9, far
        MFSR r10, fsr
        MOV  r11, [sp + 4]
        HALT
stop:   MOV  r9, #0xDEAD
        MOV  r10, [sp + 4]      ; the PC
        HALT
        .org 0x1000
"""


def boot(user, sysctl=1, flags=0):
    src = SUPERVISOR.replace("SYSCTL", str(sysctl)).replace("FLAGS", str(flags)) + user
    img = asmcore.assemble_text(isas.get("v1bs"), src)
    m = Machine32(isas.get("v1bs"), img)
    m.run(100_000)
    return m


class System(unittest.TestCase):
    def test_swi_number_and_user_registers(self):
        m = boot("        MOV r1, #42\n        SWI #7\n")
        self.assertEqual(m.r[9:13], [7, 42, 0x77, 0x20])     # fsr, user r1, user r9, S set
        self.assertEqual(m._m.sys["s"], 1)

    def test_privileged_instructions_trap(self):
        for insn in ("EI", "DI", "HALT", "RTI", "MTSR ctx, r1", "MFSR r1, far", "MFUR r1, r2"):
            m = boot(f"        NOP\n        {insn}\n")
            self.assertEqual((m.r[9], m.r[10]), (0xDEAD, 2), insn)
            self.assertEqual(m.traps, [(2, "privileged instruction")], insn)

    def test_mtf_in_user_mode_changes_only_nzcv(self):
        m = boot("        MOV r1, #0xFF\n        MTF r1\n        MFF r1\n        SWI #0\n",
                 flags=0x10)
        self.assertEqual(m.r[10], 0x1F)      # I stays on, S stays off; N Z C V set

    def test_page_fault_is_precise(self):
        # [r2]+ to an unmapped page: the fault leaves r2 as it was
        m = boot("        MOV r2, #0x5000\n        MOV r1, [r2]+\n")
        self.assertEqual(m.r[9:12], [0x5000, 1, 4])           # far, fsr invalid, the PC
        self.assertEqual(m._m.bank(3)[2], 0x5000)

    def test_fetch_fault(self):
        m = boot("        MOV r1, #0x7000\n        JMP r1\n")
        self.assertEqual(m.r[9:12], [0x7000, 0x21, 0x7000])  # invalid, fetch
        m = boot("        MOV r1, #0x3000\n        JMP r1\n")
        self.assertEqual(m.r[10], 0x24)                      # not executable, fetch

    def test_out_of_range_and_write_protect(self):
        m = boot("        MOV r2, #0x1000000\n        MOV r1, [r2]\n")
        self.assertEqual(m.r[10], 8)                         # beyond the 16 MB
        m = boot("        MOV r2, #0x3000\n        MOV r1, [r2]\n        ST r1, [r2]\n")
        self.assertEqual(m.r[9:12], [0x3000, 0x12, 6])       # write-protected, a store

    def test_bank_policies(self):
        # with no banks, the handler's MFSR r9 has overwritten the user's r9
        # before MFUR reads it; with half banks r1 is shared and r9 the
        # user's own; with full banks both are the user's
        user = "        MOV r1, #42\n        SWI #0\n"
        self.assertEqual(boot(user, sysctl=0).r[10:12], [42, 0])
        self.assertEqual(boot(user, sysctl=2).r[10:12], [42, 0x77])
        self.assertEqual(boot(user, sysctl=1).r[10:12], [42, 0x77])

    def test_plain_1b_traps_on_system_registers(self):
        img = asmcore.assemble_text(isas.get("v1bs"),
                                    "        MOV sp, #0x800\n        MFUR r1, r2\n        HALT\n")
        m = Machine32(isas.get("v1b"), img)
        m.run(1000)
        self.assertEqual(m.traps[0][1], "illegal instruction")
        self.assertIsNone(m._m.sys)


class Preprocessor(unittest.TestCase):
    def test_if_else(self):
        text = ".if a\nA\n.else\nB\n.endif\n.if !a|c\nC\n.endif"
        self.assertEqual(build.preprocess(text, {"a"}).split("\n"), ["", "A", "", "", "", "", "", ""])
        self.assertEqual(build.preprocess(text, {"c"}).split("\n"), ["", "", "", "B", "", "", "C", ""])


class Nucleus(unittest.TestCase):
    """Every scenario on every variant: the output is right, no thread
    faults, and the costs are in a sane range."""

    def test_scenarios(self):
        for s in bench.SCENARIOS:
            for b in build.BANKS:
                r = bench.measure(s, b)
                c = r.per_op[bench.CONFIG]
                self.assertGreater(c, 20, f"{s.name} {b}")
                self.assertLess(c, 10_000, f"{s.name} {b}")

    def test_banks_save_work(self):
        ipc = {b: bench.measure("ipc", b).per_op[bench.CONFIG] for b in build.BANKS}
        self.assertLess(ipc["half"], ipc["none"])
        pre = {b: bench.measure("preempt", b).per_op[bench.CONFIG] for b in build.BANKS}
        self.assertLess(pre["full"], pre["half"])
        self.assertLess(pre["half"], pre["none"])


class Micro(unittest.TestCase):
    def test_runs(self):
        t = micro.table(["calls", "globals", "coswitch"])
        self.assertEqual(t["calls"]["v1b"][0]["D32-separate"], 8)


class Pages(unittest.TestCase):
    def test_counts(self):
        from heron.studies.kernel import pages
        st = pages.measure(["asm-vm"])[0]
        self.assertEqual(st.p["fetch"]["refs"], st.instructions)
        self.assertEqual(st.lru_misses("both", 64), st.p["both"]["cold"])


if __name__ == "__main__":
    unittest.main()
