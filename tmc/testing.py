"""Program test suite and instruction-level benchmark table.

Each top-level programs/*.s file is a test. Optional metadata lines:

    ;! input: "text\\n"         console input (Python string literal)
    ;! max-cycles: 5000000

Expected console output lives in programs/expected/<name>.txt, written by
programs/reference.py from independent Python implementations.
"""

import ast
import glob
import os
import sys

from . import asm as asmcore
from . import isa as isas
from .sim import Machine, SimError

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
PROGRAMS = os.path.join(ROOT, "programs")


def program_paths(names=None):
    paths = sorted(glob.glob(os.path.join(PROGRAMS, "*.s")))
    if names:
        paths = [p for p in paths if os.path.basename(p)[:-2] in names]
    return paths


def metadata(path):
    meta = {"input": b"", "max-cycles": 50_000_000}
    with open(path) as f:
        for line in f:
            if line.startswith(";!"):
                key, _, val = line[2:].partition(":")
                key, val = key.strip(), val.strip()
                if key == "input":
                    meta["input"] = ast.literal_eval(val).encode("latin-1")
                elif key == "max-cycles":
                    meta["max-cycles"] = int(val)
                else:
                    meta[key] = val
    return meta


def expected_output(name):
    p = os.path.join(PROGRAMS, "expected", name + ".txt")
    if not os.path.exists(p):
        return None
    with open(p, "rb") as f:
        return f.read()


def timing_for(isa_name):
    try:
        from .hw import microcode
    except ImportError:
        return None
    return microcode.timing_function(isa_name)


def run_program(path, isa_name=isas.DEFAULT, timing=True):
    """Assemble and run one program. Returns a result dict."""
    isa = isas.get(isa_name)
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
            res["error"] = "no expected output (run programs/reference.py)"
        elif out != exp:
            res["error"] = "output differs from expected"
        else:
            res["ok"] = True
    return res


def first_diff(a, b):
    for i, (x, y) in enumerate(zip(a, b)):
        if x != y:
            return i
    return min(len(a), len(b))


def cmd_test(args):
    paths = program_paths(args.names)
    if not paths:
        print("no programs found")
        return 1
    failed = 0
    print(f"{'program':<14} {'result':<6} {'instr':>10} {'cycles':>11} {'CPI':>5} {'code B':>7}")
    for p in paths:
        r = run_program(p, args.isa)
        status = "ok" if r["ok"] else "FAIL"
        if r.get("instructions") is not None:
            cpi = r["cycles"] / max(1, r["instructions"])
            print(f"{r['name']:<14} {status:<6} {r['instructions']:>10} {r['cycles']:>11}"
                  f" {cpi:>5.2f} {r['code_bytes']:>7}")
        else:
            print(f"{r['name']:<14} {status:<6}")
        if not r["ok"]:
            failed += 1
            print(f"    {r['error']}")
            if r.get("expected") is not None and r.get("output") is not None and args.v:
                i = first_diff(r["output"], r["expected"])
                print(f"    first difference at byte {i}:")
                print(f"      got:      {r['output'][max(0, i - 40):i + 40]!r}")
                print(f"      expected: {r['expected'][max(0, i - 40):i + 40]!r}")
    print(f"\n{len(paths) - failed}/{len(paths)} passed")
    return 1 if failed else 0


def cmd_bench(args):
    rows = []
    for p in program_paths():
        r = run_program(p, args.isa)
        rows.append(r)
    clocks = [1e6, 2e6, 4e6]
    if args.markdown:
        print("| Program | Instructions | Cycles | CPI | Code bytes | " +
              " | ".join(f"@ {c / 1e6:g} MHz" for c in clocks) + " |")
        print("|---|---:|---:|---:|---:|" + "---:|" * len(clocks))
    for r in rows:
        if r.get("instructions") is None:
            continue
        cpi = r["cycles"] / max(1, r["instructions"])
        times = [fmt_time(r["cycles"] / c) for c in clocks]
        if args.markdown:
            print(f"| {r['name']} | {r['instructions']:,} | {r['cycles']:,} | {cpi:.2f} | "
                  f"{r['code_bytes']} | " + " | ".join(times) + " |")
        else:
            print(f"{r['name']:<14} {r['instructions']:>10} {r['cycles']:>11} {cpi:>5.2f} "
                  f"{r['code_bytes']:>6}  " + "  ".join(f"{t:>9}" for t in times))
    return 0


def fmt_time(s):
    if s < 1e-3:
        return f"{s * 1e6:.0f} µs"
    if s < 1:
        return f"{s * 1e3:.1f} ms"
    return f"{s:.2f} s"


if __name__ == "__main__":
    sys.exit(cmd_test(type("A", (), {"names": sys.argv[1:], "isa": isas.DEFAULT, "v": True})))
