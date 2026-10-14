"""The browser version: web/ (the page, app.js and the simulator crate)
put together with the snapshots into a folder of static files,
build/egret_gui/web/, which any web server can serve.
"""

import os
import shutil
import subprocess
import zlib

from heron import ROOT

from . import build, snapshot

HERE = os.path.dirname(os.path.abspath(__file__))
WEB = os.path.join(HERE, "web")
SITE = os.path.join(build.BUILD, "web")
CRATE = "egret-gui-web"
TARGET = "wasm32-unknown-unknown"
DEPTHS = (3, 0)


def wasm():
    """Build the simulator for the browser; returns the .wasm's path."""
    cargo = shutil.which("cargo")
    if cargo is None:
        raise RuntimeError("building the browser version needs cargo: https://rustup.rs")
    r = subprocess.run([cargo, "build", "--release", "--package", CRATE, "--target", TARGET],
                       cwd=ROOT, capture_output=True, text=True)
    if r.returncode:
        if f"target may not be installed" in r.stderr or "can't find crate for `core`" in r.stderr:
            raise RuntimeError(f"cargo needs the {TARGET} target: rustup target add {TARGET}")
        raise RuntimeError("cargo:\n" + r.stderr)
    return os.path.join(ROOT, "build", "cargo", TARGET, "release", CRATE.replace("-", "_") + ".wasm")


def page():
    """index.html as a whole document (web/index.html is the page without
    the skeleton, as published artifacts want it)."""
    with open(os.path.join(WEB, "index.html")) as f:
        body = f.read()
    head, rest = body.split("<main", 1)
    return ("<!doctype html>\n<html lang=\"en\">\n<head>\n<meta charset=\"utf-8\">\n"
            "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1, viewport-fit=cover\">\n"
            + head + "</head>\n<body>\n<main" + rest + "</body>\n</html>\n")


def _snapshots(depth, source):
    """(cold, booted), compressed, cached by what they're made from."""
    files = build._inputs() + [os.path.join(build.LIB, f) for f in os.listdir(build.LIB)]
    key = build.egret._digest(files, f"{depth}{source or ''}")
    cache = os.path.join(build.BUILD, "snapshots")
    os.makedirs(cache, exist_ok=True)
    out = []
    for kind in ("cold", "booted"):
        path = os.path.join(cache, f"{kind}-{depth}-{key}.bin")
        if not os.path.exists(path):
            fn = snapshot.cold if kind == "cold" else snapshot.booted
            data = zlib.compress(fn(depth, source), 9)
            with open(path + ".tmp", "wb") as f:
                f.write(data)
            os.replace(path + ".tmp", path)
        out.append(path)
    return out


def site(out=SITE, depths=DEPTHS, source=None, log=print):
    """Write the static site to `out`; returns its path."""
    os.makedirs(out, exist_ok=True)
    log("building the simulator for the browser")
    shutil.copyfile(wasm(), os.path.join(out, "heron.wasm"))
    with open(os.path.join(out, "index.html"), "w") as f:
        f.write(page())
    shutil.copyfile(os.path.join(WEB, "app.js"), os.path.join(out, "app.js"))
    for d in depths:
        log(f"booting the desktop at {1 << d} bit{'s' if d else ''} per pixel for the snapshot")
        cold, booted = _snapshots(d, source)
        shutil.copyfile(cold, os.path.join(out, f"cold-{d}.bin"))
        shutil.copyfile(booted, os.path.join(out, f"booted-{d}.bin"))
    return out
