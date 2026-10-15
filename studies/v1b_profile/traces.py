"""The traces: every program that runs on draft 1b, and how to run it.

A Trace names a run: a study's program, in a variant (interpreted or
compiled, an optimisation level, a scene at a depth, a scenario of the
desktop). Its `run(attach)` builds the program, runs it the way its study
does, calling `attach` on the machine before it starts, and returns a
Done: the output, whether it was right, and the symbols.

The egret_gui traces need the study, which lives on its own branch for
now; they are listed when it is there.
"""

import contextlib
import fnmatch
import os
from functools import partial

from heron import ROOT
from heron.infra import isas

from .collect import Symbols


class Done:
    def __init__(self, output=b"", ok=None, symbols=None, isa="v1b", notes=None, input=None):
        self.output = bytes(output)
        self.ok = ok
        self.symbols = symbols or Symbols()
        self.isa = isa
        self.notes = notes
        self.input = input


class Trace:
    """`weight`: a rough cost in millions of instructions, to start the
    long ones first; `prepare`: what to build once, before workers start."""

    def __init__(self, name, run, language, description, input="", isa="v1b", weight=1,
                 prepare=None):
        self.name = name
        self.study, self.program, *rest = name.split("/")
        self.variant = "/".join(rest) or None
        self.run = run
        self.language = language
        self.description = description
        self.input = input
        self.isa = isa
        self.weight = weight
        self.prepare = prepare

    def __repr__(self):
        return f"Trace({self.name!r})"


def _machine(isa_name, img, inp=b"", **kw):
    from heron.studies.v1_isa.sim32 import Machine32
    return Machine32(isas.get(isa_name), img, inp=inp, **kw)


@contextlib.contextmanager
def capture(attach):
    """Attach a profile to every Machine32 made inside the block (for the
    studies whose run functions make their own)."""
    from heron.studies.v1_isa import sim32
    init = sim32.Machine32.__init__

    def patched(self, *a, **kw):
        init(self, *a, **kw)
        attach(self)
    sim32.Machine32.__init__ = patched
    try:
        yield
    finally:
        sim32.Machine32.__init__ = init


def _run(m, max_cycles):
    """Run a Machine32; the error, if it stopped on one."""
    from heron.studies.v1_isa.sim32 import SimError
    try:
        m.run(max_cycles=max_cycles)
    except SimError as e:
        return str(e)
    return None


def _comment(path, prefix=";"):
    """A source file's first comment paragraph, as a description."""
    lines = []
    with open(path, encoding="latin-1") as f:
        for line in f:
            s = line.strip()
            if not s.startswith(prefix):
                if lines:
                    break
                continue
            s = s.lstrip(prefix).strip()
            if not s:
                if lines:
                    break
                continue
            lines.append(s)
    text = " ".join(lines)
    return text[:300]


def _in(text, limit=60):
    """Console input, briefly."""
    if not text:
        return ""
    s = text[:limit].decode("latin-1").replace("\n", "\\n")
    return s + ("..." if len(text) > limit else "") + f" ({len(text)} bytes)"


# ---------------------------------------------------------------- v1_isa

def _asm(path, name, attach):
    from heron.infra import asm as asmcore
    from heron.studies.v1_isa.testing import expected_output, metadata
    meta = metadata(path)
    img = asmcore.assemble_file(isas.get("v1b"), path)
    m = _machine("v1b", img, meta["input"])
    attach(m)
    err = _run(m, meta["max-cycles"])
    out = bytes(m.dev.out)
    exp = expected_output(name) if name else None
    ok = None if exp is None else (err is None and not m.traps and out == exp)
    return Done(out, ok, Symbols.of(img), notes=err)


def v1_isa():
    from heron.studies.v1_isa.testing import metadata, program_paths
    for path in program_paths(None, "v1b"):
        name = os.path.basename(path)[:-2]
        yield Trace(f"v1_isa/{name}", partial(_asm, path, name), "asm", _comment(path),
                    _in(metadata(path)["input"]), weight=0.2)


