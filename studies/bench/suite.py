"""The workloads: finding them, building them at a size, their reference
outputs, and running them on the instruction-level simulator.

A workload is a folder in workloads/ with a workload.py that says what it
is (README.md has the full contract):

    TITLE = "a Forth, compiling and running its programs"
    PART = "asm"                  # or "c": hand-written or compiled
    CATEGORY = "interpreters"
    SOURCES = ["forth.s"]         # in the folder; .s for asm, .c for C
    SIZES = {"test": {"N": 2}, "ref": {"N": 20}}

and optionally:

    def data(p): return {"corpus": b"..."}   # linked in, by name
    def input(p): return b"..."              # console input
    def reference(p): return b"..."          # the expected output, from Python
    REFERENCE_C = ["ref.c"]                  # ... or from C built with gcc
    def build(p): return image, inp          # build the image some other way
    MAX_CYCLES = 50_000_000

`p` is the size's parameters. They reach the code as `.equ` in every
assembly source and as `#define` in every C file. A C workload's reference
is by default its own SOURCES built with gcc on the host.
"""

import functools
import hashlib
import importlib
import os
import subprocess
import tempfile

from heron import BUILD

HERE = os.path.dirname(os.path.abspath(__file__))
LIB = os.path.join(HERE, "lib")
WORKLOADS = os.path.join(HERE, "workloads")
OUT = os.path.join(BUILD, "bench")
SIZES = ("test", "small", "ref")
PARTS = {"asm": "hand-written assembly", "c": "compiled C"}
MAX_CYCLES = 200_000_000
ISA = "v2"
# RFC 0028's tentative instructions (5.10) and BCOPY: optional, so not used
TENTATIVE = {"ADD.B4", "FFS", "POPC", "REV", "MULA", "MERGE", "MULFX",
             "TMOV", "TTST", "TADD", "TSUB", "TCMP", "BCOPY"}


class BenchError(Exception):
    pass


class Workload:
    def __init__(self, name):
        self.name = name
        self.dir = os.path.join(WORKLOADS, name)
        self.mod = importlib.import_module(f"heron.studies.bench.workloads.{name}.workload")
        m = self.mod
        self.title = m.TITLE
        self.part = m.PART
        self.category = m.CATEGORY
        self.sources = [os.path.join(self.dir, s) for s in getattr(m, "SOURCES", [])]
        self.sizes = m.SIZES
        self.max_cycles = getattr(m, "MAX_CYCLES", MAX_CYCLES)
        if self.part not in PARTS:
            raise BenchError(f"{name}: PART is {self.part!r}, not one of {list(PARTS)}")
        if set(self.sizes) != set(SIZES):
            raise BenchError(f"{name}: SIZES has {sorted(self.sizes)}, not {list(SIZES)}")

    def __repr__(self):
        return f"<workload {self.name}>"

    def params(self, size):
        return dict(self.sizes[size])

    def data(self, size):
        f = getattr(self.mod, "data", None)
        return f(self.params(size)) if f else {}

    def input(self, size):
        f = getattr(self.mod, "input", None)
        return f(self.params(size)) if f else b""

    def expected_path(self, size):
        return os.path.join(self.dir, "expected", f"{size}.txt")

    def expected(self, size):
        p = self.expected_path(size)
        if not os.path.exists(p):
            return None
        with open(p, "rb") as f:
            return f.read()

    def image(self, size):
        """(image, console input) at a size; built once per process."""
        return _image(self.name, size)

    def reference(self, size):
        """The expected output, from the workload's host reference."""
        p = self.params(size)
        f = getattr(self.mod, "reference", None)
        if f is not None:
            return f(p)
        srcs = getattr(self.mod, "REFERENCE_C", None)
        if srcs is not None:
            srcs = [os.path.join(self.dir, s) for s in srcs]
        elif self.part == "c":
            srcs = self.sources
        else:
            raise BenchError(f"{self.name}: no reference (reference() or REFERENCE_C)")
        return run_host(srcs, p, self.data(size), self.input(size), [self.dir])


def names():
    return sorted(d for d in os.listdir(WORKLOADS)
                  if os.path.exists(os.path.join(WORKLOADS, d, "workload.py")))


@functools.lru_cache(None)
def get(name):
    if name not in names():
        raise BenchError(f"no workload {name!r} (there are: {', '.join(names())})")
    return Workload(name)


