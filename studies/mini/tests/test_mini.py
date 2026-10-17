"""Heron Mini: the register-transfer model against the instruction-level
simulator, the boot, the address error, the netlist on the chip-level
simulator (a program exactly as the model runs it, the address error, the
devices, at the measured length classes and with no timing violation),
the measured periods current, the video's timing."""

import math
import unittest
from collections import defaultdict

import heron.studies.v2_isa  # noqa: F401
from heron.infra import asm as asmcore
from heron.infra import isas
from heron.infra.programs import metadata
from heron.studies.mini import board, check as chk, hw, rtl, sta, system, timing, ucode as uc, video


def assemble(name):
    p = chk.program_paths([name])[0]
    return asmcore.assemble_file(isas.get("v2"), p), metadata(p)["input"]


class Model(unittest.TestCase):
    def test_against_isa(self):
        for name in ("hello", "strings", "arith"):
            img, inp = assemble(name)
            m = chk.run_rtl(img, inp)
            sim = chk.run_isa(img, inp)
            self.assertEqual(chk.compare(sim, m), [], name)

    def test_boot(self):
        # reset copies the boot flash's image to RAM and starts it
        img, _ = assemble("hello")
        words = (max(img.mem) + 4) // 4
        ram = bytearray(4 * words)
        for a, b in img.mem.items():
            ram[a] = b
        s = system.System(boot=words.to_bytes(4, "little") + bytes(ram))
        m = rtl.RTL(s).run(100_000)
        self.assertEqual(m.out, b"Hello, world!\n")

    def test_address_error(self):
        # a misaligned access traps at its instruction and changes nothing
        img, inp = assemble("addrerr")
        m = chk.run_rtl(img, inp)
        sim = chk.run_isa(img, inp)
        self.assertEqual(chk.compare(sim, m), [])
        self.assertEqual(len(sim.traps), 22)

    def test_io_hold(self):
        # region r holds an access 16 - 2r ticks
        self.assertEqual([system.IO_HOLD[r] for r in range(8)], [16, 14, 12, 10, 8, 6, 4, 2])


class ChipLevel(unittest.TestCase):
    def test_hello(self):
        m, out, diffs = hw.check(chk.program_paths(["hello"])[0])
        self.assertEqual(diffs, [])
        self.assertEqual(out["violation_total"], 0)
        self.assertEqual(out["output"], b"Hello, world!\n")

    def test_power_up(self):
        # whatever state the flip-flops come up in, the machine runs
        for seed in (2, 3):
            m, out, diffs = hw.check(chk.program_paths(["hello"])[0], seed=seed)
            self.assertEqual(diffs, [], seed)
            self.assertEqual(out["violation_total"], 0, seed)

    def test_address_error(self):
        m, out, diffs = hw.check(chk.program_paths(["addrerr"])[0])
        self.assertEqual(diffs, [])
        self.assertEqual(out["violation_total"], 0)

    def test_devices(self):
        out, uarts, diffs = hw.run_devices()
        self.assertEqual(diffs, [])
        self.assertEqual(out["violation_total"], 0)

    def test_netlists(self):
        # both build and pass the netlist's checks
        board.build(sim=True, capture=True)
        board.build(sim=False)


class Timing(unittest.TestCase):
    def test_every_microinstruction_measured(self):
        self.assertEqual(uc.built().estimated, 0)

    def test_table_is_current(self):
        # if this fails, the netlist (or the microcode) changed: run
        # `heron mini hw sta --write`
        ns = defaultdict(float)
        for T, w, *_rest in sta.analyse(force=True):
            self.assertLess(T, math.inf)
            ns[f"{w:x}"] = max(ns[f"{w:x}"], round(T, 1))
        self.assertEqual(dict(ns), timing.measured())


class Video(unittest.TestCase):
    def test_timing_rom(self):
        # VGA 640 x 480: per line 640 pixels shown, a 96-pixel sync; per
        # frame 480 lines shown, a 2-line sync
        rom = video.timing_rom()

        def held(h, v):           # what the register holds in character h of line v
            ph, pv = (h - 1, v) if h else (video.H_CHARS - 1, (v - 1) % video.V_LINES)
            return rom[ph | (pv << 7)]
        line = [held(h, 100) for h in range(video.H_CHARS)]
        self.assertEqual(sum(8 for b in line if b >> video.DE & 1), 640)
        self.assertEqual(sum(8 for b in line if not b >> video.HSYNC & 1), 96)
        shown = sum(1 for v in range(video.V_LINES) if held(0, v) >> video.DE & 1)
        self.assertEqual(shown, 480)
        vsync = sum(1 for v in range(video.V_LINES) if not held(10, v) >> video.VSYNC & 1)
        self.assertEqual(vsync, 2)
        loads = sum(1 for h in range(video.H_CHARS) for v in range(video.V_LINES)
                    if held(h, v) >> video.SHLD & 1)
        self.assertEqual(loads, 480 * video.WORDS)

    def test_render(self):
        # a line's descriptor picks its words and its palette bank
        ram = bytearray(system.RAM_SIZE)
        pal = [0] * 256
        pal[0x12], pal[0x13] = 0x1234, 0x5678
        d = (1 << 19) | 0x1000                       # bank 1, word 0x1000 of bank 1
        a = video.BANK1 + 4 * video.TABLE
        ram[a:a + 4] = d.to_bytes(4, "little")
        w = video.BANK1 + 4 * 0x1000
        ram[w:w + 4] = (0x32323232).to_bytes(4, "little")
        rows = video.render(ram, pal)
        self.assertEqual(rows[0][:4], [0x1234, 0x5678, 0x1234, 0x5678])


if __name__ == "__main__":
    unittest.main()
