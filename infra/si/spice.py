"""Running ngspice in batch mode."""

import os
import shutil
import subprocess
import tempfile
import warnings

import numpy as np


def have_ngspice():
    return shutil.which("ngspice") is not None


def run(lines, probes, tstop, maxstep=20e-12, title="si", timeout=300):
    """Transient analysis of a netlist (a list of lines, no .end). Returns
    {'time': t, probe: values} for each probe expression, e.g. 'v(n3)'.
    Raises RuntimeError, naming the run by `title`, if ngspice fails or its
    output stops short of tstop."""
    with tempfile.TemporaryDirectory(prefix="heron-si-") as d:
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
        tail = "\n".join((r.stdout + r.stderr).splitlines()[-30:])
        if not os.path.exists(out):
            raise RuntimeError(f"ngspice failed ({title}):\n{tail}")
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")         # numpy's "Empty input file"
            try:
                data = np.loadtxt(out, skiprows=1, ndmin=2)
            except ValueError as e:                 # a half-written line
                raise RuntimeError(f"ngspice output unreadable ({title}): {e}\n{tail}") from None
    # A run that stops early (ngspice's "timestep too small") still writes
    # what it has, and measuring an empty window fails later in numpy.
    if data.shape[0] == 0:
        raise RuntimeError(f"ngspice wrote no data ({title}):\n{tail}")
    if data.shape[1] != 1 + len(probes):
        raise RuntimeError(f"ngspice wrote {data.shape[1]} columns for {len(probes)} probes "
                           f"({title}):\n{tail}")
    if data[-1, 0] < tstop * (1 - 1e-3):
        raise RuntimeError(f"ngspice stopped at {data[-1, 0] * 1e9:.3f} ns of {tstop * 1e9:.3f} ns "
                           f"({title}):\n{tail}")
    res = {"time": data[:, 0]}
    for i, p in enumerate(probes):
        res[p] = data[:, 1 + i]
    return res


def version():
    try:
        r = subprocess.run(["ngspice", "-v"], capture_output=True, text=True, timeout=30)
        for line in (r.stdout + r.stderr).splitlines():
            if "ngspice-" in line:
                return line.strip(" *")
    except (OSError, subprocess.SubprocessError):
        pass
    return None
