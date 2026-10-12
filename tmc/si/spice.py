"""Running ngspice in batch mode."""

import os
import shutil
import subprocess
import tempfile

import numpy as np


def have_ngspice():
    return shutil.which("ngspice") is not None


def run(lines, probes, tstop, maxstep=20e-12, title="si", timeout=300):
    """Transient analysis of a netlist (a list of lines, no .end). Returns
    {'time': t, probe: values} for each probe expression, e.g. 'v(n3)'."""
    with tempfile.TemporaryDirectory(prefix="tmc-si-") as d:
        cir = os.path.join(d, "c.cir")
        out = os.path.join(d, "out.txt")
        seen = set()
        uniq = []
        for ln in lines:
            if ln.startswith(".model"):
                if ln in seen:
                    continue
                seen.add(ln)
            uniq.append(ln)
        body = [f"* {title}"] + uniq + [
            ".options reltol=1e-4 abstol=1e-9 vntol=1e-5 method=gear",
            ".control",
            "set wr_singlescale",
            "set wr_vecnames",
            "option numdgt=7",
            f"tran {maxstep / 2:.4g} {tstop:.6g} 0 {maxstep:.4g}",
            f"wrdata {out} " + " ".join(probes),
            "quit",
            ".endc",
            ".end",
        ]
        with open(cir, "w") as f:
            f.write("\n".join(body) + "\n")
        # one thread each: the sweeps run several ngspice processes at once
        env = dict(os.environ, OMP_NUM_THREADS="1")
        r = subprocess.run(["ngspice", "-b", cir], capture_output=True, text=True, cwd=d, env=env,
                           timeout=timeout)
        if not os.path.exists(out):
            tail = "\n".join((r.stdout + r.stderr).splitlines()[-30:])
            raise RuntimeError(f"ngspice failed ({title}):\n{tail}")
        with open(out) as f:
            names = f.readline().split()
        data = np.loadtxt(out, skiprows=1, ndmin=2)
    res = {"time": data[:, 0]}
    for i, p in enumerate(probes):
        res[p] = data[:, 1 + i]
    _ = names
    return res
