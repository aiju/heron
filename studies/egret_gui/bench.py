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
REPORT_DIR = os.path.join(ROOT, "reports", "0021-report-egret-gui")


def busy(s):
    """Cycles spent executing instructions so far (the waits not counted)."""
    return s.m.cycles_for(run.reference(s.isa))


def ms(cycles):
    return cycles / (MHZ * 1000)


class Probe:
    """A booted desktop to measure things on."""

    def __init__(self, depth=3, clock=False, isa="v1b"):
        self.s = run.Session(depth=depth, isa=isa).boot()
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


def measure(log=print, isa="v1b"):
    rows = []                                   # (section, what, cycles)

    def row(section, what, cycles):
        rows.append((section, what, cycles))
        log(f"{what}: {cycles:,} cycles, {ms(cycles):.0f} ms")

    # booting: up to "ready", then until the first windows are painted
    s = run.Session(source='print("ready")', isa=isa)
    s.m.run_until(10 ** 10)                     # it halts when it's done
    vm = s.cycles
    row("Booting", "Start the VM, draw the splash, read the source, compile the prelude (408 lines)", vm)
    s = run.Session(isa=isa).boot()
    lines = sum(open(os.path.join(build.LIB, f)).read().count("\n") for f in build.DESKTOP)
    row("Booting", f"Compile the desktop ({lines} lines of Egret) and open its first windows",
        s.cycles - vm)
    b, c = busy(s), s.cycles
    s.run(6)
    p = Probe(isa=isa)
    row("Booting", "Paint the first windows", round(busy(s) - b - p.rate * (s.cycles - c)))

    # idle
    row("Idle", "The event loop, a second with nothing to do", round(p.rate * MHZ * 1e6))
    pc = Probe(clock=True, isa=isa)
    row("Idle", "The same with the clock moving its hands", round(pc.rate * MHZ * 1e6))

    # the Workspace
    t = p.s
    t.click(60, 136)                            # a blank line
    t.run(1)
    row("Workspace", "Type a character", p.cost(lambda: t.key("x"), 0.5))
    row("Workspace", "Delete it", p.cost(lambda: t.key("backspace"), 0.5))
    row("Workspace", "Return, with the lines below it redrawn", p.cost(lambda: t.key("return"), 1))
    t.click(100, 152)                           # 3 + 4 * 5
    t.run(1)
    row("Workspace", "Print it: `3 + 4 * 5`", p.cost(lambda: t.key("p", ["ctrl"]), 1))
    t.click(100, 168)                           # 2 ** 100
    t.run(1)
    row("Workspace", "Print it: `2 ** 100`", p.cost(lambda: t.key("p", ["ctrl"]), 1))
    row("Workspace", "Scroll to the end (Ctrl-End)", p.cost(lambda: t.key("end", ["ctrl"]), 1))

    # windows and the menu
    q = Probe(isa=isa)
    u = q.s
    row("Windows", "Open the desktop menu and close it (Escape)",
        q.cost(lambda: (u.click(550, 300, dt=0.2), u.key("escape")), 1))
    row("Windows", "Drag the Workspace by 100 pixels (8 steps of its outline) and move it",
        q.cost(lambda: u.drag(200, 50, 300, 150), 2))
    row("Windows", "Raise the Transcript from behind the Workspace",
        q.cost(lambda: u.click(250, 361), 2))
    # (the Workspace is at (130, 140) now, partly under the Transcript)
    row("Windows", "Close the Workspace (and paint the desktop under it)", q.cost(lambda: u.click(140, 150), 2))

    # the applications, opened from a Workspace (its line, compiled and run)
    for name, code, settle in [("Transcript", "Transcript()", 3), ("Browser", "Browser()", 4),
                               ("Paint", "Paint()", 3), ("About", "About()", 3)]:
        r = Probe(isa=isa)
        row("Opening", f"{name}", r.workspace_do(code, settle))
    r = Probe(isa=isa)
    r.workspace_do("Browser()", 4)
    row("Browser", "Pick a class (Ball)", r.cost(lambda: r.s.click(100, 120), 2))
    row("Browser", "Pick a method and show its source (draw)", r.cost(lambda: r.s.click(300, 135), 2))

    # Life and the Mandelbrot set
    life = Probe(isa=isa)
    life.workspace_do("Life()", 0.1)
    life.s.run(30)
    life.workspace_do("print(\"generation \" + DESK.find(Life).generation.to_s)", 1)
    m = re.search(r"generation (\d+)", life.s.output)
    gens = int(m.group(1))
    mandel = Probe(isa=isa)
    mandel.workspace_do("Mandel()", 0.1)
    t0, c0 = time.perf_counter(), mandel.s.cycles
    i0 = mandel.s.m.instructions
    while "Mandelbrot: drawn" not in mandel.s.output and mandel.s.seconds < 1000:
        mandel.s.run(5)
    host = time.perf_counter() - t0
    secs = float(re.search(r"Mandelbrot: drawn in ([\d.]+) s", mandel.s.output).group(1))
    speed = ((mandel.s.cycles - c0) / host / 1e6, (mandel.s.m.instructions - i0) / host / 1e6)

    # Gadgets' table, as it opens, running for 20 s where nothing covers it
    gad = Probe(isa=isa)
    gad.workspace_do("G = Gadgets(); G.move_to(175, 120); G.run", 0.1)
    b0, c0 = busy(gad.s), gad.s.cycles
    gad.s.run(20)
    gbusy = busy(gad.s) - b0 - gad.rate * (gad.s.cycles - c0)
    gad.workspace_do('print("gadgets", G.run_frames, G.statics.find { |p| p.is_a?(Bucket) }.count)', 3)
    m = re.search(r"gadgets (\d+) (\d+)", gad.s.output)
    gframes, gcaught = int(m.group(1)), int(m.group(2))
    row("Gadgets", "A frame of the table it opens with (two to five balls moving), on average",
        round(gbusy / gframes))

    # memory, once the desktop is up
    st = Probe(isa=isa)
    st.workspace_do("print(\"stats \" + gui_stats().inspect)", 1)
    mem = [int(x) for x in re.search(r"stats \[([\d, ]+)\]", st.s.output).group(1).split(",")]
    return {"rows": rows, "life": gens / 30, "mandel": secs, "image": build.image(isa), "host": speed,
            "gadgets": (gframes / 20, gcaught),
            "profiles": profiles() if isa == "v1b" else None,
            "mem": mem,
            "lines": {f: open(os.path.join(build.LIB, f)).read().count("\n") for f in build.DESKTOP},
            "c_lines": {os.path.basename(f): open(f).read().count("\n")
                        for f in sorted(glob.glob(os.path.join(build.SRC, "*.[chs]")))}}


