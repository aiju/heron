"""The Egret desktop and Egretica (studies/egret_gui) on 1b and on v1bl.

The desktop is in pull request 35, not yet on main; this runs when the
egret_gui study is there. Its image for v1bl is built as
egret_gui/build.py builds 1b's, from v1bl's pieces: the C compiled for
v1bl, the edited graphics kernels (graphics.py), Egret's interpreter for
v1bl (egret.py) and the desktop's start code with setjmp and longjmp
keeping r7.

The measurements are a selection of egret_gui/bench.py's, the same way:
an action's cost is the cycles spent while it's dealt with, less what the
idle loop would have spent in the time. Here in two currencies, the
reference configuration's busy cycles (as the bench) and the 1b
hardware's (hw.py, idle subtracted the same way).
"""

import os
import re
from collections import Counter

from heron import native
from . import egret as E, graphics as G, hw

RT_EDITS = [("""        ST   sp, [r1 + 28]
        MOV  r2, [sp]
        ST   r2, [r1 + 32]""", """        ST   sp, [r1 + 28]
        ST   r7, [r1 + 32]      ; v1bl: the return address"""),
            ("""        MOV  sp, [r1 + 28]
        MOV  r3, [r1 + 32]
        ST   r3, [sp]""", """        MOV  sp, [r1 + 28]
        MOV  r7, [r1 + 32]      ; v1bl: setjmp's return address""")]


def available():
    try:
        import heron.studies.egret_gui.run  # noqa: F401
    except ImportError:
        return False
    return True


def _rt_v1bl(src_dir):
    with open(os.path.join(src_dir, "rt_v1b.s")) as f:
        src = f.read()
    for a, b in RT_EDITS:
        if src.count(a) != 1:
            raise RuntimeError(f"egret_gui's rt_v1b.s has changed: {a!r}")
        src = src.replace(a, b)
    return src


def _units(p, isa):
    from heron.studies.c_compiler.cc import driver
    objs = []
    for u in p.units:
        text = driver.unit_assembly(u, isa)
        tables = re.findall(r"^(\w+_jt\d+):", text, re.M)
        if tables:
            text = "        .far " + ", ".join(tables) + "\n" + text
        objs.append(driver.assemble(isa, text, os.path.basename(u.path)[:-2] + ".o"))
    return objs


def compile_v1bl():
    """egret_gui/build.py's compile_image, for v1bl."""
    from heron.infra import link as L
    from heron.studies.c_compiler.cc import driver
    from heron.studies.egret import build as egret
    from heron.studies.egret_gui import build as B
    from heron.studies.graphics import fonts
    isa = "v1bl"
    vm = {"EGRET_ASM": "1", "EGRET_GUI": "1"}
    inc = [B.SRC, egret.VM, B.GFX_SRC]
    gfx = {"GFX_ASM": "1", "malloc": "gui_alloc", "calloc": "gui_calloc"}
    g = driver.Program(isa)
    for s in B.GFX_LIB:
        path = os.path.join(B.GFX_SRC, s)
        g.add_file(path, [B.GFX_SRC], gfx, text=B._shrunk(path))
    kernels = [driver.assemble(isa, G.kernel(n), n + ".o") for n in sorted(G.EDITS)]
    v = driver.Program(isa)
    for s in egret.SOURCES:
        v.add_file(os.path.join(egret.VM, s), inc, vm)
    v.add_file(egret.prelude_c(), [egret.VM])
    ours = driver.Program(isa)
    for s in B.OURS:
        ours.add_file(os.path.join(B.SRC, s), inc, vm)
    rt = driver.assemble(isa, _rt_v1bl(B.SRC), "rt_v1bl.o")
    objs = _units(g, isa) + kernels + _units(ours, isa)
    objs += [o for _, o in driver.library(isa)[0]]
    objs += [rt] + _units(v, isa)
    objs.append(driver.assemble(isa, E.interp_v1bl(), "interp_v1bl.o"))
    objs.append(driver.assemble(isa, fonts.data_asm(), "fonts.o"))
    return L.link(objs, [], isa)


_images = {}


def image(isa):
    if isa not in _images:
        from heron.studies.egret_gui import build as B
        _images[isa] = B.image() if isa == "v1b" else compile_v1bl()
    return _images[isa]


def session(isa, source=None, depth=3):
    """egret_gui's run.Session, on isa."""
    from heron.studies.egret_gui import build as B, run as R

    class Session(R.Session):
        def __init__(self):
            self.m = native.v1.Machine(isa, R.ram_image(image(isa)),
                                       B.console_input(depth, source))
            self.time_of_day = 10 * 3600 + 8 * 60
            self.m.time_of_day = self.time_of_day
            self.mouse = (0, 0)
            self.buttons = 0
    return Session()


