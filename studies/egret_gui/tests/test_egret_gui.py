"""The GUI: the simulator's display, keyboard and mouse; the desktop
booting at both depths; the Workspace running code; the apps opening
without errors; and snapshots."""

import struct
import unittest

from heron import native
from heron.infra import asm, isas
from heron.studies.egret_gui import run, snapshot

# the same program for both: write VRAM, set a palette entry, read an event
DEVICES = """
        .org 0
        LI   r1, #0x01000000
        LI   r2, #0x12345678
        ST   r2, [r1 + 640]
        MOV  r3, byte [r1 + 641]
        ST   r3, [0xFFFFFF00]            ; the console: 0x56
        LI   r2, #7
        ST   r2, [0xFFFFFF30]           ; palette index 7
        LI   r2, #0xABCDEF
        ST   r2, [0xFFFFFF34]
        MOV  r4, [0xFFFFFF20]           ; an event
        ST   r4, [0x100]
        MOV  r4, [0xFFFFFF20]           ; none left: -1
        ST   r4, [0x104]
        MOV  r4, [0xFFFFFF24]           ; the mouse
        ST   r4, [0x108]
        HALT
"""


class Devices(unittest.TestCase):
    def test_display_and_input(self):
        img = asm.assemble_text(isas.get("v1b"), DEVICES)
        ram = bytearray(run.RAM_SIZE)
        for a, b in img.mem.items():
            ram[a] = b
        m = native.v1.Machine("v1b", bytes(ram))
        m.push_event(0x1000_0041)
        m.set_mouse(12, 34, 1)
        m.run()
        self.assertEqual(m.vram[640:644], bytes([0x78, 0x56, 0x34, 0x12]))
        self.assertEqual(m.out, bytes([0x56]))
        self.assertEqual(m.palette[7], 0xABCDEF)
        words = struct.unpack("<3I", m.mem[0x100:0x10C])
        self.assertEqual(words, (0x1000_0041, 0xFFFF_FFFF, 12 | 34 << 16))


def workspace_do(s, code, settle=3):
    """Raise the Workspace (its title bar), add a line of code, do it."""
    s.click(200, 50)
    s.key("end", ["ctrl"])
    s.type("\n" + code)
    s.key("d", ["ctrl"])
    s.run(settle)


class Desktop(unittest.TestCase):
    def setUp(self):
        self.s = run.Session().boot()
        self.s.run(3)

    def test_boots(self):
        self.assertIn("Egret desktop ready", self.s.output)
        self.assertNotIn("error", self.s.output)

    def test_workspace_runs_code(self):
        workspace_do(self.s, "print(6 * 7, \"from the test\")")
        self.assertIn("42 from the test", self.s.output)

    def test_errors_are_caught(self):
        workspace_do(self.s, "Window(\"x\", 10, 10, 50, 50).no_such_method")
        workspace_do(self.s, "print(\"still here\")")
        self.assertIn("still here", self.s.output)

    def test_class_source_with_edits(self):
        # a class's source is its class statement as booted, with what a
        # Workspace changed in place and what it added at the end
        workspace_do(self.s, 'print(class_source(Clock).first, class_source(Clock).last)')
        self.assertIn("class Clock < Window end", self.s.output)
        workspace_do(self.s, 'record_edits("class Clock\\n  def tick(t) = nil\\n  def hello = 1\\nend")')
        workspace_do(self.s, 'c = class_source(Clock); print(c.index("  def tick(t) = nil") != nil, c[-2])', 4)
        self.assertIn("true   def hello = 1", self.s.output)

    def test_apps_open(self):
        for k in ["Life", "Mandel", "Paint", "Browser", "About"]:
            workspace_do(self.s, f"{k}()")
        self.assertNotIn("error", self.s.output)
        self.assertEqual(len(self.s.output.splitlines()), 1)


class Snapshots(unittest.TestCase):
    def test_one_bit_boots(self):
        s = run.Session(depth=0).boot()
        s.run(1)
        self.assertNotIn("error", s.output)
        self.assertEqual(s.m.depth, 0)
        # black and white, and both used
        self.assertEqual(set(s.rgb()), {0, 255})

    def test_layout(self):
        snap = snapshot.cold()
        self.assertEqual(snap[:8], b"HERONSNP")
        ram, vram, inp = struct.unpack("<3I", snap[124:136])
        self.assertEqual(len(snap), 1160 + ram + vram + inp)
        self.assertIn(b"DESK.run", snap[-inp:])


if __name__ == "__main__":
    unittest.main()