def _exercise(attach):
    from heron.studies.v1b_hw import check
    return _asm(check.exercise_path(), None, attach)


def v1b_hw():
    yield Trace("v1b_hw/exercise", _exercise, "asm",
                "The generated exercise program: every instruction class, mode and trap "
                "(studies/v1b_hw/exercise.py)", weight=0.4)


# ---------------------------------------------------------------- c_compiler

def _c(path, opt, inp, expected, attach):
    from heron.studies.c_compiler.cc import driver
    _, img, _ = driver.build([path], "v1b", opt=opt)
    m = _machine("v1b", img, inp)
    attach(m)
    err = _run(m, 200_000_000)
    out = bytes(m.dev.out)
    ok = None if expected is None else (err is None and not m.traps and out == expected)
    return Done(out, ok, Symbols.of(img), notes=err)


def c_compiler():
    from heron.studies.v1_isa import testing
    cc = os.path.join(ROOT, "studies", "c_compiler")
    for f in sorted(os.listdir(os.path.join(cc, "programs"))):
        if not f.endswith(".c"):
            continue
        name = f[:-2]
        path = os.path.join(cc, "programs", f)
        asm = os.path.join(testing.program_dir("v1b"), name + ".s")
        inp = testing.metadata(asm)["input"] if os.path.exists(asm) else b""
        exp = testing.expected_output(name)
        desc = f"The C version of the suite's {name} (studies/c_compiler/programs)"
        yield Trace(f"c_compiler/{name}", partial(_c, path, 1, inp, exp), "C", desc, _in(inp), weight=0.3)
        if name in ("life", "sort", "queens", "sha256", "wordfreq"):
            yield Trace(f"c_compiler/{name}/O0", partial(_c, path, 0, inp, exp), "C",
                        desc + ", without optimisation", _in(inp), weight=0.6)
    tests = os.path.join(cc, "tests", "cc")
    for f in sorted(os.listdir(tests)):
        if not f.endswith(".c"):
            continue
        name = f[:-2]
        ep = os.path.join(tests, "expected", name + ".txt")
        exp = open(ep, "rb").read() if os.path.exists(ep) else None
        yield Trace(f"c_compiler/test-{name}", partial(_c, os.path.join(tests, f), 1, b"", exp), "C",
                    f"The compiler's test {name}.c (studies/c_compiler/tests/cc)", weight=0.1)


# ---------------------------------------------------------------- lisp

def _lisp(path, compiled, features, attach):
    from heron.studies.lisp import machine, testing
    with open(path, "rb") as f:
        text = f.read()
    img, m = machine.start(text, features, compiled)
    attach(m)
    err = _run(m, 4_000_000_000)
    if err is None:
        for pc, what in m.traps:
            # address errors and tag traps are the runtime's type checks
            if not ("misaligned" in what or what in ("tag check", "tagged overflow")):
                err = f"trap at {pc:X}: {what}"
                break
    out = bytes(m.dev.out)
    exp = testing.expected(path)
    ok = None if exp is None else (err is None and out == exp)
    return Done(out, ok, Symbols.of(img), isa=machine.isa_name(features), notes=err)


def _lisp_core(features):
    from heron.studies.lisp import machine
    machine.core(features)


# interpreted instructions, in millions (report 0020 and runs)
_LISP_WEIGHT = {"boyer": 310, "meta": 200, "sieve": 150, "nqueens": 150, "tak": 120}