def hw_busy(m):
    """The 1b hardware's cycles for everything m has executed."""
    return hw.total(Counter({(pc, k): n for pc, k, n in m.pc_keys()}))


class Probe:
    """egret_gui/bench.py's Probe on isa: a booted desktop without its
    clock, with what it spends idle; costs in both currencies."""

    def __init__(self, isa):
        from heron.studies.egret_gui import bench as BE
        self.BE = BE
        self.s = session(isa).boot()
        self.s.run(4)
        self.s.click(510, 19)                   # the clock's close box
        self.s.run(1)
        b, h, c = BE.busy(self.s), hw_busy(self.s.m), self.s.cycles
        self.s.run(2)
        dc = self.s.cycles - c
        self.rate = (BE.busy(self.s) - b) / dc
        self.hrate = (hw_busy(self.s.m) - h) / dc

    def cost(self, action, settle=1.0):
        s, BE = self.s, self.BE
        b, h, c = BE.busy(s), hw_busy(s.m), s.cycles
        action()
        s.run(settle)
        dc = s.cycles - c
        return (round(BE.busy(s) - b - self.rate * dc), round(hw_busy(s.m) - h - self.hrate * dc))

    def workspace_do(self, code, settle=2.0):
        s = self.s
        s.click(200, 50)
        s.key("end", ["ctrl"])
        s.type("\n" + code)
        s.run(1)
        return self.cost(lambda: s.key("d", ["ctrl"]), settle)

    def egretica(self, line):
        s = self.s
        s.key("escape")
        s.type(line)
        s.run(1)

        def enter():
            s.key("return", dt=0.05)
            self.BE.wait_done(s)
        return self.cost(enter, 0.5)


def measure(isa, log=None):
    """{what: (reference cycles, 1b hardware cycles)} for booting, some of
    the bench's actions, Egretica's lines and Gadgets; and the screen after
    Egretica's lines, to check that both ISAs drew the same."""
    from heron.studies.egret_gui import bench as BE
    rows = {}

    def row(what, v):
        rows[what] = v
        if log:
            log(f"{isa} {what}: {v}")
    s = session(isa, source='print("ready")')
    s.m.run_until(10 ** 10)
    row("Boot: start the VM, the splash, the prelude", (s.cycles, hw_busy(s.m)))
    s = session(isa).boot()
    row("Boot: to ready, compiling the desktop", (s.cycles, hw_busy(s.m)))
    p = Probe(isa)
    t = p.s
    t.click(60, 136)
    t.run(1)
    row("Workspace: type a character", p.cost(lambda: t.key("x"), 0.5))
    row("Workspace: Return, with the lines below redrawn", p.cost(lambda: t.key("return"), 1))
    t.click(100, 168)
    t.run(1)
    row("Workspace: print `2 ** 100`", p.cost(lambda: t.key("p", ["ctrl"]), 1))
    q = Probe(isa)
    u = q.s
    row("Windows: open the menu and close it", q.cost(lambda: (u.click(550, 300, dt=0.2),
                                                               u.key("escape")), 1))
    row("Windows: drag the Workspace", q.cost(lambda: u.drag(200, 50, 300, 150), 2))
    row("Windows: raise the Transcript", q.cost(lambda: u.click(250, 361), 2))
    for name, code, settle in [("Transcript", "Transcript()", 3), ("Browser", "Browser()", 4),
                               ("Egretica", "Notebook()", 4), ("About", "About()", 3)]:
        row(f"Open: {name}", Probe(isa).workspace_do(code, settle))
    eg = Probe(isa)
    eg.workspace_do("Notebook()", 4)
    for line in BE.EGRETICA:
        row(f"Egretica: `{line}`", eg.egretica(line))
    rows["screen"] = bytes(eg.s.rgb())
    gad = Probe(isa)
    gad.workspace_do("G = Gadgets(); G.move_to(175, 120); G.run", 0.1)
    b0, h0, c0 = BE.busy(gad.s), hw_busy(gad.s.m), gad.s.cycles
    gad.s.run(20)
    dc = gad.s.cycles - c0
    gb = BE.busy(gad.s) - b0 - gad.rate * dc
    gh = hw_busy(gad.s.m) - h0 - gad.hrate * dc
    gad.workspace_do('print("gadgets", G.run_frames)', 1)
    frames = int(re.search(r"gadgets (\d+)", gad.s.output).group(1))
    row("Gadgets: a frame, on average over 20 s", (round(gb / frames), round(gh / frames)))
    return rows