def tables(r, r2=None):
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
            f"| Gadgets' table, frames a second (of 30) | {r['gadgets'][0]:.0f} |",
            f"| ... and balls in the bucket after 20 s | {r['gadgets'][1]} |",
            f"| The simulator on the host, natively: million cycles a second | {r['host'][0]:.0f} |",
            f"| ... and million instructions a second | {r['host'][1]:.0f} |", ""]
    out += ["## Where the cycles go", "",
            "Each column is all the cycles from the event to the end of a short wait",
            "after it (the idle loop's included), by the kind of function they were in.", ""]
    profs = r["profiles"]
    out.append("| | " + " | ".join(w for w, _ in profs) + " |")
    out.append("|---|" + "---:|" * len(profs))
    for k in KINDS:
        cells = []
        for _, d in profs:
            tot = sum(d.values())
            cells.append(f"{100 * d[k] / tot:.0f}%")
        out.append(f"| {k} | " + " | ".join(cells) + " |")
    out.append("| all, at 3 MHz | " + " | ".join(f"{ms(sum(d.values())):,.0f} ms" for _, d in profs) + " |")
    out.append("")
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
    if r2:
        out += compare(r, r2)
    return "\n".join(out) + "\n"


def compare(r, r2):
    """The same on draft 2: every row against 1b's."""
    out = ["", "## On draft 2", "",
           "The same desktop built for draft 2 (RFC 0028): the VM's C through the",
           "C compiler's draft 2 backend, its interpreter in `interp_v2.s`, the",
           "graphics study's draft 2 kernels, on draft 2's simulator in the same",
           "reference configuration.", "",
           "| | 1b | 2 | 2 against 1b |", "|---|---:|---:|---:|"]
    theirs = {(sec, what): c for sec, what, c in r2["rows"]}
    for sec, what, c in r["rows"]:
        c2 = theirs.get((sec, what))
        if c2 is not None:
            out.append(f"| {what} | {ms(c):,.0f} ms | {ms(c2):,.0f} ms | {100 * c2 / c:.0f}% |")
    out += [f"| Life, generations a second | {r['life']:.1f} | {r2['life']:.1f} | {100 * r2['life'] / r['life']:.0f}% |",
            f"| The Mandelbrot set | {r['mandel']:.1f} s | {r2['mandel']:.1f} s | {100 * r2['mandel'] / r['mandel']:.0f}% |",
            f"| Gadgets' table, frames a second (of 30) | {r['gadgets'][0]:.0f} | {r2['gadgets'][0]:.0f} | {100 * r2['gadgets'][0] / r['gadgets'][0]:.0f}% |",
            f"| The image: code | {r['image'].code_bytes() // 1024} KB | {r2['image'].code_bytes() // 1024} KB | {100 * r2['image'].code_bytes() / r['image'].code_bytes():.0f}% |",
            f"| Egret's permanent space once the desktop is up | {r['mem'][0] // 1024} KB | {r2['mem'][0] // 1024} KB | |"]
    return out


