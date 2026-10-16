"""The program suite on draft 2: every .s file directly in programs/ is a
test program, run on the instruction-level simulator and checked against
the expected output in studies/v1_isa/programs/expected/. Every draft
shares it: a program prints the same in each, and programs/reference.py
there writes it. Metadata lines are described in heron.infra.programs.
"""

import os

from heron.infra import asm as asmcore
from heron.infra import isas
from heron.infra.programs import bench_table, metadata, run_suite
from heron.studies.v1_isa import testing as suite

HERE = os.path.dirname(os.path.abspath(__file__))
PROGRAMS = os.path.join(HERE, "programs")


def program_paths(names=None):
    paths = sorted(os.path.join(PROGRAMS, f) for f in os.listdir(PROGRAMS) if f.endswith(".s"))
    if names:
        paths = [p for p in paths if os.path.basename(p)[:-2] in names]
    return paths


def expected_output(name):
    return suite.expected_output(name)


def run_program(path):
    """Assemble and run one program on the instruction-level simulator.
    Returns a result dict."""
    from .sim import Machine, SimError
    name = os.path.basename(path)[:-2]
    meta = metadata(path)
    res = {"name": name, "path": path, "ok": False, "error": None}
    try:
        img = asmcore.assemble_file(isas.get("v2"), path)
    except asmcore.AsmError as e:
        res["error"] = f"assembly failed: {e}"
        return res
    m = Machine(img, inp=meta["input"])
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
            res["error"] = "no expected output (run studies/v1_isa/programs/reference.py)"
        elif out != exp:
            res["error"] = "output differs from expected"
        else:
            res["ok"] = True
    return res


def cmd_test(args):
    return run_suite(program_paths(args.names), run_program, args.v)


def cmd_bench(args):
    return bench_table([run_program(p) for p in program_paths()], args.markdown)
