"""The full-screen editor's measurements: the editor's script of keys
(apps/editor/measure.py, with this editor's coordinates) in every mode,
layout, variant, and with rows moved by descriptors or by copying, as
markdown tables for NOTES.md.

    python3 studies/mini_gfx/apps/fsedit/measure.py           # everything (a few minutes, 4 at a time)
    python3 studies/mini_gfx/apps/fsedit/measure.py --only M6
"""

import argparse
import importlib.util
import multiprocessing
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, *[".."] * 4))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from heron.studies.mini_gfx import programs  # noqa: E402

# the editor's script and tables (apps/editor/measure.py)
_spec = importlib.util.spec_from_file_location(
    "editor_measure", os.path.join(HERE, "..", "editor", "measure.py"))
editor_measure = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(editor_measure)

OPS = editor_measure.OPS
ms = editor_measure.ms


def bench_script(gap=6):
    """The editor's script, for text at the screen's top left."""
    return editor_measure.bench_script(gap, x0=0, y0=0)


def run_one(cfg):
    name, variant, layout, pokes = cfg
    p = programs.get("apps/fsedit")
    script, frames = bench_script()
    pk = {"_bench": 1}
    pk.update(pokes)
    r = p.run(variant=variant, layout=layout, frames=frames, script=script, pokes=pk)
    return name, r.perf, r.status, r.trap, r.stats


def configs():
    out = []
    for mode, mname in [(6, "M6"), (5, "M5"), (4, "M4"), (0, "M0")]:
        layouts = [("L0", "L0", 0), ("L1", "L1", 0)]
        if mode != 0:
            layouts.insert(0, ("F1", "L0", 1))
        for lname, layout, f1 in layouts:
            for v in ("c", "asm", "blk"):
                for copy in (0, 1):
                    out.append((f"{mname} {lname} {v} {'copy' if copy else 'desc'}", v, layout,
                                {"_mode": mode, "_f1": f1, "_scroll_copy": copy}))
    for mode, mname, lname, layout, f1 in [(6, "M6", "F1", "L0", 1), (6, "M6", "L0", "L0", 0),
                                           (0, "M0", "L0", "L0", 0)]:
        for v in ("c", "blk"):
            out.append((f"{mname} {lname} {v} desc lib", v, layout,
                        {"_mode": mode, "_f1": f1, "_text_lib": 1}))
    for v in ("c", "blk"):
        out.append((f"M6 F1 {v} desc bytes", v, "L0", {"_mode": 6, "_f1": 1, "_text_bytes": 1}))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--jobs", type=int, default=4)
    ap.add_argument("--only", help="configurations whose names contain this")
    args = ap.parse_args()
    cfgs = configs()
    if args.only:
        cfgs = [c for c in cfgs if args.only in c[0]]
    editor_measure.prebuild("apps/fsedit", {c[1] for c in cfgs})
    with multiprocessing.Pool(args.jobs) as pool:
        res = pool.map(run_one, cfgs)
    results, steals = {}, {}
    for name, perf, status, trap, stats in res:
        if trap or status not in ("done", "halted"):
            print(f"{name}: {status} {trap or ''}", file=sys.stderr)
        results[name] = perf
        steals[name] = (stats["steal_ticks"], stats["underruns"])
    names = [c[0] for c in cfgs]
    tab = editor_measure.table
    print("Milliseconds from the key's arrival to the screen's memory updated:\n")
    print(tab(results, names))
    print("\nMilliseconds from the key's arrival to the descriptor table's switch "
          "(rows moved by descriptors):\n")
    print(tab(results, names, lambda p, op: p.get(op + "_shown", [0])[0]))
    print("\nWorst case (ms):\n")
    print(tab(results, names, lambda p, op: p.get(op, [0, 0])[1]))
    print("\nWork per operation (cells drawn / rows drawn / rows moved / tables written):\n")
    for n in names[:2]:
        print(f"{n}: " + "; ".join(f"{op} {results[n][op + '_work']}" for op in OPS
                                   if op + "_work" in results[n]))
    print("\nFirst draw (ms): " + ", ".join(f"{n} {ms(results[n].get('first_draw', [0])[0])}"
                                            for n in names))
    print("\nVideo steals and underruns: " + ", ".join(f"{n} {steals[n]}" for n in names
                                                        if steals[n] != (0, 0)))


if __name__ == "__main__":
    main()
