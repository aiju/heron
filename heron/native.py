"""The Rust engines (RFC 0015), as a Python module.

    from heron import native
    native.version()

The engines are crates in the Cargo workspace at the repository root, and
heron/bindings wraps them as one extension module, heron._native. It's built
on demand into build/native/: the first use of heron.native runs
`cargo build` if any Rust source is newer than the module, and `heron build`
builds it explicitly. Either needs cargo on the PATH (https://rustup.rs).
"""

import importlib.machinery
import importlib.util
import json
import os
import shutil
import subprocess
import sys

from . import BUILD, ROOT

CRATE = "heron-bindings"
NAME = "heron._native"
MODULE = os.path.join(BUILD, "native", "_native" + (".pyd" if sys.platform == "win32" else ".so"))

_module = None


def sources():
    """The files the module is built from: every Rust source and Cargo file
    in the repository, outside build/ and hidden folders."""
    out = [os.path.join(ROOT, ".cargo", "config.toml")]
    for path, dirs, files in os.walk(ROOT):
        dirs[:] = [d for d in dirs if not d.startswith(".") and d not in ("build", "target", "__pycache__")]
        out += [os.path.join(path, f) for f in files
                if f.endswith(".rs") or f in ("Cargo.toml", "Cargo.lock")]
    return out


def stale():
    """Whether the module is missing or older than a Rust source."""
    if not os.path.exists(MODULE):
        return True
    built = os.path.getmtime(MODULE)
    return any(os.path.getmtime(p) > built for p in sources())


def build():
    """Build the module with cargo (release profile) and copy it to MODULE.
    Returns MODULE."""
    cargo = shutil.which("cargo")
    if cargo is None:
        raise RuntimeError("the Rust engines need cargo on the PATH: https://rustup.rs")
    out = subprocess.run([cargo, "build", "--release", "--package", CRATE,
                          "--message-format=json-render-diagnostics"],
                         cwd=ROOT, stdout=subprocess.PIPE, text=True, check=True).stdout
    lib = None
    for line in out.splitlines():
        msg = json.loads(line)
        if msg.get("reason") == "compiler-artifact" and "cdylib" in msg["target"]["kind"]:
            lib = msg["filenames"][0]
    if lib is None:
        raise RuntimeError(f"cargo built no library for {CRATE}")
    # Copy, then rename over the old module: a process that has the old one
    # loaded keeps it, and the copy's time says when it was built.
    os.makedirs(os.path.dirname(MODULE), exist_ok=True)
    tmp = f"{MODULE}.{os.getpid()}"
    shutil.copyfile(lib, tmp)
    os.replace(tmp, MODULE)
    return MODULE


def load():
    """The extension module, built first if it's stale."""
    global _module
    if _module is None:
        if stale():
            build()
        loader = importlib.machinery.ExtensionFileLoader(NAME, MODULE)
        spec = importlib.util.spec_from_file_location(NAME, MODULE, loader=loader)
        _module = importlib.util.module_from_spec(spec)
        loader.exec_module(_module)
        sys.modules[NAME] = _module
    return _module


def __getattr__(name):
    # heron.native.X is X in the extension module. Dunder names aren't
    # passed on, so that looking for __path__, __file__ and the like
    # doesn't start a build.
    if name.startswith("__"):
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    return getattr(load(), name)
