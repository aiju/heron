"""Reed whole: the five boards joined on the backplane by the nets'
names, and what the boards are made of.

    machine(sim)       the netlist of every board, each under its name
                       (CTRL.U_UPC0, ALU.U_ALU3, ...), the backplane's
                       nets (bus.py) joined
    check(nl)          the netlist's own checks, the 22V10s' (gal.check), and
                       the backplane's: each control line driven by its
                       board alone
    stats()            per board: packages, area, 22V10s, parts
"""

from collections import Counter, defaultdict

from heron.infra.hw import chips, gal
from heron.infra.hw.netlist import Netlist

from . import alu, bus as BP, ctrl, io, mem, parts, video

BUILDERS = {"CTRL": ctrl.build, "ALU": alu.build, "MEM": mem.build, "IO": io.build, "VIDEO": video.build}
_cache = {}


def board(name, sim=True):
    key = (name, sim)
    if key not in _cache:
        _cache[key] = BUILDERS[name](sim=sim)
    return _cache[key]


def backplane_nets():
    return set(BP.A) | set(BP.B) | set(BP.CONTROL) | {"GND", "VCC"}


def machine(sim=True):
    nl = Netlist()
    joined = {n: n for n in backplane_nets()}
    for name in BUILDERS:
        b = board(name, sim)
        nl.include(b, name, {n: n for n in joined if n not in ("GND", "VCC")})
    return nl


def check(nl):
    """The netlist's checks; then each control line: its drivers all on
    the board bus.py names, and something drives it."""
    nl.check()
    gal.check(nl)
    nets = nl.nets()
    errors = []
    for line, (owner, _) in BP.CONTROL.items():
        drivers = [(i, p) for i, p, k in nets.get(line, []) if k in ("out", "tri", "io")
                   and i.type.family not in ("passive",)]
        boards = {i.ref.split(".")[0] for i, p in drivers}
        if not drivers:
            errors.append(f"{line}: no driver")
        elif boards != {owner}:
            errors.append(f"{line}: driven from {sorted(boards)}, not {owner} alone")
    if errors:
        raise ValueError("backplane errors:\n  " + "\n  ".join(errors))


def package_of(inst):
    part = inst.part_number(parts.VARIANT)
    return part, parts.PACKAGES.get(part)


def stats():
    """{board: {"packages", "area", "gals", "parts": Counter, "unknown": set}}"""
    out = {}
    for name in BUILDERS:
        nl = board(name, True)
        per = Counter()
        unknown = set()
        for inst in nl.instances:
            fam = inst.type.family
            if fam in ("fixture", "osc") and inst.ref.startswith("X_"):
                continue
            if inst.type.name in ("const", "din96", "conn", "pullup"):
                continue
            part, pkg = package_of(inst)
            per[part] += 1
            if pkg is None:
                unknown.add(part)
        pk = Counter({p: -(-n // parts.HALVES.get(p, 1)) for p, n in per.items()})
        area = sum(n * parts.PACKAGES.get(p, ("?", 1.0))[1] for p, n in pk.items())
        gals = sum(n for p, n in pk.items() if p.startswith("ATF22V10"))
        out[name] = {"packages": sum(pk.values()), "area": area, "gals": gals, "parts": pk,
                     "unknown": unknown}
    return out


def report():
    lines = []
    st = stats()
    lines.append(f"{'board':<7} {'packages':>8} {'area':>6} {'22V10s':>6}")
    tp = ta = tg = 0
    for name, s in st.items():
        lines.append(f"{name:<7} {s['packages']:>8} {s['area']:>6.1f} {s['gals']:>6}")
        tp += s["packages"]
        ta += s["area"]
        tg += s["gals"]
    lines.append(f"{'total':<7} {tp:>8} {ta:>6.1f} {tg:>6}")
    for name, s in st.items():
        lines.append(f"\n{name}: " + ", ".join(f"{n} {p}" for p, n in sorted(s["parts"].items())))
        if s["unknown"]:
            lines.append(f"  (no package known: {', '.join(sorted(s['unknown']))})")
    return "\n".join(lines)
