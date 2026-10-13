"""The program suite: every .s file directly in programs/v1a or programs/v1b
is a test program for that encoding, run on the instruction-level
simulator and checked against programs/expected/<name>.txt.

The expected output is written by programs/reference.py from independent
Python implementations. It's shared: a program prints the same in every
draft (draft 0's versions in the v0_hw study too), and so does its C version
in the c_compiler study. Metadata lines are described in heron.infra.programs.
"""

import os

from heron.infra import asm as asmcore
from heron.infra import isas
from heron.infra.programs import metadata, read_expected, run_suite, bench_table, fmt_time  # noqa: F401

HERE = os.path.dirname(os.path.abspath(__file__))
PROGRAMS = os.path.join(HERE, "programs")
EXPECTED = os.path.join(PROGRAMS, "expected")


def program_dir(isa_name="v1b"):
    return os.path.join(PROGRAMS, isa_name)


def program_paths(names=None, isa_name="v1b"):
    d = program_dir(isa_name)
    paths = sorted(os.path.join(d, f) for f in os.listdir(d) if f.endswith(".s"))
    if names:
        paths = [p for p in paths if os.path.basename(p)[:-2] in names]
    return paths


def expected_output(name):
    return read_expected(EXPECTED, name)


def run_program(path, isa_name="v1b"):
    """Assemble and run one program on the instruction-level simulator.
    Returns a result dict."""
    from .sim32 import Machine32, SimError
    isa = isas.get(isa_name)
    name = os.path.basename(path)[:-2]
    meta = metadata(path)
    res = {"name": name, "path": path, "ok": False, "error": None}
    try:
        img = asmcore.assemble_file(isa, path)
    except asmcore.AsmError as e:
        res["error"] = f"assembly failed: {e}"
        return res
    m = Machine32(isa, img, inp=meta["input"])
    try:
        m.run(max_cycles=meta["max-cycles"])
    except SimError as e:
        res["error"] = str(e)
    out = bytes(m.dev.out)
    exp = expected_output(name)
    res.update(
        image=img, machine=m, output=out, expected=exp,
        instructions=m.instructions, cycles=m.cycles,
        code_bytes=img.code_bytes(), traps=m.traps, min_sp=m.min_sp, irqs=m.irqs,
    )
    if res["error"] is None:
        if m.traps:
            pc, what = m.traps[0]
            res["error"] = f"trap at pc {pc:X}: {what}" + (f" (+{len(m.traps) - 1} more)" if len(m.traps) > 1 else "")
        elif exp is None:
            res["error"] = "no expected output (run programs/reference.py)"
        elif out != exp:
            res["error"] = "output differs from expected"
        else:
            res["ok"] = True
    return res


def cmd_test(args):
    return run_suite(program_paths(args.names, args.isa), lambda p: run_program(p, args.isa), args.v)


def cmd_bench(args):
    return bench_table([run_program(p, args.isa) for p in program_paths(isa_name=args.isa)], args.markdown)