def lisp():
    d = os.path.join(ROOT, "studies", "lisp", "programs")
    for f in sorted(os.listdir(d)):
        if not f.endswith(".lisp"):
            continue
        name = f[:-5]
        path = os.path.join(d, f)
        desc = _comment(path, ";")
        w = _LISP_WEIGHT.get(name, 60)
        yield Trace(f"lisp/{name}/interp", partial(_lisp, path, False, ()), "Lisp",
                    desc + " (interpreted)", weight=w)
        yield Trace(f"lisp/{name}/compiled", partial(_lisp, path, True, ()), "Lisp",
                    desc + " (compiled on the machine, then run)", weight=w / 5,
                    prepare=partial(_lisp_core, ()))
        if name in ("boyer", "tak", "nqueens", "deriv"):
            yield Trace(f"lisp/{name}/tagged", partial(_lisp, path, True, ("tagged",)), "Lisp",
                        desc + " (compiled, with v1bx's tagged mode)", isa="v1bx", weight=w / 5,
                        prepare=partial(_lisp_core, ("tagged",)))


# ---------------------------------------------------------------- graphics

def _gfx(scene, depth, kernels, stm, attach):
    from heron.studies.graphics import build, run
    img = build.image("v1b", kernels=kernels, stm=stm)
    with capture(attach):
        phases = run.run(img, "v1b", scene, depth)
    problems = run.check(phases, scene, depth)
    notes = "; ".join(problems) or None
    marks = ", ".join(f"{p.name} {p.instructions}" for p in phases)
    return Done(b"", not problems, Symbols.of(img), notes=(notes + "\n" if notes else "") +
                f"phases (instructions): {marks}")


def graphics():
    scenes = {"prims": "lines, rectangles, circles, fills and blits",
              "text": "bitmap and TrueType text", "wm": "the window manager's drawing"}
    for scene, what in scenes.items():
        for depth in range(4):
            bpp = 1 << depth
            yield Trace(f"graphics/{scene}/asm-{bpp}bpp", partial(_gfx, scene, depth, True, False),
                        "C", f"The {scene} scene ({what}) at {bpp} bits per pixel, with the "
                        "assembly kernels", f"{scene} {depth}", weight=8)
        yield Trace(f"graphics/{scene}/c-8bpp", partial(_gfx, scene, 3, False, False), "C",
                    f"The {scene} scene ({what}) at 8 bits per pixel, all in C", f"{scene} 3",
                    weight=10)
    yield Trace("graphics/wm/stm-8bpp", partial(_gfx, "wm", 3, True, True), "C",
                "The window manager's drawing at 8 bits per pixel, with the store-multiple "
                "experiment", "wm 3", weight=8)


# ---------------------------------------------------------------- kernel

def _kernel_symbols(boot):
    from heron.studies.kernel import build
    syms = Symbols.of(boot.kernel)
    regions = []
    for proc, base in zip(boot.procs, boot.bases):
        img = build.user(proc.prog)
        hi = base + (max(img.mem) + 1 if img.mem else 0)
        regions.append((base, hi, Symbols.of(img, prefix=f"{proc.prog}:"), base))
    syms.regions = regions
    return syms


def _kernel(scenario, banks, attach):
    from heron.studies.kernel import bench
    s = bench.BY_NAME[scenario]
    features = (banks,) + s.extra
    timer = 3000 if s.name in ("preempt", "irqdrv") else 0
    with capture(attach):
        r = bench.run(features, s.procs(s.n), timer=timer)
    out = bytes(r.m.dev.out)
    problems = r.problems()
    ok = not problems and (s.check is None or s.check(out, s.n))
    return Done(out, ok, _kernel_symbols(r.boot), isa="v1bs", notes="; ".join(problems) or None)


def _micro(name, variant, n, attach):
    from heron.infra import asm as asmcore
    from heron.studies.kernel.build import preprocess
    from heron.studies.kernel.micro import MICRO
    path = os.path.join(MICRO, f"{name}_v1b.s")
    with open(path) as f:
        text = f"N = {n}\n" + preprocess(f.read(), {f"V{variant}"})
    a = asmcore.Assembler(isas.get("v1b"))
    a.load(path, text=text)
    img = a.assemble()
    m = _machine("v1b", img)
    attach(m)
    err = _run(m, 500_000_000)
    return Done(bytes(m.dev.out), err is None and not m.traps, Symbols.of(img), notes=err)


