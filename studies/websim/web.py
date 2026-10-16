"""The simulator as static files: the engine for the browser, the page and
the machines, which any web server can serve.

    websim.wasm             the engine (engine/ and wasm/) for wasm32-unknown-unknown
    index.html              the page: web/body.html, in the site's shell or a page of its own
    sim.js, term.js, sim.css
    machines.json           every machine's description (machines.py), what the page shows
    blobs/HASH.gz           what the machines load, gzipped, named by their contents

heron site --apps puts them in the website at apps/sim/ (heron/site), and
`heron websim serve` serves them on their own.
"""

import gzip
import hashlib
import json
import os
import shutil
import subprocess

from heron import BUILD, ROOT

from . import machines as M

HERE = os.path.dirname(os.path.abspath(__file__))
WEB = os.path.join(HERE, "web")
OUT = os.path.join(BUILD, "websim", "site")
CRATE = "websim-wasm"
TARGET = "wasm32-unknown-unknown"
FILES = ("sim.js", "term.js", "sim.css")


def wasm():
    """Build the engine for the browser; the .wasm's path."""
    cargo = shutil.which("cargo")
    if cargo is None:
        raise RuntimeError("the simulator needs cargo: https://rustup.rs")
    r = subprocess.run([cargo, "build", "--release", "--package", CRATE, "--target", TARGET],
                       cwd=ROOT, capture_output=True, text=True)
    if r.returncode:
        if "target may not be installed" in r.stderr or "can't find crate for `core`" in r.stderr:
            raise RuntimeError(f"cargo needs the {TARGET} target: rustup target add {TARGET}")
        raise RuntimeError("cargo:\n" + r.stderr)
    return os.path.join(ROOT, "build", "cargo", TARGET, "release", CRATE.replace("-", "_") + ".wasm")


def body():
    with open(os.path.join(WEB, "body.html")) as f:
        return f.read()


def standalone(text):
    """The page on its own, without the rest of the site: the site's
    stylesheet beside it for the look."""
    from heron.site import FONTS
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Simulator · Heron</title>
<link rel="stylesheet" href="{FONTS}">
<link rel="stylesheet" href="site.css">
</head>
<body>
<main class="gutter">
{text}
</main>
</body>
</html>
"""


class Blobs:
    """Files named by their contents, so that machines share what's the
    same and a browser can keep them."""

    def __init__(self, out):
        self.dir = os.path.join(out, "blobs")
        os.makedirs(self.dir, exist_ok=True)
        self.names = set()

    def add(self, data):
        name = hashlib.sha256(data).hexdigest()[:20] + ".gz"
        path = os.path.join(self.dir, name)
        if name not in self.names and not os.path.exists(path):
            with open(path + ".tmp", "wb") as f:
                f.write(gzip.compress(data, 9, mtime=0))
            os.replace(path + ".tmp", path)
        self.names.add(name)
        return "blobs/" + name


def describe(m, b, blobs):
    """A machine's entry in machines.json."""
    loads = []
    for target, at, data in b.loads:
        if len(data) < 4096 and data.isascii():
            loads.append({"target": target, "at": at, "text": data.decode()})
        else:
            loads.append({"target": target, "at": at, "blob": blobs.add(data), "size": len(data)})
    d = {
        "id": m.id, "group": m.group, "variant": m.variant, "title": f"{m.group}, {m.variant}",
        "summary": m.summary, "board": b.board, "params": b.params, "loads": loads,
        "terminal": m.terminal, "screen": m.screen, "log": b.board == "fen", "speed": m.speed,
        "about": m.about, "examples": m.examples, "links": m.links,
    }
    if b.symbols:
        text = "".join(f"{a:x} {n}\n" for n, a in sorted(b.symbols.items(), key=lambda s: (s[1], s[0])))
        d["symbols"] = blobs.add(text.encode())
    return d


def write(out=OUT, ids=None, page=None, log=print):
    """Write the simulator to `out`: the engine, the page (`page`: the
    body in a shell, the standalone one by default) and the machines (all,
    or those in `ids`). Returns the page's path."""
    os.makedirs(out, exist_ok=True)
    log("building the engine for the browser")
    shutil.copyfile(wasm(), os.path.join(out, "websim.wasm"))
    for f in FILES:
        shutil.copyfile(os.path.join(WEB, f), os.path.join(out, f))
    if page is None:
        shutil.copyfile(os.path.join(ROOT, "heron", "site", "site.css"), os.path.join(out, "site.css"))
        html = standalone(body())
    else:
        html = page(body())
    with open(os.path.join(out, "index.html"), "w") as f:
        f.write(html)
    blobs = Blobs(out)
    entries = []
    for m in M.MACHINES:
        if ids and m.id not in ids:
            continue
        log(f"making {m.id}")
        entries.append(describe(m, m.make(), blobs))
    commit = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, capture_output=True,
                            text=True).stdout.strip()
    with open(os.path.join(out, "machines.json"), "w") as f:
        json.dump({"commit": commit, "machines": entries}, f, indent=1)
    # blobs no machine loads any more
    for name in os.listdir(blobs.dir):
        if name not in blobs.names:
            os.remove(os.path.join(blobs.dir, name))
    return os.path.join(out, "index.html")


def picture(path):
    """A picture of the simulator for the website's apps page: Fen's
    desktop with a command run in its terminal and the clock open, made on
    the engine here (a browser on the page from disk can't fetch the
    machines)."""
    from heron.studies.fen.run import key_name, write_png

    from . import run
    r = run.Running(M.get("fen-desktop"))

    def press(name, down):
        r.s.key(name, down)
        r.run(10)

    def mouse(x, y, b):
        r.s.mouse(x, y, b)
        while r.s.mouse_busy:
            r.run(25)
        r.run(60)

    r.run(2500)
    mouse(300, 300, 1)
    mouse(300, 300, 0)
    for ch in "ls /bin | head -3\n":
        name, shift = key_name(ch)
        if shift:
            press("ShiftLeft", True)
        press(name, True)
        press(name, False)
        if shift:
            press("ShiftLeft", False)
    r.run(1500)
    # the desktop's menu (wsys: Terminal, Clock, 18 pixels each), and Clock
    mouse(600, 250, 1)
    mouse(605, 280, 1)
    mouse(605, 280, 0)
    r.run(1500)
    # the clock opens over the terminal's text: out of the way, by its title bar
    mouse(130, 53, 1)
    mouse(450, 250, 1)
    mouse(450, 250, 0)
    r.run(1500)
    rgba = r.s.screen(True)
    w, h = r.s.screen_size
    rgb = bytearray(w * h * 3)
    rgb[0::3], rgb[1::3], rgb[2::3] = rgba[0::4], rgba[1::4], rgba[2::4]
    write_png(path, bytes(rgb), w, h)
