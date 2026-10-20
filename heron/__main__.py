"""The heron command (or python3 -m heron from the repository root).

  heron list                  the studies, with their status and dependencies
  heron test [NAME...] [-v]   unit tests: the repository's own (tests/) and
                              infra's by default, or the named studies'
                              (--active: every active study's)
  heron reports [--check]     rewrite reports/README.md, the index (--check:
                              only check the front matter)
  heron reports reserve TYPE SLUG TITLE
                              reserve the next number for a report or rfc:
                              push its stub and the index to main
  heron build                 build the Rust engines' Python module, which is
                              otherwise built when first used (heron/native.py)
  heron site [--apps] [--serve]
                              build the website into build/site (--apps: with
                              the browser tools; --serve: then serve it)
  heron figures write|check|list|draw ...
                              draw the documents' figures into their SVGs
                              (check: only check them; RFC 0000's
                              figures-*.md document the languages)
  heron <study> ...           a study's own command line, for example
                              heron v1_isa run studies/v1_isa/programs/v1b/hello.s
"""

import argparse
import importlib
import os
import subprocess
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


def cmd_reserve(kind, slug, title):
    from . import reserve
    try:
        rel = reserve.reserve(kind, slug, title)
    except subprocess.CalledProcessError as e:
        print(f"heron reports reserve: {' '.join(e.cmd)}: {e.stderr.strip()}", file=sys.stderr)
        return 1
    except RuntimeError as e:
        print(f"heron reports reserve: {e}", file=sys.stderr)
        return 1
    print(f"reserved {rel} on main; now merge origin/main into your branch and write it over the stub")
    return 0


def cmd_build():
    from . import native
    try:
        path = native.build()
    except subprocess.CalledProcessError:
        return 1  # cargo has said what went wrong
    except RuntimeError as e:
        print(f"heron build: {e}", file=sys.stderr)
        return 1
    print(f"built {os.path.relpath(path)}")
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
    if cmd == "reports" and rest[:1] == ["reserve"]:
        p = argparse.ArgumentParser(prog="heron reports reserve")
        p.add_argument("type", choices=sorted(meta.STATUSES))
        p.add_argument("slug")
        p.add_argument("title")
        a = p.parse_args(rest[1:])
        return cmd_reserve(a.type, a.slug, a.title)
    if cmd == "reports":
        return cmd_reports("--check" in rest)
    if cmd == "build":
        return cmd_build()
    if cmd == "site":
        from . import site
        return site.main(rest)
    if cmd == "figures":
        from . import figures
        return figures.main(rest)
    if os.path.isdir(os.path.join(ROOT, "studies", cmd)):
        return importlib.import_module(f"heron.studies.{cmd}.cli").main(rest) or 0
    print(f"heron: no command or study {cmd!r}; heron --help lists them", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
