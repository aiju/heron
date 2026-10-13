"""Draft 0's results as a baseline for later drafts (baseline.json).

The draft 1 reports compare against draft 0. They read these numbers
instead of running draft 0, so they keep working while this study is
frozen.
"""

import json
import os

PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "baseline.json")


def load():
    """{"programs": {name: {ok, instructions, cycles, code_bytes}}, "period_ns": float}"""
    with open(PATH) as f:
        return json.load(f)


def write():
    """Recompute baseline.json from draft 0's programs and timing analysis."""
    from heron.infra.hw import sta
    from . import machine
    from .testing import program_paths, run_program
    progs = {}
    for p in program_paths():
        r = run_program(p)
        progs[r["name"]] = {k: r[k] for k in ("ok", "instructions", "cycles", "code_bytes")}
    N, res = sta.analyse(machine, "hct-ls181", "max")
    with open(PATH) as f:
        about = json.load(f)["about"]
    with open(PATH, "w") as f:
        f.write(json.dumps({"about": about, "programs": progs, "period_ns": res[0][0]}, indent=1) + "\n")
