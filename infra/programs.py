"""Running test programs against their expected output: the parts every
study shares. A study's own testing module says where its programs are and
how to run one; see heron.studies.v1_isa.testing.

A test program is a .s file. Optional metadata lines in it:

    ;! input: "text\\n"         console input (Python string literal)
    ;! input-file: ../common/x  console input from a file (relative to the program)
    ;! max-cycles: 5000000
"""

import ast
import os


def metadata(path):
    meta = {"input": b"", "max-cycles": 50_000_000}
    with open(path) as f:
        for line in f:
            if line.startswith(";!"):
                key, _, val = line[2:].partition(":")
                key, val = key.strip(), val.strip()
                if key == "input":
                    meta["input"] = ast.literal_eval(val).encode("latin-1")
                elif key == "input-file":
                    with open(os.path.join(os.path.dirname(path), val), "rb") as g:
                        meta["input"] = g.read()
                elif key == "max-cycles":
                    meta["max-cycles"] = int(val)
                else:
                    meta[key] = val
    return meta


def read_expected(expected_dir, name):
    """The expected output for program `name`, or None if there is none."""
    p = os.path.join(expected_dir, name + ".txt")
    if not os.path.exists(p):
        return None
    with open(p, "rb") as f:
        return f.read()


def first_diff(a, b):
    for i, (x, y) in enumerate(zip(a, b)):
        if x != y:
            return i
    return min(len(a), len(b))


def run_suite(paths, run, verbose=False):
    """Run every program with run(path) -> result dict (name, ok, error,
    instructions, cycles, code_bytes, output, expected) and print a table.
    Returns an exit status."""
    if not paths:
        print("no programs found")
        return 1
    failed = 0
    print(f"{'program':<14} {'result':<6} {'instr':>10} {'cycles':>11} {'CPI':>5} {'code B':>7}")
    for p in paths:
        r = run(p)
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
            if r.get("expected") is not None and r.get("output") is not None and verbose:
                i = first_diff(r["output"], r["expected"])
                print(f"    first difference at byte {i}:")
                print(f"      got:      {r['output'][max(0, i - 40):i + 40]!r}")
                print(f"      expected: {r['expected'][max(0, i - 40):i + 40]!r}")
    print(f"\n{len(paths) - failed}/{len(paths)} passed")
    return 1 if failed else 0


def bench_table(rows, markdown=False):
    """Instructions, cycles and run time at a few clock speeds, per program."""
    clocks = [1e6, 2e6, 4e6]
    if markdown:
        print("| Program | Instructions | Cycles | CPI | Code bytes | " +
              " | ".join(f"@ {c / 1e6:g} MHz" for c in clocks) + " |")
        print("|---|---:|---:|---:|---:|" + "---:|" * len(clocks))
    for r in rows:
        if r.get("instructions") is None:
            continue
        cpi = r["cycles"] / max(1, r["instructions"])
        times = [fmt_time(r["cycles"] / c) for c in clocks]
        if markdown:
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


def halt_status(m):
    """Exit status for `run` once a machine has halted: 1 if it halted in a
    trap handler (a trap, SWI included, and no RTI since): the program's
    fatal error handler, or no handler at all, since a zero vector is HALT.
    Traps a handler returns from are fine."""
    if m.in_trap:
        import sys
        print("\nerror: halted in a trap handler", file=sys.stderr)
        return 1
    return 0
