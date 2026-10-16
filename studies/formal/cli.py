"""The formal verification study's command line: heron formal <command> ...

  isacheck [-n N] [--seed S] [--coverage]   the specification against the
                                            instruction-level simulator
  prove [--kind K] [--key KEY] [--sample N] [--jobs J] [--budget S]
                                            prove decode cases of the 1b
                                            hardware against the specification
  mutate [-n N] [--kind netlist|ucode]      mutation testing: mistakes put in
                                            on purpose, caught by tests or proofs
  report [--write]                          report 0038's generated tables
"""

import sys


def main(argv=None):
    argv = sys.argv[1:] if argv is None else list(argv)
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__)
        return 0
    cmd, rest = argv[0], argv[1:]
    if cmd == "isacheck":
        from .isacheck import main as m
        return m(rest)
    if cmd == "prove":
        from .prove import main as m
        return m(rest)
    if cmd == "mutate":
        from .mutate import main as m
        return m(rest)
    if cmd == "report":
        from .report import main as m
        return m(rest)
    print(f"heron formal: no command {cmd!r}", file=sys.stderr)
    return 2
