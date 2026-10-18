"""The editor's measurements: a fixed script of keys (bench_script) run in
every mode, layout, variant and drawing option, and each operation's
time from the key's arrival to the screen, as markdown tables for
NOTES.md.

    python3 studies/mini_gfx/apps/editor/measure.py          # everything (a few minutes, 4 at a time)
    python3 studies/mini_gfx/apps/editor/measure.py --quick  # M0 and M6 only
"""

import argparse
import multiprocessing
import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), *[".."] * 4))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from heron.studies.mini_gfx import programs  # noqa: E402
from heron.studies.mini.timing import TICK  # noqa: E402

WM_F1 = 8
WM_SNAP = 4
OPS = ["type", "enter", "delete", "caret", "select", "scroll", "page", "redraw"]


def bench_script(gap=6, x0=32, y0=40):
    """Keys a few frames apart, in the C file's window (its text at (x0, y0))."""
    steps = []
    f = 20

    def at(*s, wait=gap):
        nonlocal f
        steps.append(f"{f} " + " ".join(str(x) for x in s))
        f += wait

    def ctrl(k, wait=gap):
        at("keydown ctrl", wait=0)
        at("key", k, wait=0)
        at("keyup ctrl", wait=wait)

    # typing in the middle of a code line (row 18, column 20)
    at("click", x0 + 20 * 8 + 2, y0 + 18 * 16 + 8, wait=gap)
    for ch in "abcdefghij":
        at("key", ch)
    for _ in range(5):
        at("key backspace")
    # Enter near the top: the rows under it move down
    at("click", x0 + 20 * 8 + 2, y0 + 3 * 16 + 8, wait=gap)
    for _ in range(4):
        at("key enter", wait=2 * gap)
    for _ in range(6):
        at("key right")
    at("keydown shift", wait=0)
    for _ in range(6):
        at("key right")
    at("keyup shift")
    at("key esc")
    for _ in range(10):
        ctrl("down", wait=2 * gap)
    for _ in range(4):
        at("key pgdn", wait=4 * gap)
    for _ in range(3):
        ctrl("l", wait=6 * gap)
    ctrl("q")
    return "\n".join(steps) + "\n", f + 40


def prebuild(prog, variants):
    """Each variant built once before the runs: the build's object cache
    isn't safe for processes building the same file at once."""
    p = programs.get(prog)
    for v in sorted(variants):
        p.build(v)


def run_one(cfg):
    name, prog, variant, layout, pokes = cfg
    p = programs.get(prog)
    script, frames = bench_script()
    pk = {"_bench": 1}
    pk.update(pokes)
    r = p.run(variant=variant, layout=layout, frames=frames, script=script, pokes=pk)
    return name, r.perf, r.status, r.trap


def configs(quick=False):
    out = []
    modes = [(0, "M0"), (6, "M6")] if quick else [(0, "M0"), (3, "M3"), (4, "M4"), (5, "M5"),
                                                  (6, "M6")]
    for mode, mname in modes:
        layouts = [("L0", "L0", 0), ("L1", "L1", 0)]
        if mode >= 3:
            layouts.insert(1, ("F1", "L0", WM_F1))
        for lname, layout, opt in layouts:
            for v in ("c", "asm", "blk"):
                if mode in (5, 6) and v != "blk" and not quick:
                    continue
                out.append((f"{mname} {lname} {v}", "apps/editor", v, layout,
                            {"_wm_mode": mode, "_wm_options": opt}))
    # the drawing's options, in M0 and M6
    for mode, mname, lname, layout, opt in [(0, "M0", "L0", "L0", 0), (6, "M6", "F1", "L0", WM_F1),
                                            (6, "M6", "L0", "L0", 0)]:
        for v in ("c", "blk"):
            out.append((f"{mname} {lname} {v} lib", "apps/editor", v, layout,
                        {"_wm_mode": mode, "_wm_options": opt, "_text_lib": 1}))
            out.append((f"{mname} {lname} {v} no-move", "apps/editor", v, layout,
                        {"_wm_mode": mode, "_wm_options": opt, "_no_move": 1}))
    out.append(("M0 L0 blk mono", "apps/editor", "blk", "L0",
                {"_wm_mode": 0, "_colours": 0}))
    # the window off a word: the compositor's copies shift
    for mode, mname, lname, layout, opt, x in [(0, "M0", "L0", "L0", 0, 36),
                                               (6, "M6", "F1", "L0", WM_F1, 40)]:
        for v in ("c", "blk"):
            out.append((f"{mname} {lname} {v} x={x}", "apps/editor", v, layout,
                        {"_wm_mode": mode, "_wm_options": opt, "_win_x": x}))
    return out


def ms(t):
    return f"{t * TICK / 1e6:.2f}"


def table(results, names, key=lambda perf, op: perf.get(op, [0])[0]):
    head = "| | " + " | ".join(OPS) + " |"
    lines = [head, "|---" * (len(OPS) + 1) + "|"]
    for n in names:
        perf = results[n]
        lines.append(f"| {n} | " + " | ".join(ms(key(perf, op)) if op in perf else "–"
                                              for op in OPS) + " |")
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--quick", action="store_true")
    ap.add_argument("--jobs", type=int, default=4)
    ap.add_argument("--only", help="configurations whose names contain this")
    args = ap.parse_args()
    cfgs = configs(args.quick)
    if args.only:
        cfgs = [c for c in cfgs if args.only in c[0]]
    prebuild("apps/editor", {c[2] for c in cfgs})
    with multiprocessing.Pool(args.jobs) as pool:
        res = pool.map(run_one, cfgs)
    results = {}
    for name, perf, status, trap in res:
        if trap or status not in ("done", "halted"):
            print(f"{name}: {status} {trap or ''}", file=sys.stderr)
        results[name] = perf
    names = [c[0] for c in cfgs]
    print("Milliseconds from the key's arrival to the screen (the frame's composition done):\n")
    print(table(results, names))
    print("\nThe editor's part (the redisplay into the store), ms:\n")
    print(table(results, names, lambda p, op: p.get(op + "_app", [0])[0]))
    print("\nThe compositor's part, ms:\n")
    print(table(results, names, lambda p, op: p.get(op + "_comp", [0])[0]))
    print("\nWorst case (ms):\n")
    print(table(results, names, lambda p, op: p.get(op, [0, 0])[1]))
    print("\nWork per operation (cells drawn / rows drawn / rows moved), first configuration:\n")
    p = results[names[0]]
    for op in OPS:
        if op + "_work" in p:
            print(f"- {op}: {p[op + '_work']}")
    for n in names:
        if "first_frame" in results[n]:
            pass
    print("\nFirst frame (ms): " + ", ".join(f"{n} {ms(results[n].get('first_frame', [0])[0])}"
                                             for n in names))


if __name__ == "__main__":
    main()
