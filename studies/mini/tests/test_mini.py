"""Heron Mini: the register-transfer model against the instruction-level
simulator, the boot, the address error, the netlist on the chip-level
simulator (a program exactly as the model runs it, the address error, the
devices, at the measured length classes and with no timing violation),
the measured periods current, the video's timing; the fast simulator
(sim.py, the Rust engine) against the model, with RFC 0042's video."""

import array
import math
import os
import unittest
from collections import defaultdict

import heron.studies.v2_isa  # noqa: F401
from heron.infra import asm as asmcore
from heron.infra import isas
from heron.infra.programs import metadata
from heron.studies.mini import board, check as chk, hw, rtl, sim, sta, system, timing, ucode as uc, video


HERE = os.path.dirname(os.path.abspath(__file__))


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

    def test_odt(self):
        # the debug button and ODT: hw.py's session, its transcript exactly
        # (the button found the loop's INC), the program going on as told
        img = asmcore.assemble_file(isas.get("v2"), hw.DEBUG)
        s = system.System(uart_inp=hw.ODT_SESSION)
        s.load(img)
        m = rtl.RTL(s)
        m.debug_at = 20_000
        m.run(5_000_000)
        self.assertEqual(m.out, hw.DEBUG_EXPECTED)
        out = bytes(s.uarts[0].out)
        self.assertTrue(hw.odt_transcript_ok(out))
        self.assertEqual(out, b"\r\n0000002A" + hw.ODT_ANSWERS[0] + b"0000002A" +
                         hw.ODT_ANSWERS[1] + b"0000002C" + hw.ODT_ANSWERS[2] + b"\r\n")

    def test_odt_at_reset(self):
        # an erased boot flash: reset enters ODT at PC 0, and G starts the
        # program in RAM
        img, _ = assemble("hello")
        s = system.System(uart_inp=b"G", boot=b"\xff" * 4)
        s.load(img)
        m = rtl.RTL(s).run(1_000_000)
        self.assertEqual(bytes(s.uarts[0].out), b"\r\n00000000\r\n@G\r\n")
        self.assertEqual(m.out, b"Hello, world!\n")

    def test_address_error(self):
        # a misaligned access traps at its instruction and changes nothing
        img, inp = assemble("addrerr")
        m = chk.run_rtl(img, inp)
        sim = chk.run_isa(img, inp)
        self.assertEqual(chk.compare(sim, m), [])
        self.assertEqual(len(sim.traps), 22)

    def test_block_count(self):
        # a block instruction's count isn't the condition latch an earlier
        # instruction left: FILL of 4 words after CL was set, of none
        # after it was cleared
        src = """
        .org 0x00
        JMP  start
        .org 0x1C
start:  MOV  sp, #0x100000
        MOV  r1, #0
        CLZ  r1, r1
        MOV  r1, #0x210000
        MOV  r2, #0x55555555
        MOV  r3, #4
        .half 0x01FD
        MOV  [0x1000], r1
        MOV  r1, #-1
        CLZ  r1, r1
        MOV  r1, #0x220000
        MOV  r3, #0
        .half 0x01FD
        MOV  [0x1004], r1
        HALT
"""
        a = asmcore.Assembler(isas.get("v2"))
        a.load("block.s", text=src)
        m = chk.run_rtl(a.assemble())
        ram = m.sys.ram
        word = lambda x: int.from_bytes(bytes(ram[x:x + 4]), "little")
        self.assertEqual([word(0x1000), word(0x1004)], [0x210010, 0x220000])
        self.assertEqual([word(0x210000 + 4 * i) for i in range(5)], [0x55555555] * 4 + [0])
        self.assertEqual(word(0x220000), 0)

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

    def test_ps2(self):
        out, text, diffs = hw.run_hwprog(hw.PS2, hw.PS2_EXPECTED, keyboard=hw.PS2_KEYS)
        self.assertEqual(diffs, [])
        self.assertEqual(out["violation_total"], 0)
        self.assertEqual(bytes(out["dumps"]["X_MOUSE"]), b"\xf4")

    def test_debug(self):
        # the debug button, ODT's session on UART 0, the program going on
        out, text, diffs = hw.run_hwprog(hw.DEBUG, hw.DEBUG_EXPECTED, debug_ps=hw.DEBUG_PS,
                                         uart_inp=hw.ODT_SESSION)
        self.assertEqual(diffs, [])
        self.assertEqual(out["violation_total"], 0)
        self.assertTrue(hw.odt_transcript_ok(bytes(out["dumps"]["U_UART0"])))

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
        # each family: its picture's pixels a line, its syncs, its lines,
        # a word for each of the picture's characters, the events in the
        # lines before the picture's
        rom = video.timing_rom()
        for f, sync, vsync in ((video.VGA, 96, 2), (video.XGA, 136, 6)):
            def held(h, v):   # what the register holds in character h of line v
                ph, pv = (h - 1, v) if h else (f.chars - 1, (v - 1) % f.lines)
                return rom[(f.xga << 18) | ph | (pv << 8)]
            line = [held(h, f.first + 100) for h in range(f.chars)]
            self.assertEqual(sum(8 for b in line if b >> video.DE & 1), f.width, f.name)
            self.assertEqual(sum(8 for b in line if not b >> video.HSYNC & 1), sync, f.name)
            shown = sum(1 for v in range(f.lines) if held(0, v) >> video.DE & 1)
            self.assertEqual(shown, f.height, f.name)
            vs = sum(1 for v in range(f.lines) if not held(10, v) >> video.VSYNC & 1)
            self.assertEqual(vs, vsync, f.name)
            loads = sum(1 for h in range(f.chars) for v in range(f.lines)
                        if held(h, v) >> video.SHLD & 1)
            self.assertEqual(loads, f.height * f.picture, f.name)
            evs = sorted(held(h, f.first + 5) >> video.EV0 & 7 for h in range(f.chars))
            self.assertEqual([e for e in evs if e], [1, 2, 3, 4, 7], f.name)

    def test_render(self):
        # a line's descriptor picks its words and its palette bank; the
        # cursor's tables put their pixels over it
        ram = bytearray(system.RAM_SIZE)
        pal = list(range(256))
        d = (1 << 19) | 0x1000                       # bank 1, word 0x1000 of bank 1
        a = video.BANK1 + 4 * video.VGA.table
        ram[a:a + 4] = d.to_bytes(4, "little")
        w = video.BANK1 + 4 * 0x1000
        ram[w:w + 4] = (0x32323232).to_bytes(4, "little")
        self.assertEqual(video.render(ram, pal)[0][:4], [0x12, 0x13, 0x12, 0x13])
        # M3, 2 bits a pixel: pixel p is bits 2p and 2p + 1
        self.assertEqual(video.render(ram, pal, 0x31)[0][:4], [0x12, 0x10, 0x13, 0x10])
        # M2: the bytes
        self.assertEqual(video.render(ram, pal, 0x21)[0][:2], [0x32, 0x32])
        c = video.BANK1 + 4 * (video.CURSOR0 + video.VGA.table)
        ram[c:c + 4] = (0b11100100).to_bytes(4, "little")    # pixels 0-3: 0, 1, 2, 3
        rows = video.render(ram, pal, 0x101, cursor_x=10)
        x = 10 + video.XSTART[0]
        self.assertEqual(rows[0][x:x + 4], [0x10, 253, 254, 255])  # 0 is transparent

    def test_sequencer(self):
        # every mode's shifter steps: eight a word, a word a word's time
        for mode, (f, bits, double) in video.MODES.items():
            ticks = f.ticks(32 // bits) * (2 if double else 1)
            shifts = loads = 0
            ph, px, c = 1, 7 if f.xga else 7, 0
            for n in range(ticks * 4):
                shift, load, _sel, _cs = board.sequence(mode, ph, px, c & 1, c >> 1 & 1, 1, 1,
                                                        1, 1)
                shifts += shift
                loads += load
                t = px if f.xga else 2 * px + ph
                t = (t + 1) % (8 if f.xga else 16)
                if t == 0:
                    c += 1
                ph, px = (1, t) if f.xga else (t & 1, t >> 1)
            self.assertEqual((shifts, loads), (32, 4), mode)


class Simulator(unittest.TestCase):
    def test_against_model(self):
        # cycle for cycle and tick for tick, with B0 (which never holds the
        # CPU), the interrupts and the address error
        for name in ("hello", "arith", "interrupts", "addrerr"):
            img, inp = assemble(name)
            r = chk.run_rtl(img, inp)
            m = sim.machine()
            m.console_input(inp)
            sim.load(m, img)
            self.assertEqual(m.run(10_000_000), "halted")
            self.assertEqual((m.cycles, m.ticks, m.instructions, m.output(), list(m.r), m.flags),
                             (r.cycles, r.ticks, r.instructions, r.out, r.r, r.flags_word()), name)

    def test_video_program(self):
        # sw/hw/video.s: the model's cycles with its frame interrupts, and
        # the frame shown is the reference rendering of the memory
        img = sim.assemble(os.path.join(HERE, "..", "sw", "hw", "video.s"))
        r = chk.run_rtl(img)
        m = sim.machine()
        sim.load(m, img)
        self.assertEqual(m.run(10_000_000), "halted")
        self.assertEqual((m.cycles, m.ticks, m.frames), (r.cycles, r.ticks, 3))
        w, h, data = m.frame()
        want = video.render(m.read(0, system.RAM_SIZE), r.sys.video.palette)
        self.assertEqual((w, h), (640, 480))
        self.assertEqual(list(array.array("H", data)), [c for row in want for c in row])

    def test_demo(self):
        # sw/video/demo.s: M5 from a frame base, the cursor, the beam
        m = sim.machine()
        sim.load(m, os.path.join(HERE, "..", "sw", "video", "demo.s"))
        self.assertEqual(m.run(50_000_000), "halted")
        line, char = m.output().split()
        self.assertEqual(int(line, 16), 0)
        self.assertLess(int(char, 16), 40)
        w, h, data = m.snapshot()
        self.assertEqual((w, h), (1024, 768))
        self.assertEqual(m.frame()[2], data)
        px = array.array("H", data)

        def at(x, y):
            return px[y * w + x]
        # colour (x/64 + y/64) mod 4: black, red, green, blue
        self.assertEqual([at(0, 0), at(64, 0), at(64, 64), at(0, 767)],
                         [0, 0xF800, 0x07E0, 0x001F])
        # the cursor at (500, 300): a yellow top edge, white sides
        self.assertEqual([at(500, 300), at(531, 300), at(500, 301), at(531, 331), at(501, 301)],
                         [0xFFE0, 0xFFE0, 0xFFFF, 0xFFE0, 0x001F])


if __name__ == "__main__":
    unittest.main()
