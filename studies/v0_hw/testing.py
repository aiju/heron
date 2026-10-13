"""Draft 0's test programs: every .s file directly in programs/ is one, run on
the instruction-level simulator (with cycle counts from the microcode) and
checked against the program suite's expected output, which lives in the
v1_isa study (see heron.studies.v1_isa.testing). Metadata lines are
described in heron.infra.programs.
"""

import os

from heron.infra import asm as asmcore
from heron.infra.programs import metadata, run_suite, bench_table, fmt_time  # noqa: F401
from heron.studies.v1_isa.testing import expected_output

from . import isa as v0
from .sim import Machine, SimError

HERE = os.path.dirname(os.path.abspath(__file__))
PROGRAMS = os.path.join(HERE, "programs")


def program_dir(isa_name="v0"):
    return PROGRAMS


def program_paths(names=None, isa_name="v0"):
    paths = sorted(os.path.join(PROGRAMS, f) for f in os.listdir(PROGRAMS) if f.endswith(".s"))
    if names:
        paths = [p for p in paths if os.path.basename(p)[:-2] in names]
    return paths


def timing_for(isa_name="v0"):
    from . import microcode
    return microcode.timing_function(isa_name)


def run_program(path, isa_name="v0", timing=True):
    """Assemble and run one program. Returns a result dict."""
    isa = v0
    name = os.path.basename(path)[:-2]
    meta = metadata(path)
    res = {"name": name, "path": path, "ok": False, "error": None}
    try:
        img = asmcore.assemble_file(isa, path)
    except asmcore.AsmError as e:
        res["error"] = f"assembly failed: {e}"
        return res
    m = Machine(isa, img, inp=meta["input"], timing=timing_for(isa_name) if timing else None)
    try:
        m.run(max_cycles=meta["max-cycles"])
    except SimError as e:
        res["error"] = str(e)
    out = bytes(m.dev.out)
    exp = expected_output(name)
    res.update(
        image=img, machine=m, output=out, expected=exp,
        instructions=m.instructions, cycles=m.cycles,
        code_bytes=img.code_bytes(), kinds=m.kinds, kind_cycles=m.kind_cycles,
        illegals=m.illegals, min_sp=m.min_sp, irqs=m.irqs,
    )
    if res["error"] is None:
        if m.illegals:
            res["error"] = f"illegal instruction(s): {m.illegals[:3]}"
        elif exp is None:
            res["error"] = "no expected output (run the v1_isa study's programs/reference.py)"
        elif out != exp:
            res["error"] = "output differs from expected"
        else:
            res["ok"] = True
    return res


def cmd_test(args):
    return run_suite(program_paths(args.names), run_program, args.v)


def cmd_bench(args):
    return bench_table([run_program(p) for p in program_paths()], args.markdown)
