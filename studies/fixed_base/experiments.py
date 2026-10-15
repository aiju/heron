"""The measurements: Egret, the Lisp and the nucleus, on 1b and on 1b with
[rT + 4R].

- Egret and the nucleus run for real: the code is assembled with the
  mode (the assembler picks it for every [rT + 0..60] word, as it picks
  [sp + 4R]), Egret's JIT emits it (EGRET_RT in jit.c), and the machine
  decodes it. Nothing else in their code changes, so rT is a register the
  code already keeps a struct in.
- Every workload is also scanned (scan.py): what any choice of rT, or
  RFC 0028's other short form, MOV and ST [R + 4k] with any base, would
  save, from the baseline run alone.
- The Lisp has no such register (its pointers are tagged, so its fields
  are at 4k + 1 or 4k - 1); what keeping the current closure in rT would
  save is estimated from the compiled code (lisp_closures).
"""

import contextlib
import math
import os

from . import isa, scan

CONFIGS = scan.CONFIGS


def geomean(xs):
    xs = list(xs)
    return math.exp(sum(math.log(x) for x in xs) / len(xs))


# ---- Egret ----------------------------------------------------------------------------

@contextlib.contextmanager
def _assembling_as(name):
    """The C compiler's driver assembles with the encoder of ISA `name`
    (its objects are still 1b's, so they link with the C library's)."""
    from heron.studies.c_compiler.cc import driver
    orig = driver.assemble
    driver.assemble = lambda _isa, text, obj: orig(name, text, obj)
    driver._library.clear()
    try:
        yield
    finally:
        driver.assemble = orig
        driver._library.clear()


def egret_image(variant, rt=None):
    """(image, ISA module): Egret's VM, with every part assembled for
    v1b+rtN and the JIT emitting the mode when rt is given."""
    from heron.infra import isas
    from heron.studies.egret import build
    if rt is None:
        return build.heron("v1b", None, variant), isas.get("v1b")
    mod = isa("v1b", rt)
    with _assembling_as(mod.NAME):
        img = build.heron("v1b", {"EGRET_RT": str(rt)}, variant)
    return img, mod


def egret_machine(image, source, inp=b""):
    from heron.studies.egret import build
    from heron.studies.v1_isa.sim32 import Machine32
    img, mod = image
    data = source + (b"\n__END__\n" + inp if inp else b"")
    m = Machine32(mod, img, inp=data)
    m.run(max_cycles=build.MAX_CYCLES)
    return m


def egret_program(image, prog):
    """A program's own run: its cycles less start-up and compiling it (a
    #!check run), as report 0017 counts them; and whether it printed
    what it should."""
    m = egret_machine(image, prog.source, prog.input)
    chk = egret_machine(image, b"#!check\n" + prog.source)
    out = {c: m.cycles_avg(c) - chk.cycles_avg(c) for c in CONFIGS}
    out["ok"] = bytes(m.dev.out) == prog.expected()
    return out, m, chk


def egret(variant, rts, names=None, log=None):
    """{program: {rt: cycles by config, 'ok'}, with rt None the baseline,
    and 'scan': the baseline's Scan}"""
    from heron.studies.egret.programs import catalogue
    images = {rt: egret_image(variant, rt) for rt in [None] + list(rts)}
    out = {}
    for name in names or catalogue.names():
        p = catalogue.program(name)
        row = {}
        for rt, image in images.items():
            row[rt], m, chk = egret_program(image, p)
            if rt is None:
                row["scan"] = scan.Scan().add_machine(m).add_machine(chk, weight=-1)
        out[name] = row
        if log:
            log(f"egret {variant} {name}")
    return out


# ---- the nucleus ---------------------------------------------------------------------

@contextlib.contextmanager
def _nucleus_as(name):
    """The kernel study's nucleus assembled, and booted, as ISA `name`;
    the user programs stay v1bs."""
    from heron.infra import asm as asmcore
    from heron.infra import isas
    from heron.studies.kernel import build
    from heron.studies.v1_isa.sim32 import Machine32
    orig_kernel, orig_machine = build.kernel, build.Boot.machine
    cache = {}

    def kernel(features):
        key = tuple(sorted(features))
        if key not in cache:
            build.check_features(key)
            with open(build.NUCLEUS) as f:
                text = build.preprocess(f.read(), key)
            a = asmcore.Assembler(isas.get(name))
            a.load(build.NUCLEUS, text=text)
            cache[key] = a.assemble()
        return cache[key]

    def machine(self, reference=build.REFERENCE):
        class _Img:
            mem = self.mem
        return Machine32(isas.get(name), _Img(), reference=reference)

    build.kernel, build.Boot.machine = kernel, machine
    try:
        yield
    finally:
        build.kernel, build.Boot.machine = orig_kernel, orig_machine


SCENARIOS = ["yield", "ipc", "preempt", "irqdrv", "wipc", "wserv1"]


def _nucleus_scan(r):
    """(Scan, operations): the nucleus's own instructions in the
    difference of the n and 2n runs (user programs left out), and the
    operations that difference is."""
    ra, rb = r.runs
    s = r.scenario
    if s.name in ("preempt", "irqdrv"):
        ops = rb.m.irqs - ra.m.irqs
    else:
        ops = s.n * s.per
    pcs = {pc for run in (ra, rb) for pc, _, _ in run.m._m.pc_keys()
           if pc is not None and not run.boot.symbol_at(pc).startswith("user:")}
    sc = scan.Scan().add_machine(rb.m, pcs=pcs).add_machine(ra.m, weight=-1, pcs=pcs)
    return sc, ops