def workloads(only=None):
    """The workloads, hand-written first, each part by category and name."""
    ws = [get(n) for n in (only or names())]
    if only:
        return ws
    return sorted(ws, key=lambda w: (list(PARTS).index(w.part), w.category, w.name))


# ---- building ---------------------------------------------------------------

def _equ(params):
    return "".join(f"{k} = {int(v)}\n" for k, v in params.items())


def asm_object(path, params, name=None):
    """An assembly source as an object file, the size's parameters defined
    in front of it (errors keep the file's own line numbers)."""
    from heron.infra import asm as A
    from heron.infra import isas
    with open(path) as f:
        text = f.read()
    pre = _equ(params)
    a = A.Assembler(isas.get(ISA), relocatable=True)
    try:
        a.load(path, text=pre + text)
        return a.assemble_object(name or os.path.basename(path)[:-2] + ".o")
    except A.AsmError as e:
        if e.where and e.where[0] == path:
            e.where = (path, e.where[1] - pre.count("\n"))
        raise


def data_asm(data, prefix=""):
    """Assembly for a workload's data: each name's bytes far (they may be
    big), and its length, NAME_len, as a near word."""
    out = []
    for name, b in sorted(data.items()):
        sym = prefix + name
        out.append(f"        .section .fardata.{sym}\n        .global {sym}\n        .align 4\n{sym}:")
        for i in range(0, len(b), 32):
            out.append("        .byte " + ", ".join(str(x) for x in b[i:i + 32]))
        out.append(f"        .section .data.{sym}_len\n        .global {sym}_len\n"
                   f"        .align 4\n{sym}_len:\n        .word {len(b)}")
    return "\n".join(out) + "\n"


def data_c(data):
    out = []
    for name, b in sorted(data.items()):
        body = ",".join(str(x) for x in b) or "0"
        out.append(f"const unsigned char {name}[] = {{{body}}};\nunsigned {name}_len = {len(b)};")
    return "\n".join(out) + "\n"


def _link(objs):
    from heron.infra import link as L
    return L.link(objs, [], ISA)


@functools.lru_cache(None)
def _lib_objects():
    from heron.infra import asm as A
    from heron.infra import isas
    out = {}
    for f in ("start", "util"):
        p = os.path.join(LIB, f + ".s")
        a = A.Assembler(isas.get(ISA), relocatable=True)
        a.load(p)
        out[f] = a.assemble_object(f + ".o")
    return out


def _data_object(data, prefix):
    from heron.infra import asm as A
    from heron.infra import isas
    a = A.Assembler(isas.get(ISA), relocatable=True)
    a.load("data.s", text=data_asm(data, prefix))
    return a.assemble_object("data.o")


@functools.lru_cache(None)
def _image(name, size):
    w = get(name)
    p = w.params(size)
    custom = getattr(w.mod, "build", None)
    if custom is not None:
        return custom(p)
    data = w.data(size)
    if w.part == "asm":
        lib = _lib_objects()
        objs = [lib["start"]] + [asm_object(s, p) for s in w.sources] + [lib["util"]]
        if data:
            objs.append(_data_object(data, ""))
        img = _link(objs)
    else:
        from heron.studies.c_compiler.cc import driver
        from heron.studies.c_compiler.cc.lex import CompileError
        prog = driver.Program(ISA)
        defs = {k: str(v) for k, v in p.items()}
        try:
            for s in w.sources + [os.path.join(LIB, "bench.c")]:
                prog.add_file(s, [LIB, w.dir], defs)
            prog.add_library()
            if data:
                prog.add_object(_data_object(data, "_"))
            img = prog.link()
        except CompileError as e:
            raise BenchError(f"{name}: {e}") from None
    return img, w.input(size)


# ---- the host reference --------------------------------------------------------

