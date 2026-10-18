"""The programs: every folder under check/, demos/, games/ and apps/ with
a prog.toml describing it:

    title = "Snake"
    about = "one line: what it is and what it tries"
    sources = ["snake.c", "draw.s"]   # relative to the folder
    wm = false                        # with the window manager (wm/)
    variants = ["c", "asm", "blk"]    # the kernel variants it builds in
    layout = "L0"                     # the board's (RFC 0042, 4), and
    bandwidth = "B0"                  # bandwidth (9) it runs on by default
    frames = 600                      # how long a run is, at most
    script = "demo.script"            # input (run.py's format), a file or the text
    [pokes]                           # variables set before it runs
    _level = 2
    [defines]                         # for its C
    SPEED = "3"
"""

import glob
import os
import tomllib

from . import build as B
from . import run as R

HERE = os.path.dirname(os.path.abspath(__file__))
AREAS = ("check", "bench", "demos", "games", "apps")


class Program:
    def __init__(self, path, meta):
        self.path = path                                    # e.g. games/snake
        self.name = os.path.relpath(path, HERE)
        self.meta = meta
        self.title = meta.get("title", self.name)
        self.about = meta.get("about", "")
        self.sources = [os.path.join(self.name, s) for s in meta.get("sources", [])]
        self.wm = meta.get("wm", False)
        self.variants = meta.get("variants", list(B.VARIANTS))
        self.layout = meta.get("layout", "L0")
        self.bandwidth = meta.get("bandwidth", "B0")
        self.frames = meta.get("frames", 600)
        self.pokes = meta.get("pokes", {})
        self.defines = {k: str(v) for k, v in meta.get("defines", {}).items()}

    def script(self):
        s = self.meta.get("script", "")
        f = os.path.join(self.path, s)
        if s and os.path.isfile(f):
            with open(f) as fh:
                return fh.read()
        return s

    def build(self, variant=None, defines=None):
        d = dict(self.defines)
        d.update(defines or {})
        return B.build(self.sources, variant or self.variants[0], d, wm=self.wm,
                       name=self.name)

    def run(self, variant=None, layout=None, bandwidth=None, frames=None, script=None,
            shots_dir=None, profile=0, pokes=None, defines=None):
        b = self.build(variant, defines)
        p = dict(self.pokes)
        p.update(pokes or {})
        s = R.Session(b, layout or self.layout, bandwidth or self.bandwidth, p)
        res = s.run(frames or self.frames, self.script() if script is None else script,
                    shots_dir=shots_dir, profile=profile)
        res.build = b
        return res


def all_programs():
    out = {}
    for area in AREAS:
        for f in sorted(glob.glob(os.path.join(HERE, area, "*", "prog.toml"))):
            with open(f, "rb") as fh:
                meta = tomllib.load(fh)
            p = Program(os.path.dirname(f), meta)
            out[p.name] = p
    return out


def get(name):
    progs = all_programs()
    name = name.rstrip("/")
    if name in progs:
        return progs[name]
    matches = [p for n, p in progs.items() if n.endswith("/" + name)]
    if len(matches) == 1:
        return matches[0]
    raise KeyError(f"no program {name!r} (heron mini_gfx list)")