def kernel(rts, names=None, log=None):
    """{(scenario, banks): {rt: cycles per operation by config, 'scan':
    the baseline nucleus's Scan, 'ops'}}"""
    from heron.studies.kernel import bench, build
    out = {}
    for name in names or SCENARIOS:
        for b in build.BANKS:
            r = bench.measure(name, b, CONFIGS)
            sc, ops = _nucleus_scan(r)
            out[(name, b)] = {None: r.per_op, "scan": sc, "ops": ops}
    for rt in rts:
        with _nucleus_as(isa("v1bs", rt).NAME):
            for (name, b), row in out.items():
                row[rt] = bench.measure(name, b, CONFIGS).per_op
        if log:
            log(f"kernel rt{rt}")
    return out


def nucleus_size(rts):
    """{banks: {rt: bytes of instructions}}, rt None the baseline"""
    from heron.infra import asm as asmcore
    from heron.infra import isas
    from heron.studies.kernel import build
    out = {}
    for b in build.BANKS:
        with open(build.NUCLEUS) as f:
            text = build.preprocess(f.read(), (b,))
        out[b] = {}
        for rt in [None] + list(rts):
            a = asmcore.Assembler(isas.get("v1bs") if rt is None else isa("v1bs", rt))
            a.load(build.NUCLEUS, text=text)
            out[b][rt] = a.assemble().code_bytes()
    return out


# ---- the Lisp ------------------------------------------------------------------------

LISP_FEATURES = ("tagged",)


def lisp_programs():
    from heron import ROOT
    d = os.path.join(ROOT, "studies", "lisp", "programs")
    return sorted(f[:-5] for f in os.listdir(d) if f.endswith(".lisp"))


def lisp(names=None, log=None):
    """Compiled Lisp (with v1bx's tagged operations, as the baseline),
    over the compiled forms' running: {program: {'scan', 'closures',
    'runtime_vars'}}.

    closures: what keeping the current closure in rT would save, by
    config. A free variable is read now as MOV r, [sp + 4k] (the closure)
    and MOV r, [r + 5 + 4i]; with the closure in rT it would be one
    one-parcel load. Each entry to a function with free variables would
    then set rT and keep the caller's, two more one-parcel instructions
    than the closure push it has now, costed at 6 cycles on D32-separate
    and 4 on D32-wide. Reaching the fields at 5 + 4i needs either an
    untagged rT, which the collector would have to know about, or
    pointers whose fields are at multiples of 4.

    runtime_vars: executed words at absolute addresses 0x100-0x13F, the
    runtime's variables (the heap and stack limits): what a globals
    pointer in rT would reach."""
    from heron.studies.lisp import machine, measure
    from heron import ROOT
    out = {}
    for name in names or lisp_programs():
        with open(os.path.join(ROOT, "studies", "lisp", "programs", name + ".lisp"), "rb") as f:
            text = f.read()
        r = machine.run(text, LISP_FEATURES, compiled=True, reference=measure.CONFIG)
        if r.error:
            raise RuntimeError(f"{name}: {r.error}")
        counts = measure.window_counts(text, LISP_FEATURES, r)
        items = [(pc, k, n) for (pc, k), n in counts.items() if n]
        p = r.machine._m.parcel
        sc = scan.Scan().add(items, p)
        code_base = r.image.symbols["gen_end"]
        catmap = r.image.symbols["CATMAP"]
        mem = r.machine.mem

        def cat(pc):
            return measure.CATEGORIES[mem[catmap + (pc - code_base) // 2]]

        saved, reads, entries = {c: 0 for c in CONFIGS}, 0, 0
        one = (1, 0, "ld", "rd", 4, 0)
        for pc, key, n in items:
            if pc is None or pc < code_base:
                continue
            w = p(pc)
            op, d, mode, rn = w >> 12, (w >> 8) & 15, (w >> 4) & 15, w & 15
            if cat(pc) == "var" and op == 1 and mode == 3 and d == rn:
                disp = scan.sext16(p(pc + 2))
                if disp >= 5 and disp % 4 == 1:
                    reads += n
                    for c in CONFIGS:
                        saved[c] += n * (scan.cycles(key, c) + scan.cycles(one, c)
                                         - scan.cycles((1,) + tuple(key[1:]), c))
            if op == 2 and mode == 7 and rn == 15 and d == 1:
                prev = p(pc - 2)    # PUSH r1 after the entry's SAVE or stack check
                if cat(pc - 2) == "entry" and (prev >> 12 == 0xE or (prev >> 12 == 0 and prev & 15 == 5)):
                    entries += n
        for c in CONFIGS:
            saved[c] -= entries * (6 if c == "D32-separate" else 4)
        rv = sum(v for a, v in sc.abs16.items() if 0x100 <= a < 0x140)
        out[name] = {"scan": sc, "closures": saved, "reads": reads, "entries": entries,
                     "runtime_vars": rv}
        if log:
            log(f"lisp {name}")
    return out