def run_host(sources, params, data=None, inp=b"", include=(), timeout=600):
    """C sources built with gcc and bench.c, the data linked in, run on the
    host: its output. The C is the same as the machine's: int and pointers
    aside, it must not depend on the host (char is unsigned, as on Heron;
    long is 64 bits here and 32 there, so the workloads don't use it)."""
    os.makedirs(OUT, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=OUT) as d:
        dc = os.path.join(d, "data.c")
        with open(dc, "w") as f:
            f.write(data_c(data or {}))
        exe = os.path.join(d, "a.out")
        cmd = ["gcc", "-O1", "-w", "-std=gnu99", "-funsigned-char", "-fwrapv",
               "-fno-builtin", "-DBENCH_HOST=1", "-I", LIB]
        for i in include:
            cmd += ["-I", i]
        cmd += [f"-D{k}={v}" for k, v in params.items()]
        cmd += list(sources) + [os.path.join(LIB, "bench.c"), dc, "-o", exe]
        r = subprocess.run(cmd, capture_output=True, text=True)
        if r.returncode:
            raise BenchError("gcc failed:\n" + r.stderr)
        r = subprocess.run([exe], input=inp, capture_output=True, timeout=timeout)
        if r.returncode:
            raise BenchError(f"the host reference exited with {r.returncode}: "
                             + r.stderr.decode(errors="replace"))
        return r.stdout


def write_expected(w, sizes=SIZES):
    for size in sizes:
        out = w.reference(size)
        path = w.expected_path(size)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as f:
            f.write(out)
        yield size, len(out)


# ---- running on the instruction-level simulator -----------------------------------

class Run:
    """A workload run on the instruction-level simulator."""

    def __init__(self, w, size, m, img, error):
        self.workload = w
        self.size = size
        self.machine = m
        self.image = img
        self.output = bytes(m.dev.out)
        self.expected = w.expected(size)
        self.error = error
        if error is None and m.in_trap:
            self.error = "halted in a trap handler: " + ", ".join(
                f"{what} at {pc:X}" for pc, what in m.traps[-3:])
        if self.error is None:
            bad = tentative(m)
            if bad:
                self.error = "runs tentative instructions: " + ", ".join(sorted(bad))
        if self.error is None and self.expected is None:
            self.error = "no expected output (heron bench expected)"
        elif self.error is None and self.output != self.expected:
            i = next((k for k, (a, b) in enumerate(zip(self.output, self.expected)) if a != b),
                     min(len(self.output), len(self.expected)))
            self.error = (f"output differs from the expected at byte {i}: "
                          f"{self.output[max(0, i - 40):i + 40]!r}")

    @property
    def ok(self):
        return self.error is None


def tentative(m):
    """The tentative instructions a finished run executed."""
    from heron.infra import isas
    isa = isas.get(ISA)
    out = set()
    for pc in m.pc_counts:
        ws = [m.parcel(pc + 2 * k) for k in range(3)]
        op = isa.disassemble(ws, pc)[0].split()[0].upper()
        if op in TENTATIVE:
            out.add(op)
    return out


def run(w, size="ref", trace=None):
    from heron.studies.v2_isa.sim import Machine, SimError
    img, inp = w.image(size)
    m = Machine(img, inp=inp)
    m.trace = trace
    err = None
    try:
        m.run(max_cycles=w.max_cycles)
    except SimError as e:
        err = str(e)
    return Run(w, size, m, img, err)


def image_key(img, inp):
    """A hash of an image and its input, for caching runs."""
    h = hashlib.sha1()
    for a, b in sorted(img.mem.items()):
        h.update(a.to_bytes(4, "little") + bytes([b]))
    h.update(b"\0input\0" + bytes(inp))
    return h.hexdigest()[:16]


def stats(r):
    """What a run on the instruction-level simulator says about a workload:
    its size, its instruction mix and how it spends the reference
    configuration's cycles."""
    from collections import Counter
    from heron.infra import isas
    from heron.studies.v2_isa import sim
    isa = isas.get(ISA)
    m = r.machine
    img = r.image

    def parcels(pc):
        return [m.parcel(pc + 2 * k) for k in range(3)]

    kinds = Counter()
    touched = 0
    for pc, n in m.pc_counts.items():
        ws = parcels(pc)
        kinds[isa.kind(ws)] += n
        touched += 2 * isa.disassemble(ws, pc)[1]
    lo, hi = img.extent()
    return {
        "instructions": m.instructions,
        "cycles": m.cycles_for(sim.REFERENCE),
        "code_bytes": img.code_bytes(),
        "code_touched": touched,
        "image_bytes": hi - lo,
        "stack_bytes": 0x100000 - m.min_sp if m.min_sp <= 0x100000 else 0,
        "data_bytes": m.data_bytes,       # bytes read and written, all told
        "kinds": dict(kinds),
        "output": len(r.output),
    }

