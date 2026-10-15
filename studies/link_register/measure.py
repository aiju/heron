"""Running the workloads on draft 1b and on v1bl, and what each run did.

A workload is a set of programs, each of which can be built for both ISAs
and checked against its expected output:

  asm    the draft 1 suite by hand: studies/v1_isa/programs/v1b on 1b, the
         ported copies in programs/ on v1bl
  c      the C versions (studies/c_compiler/programs), with the C library,
         compiled for each
  egret  Egret's programs on its VM, in its C and assembly builds
         (egret.py)

A run gives the instruction count, the cycles of the six configurations of
draft 1's timing model, the cycles on the 1b hardware (hw.py; for asm and
c also exactly, on the RTL model with each ISA's microcode), the code size,
and how the calls went (call_stats). Results are cached in
build/link_register/ until a file they depend on changes.
"""

import glob
import hashlib
import math
import os
import pickle
from concurrent.futures import ProcessPoolExecutor

from heron import BUILD, ROOT
from heron.infra import asm as asmcore
from heron.infra import isas
from heron.infra.programs import metadata
from heron.studies.v1_isa import testing, timing32
from heron.studies.v1_isa.sim32 import Machine32
from . import hw

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(BUILD, "link_register")
ISAS = ("v1b", "v1bl")
CDIR = os.path.join(ROOT, "studies", "c_compiler", "programs")
# Left out of the means, as in report 0012: hello does no work, and
# interrupts mostly waits in HALT.
SKIP = ("hello", "interrupts")


def geomean(xs):
    xs = list(xs)
    return math.exp(sum(math.log(x) for x in xs) / len(xs))


# ---- what a run did ---------------------------------------------------------------

CALLS = ("call", "callm", "link", "linkm")


def call_stats(m):
    """Executed calls and returns, and how the return address was kept:

    calls        BSR and CALL, every form
    pushes       v1bl: the link register saved on the stack (SAVE r7-rN,
                 PUSH r7); a copy to another register (lines.s's plot4)
                 isn't told from a use of r7 as data, so isn't counted
    stack_rets   1b's RET, and v1bl's JMP [sp]+ (a return that pops)
    """
    out = {"calls": 0, "pushes": 0, "stack_rets": 0}
    for (pc, k), n in m.pc_keys.items():
        if k[2] in CALLS:
            out["calls"] += n
        if pc is None:
            continue
        w = m.parcel(pc)
        if k[2] == "ret" or w == 0xB06F:                       # RET, JMP [sp]+
            out["stack_rets"] += n
        if (w & 0xF00F) == 0x0005 and (w >> 8) & 15 == 7:      # SAVE r7-rN
            out["pushes"] += n
        elif w == 0x277F:                                      # PUSH r7
            out["pushes"] += n
    return out


def result(m, ok, code_bytes):
    """What the tables need from a finished run."""
    cyc = m.all_cycles()
    return {"ok": ok, "instructions": m.instructions, "cycles": cyc,
            "hw": hw.total(m.pc_keys), "code": code_bytes, "calls": call_stats(m)}


def rtl_cycles(img, inp, isa, max_cycles):
    """The exact cycles on the 1b hardware, and the output, from the RTL
    model running the ISA's microcode."""
    from heron.studies.v1b_hw import ucode as uc
    from heron.studies.v1b_hw.rtl import RTL
    r = RTL(img, inp=inp, mc=uc.built(isa == "v1bl"))
    r.run(max_cycles=max_cycles)
    return r.cycles, r.out


# ---- the workloads ----------------------------------------------------------------

def asm_paths(isa):
    if isa == "v1b":
        return testing.program_paths(None, "v1b")
    d = os.path.join(HERE, "programs")
    return sorted(glob.glob(os.path.join(d, "*.s")))


def _asm_job(args):
    path, isa, rtl = args
    name = os.path.basename(path)[:-2]
    meta = metadata(path)
    mod = isas.get(isa)
    img = asmcore.assemble_file(mod, path)
    m = Machine32(mod, img, inp=meta["input"])
    m.run(max_cycles=meta["max-cycles"])
    exp = testing.expected_output(name)
    ok = not m.traps and bytes(m.dev.out) == exp
    res = result(m, ok, img.code_bytes())
    if rtl:
        res["rtl"], out = rtl_cycles(img, meta["input"], isa, 20 * meta["max-cycles"])
        res["ok"] = ok and out == exp
    return name, isa, res


def _c_build(path, isa):
    from heron.studies.c_compiler.cc import driver
    # char arrays aligned the same way in both builds, whatever the code
    # before them (driver.MIN_DATA_ALIGN)
    driver.MIN_DATA_ALIGN = 4
    prog = driver.Program(isa)
    _text, img, _ = driver.build([path], isa, program=prog)
    return img


