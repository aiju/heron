"""The simulator's command line: heron websim <command> ...

  list                          the machines
  build [-o DIR] [MACHINE...]   the simulator as static files (build/websim/site by
                                default): the engine for the browser, the page, the
                                machines (all, or those named)
  serve [--port N] [MACHINE...] build it, then serve it on localhost
  check [MACHINE...]            boot each machine here, on the same engine, and check
                                it answers as it should (what the tests do)
  run MACHINE                   a machine's terminal in this one (^] quits a raw one,
                                the end of the input a line one)
"""

import argparse
import os
import sys
import time

from . import machines as M


def cmd_list(args):
    w = max(len(m.id) for m in M.MACHINES)
    for m in M.MACHINES:
        print(f"{m.id:{w}}  {m.group}, {m.variant}: {m.summary}")
    return 0


def _ids(names):
    for n in names:
        M.get(n)
    return set(names) or None


def cmd_build(args):
    from . import web
    path = web.write(os.path.abspath(args.out), _ids(args.machines))
    print(f"wrote {os.path.relpath(os.path.dirname(path))}")
    return 0


def cmd_serve(args):
    from heron.site import serve
    cmd_build(args)
    return serve(os.path.abspath(args.out), args.port)


def cmd_check(args):
    from . import run
    bad = 0
    for m in [M.get(n) for n in args.machines] or M.MACHINES:
        t = time.time()
        try:
            run.check(m)
            print(f"ok    {m.id} ({time.time() - t:.1f} s)")
        except Exception as e:      # noqa: BLE001 (every machine is checked)
            bad += 1
            print(f"FAIL  {m.id}: {e}")
    return 1 if bad else 0


def cmd_run(args):
    from . import run
    return run.console(M.get(args.machine))


def main(argv=None):
    from . import web
    p = argparse.ArgumentParser(prog="heron websim", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list").set_defaults(fn=cmd_list)
    for name, fn in (("build", cmd_build), ("serve", cmd_serve)):
        b = sub.add_parser(name)
        b.add_argument("machines", nargs="*")
        b.add_argument("-o", "--out", default=web.OUT)
        if name == "serve":
            b.add_argument("--port", type=int, default=8000)
        b.set_defaults(fn=fn)
    c = sub.add_parser("check")
    c.add_argument("machines", nargs="*")
    c.set_defaults(fn=cmd_check)
    r = sub.add_parser("run")
    r.add_argument("machine")
    r.set_defaults(fn=cmd_run)
    args = p.parse_args(argv)
    try:
        return args.fn(args)
    except (KeyError, RuntimeError) as e:
        print(f"heron websim: {e.args[0] if e.args else e}", file=sys.stderr)
        return 1