# ---- where the cycles go: functions by kind

GWM_STATIC = {"isect", "empty", "rgn_copy", "rgn_rect", "add", "rgn_sub", "unite", "content_of",
              "title_of", "close_of", "level", "visible_in", "draw_frame", "paint_part",
              "paint_desktop", "repaint", "set_title", "repaint_title", "clamp"}
KINDS = ["Egret's interpreter (the assembly loop)", "its slow path, in C",
         "allocation and collection", "drawing (the graphics library)", "the window manager",
         "Egret's primitives (prims.c, gui_prims.c)", "the rest of the VM and the C library"]


def kind(name):
    if not name.startswith("_"):
        return KINDS[0]
    n = name[1:]
    if n in ("step", "egret_step", "egret_raise", "egret_prim_failed", "asm_run"):
        return KINDS[1]
    if n.startswith(("alloc_", "gc", "forward", "scan", "copy_obj")) or n in (
            "make_list", "make_string", "list_push", "push_root", "pop_roots"):
        return KINDS[2]
    if n.startswith(("gfx_", "font_", "ttf_", "rs_", "theme_", "bitmap_get")) or n.endswith("_rows") \
            or n in ("line_run", "span_run"):
        return KINDS[3]
    if n.startswith("gwm_") or n in GWM_STATIC:
        return KINDS[4]
    if n.startswith("p_") or n in ("int_list", "cstr", "ints", "window_ok", "ramp_for", "font_arg"):
        return KINDS[5]
    return KINDS[6]


class Profile:
    """Cycles by kind of function, for what happens between two points."""

    def __init__(self, s):
        import bisect
        img = build.image(s.isa)
        syms = sorted((v, k) for k, v in img.symbols.items()
                      if not k.startswith(".") and "." not in k[1:] and v < run.RAM_SIZE)
        self.addrs = [v for v, _ in syms]
        self.names = [k for _, k in syms]
        self.bisect = bisect.bisect_right
        self.s = s

    def snap(self):
        return self.s.m.pc_cycles(run.reference(self.s.isa))

    def by_kind(self, a, b):
        out = dict.fromkeys(KINDS, 0)
        for pc, v in b.items():
            d = v - a.get(pc, 0)
            if not d:
                continue
            if pc is None:
                out[KINDS[6]] += d
                continue
            i = self.bisect(self.addrs, pc) - 1
            out[kind(self.names[i]) if i >= 0 else KINDS[6]] += d
        return out