def _c_input(name):
    asm = os.path.join(testing.program_dir("v1b"), name + ".s")
    return metadata(asm)["input"] if os.path.exists(asm) else b""


def _c_job(args):
    path, isa, rtl = args
    name = os.path.basename(path)[:-2]
    img = _c_build(path, isa)
    inp = _c_input(name)
    m = Machine32(isas.get(isa), img, inp=inp)
    m.run(max_cycles=200_000_000)
    exp = testing.expected_output(name)
    ok = not m.traps and bytes(m.dev.out) == exp
    res = result(m, ok, img.code_bytes())
    if rtl:
        res["rtl"], out = rtl_cycles(img, inp, isa, 200_000_000)
        res["ok"] = ok and out == exp
    return name, isa, res


def _sources(*dirs, exts=(".py", ".s", ".c", ".h", ".rs", ".eg")):
    out = []
    for d in dirs:
        for p in glob.glob(os.path.join(ROOT, d, "**", "*"), recursive=True):
            if p.endswith(exts) and "/tests/" not in p:
                out.append(p)
    return sorted(out)


def _digest(paths):
    h = hashlib.sha1()
    for p in paths:
        with open(p, "rb") as f:
            h.update(p.encode() + b"\0" + f.read())
    return h.hexdigest()[:12]


def _cached(name, deps, compute):
    """compute(), cached in build/link_register/ by the digest of deps."""
    path = os.path.join(OUT, f"{name}-{_digest(deps)}.pkl")
    if os.path.exists(path):
        with open(path, "rb") as f:
            return pickle.load(f)
    out = compute()
    os.makedirs(OUT, exist_ok=True)
    with open(path + ".tmp", "wb") as f:
        pickle.dump(out, f)
    os.replace(path + ".tmp", path)
    return out


_BASE_DEPS = ("studies/link_register", "studies/v1_isa/isa", "studies/v1b_hw/ucode.py",
              "studies/v1b_tradeoffs/cycles.py")


def _run_jobs(fn, jobs, workers):
    out = {}
    with ProcessPoolExecutor(workers) as ex:
        for name, isa, res in ex.map(fn, jobs):
            out.setdefault(name, {})[isa] = res
    return out


def asm(rtl=True, workers=4):
    """{program: {isa: result}} for the hand-written suite."""
    deps = _sources(*_BASE_DEPS, "studies/v1_isa/programs")
    jobs = [(p, isa, rtl) for isa in ISAS for p in asm_paths(isa)]
    return _cached(f"asm{'-rtl' if rtl else ''}", deps, lambda: _run_jobs(_asm_job, jobs, workers))


def c(rtl=True, workers=4):
    """{program: {isa: result}} for the C versions."""
    deps = _sources(*_BASE_DEPS, "studies/c_compiler", "studies/v1_isa/programs")
    paths = sorted(glob.glob(os.path.join(CDIR, "*.c")))
    jobs = [(p, isa, rtl) for isa in ISAS for p in paths]
    return _cached(f"c{'-rtl' if rtl else ''}", deps, lambda: _run_jobs(_c_job, jobs, workers))


def _egret_job(args):
    name, isa, variant = args
    from . import egret as E
    from heron.studies.egret.programs import catalogue
    base = E.machine(isa, variant, b"")
    if name is None:
        return None, (isa, variant), result(base, True, E.image(isa, variant).code_bytes())
    prog = catalogue.program(name)
    m = E.machine(isa, variant, prog.source, prog.input)
    res = result(m, bytes(m.dev.out) == prog.expected(), 0)
    # the program alone: the empty program's start-up and prelude taken off
    b = result(base, True, 0)
    res["instructions"] -= b["instructions"]
    res["hw"] -= b["hw"]
    res["cycles"] = {c: v - b["cycles"][c] for c, v in res["cycles"].items()}
    res["calls"] = {k: v - b["calls"][k] for k, v in res["calls"].items()}
    return name, (isa, variant), res


def egret(workers=4):
    """{program: {(isa, variant): result}} for Egret's programs on its C and
    assembly builds, the empty program's cycles taken off; program None is
    the empty program itself (start-up, and compiling the prelude)."""
    from . import egret as E
    from heron.studies.egret.programs import catalogue
    deps = _sources(*_BASE_DEPS, "studies/c_compiler", "studies/egret")
    jobs = [(n, isa, v) for v in E.VARIANTS for isa in ISAS
            for n in [None] + catalogue.names()]

    def compute():
        for isa in ISAS:                  # build the images once, not per worker
            for v in E.VARIANTS:
                E.image(isa, v)
        return _run_jobs(_egret_job, jobs, workers)
    return _cached("egret", deps, compute)


def configs():
    return list(timing32.CONFIG_NAMES)