def kernel():
    from heron.studies.kernel import bench
    from heron.studies.kernel.micro import ROUTINES
    for s in bench.SCENARIOS:
        yield Trace(f"kernel/{s.name}/full", partial(_kernel, s.name, "full"), "asm",
                    f"The nucleus with full register banks: {s.text} ({s.n} iterations)",
                    isa="v1bs", weight=1)
        if s.name in ("null", "yield", "ipc", "preempt", "fault"):
            yield Trace(f"kernel/{s.name}/none", partial(_kernel, s.name, "none"), "asm",
                        f"The nucleus without register banks: {s.text} ({s.n} iterations)",
                        isa="v1bs", weight=1)
    for name, (texts, _, n) in ROUTINES.items():
        for v, what in enumerate(texts):
            yield Trace(f"kernel/micro-{name}/v{v}", partial(_micro, name, v, n), "asm",
                        f"Micro-benchmark {name}: {what} ({n} iterations)", weight=0.1)


# ---------------------------------------------------------------- egret

def _egret(name, variant, attach):
    from heron.studies.egret import build
    from heron.studies.egret.programs import catalogue
    if name is None:
        source, inp, exp = b"", b"", None
    else:
        p = catalogue.program(name)
        source, inp, exp = p.source, p.input, p.expected()
    img = build.heron("v1b", None, variant)
    data = source + (b"\n__END__\n" + inp if inp else b"")
    m = _machine("v1b", img, data)
    attach(m)
    err = _run(m, build.MAX_CYCLES)
    out = bytes(m.dev.out)
    ok = None if exp is None else (err is None and out == exp)
    return Done(out, ok, Symbols.of(img), notes=err)


def _egret_vm(variant):
    from heron.studies.egret import build
    build.heron("v1b", None, variant)


_EGRET_VARIANTS = {"asm": "the hand-written interpreter loop", "c": "the interpreter loop in C",
                   "jit": "the JIT"}


def egret():
    from heron.studies.egret.programs import catalogue
    for variant, what in _EGRET_VARIANTS.items():
        prep = partial(_egret_vm, variant)
        yield Trace(f"egret/startup/{variant}", partial(_egret, None, variant), "Egret",
                    f"The VM starting up with an empty program ({what})", weight=2, prepare=prep)
        for name in catalogue.names():
            p = catalogue.program(name)
            desc = _comment(p.path, "#")
            yield Trace(f"egret/{name}/{variant}", partial(_egret, name, variant), "Egret",
                        f"{desc} ({what})", _in(p.input), weight=20, prepare=prep)


# ---------------------------------------------------------------- egret_gui

def _gui_prepare():
    from heron.studies.egret_gui import build
    build.image()


def _gui_do(s, code, settle):
    """Type a line into the Workspace and do it (bench.Probe.workspace_do)."""
    s.click(200, 50)
    s.key("end", ["ctrl"])
    s.type("\n" + code)
    s.run(1)
    s.key("d", ["ctrl"])
    s.run(settle)


def _gui_workspace(s):
    s.click(60, 136)
    s.run(1)
    for k in ("x", "y", "z"):
        s.key(k)
        s.run(0.5)
    s.key("backspace")
    s.run(0.5)
    s.key("return")
    s.run(1)
    s.click(100, 152)
    s.run(1)
    s.key("p", ["ctrl"])
    s.run(1)
    s.click(100, 168)
    s.run(1)
    s.key("p", ["ctrl"])
    s.run(1)
    s.key("end", ["ctrl"])
    s.run(1)


def _gui_windows(s):
    s.click(550, 300, dt=0.2)
    s.key("escape")
    s.run(1)
    s.drag(200, 50, 300, 150)
    s.run(2)
    s.click(250, 361)
    s.run(2)
    s.click(140, 150)
    s.run(2)


