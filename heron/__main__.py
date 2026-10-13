"""The heron command (or python3 -m heron from the repository root).

  heron list                  the studies, with their status and dependencies
  heron test [NAME...] [-v]   unit tests: the repository's own (tests/) and
                              infra's by default, or the named studies'
                              (--active: every active study's)
  heron reports [--check]     rewrite reports/README.md, the index (--check:
                              only check the front matter)
  heron <study> ...           a study's own command line, for example
                              heron v1_isa run studies/v1_isa/programs/v1b/hello.s
"""

import argparse
import importlib
import os
import sys
import unittest

from . import ROOT, meta


def test_modules(directory, package):
    """Dotted names of the test_*.py modules in a directory."""
    if not os.path.isdir(directory):
        return []
    return [f"{package}.{f[:-3]}" for f in sorted(os.listdir(directory))
            if f.startswith("test_") and f.endswith(".py")]


def cmd_test(names, active, verbose):
    studies = meta.studies()
    if active:
        names = [n for n, fm in studies.items() if fm.get("status") == "active"]
    modules = []
    if not names:
        modules += test_modules(os.path.join(ROOT, "tests"), "heron.tests")
    for n in names:
        if n not in studies:
            print(f"no study {n!r} (heron list shows them)", file=sys.stderr)
            return 2
        modules += test_modules(os.path.join(ROOT, "studies", n, "tests"), f"heron.studies.{n}.tests")
    suite = unittest.defaultTestLoader.loadTestsFromNames(modules)
    result = unittest.TextTestRunner(verbosity=2 if verbose else 1).run(suite)
    return 0 if result.wasSuccessful() else 1


def cmd_list():
    for name, fm in meta.studies().items():
        deps = ", ".join(fm.get("depends-on") or []) or "-"
        print(f"{name:<14} {fm.get('status', '?'):<8} depends on: {deps}")
    return 0


def cmd_reports(check):
    msgs = meta.problems()
    for m in msgs:
        print(m, file=sys.stderr)
    if msgs:
        return 1
    if not check:
        with open(meta.INDEX, "w") as f:
            f.write(meta.index())
        print(f"wrote {os.path.relpath(meta.INDEX)}")
    return 0


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__.strip())
        print("\nstudies: " + ", ".join(meta.studies()))
        return 0
    cmd, rest = argv[0], argv[1:]
    if cmd == "list":
        return cmd_list()
    if cmd == "test":
        p = argparse.ArgumentParser(prog="heron test")
        p.add_argument("names", nargs="*")
        p.add_argument("--active", action="store_true")
        p.add_argument("-v", action="store_true")
        a = p.parse_args(rest)
        return cmd_test(a.names, a.active, a.v)
    if cmd == "reports":
        return cmd_reports("--check" in rest)
    if os.path.isdir(os.path.join(ROOT, "studies", cmd)):
        return importlib.import_module(f"heron.studies.{cmd}.cli").main(rest) or 0
    print(f"heron: no command or study {cmd!r}; heron --help lists them", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
