"""What the desktop costs on the machine: booting, sitting idle, and the
things people do, in the reference configuration's cycles (D16-overlap)
and in time at 3 MHz. `heron egret_gui bench` prints the tables; with
--write they go to the report (REPORT_DIR/performance.md).

An action's cost is the cycles the machine spent executing instructions
while it was dealt with (not waiting for the timer), less what the idle
loop would have spent in the same time. The desktop runs without its
clock unless said otherwise, so that the clock's redrawing isn't counted.
"""

import glob
import os
import re
import time

from heron import ROOT, native

from . import build, run

MHZ = 3.0
REPORT_DIR = os.path.join(ROOT, "reports", "0022-report-egret-gui")


def busy(s):
    """Cycles spent executing instructions so far (the waits not counted)."""
    return s.m.cycles_for(native.v1.reference())


def ms(cycles):
    return cycles / (MHZ * 1000)


class Probe:
    """A booted desktop to measure things on."""

    def __init__(self, depth=3, clock=False):
        self.s = run.Session(depth=depth).boot()
        self.s.run(4)
        if not clock:
            self.s.click(510, 19)               # the clock's close box
            self.s.run(1)
        self.rate = self.idle_rate()

    def idle_rate(self, seconds=2):
        """Busy cycles per cycle, idle."""
        s = self.s
        b, c = busy(s), s.cycles
        s.run(seconds)
        return (busy(s) - b) / (s.cycles - c)

    def cost(self, action, settle=1.0):
        s = self.s
        b, c = busy(s), s.cycles
        action()
        s.run(settle)
        return round(busy(s) - b - self.rate * (s.cycles - c))

    def workspace_do(self, code, settle=2.0):
        """Raise the Workspace, add a line, and do it; returns its cost."""
        s = self.s
        s.click(200, 50)
        s.key("end", ["ctrl"])
        s.type("\n" + code)
        s.run(1)
        return self.cost(lambda: s.key("d", ["ctrl"]), settle)


def measure(log=print):
    rows = []                                   # (section, what, cycles)

    def row(section, what, cycles):
        rows.append((section, what, cycles))
        log(f"{what}: {cycles:,} cycles, {ms(cycles):.0f} ms")

    # booting: up to "ready", then until the first windows are painted
    s = run.Session(source='print("ready")')
    s.m.run_until(10 ** 10)                     # it halts when it's done
    vm = s.cycles
    row("Booting", "Start the VM and compile the prelude (408 lines)", vm)
    s = run.Session().boot()
    lines = sum(open(os.path.join(build.LIB, f)).read().count("\n") for f in build.DESKTOP)
    row("Booting", f"Compile the desktop ({lines} lines of Egret) and open its first windows",
        s.cycles - vm)
    b, c = busy(s), s.cycles
    s.run(6)
    p = Probe()
    row("Booting", "Paint the first windows", round(busy(s) - b - p.rate * (s.cycles - c)))

    # idle
    row("Idle", "The event loop, a second with nothing to do", round(p.rate * MHZ * 1e6))
    pc = Probe(clock=True)
    row("Idle", "The same with the clock moving its hands", round(pc.rate * MHZ * 1e6))

    # the Workspace
    t = p.s
    t.click(60, 120)                            # a blank line
    t.run(1)
    row("Workspace", "Type a character", p.cost(lambda: t.key("x"), 0.5))
    row("Workspace", "Delete it", p.cost(lambda: t.key("backspace"), 0.5))
    row("Workspace", "Return, with the lines below it redrawn", p.cost(lambda: t.key("return"), 1))
    t.click(100, 136)                           # 3 + 4 * 5
    t.run(1)
    row("Workspace", "Print it: `3 + 4 * 5`", p.cost(lambda: t.key("p", ["ctrl"]), 1))
    t.click(100, 152)                           # 2 ** 100
    t.run(1)
    row("Workspace", "Print it: `2 ** 100`", p.cost(lambda: t.key("p", ["ctrl"]), 1))
    row("Workspace", "Scroll to the end (Ctrl-End)", p.cost(lambda: t.key("end", ["ctrl"]), 1))

    # windows and the menu
    q = Probe()
    u = q.s
    row("Windows", "Open the desktop menu and close it (Escape)",
        q.cost(lambda: (u.click(550, 300, dt=0.2), u.key("escape")), 1))
    row("Windows", "Drag the Workspace by 100 pixels (8 steps of its outline) and move it",
        q.cost(lambda: u.drag(200, 50, 300, 150), 2))
    row("Windows", "Raise the Transcript from behind it",
        q.cost(lambda: u.click(250, 361), 2))
    row("Windows", "Close the Workspace (and paint the desktop under it)", q.cost(lambda: u.click(40, 50), 2))

    # the applications, opened from a Workspace (its line, compiled and run)
    for name, code, settle in [("Transcript", "Transcript()", 3), ("Browser", "Browser()", 4),
                               ("Paint", "Paint()", 3), ("About", "About()", 3)]:
        r = Probe()
        row("Opening", f"{name}", r.workspace_do(code, settle))
    r = Probe()
    r.workspace_do("Browser()", 4)
    row("Browser", "Pick a class (Clock)", r.cost(lambda: r.s.click(100, 195), 2))
    row("Browser", "Pick a method and show its source (paint)", r.cost(lambda: r.s.click(300, 135), 2))

    # Life and the Mandelbrot set
    life = Probe()
    life.workspace_do("Life()", 0.1)
    life.s.run(30)
    life.workspace_do("print(\"generation \" + DESK.find(Life).generation.to_s)", 1)
    m = re.search(r"generation (\d+)", life.s.output)
    gens = int(m.group(1))
    mandel = Probe()
    mandel.workspace_do("Mandel()", 0.1)
    t0, c0 = time.perf_counter(), mandel.s.cycles
    i0 = mandel.s.m.instructions
    while "Mandelbrot: drawn" not in mandel.s.output and mandel.s.seconds < 1000:
        mandel.s.run(5)
    host = time.perf_counter() - t0
    secs = float(re.search(r"Mandelbrot: drawn in ([\d.]+) s", mandel.s.output).group(1))
    speed = ((mandel.s.cycles - c0) / host / 1e6, (mandel.s.m.instructions - i0) / host / 1e6)

    # memory, once the desktop is up
    st = Probe()
    st.workspace_do("print(\"stats \" + gui_stats().inspect)", 1)
    mem = [int(x) for x in re.search(r"stats \[([\d, ]+)\]", st.s.output).group(1).split(",")]
    return {"rows": rows, "life": gens / 30, "mandel": secs, "image": build.image(), "host": speed,
            "mem": mem,
            "lines": {f: open(os.path.join(build.LIB, f)).read().count("\n") for f in build.DESKTOP},
            "c_lines": {os.path.basename(f): open(f).read().count("\n")
                        for f in sorted(glob.glob(os.path.join(build.SRC, "*.[chs]")))}}