def profiles():
    """[(what, {kind: cycles})] for a few things, idle included."""
    out = []
    p = Probe()
    f = Profile(p.s)
    a = f.snap()
    p.s.run(1)
    out.append(("an idle second", f.by_kind(a, f.snap())))
    p.s.click(60, 136)
    p.s.run(1)
    a = f.snap()
    p.s.key("x")
    p.s.run(0.2)
    out.append(("typing a character", f.by_kind(a, f.snap())))
    p.s.click(100, 168)                         # 2 ** 100
    p.s.run(1)
    a = f.snap()
    p.s.key("p", ["ctrl"])
    p.s.run(0.5)
    out.append(("print it: `2 ** 100`", f.by_kind(a, f.snap())))
    q = Probe()
    f = Profile(q.s)
    a = f.snap()
    menu(q.s, "Browser")
    q.s.run(2)
    out.append(("opening the Browser", f.by_kind(a, f.snap())))
    return out


# the middles of the desktop menu's items, from its top
MENU = {"Workspace": 11, "Transcript": 29, "Browser": 47, "Clock": 72, "Life": 90,
        "Gadgets": 108, "Mandelbrot": 126, "Paint": 144, "About": 169}


def menu(s, item, x=550, y=300):
    """Open the desktop menu at (x, y), which must be on the desktop, and
    choose an item (the menu opens there if it fits on the screen)."""
    s.click(x, y, dt=0.2)
    s.click(x + 30, y + MENU[item], dt=1)


def screenshots(out=REPORT_DIR, log=print):
    """The report's pictures: the desktop at 8 and 1 bits per pixel with
    some things done in it, the Browser, Gadgets, and the splash."""
    paths = []
    for depth in (3, 0):
        s = run.Session(depth=depth).boot()
        s.run(3)
        for y in (152, 168, 184):               # print it: three lines of the Workspace
            s.click(240, y)
            s.key("end")
            s.key("p", ["ctrl"])
            s.run(1)
        s.click(100, 232)                       # do it: print("Hello from the Workspace"), below the map's result, which wraps
        s.key("d", ["ctrl"])
        s.run(1)
        menu(s, "Mandelbrot")
        s.drag(130, 71, 530, 191)               # out to the right
        while "Mandelbrot: drawn" not in s.output and s.seconds < 1000:
            s.run(5)
        s.run(2)
        paths.append(os.path.join(out, f"desktop-{1 << depth}.png"))
        s.png(paths[-1])
    s = run.Session().boot()
    s.run(3)
    menu(s, "Life")                             # at (54, 62)
    s.drag(150, 71, 414, 250)                   # to the bottom right
    s.run(2)
    menu(s, "Browser", 450, 190)                # at (78, 84)
    s.click(124, 142)                           # Ball
    s.run(1)
    s.click(324, 127)                           # bounce_off
    s.run(6)
    paths.append(os.path.join(out, "browser.png"))
    s.png(paths[-1])
    # Gadgets, with a part made in the Workspace and put on the table
    s = run.Session().boot()
    s.run(3)
    s.click(200, 50)
    s.key("end", ["ctrl"])
    s.type("\n\nclass Balloon < Ball; def radius = 9; def color = PAL.yellow; def gravity = -30; end")
    s.key("d", ["ctrl"])
    s.run(2)
    menu(s, "Gadgets")                          # its table at (176, 44)
    s.run(2)
    s.click(595, 56)                            # Run
    s.run(9)
    s.click(614, 219)                           # the Balloon, last in the bin
    s.click(470, 300)                           # on the table
    s.run(1.2)
    paths.append(os.path.join(out, "gadgets.png"))
    s.png(paths[-1])
    # the splash, a few seconds into a cold boot
    s = run.Session()
    s.run(6)
    paths.append(os.path.join(out, "splash.png"))
    s.png(paths[-1])
    for p in paths:
        log(f"wrote {os.path.relpath(p)}")
    return paths


def write(r, r2=None):
    os.makedirs(REPORT_DIR, exist_ok=True)
    path = os.path.join(REPORT_DIR, "performance.md")
    with open(path, "w") as f:
        f.write(tables(r, r2))
    screenshots()
    return path