def _gui_apps(s):
    for code, settle in (("Transcript()", 3), ("Paint()", 3), ("About()", 3)):
        _gui_do(s, code, settle)


def _gui_browser(s):
    _gui_do(s, "Browser()", 4)
    s.click(100, 120)
    s.run(2)
    s.click(300, 135)
    s.run(2)


def _gui_mandel(s):
    _gui_do(s, "Mandel()", 0.1)
    while "Mandelbrot: drawn" not in s.output and s.seconds < 600:
        s.run(5)


GUI_SCENARIOS = {
    "boot": ("From power on to the desktop painted: the VM, the splash, compiling the "
             "desktop's Egret, the first windows", None, 80),
    "idle": ("The desktop for 5 s with nothing to do (the clock closed)",
             lambda s: s.run(5), 1),
    "clock": ("The desktop for 5 s with the clock moving its hands",
              lambda s: s.run(5), 2),
    "workspace": ("The Workspace: typing three characters, a backspace and a Return, Print it "
                  "on `3 + 4 * 5` and `2 ** 100`, Ctrl-End", _gui_workspace, 3),
    "windows": ("Windows: the desktop menu opened and closed, a window dragged, one raised, "
                "one closed", _gui_windows, 3),
    "apps": ("Opening the Transcript, Paint and About from the Workspace", _gui_apps, 6),
    "browser": ("The class Browser: opened, a class and a method picked", _gui_browser, 6),
    "life": ("Life running for 10 s", lambda s: (_gui_do(s, "Life()", 0.1), s.run(10)), 15),
    "mandel": ("The Mandelbrot set drawn, 160 x 120, up to 32 steps", _gui_mandel, 40),
    "gadgets": ("Gadgets' table of balls and parts running for 10 s",
                lambda s: (_gui_do(s, "G = Gadgets(); G.move_to(175, 120); G.run", 0.1),
                           s.run(10)), 20),
}


def _gui(scenario, attach):
    from heron.studies.egret_gui import build, run
    what, script, _ = GUI_SCENARIOS[scenario]
    s = run.Session()
    if script is None:
        attach(s.m)
        s.boot()
        s.run(6)
    else:
        s.boot()
        s.run(4)
        if scenario != "clock":
            s.click(510, 19)            # the clock's close box
            s.run(1)
        attach(s.m)
        script(s)
    return Done(s.m.out, None, Symbols.of(build.image()))


def egret_gui():
    try:
        import heron.studies.egret_gui  # noqa: F401
    except ImportError:
        return
    for name, (what, _, weight) in GUI_SCENARIOS.items():
        yield Trace(f"egret_gui/{name}", partial(_gui, name), "Egret", what, "the desktop",
                    weight=weight, prepare=_gui_prepare)


# ---------------------------------------------------------------- all

STUDIES = {"v1_isa": v1_isa, "v1b_hw": v1b_hw, "c_compiler": c_compiler, "lisp": lisp,
           "graphics": graphics, "kernel": kernel, "egret": egret, "egret_gui": egret_gui}


def all_traces():
    import heron.studies.v1_isa  # noqa: F401  (registers the ISAs)
    out = []
    for name, fn in STUDIES.items():
        if os.path.isdir(os.path.join(ROOT, "studies", name)):
            out += list(fn())
    return out


def select(patterns=None, exclude=None):
    """The traces whose names match any of the glob patterns (all without),
    and none of `exclude`."""
    ts = all_traces()
    if patterns:
        ts = [t for t in ts if any(fnmatch.fnmatch(t.name, p) or t.name.startswith(p.rstrip("/") + "/")
                                   or t.name == p for p in patterns)]
    if exclude:
        ts = [t for t in ts if not any(fnmatch.fnmatch(t.name, p) for p in exclude)]
    return ts


def by_name(name):
    for t in all_traces():
        if t.name == name:
            return t
    raise KeyError(name)

