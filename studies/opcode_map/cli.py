"""The opcode map's command line: heron opcode_map <command> ...

  build [-o FILE] [--map JSON]   the explorer with RFC 0028's map built in, as one
                                 page (build/opcode_map/opcode-map.html by default)
  serve [--port N] [--map JSON]  build it, then serve it on localhost
"""

import argparse
import os
import sys

from heron import BUILD

from . import page

OUT = os.path.join(BUILD, "opcode_map", "opcode-map.html")


def cmd_build(args):
    path = page.write(os.path.abspath(args.out), args.map)
    print(f"wrote {os.path.relpath(path)}")
    return 0


def cmd_serve(args):
    from heron.site import serve
    path = page.write(os.path.abspath(args.out), args.map)
    print(f"open http://localhost:{args.port}/{os.path.basename(path)}")
    return serve(os.path.dirname(path), args.port)


def main(argv=None):
    p = argparse.ArgumentParser(prog="heron opcode_map", description=__doc__.split("\n\n")[0],
                                formatter_class=argparse.RawDescriptionHelpFormatter, epilog=__doc__)
    sub = p.add_subparsers(dest="cmd", required=True)
    for name, fn in (("build", cmd_build), ("serve", cmd_serve)):
        q = sub.add_parser(name)
        q.add_argument("-o", "--out", default=OUT, help="the page to write")
        q.add_argument("--map", default=page.MAP, help="an exported map (default RFC 0028's)")
        if name == "serve":
            q.add_argument("--port", type=int, default=8000)
        q.set_defaults(fn=fn)
    a = p.parse_args(sys.argv[1:] if argv is None else argv)
    return a.fn(a)