def tables(r):
    out = ["<!-- generated by heron egret_gui bench --write; don't edit -->", "",
           "# The desktop's costs", "",
           "Cycles of the reference configuration (D16-overlap) spent executing",
           "instructions, less what the idle loop would have spent in the same",
           f"time; and that as time at {MHZ:g} MHz.", ""]
    section = None
    for sec, what, cycles in r["rows"]:
        if sec != section:
            out += ["", f"## {sec}", "", "| | cycles | at 3 MHz |", "|---|---:|---:|"]
            section = sec
        out.append(f"| {what} | {cycles:,} | {ms(cycles):,.0f} ms |")
    out += ["", "## Running", "", "| | |", "|---|---:|",
            f"| Life, generations a second (the glider gun) | {r['life']:.1f} |",
            f"| The Mandelbrot set, 160 x 120, up to 32 steps | {r['mandel']:.1f} s |",
            f"| The simulator on the host, natively: million cycles a second | {r['host'][0]:.0f} |",
            f"| ... and million instructions a second | {r['host'][1]:.0f} |", ""]
    img = r["image"]
    out += ["## Sizes", "", "| | |", "|---|---:|",
            f"| The image: the VM, the graphics library and kernels, the fonts, the GUI's C | {img.extent()[1] // 1024} KB |",
            f"| ... of which code | {img.code_bytes() // 1024} KB |",
            f"| Egret's permanent space used once the desktop is up (classes, methods, symbols) | {r['mem'][0] // 1024} of {r['mem'][1] // 1024} KB |",
            f"| Egret's heap in use then | {r['mem'][2] // 1024} of {r['mem'][3] // 1024} KB |"]
    for f, n in r["lines"].items():
        out.append(f"| `lib/{f}`, lines of Egret | {n} |")
    for f, n in r["c_lines"].items():
        out.append(f"| `src/{f}`, lines | {n} |")
    return "\n".join(out) + "\n"


def write(r):
    os.makedirs(REPORT_DIR, exist_ok=True)
    path = os.path.join(REPORT_DIR, "performance.md")
    with open(path, "w") as f:
        f.write(tables(r))
    return path
