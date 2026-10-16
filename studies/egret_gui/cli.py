"""The GUI's command line: heron egret_gui <command> ...

  shot   [--depth D] [--source F.eg] [--do ACTIONS] [-o OUT.png]
                     boot the desktop (or a program) without a browser,
                     do some things to it, and save the screen
  web    [-o DIR] [--source F.eg]
                     the browser version as static files (default
                     build/egret_gui/web/): the page, the simulator as
                     WebAssembly, and snapshots of the machine
  serve  [--port N] [--source F.eg]
                     build the browser version and serve it on localhost
  bench  [--write]   what the desktop costs on the machine, on draft 1b
                     and draft 2 (--write: the report's performance.md)
  test               the study's unit tests (heron test egret_gui)

Actions for shot, separated by ';': `click X Y`, `drag X0 Y0 X1 Y1`,
`type TEXT` (\\n for return), `key NAME [MODS...]`, `wait SECONDS`,
`png FILE`.
"""

import argparse
import os
import sys

from . import build, run


def do_actions(s, actions):
    for act in filter(None, (a.strip() for a in actions.split(";"))):
        word, _, rest = act.partition(" ")
        args = rest.split()
        if word == "click":
            s.click(int(args[0]), int(args[1]))
        elif word == "drag":
            s.drag(*map(int, args[:4]))
        elif word == "type":
            s.type(rest.replace("\\n", "\n"))
        elif word == "key":
            s.key(args[0], args[1:])
        elif word == "wait":
            s.run(float(args[0]))
        elif word == "png":
            s.png(args[0])
        else:
            raise SystemExit(f"no action {word!r}")


def cmd_shot(args):
    source = open(args.source).read() if args.source else None
    s = run.Session(source, args.depth, isa=args.isa).boot()
    if args.do:
        do_actions(s, args.do)
    s.run(0.2)
    s.png(args.out)
    sys.stdout.write(s.output)
    print(f"[{s.seconds:.1f} s of machine time; screen in {args.out}]")
    return 0


def cmd_web(args):
    from . import web
    source = open(args.source).read() if args.source else None
    path = web.site(args.out, source=source)
    print(f"wrote {os.path.relpath(path)}")
    return 0


def cmd_serve(args):
    import functools
    import http.server
    from . import web
    source = open(args.source).read() if args.source else None
    path = web.site(source=source)
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=path)
    handler.extensions_map = {**http.server.SimpleHTTPRequestHandler.extensions_map,
                              ".wasm": "application/wasm"}
    with http.server.ThreadingHTTPServer(("127.0.0.1", args.port), handler) as srv:
        print(f"serving {os.path.relpath(path)} at http://127.0.0.1:{args.port}/ (Ctrl-C stops)")
        try:
            srv.serve_forever()
        except KeyboardInterrupt:
            pass
    return 0


def cmd_bench(args):
    from . import bench
    r = bench.measure()
    r2 = bench.measure(isa="v2")
    print(bench.tables(r, r2))
    if args.write:
        print(f"wrote {os.path.relpath(bench.write(r, r2))}")
    return 0


def cmd_test(args):
    from heron.__main__ import cmd_test as test
    return test(["egret_gui"], False, args.verbose)


def main(argv=None):
    p = argparse.ArgumentParser(prog="heron egret_gui", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("shot")
    s.add_argument("--depth", type=int, default=3, choices=range(4))
    s.add_argument("--isa", default="v1b", choices=build.ISAS)
    s.add_argument("--source")
    s.add_argument("--do")
    s.add_argument("-o", "--out", default="egret_gui.png")
    s.set_defaults(fn=cmd_shot)
    s = sub.add_parser("web")
    s.add_argument("-o", "--out", default=None)
    s.add_argument("--source")
    s.set_defaults(fn=cmd_web)
    s = sub.add_parser("serve")
    s.add_argument("--port", type=int, default=8000)
    s.add_argument("--source")
    s.set_defaults(fn=cmd_serve)
    s = sub.add_parser("bench")
    s.add_argument("--write", action="store_true")
    s.set_defaults(fn=cmd_bench)
    s = sub.add_parser("test")
    s.add_argument("-v", "--verbose", action="store_true")
    s.set_defaults(fn=cmd_test)
    args = p.parse_args(argv)
    if getattr(args, "out", 1) is None:
        from . import web
        args.out = web.SITE
    try:
        return args.fn(args)
    except run.Halted as e:
        print(e, file=sys.stderr)
        return 1
