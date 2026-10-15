"""Egret's VM on the host with this study's memory map: gcc builds it from
Egret's sources with EGRET_GUI, and src/host.c in place of the GUI's C
side, so nothing draws. It runs what of the desktop doesn't need the
screen, in a fraction of a second: Egretica's algebra, for the tests.
"""

import os
import subprocess

from heron.studies.egret import build as egret

from . import build

HOST_C = os.path.join(build.SRC, "host.c")


def vm():
    """The host VM's path, built if needed."""
    files = egret._vm_files() + [HOST_C, os.path.join(build.SRC, "gui_map.h")]
    exe = os.path.join(build.BUILD, f"egret-gui-host-{egret._digest(files)}")
    if not os.path.exists(exe):
        os.makedirs(build.BUILD, exist_ok=True)
        pre = egret.prelude_c()
        cmd = ["gcc", "-O2", "-std=gnu99", "-Wall", "-Wno-unused-parameter", "-fno-strict-aliasing",
               "-fwrapv", "-DEGRET_GUI=1", "-I", egret.VM, "-I", build.SRC, "-o", exe + ".tmp"]
        cmd += [os.path.join(egret.VM, s) for s in egret.SOURCES] + [pre, HOST_C]
        subprocess.run(cmd, check=True)
        os.replace(exe + ".tmp", exe)
    return exe


def run(source, timeout=120):
    """(output, exit status) of a program: Egret source, as text."""
    r = subprocess.run([vm()], input=source.encode(), capture_output=True, timeout=timeout)
    return (r.stdout + r.stderr).decode("latin-1"), r.returncode


def lib(*names):
    """Files of lib/, as one source."""
    out = []
    for n in names:
        with open(os.path.join(build.LIB, n)) as f:
            out.append(f.read())
    return "\n".join(out)
