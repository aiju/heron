"""The register-transfer model in Rust (rtl/, rtl_native.py) against
rtl.py: the same cycles, output, registers, flags, memory and cycles per
instruction address."""

import unittest
from collections import Counter

from heron.infra import asm as asmcore
from heron.infra import isas
from heron.studies.v1_isa.testing import metadata, program_paths
from heron.studies.v1b_hw import rtl_native
from heron.studies.v1b_hw.rtl import RTL


def python_rtl(img, inp):
    r = RTL(img, inp=inp)
    r.fetch_log = []
    r.run()
    log = [f for f in r.fetch_log if f[0] >= 0]
    pcs = Counter()
    for (c0, a0, _), (c1, _, _) in zip(log, log[1:]):
        pcs[a0] += c1 - c0
    if log:
        pcs[log[-1][1]] += r.cycles - log[-1][0]
    return r, dict(pcs)


class RustRTL(unittest.TestCase):
    def check(self, name):
        path = program_paths([name], "v1b")[0]
        meta = metadata(path)
        img = asmcore.assemble_file(isas.get("v1b"), path)
        r, pcs = python_rtl(img, meta["input"])
        n = rtl_native.run(img, meta["input"])
        self.assertEqual(n.cycles, r.cycles)
        self.assertEqual(n.out, r.out)
        self.assertEqual(list(n.rf), r.rf)
        self.assertEqual(n.pc, r.PC)
        self.assertEqual(n.flags, (r.n, r.z, r.c, r.v, r.i))
        self.assertEqual(n.mem, bytes(r.mem))
        self.assertEqual(dict(n.pc_cycles()), pcs)

    def test_bignum(self):
        self.check("bignum")

    def test_strings(self):
        self.check("strings")

    def test_interrupts(self):
        # the timer and interrupt entry
        self.check("interrupts")


if __name__ == "__main__":
    unittest.main()
