"""The graphics study's command line: heron graphics <command> ...

  run SCENE [--isa v1a|v1b] [--depth N] [--asm] [--png DIR] [--profile]
                    run a scene: every phase's cycles, checked against the
                    host reference
  test [SCENE...] [--isa ...]   every scene at every depth, for both ISAs,
                    compiled C and with the assembly kernels
  expected          rewrite expected/ from the host build (needs gcc)
  selftest          the word-level code against pixel-at-a-time
                    references, on the host (needs gcc)
  bench [--write]   the tables of report 0019 (--write: its performance.md)
"""

import argparse
import os
import subprocess
import sys

from . import build, run as runmod


def depths(arg):
    return [int(arg)] if arg is not None else [0, 1, 2, 3]


def cmd_run(args):
    img = build.image(args.isa, args.asm)
    for d in depths(args.depth):
        shots = None
        if args.png:
            from . import png
            os.makedirs(args.png, exist_ok=True)
            n = [0]

            def shots(name, scr, d=d):
                path = os.path.join(args.png, f"{args.scene}-{d}-{n[0]:02d}-{name}.png")
                png.write(path, scr, runmod.SCREEN_W, runmod.SCREEN_H, d)
                n[0] += 1
        phases = runmod.run(img, args.isa, args.scene, d, profile=args.profile, screens=shots)
        print(f"{args.scene} at {1 << d} bit{'s' if d else ''} per pixel, {args.isa}"
              f"{' with the assembly kernels' if args.asm else ''} ({args.config}):")
        for p in phases:
            if p.name.startswith("_") and not args.all:
                continue
            c = p.cycles[args.config]
            per = f"{c / p.count:10.1f} per unit" if p.count else ""
            print(f"  {p.name:<22} {c:12,.0f} cycles {c / 3000:10.1f} ms {per}")
            if args.profile:
                print_profile(img, args.isa, p, args.config)
        for msg in runmod.check(phases, args.scene, d):
            print("  " + msg)
    return 0


def print_profile(img, isa, p, config):
    from heron.studies.v1_isa import timing32
    from heron.infra import isas
    mod = isas.get(isa)
    labels = sorted((st.addr, st.label) for st in img.stmts if st.kind == "label" and "." not in st.label)
    import bisect
    starts = [a for a, _ in labels]
    by_fn = {}
    for (pc, key), n in p.keys.items():
        c = timing32.cycles(key, config) * n
        k = bisect.bisect_right(starts, pc) - 1 if pc is not None else -1
        name = labels[k][1] if k >= 0 else "?"
        by_fn[name] = by_fn.get(name, 0) + c
    total = sum(by_fn.values()) or 1
    for name, c in sorted(by_fn.items(), key=lambda x: -x[1])[:8]:
        print(f"      {name:<24} {100 * c / total:5.1f}%")
    del mod


def cmd_test(args):
    fails = 0
    scenes = args.scenes or [s for s in runmod.SCENES
                             if os.path.exists(runmod.expected_path(s, 0))]
    for isa in args.isa or build.ISAS:
        for kernels in (False, True):
            img = build.image(isa, kernels)
            for scene in scenes:
                for d in range(4):
                    msgs = runmod.check(runmod.run(img, isa, scene, d), scene, d)
                    what = f"{isa} {'asm' if kernels else 'C  '} {scene} depth {d}"
                    print(f"{what}: {'ok' if not msgs else 'FAIL'}")
                    for m in msgs:
                        print("    " + m)
                    fails += bool(msgs)
    print(f"{fails} failures" if fails else "all ok")
    return 1 if fails else 0


def cmd_expected(args):
    exe = build.host_binary()
    for scene in runmod.SCENES:
        for d in range(4):
            r = subprocess.run([exe, scene, str(d)], capture_output=True, text=True)
            if r.returncode:
                if "no scene" in r.stderr:
                    break
                print(r.stderr, file=sys.stderr)
                return 1
            with open(runmod.expected_path(scene, d), "w") as f:
                f.write(r.stdout)
            print(f"wrote {os.path.relpath(runmod.expected_path(scene, d))}")
    return 0


def cmd_selftest(args):
    """On the host (the C kernels, if gcc is there), then on the simulator
    for both ISAs (the assembly kernels)."""
    from heron.studies.c_compiler.cc import driver
    fails = 0
    if not args.machine_only:
        r = subprocess.run([build.selftest_binary()], capture_output=True, text=True)
        print(f"host (C kernels): {r.stdout.strip()}")
        fails += r.returncode != 0
    for isa in build.ISAS:
        m = driver.run_image(build.selftest_image(isa, args.iters), isa, max_cycles=20_000_000_000)
        out = bytes(m.dev.out).decode(errors="replace").strip()
        ok = m.error is None and not m.traps and out == "all good"
        print(f"{isa} (assembly kernels): {out or m.error or m.traps}")
        fails += not ok
    return 1 if fails else 0


def main(argv=None):
    p = argparse.ArgumentParser(prog="heron graphics", description="Graphics on draft 1")
    sub = p.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run", help="run a scene, phase by phase")
    r.add_argument("scene", choices=runmod.SCENES)
    r.add_argument("--isa", default="v1b", choices=build.ISAS)
    r.add_argument("--depth", type=int, choices=range(4))
    r.add_argument("--asm", action="store_true", help="with the assembly kernels")
    r.add_argument("--png", metavar="DIR", help="write the screen at every mark")
    r.add_argument("--config", default="D16-overlap", choices=runmod.CONFIGS)
    r.add_argument("--profile", action="store_true", help="where each phase spends its cycles")
    r.add_argument("--all", action="store_true", help="show the set-up phases too")
    r.set_defaults(fn=cmd_run)
    t = sub.add_parser("test", help="every scene against the host reference")
    t.add_argument("scenes", nargs="*")
    t.add_argument("--isa", action="append", choices=build.ISAS)
    t.set_defaults(fn=cmd_test)
    e = sub.add_parser("expected", help="rewrite expected/ with the host build (gcc)")
    e.set_defaults(fn=cmd_expected)
    s = sub.add_parser("selftest", help="the word-level code against pixel references")
    s.add_argument("--iters", type=int, default=200, help="iterations per depth on the simulator")
    s.add_argument("--machine-only", action="store_true", help="not on the host (no gcc needed)")
    s.set_defaults(fn=cmd_selftest)
    b = sub.add_parser("bench", help="report 0019's tables")
    b.add_argument("--write", action="store_true")
    b.set_defaults(fn=lambda a: __import__("heron.studies.graphics.bench", fromlist=["x"]).main(a.write))
    args = p.parse_args(argv)
    try:
        return args.fn(args) or 0
    except build.BuildError as e:
        print(f"heron graphics: {e}", file=sys.stderr)
        return 1
