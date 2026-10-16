"""Mutation testing: small mistakes put into the 1b hardware on purpose,
and which of them the tests catch and which the proofs do.

    heron formal mutate [-n 12] [--seed 1] [--jobs 4] [--budget 300] [--cap 1200]
    heron formal mutate ... --resume CAP [--budget 1800]

Two sets of mutants:

  - made by hand (HANDMADE, HANDMADE_UCODE): one wire or one control bit
    each, chosen to be wrong only for some values, flags or encodings;
  - random: one input pin of the netlist stuck at 0 or 1, two input pins
    of a part swapped, or a pin moved to the next wire of its bus; or one
    bit of one control word flipped. Some of these change nothing that
    matters (a control bit no path reads), and survive everything.

For each mutant:

  - the tests: the exercise program (every instruction class, 1.5 million
    cycles) on the chip-level simulator, against the RTL model, as
    `heron v1b_hw hw test` compares (results, cycles, every fetch); if
    that passes, the whole program suite too;
  - the proofs: the decode cases the mutant can affect, cheapest first,
    until one fails or the time per mutant runs out. For the microcode,
    those whose routines reach the changed word (`affected`); for the
    netlist, those that read a changed pin on some path of the unmutated
    netlist (`pin_map`, `relevant`): up to the first such read, a run on
    the mutant is the same.
"""

import argparse
import copy
import json
import os
import random
import re
import time

from heron import BUILD

from . import prove, v1b

OUT = os.path.join(BUILD, "formal", "mutants.json")

# Mutants made by hand: (description, {(reference, pin): new net}). Each is
# one wire, wrong only for some values.
HANDMADE = [
    ("immediate unit: a 16-bit displacement sign-extended from T[14], not T[15]",
     {("U_FILLM", "D4"): "TQ14"}),
    ("byte lanes: a byte at an odd address gets its bit 3 from T[12], not T[11]",
     {("U_BT10", "A4"): "TQ12"}),
    ("carry lookahead: nibble 2's generate taken from its propagate",
     {("U_CLA0", "G2"): "ALUP2"}),
    ("result multiplexer: RRC shifts in V, not C",
     {("U_SINM", "D2"): "VFLAG"}),
    ("flags: ADC and SBC's Z not sticky (the gate's Z input tied high)",
     {("@ZSTICKY", "ZFLAG"): "VCC"}),
    ("store data: bits 14 and 15 of the low half swapped",
     {("U_DR1", "A7"): "RES15", ("U_DR1", "A8"): "RES14"}),
    ("PC: the carry into bits 25-28 comes early (only above 1 MB)",
     {("@PCE6", "PCRCO5"): "VCC"}),
]


def _resolve(nl, changes):
    """{(ref, pin): net}, with ("@NET", input net) naming the gate that
    drives NET and its pin on that input."""
    out = {}
    for (ref, pin), net in changes.items():
        if ref.startswith("@"):
            g = next(g for g in nl.gates if nl.refs[g.ref].conn.get(g.output) == ref[1:])
            inst = nl.refs[g.ref]
            pin = next(p for p in g.inputs if inst.conn[p] == pin)
            ref = g.ref
        out[(ref, pin)] = net
    return out


def handmade_ucode():
    """Microcode mutants made by hand: (description, (address, bit))."""
    mc = v1b.microcode()
    pos = v1b.uc._pos
    out = []
    # CMP rd, #-9: its own routine; the constant's bit 1 flipped (-9 -> -11)
    node = mc.entry[("ea", 6, None, 13, 8)]
    while "KONST" not in node.f:
        node = node.succ[1]
    out.append(("CMP rd, #-9 compares with -11 (a constant bit in its routine)",
                (node.addr, pos["KONST"][0] + 1)))
    # MOV rd, half [rn + d16]: the fill above the half from T[15], not 0
    for n in _reachable(mc.entry[("ea", 1, None, 12, None)]):
        if n.f.get("BF23") and n.f.get("FSEL", 0) == 0 and n.f.get("BT1"):
            out.append(("MOV rd, half [rn + d16] sign-extends (fill select 0 -> T[15])",
                        (n.addr, pos["FSEL"][0] + 2)))
            break
    return out


def _reachable(entry):
    seen, todo, out = set(), [entry], []
    while todo:
        n = todo.pop()
        if id(n) in seen:
            continue
        seen.add(id(n))
        out.append(n)
        s = n.succ
        if s[0] == "next":
            todo.append(s[1])
        elif s[0] == "branch":
            todo += [s[2], s[3]]
        elif s[0] == "dispatch":
            todo += list(s[1])
    return out


def affected(addr):
    """The decode cases whose routines reach the control word at addr."""
    mc = v1b.microcode()
    out = []
    for c in v1b.cases():
        if any(n.addr == addr for n in _reachable(mc.entry[c.key])):
            out.append(c)
    return out


def cost(c):
    """A rough order of how long a case takes to prove."""
    k = c.key
    if k[0] == "ea":
        m = k[3]
        if m in (1, 13):
            return 1
        if m == 15 and k[4] <= 3:
            return 2
        if m == 0:
            return 4
        if m == 5:
            return 200
        return 10 if m != 4 else 15
    if k[0] == "sys":
        return 10 * (k[3] - k[2] + 1) if k[1] in (5, 6) else 2
    if k[0] == "un":
        return 2 if k[1] < 11 else 60          # CLZ loops
    if k[0] == "rr":
        return 3 if k[1] < 4 else 10000        # multiply and divide
    return {"shift": 1, "bcc": 2, "jcc": 3, "shreg": 80, "illegal": 10000}[k[0]]


# ---------------------------------------------------------------- mutants

def _bus_next(net):
    """The next wire of the same bus (ABUS5 -> ABUS6), or None."""
    m = re.fullmatch(r"([A-Za-z_]+?)(\d+)(_n)?", net)
    if not m:
        return None
    return f"{m.group(1)}{int(m.group(2)) + 1}{m.group(3) or ''}"


def netlist_mutants(n, rng):
    """n random netlist mutations: (description, function changing a netlist)."""
    nl = v1b.netlist()
    nets = set(nl.nets())
    skip = {"fixture", "mem"}
    def used(inst, pin):
        """False for an input of a gate package's spare section."""
        if inst.type.model not in ("nand", "and", "or", "nor", "xor"):
            return True
        pre = pin[:-1]
        return any(p.startswith(pre) and k == "out" and p in inst.conn for p, k in inst.type.pins)
    sites = [(inst.ref, pin) for inst in nl.instances if inst.type.family not in skip
             and not inst.ref.startswith(("U_UIR", "U_UC", "U_DEC"))
             for pin, kind in inst.type.pins if kind == "in" and inst.conn.get(pin) not in
             (None, "CLK") and used(inst, pin)]
    out = []
    while len(out) < n:
        ref, pin = rng.choice(sites)
        inst = nl.refs[ref]
        net = inst.conn[pin]
        kind = rng.choice(("stuck", "swap", "rewire"))
        if kind == "stuck":
            to = "VCC" if net == "GND" else "GND" if net == "VCC" else rng.choice(("GND", "VCC"))
            out.append((f"{ref}.{pin} ({net}) stuck at {to == 'VCC':d}", {(ref, pin): to}))
        elif kind == "swap":
            others = [p for p, k in inst.type.pins if k == "in" and p != pin
                      and inst.conn.get(p) not in (None, net, "CLK")]
            if not others:
                continue
            q = rng.choice(others)
            out.append((f"{ref}.{pin} and .{q} swapped ({net}, {inst.conn[q]})",
                        {(ref, pin): inst.conn[q], (ref, q): net}))
        else:
            to = _bus_next(net)
            if to is None or to not in nets:
                continue
            out.append((f"{ref}.{pin} on {to} instead of {net}", {(ref, pin): to}))
    return out


def apply_netlist(changes):
    nl = copy.deepcopy(v1b.netlist())
    for (ref, pin), net in _resolve(nl, changes).items():
        nl.refs[ref].conn[pin] = net
    return nl


def ucode_mutants(n, rng):
    """n random microcode mutations: one control bit of one word in use
    flipped (in both IRQP halves)."""
    mc = v1b.microcode()
    addrs = sorted({nd.addr for nd in mc.nodes if nd.addr is not None and nd.addr >= 0})
    nets = v1b.uir_nets()
    out = []
    for _ in range(n):
        a = rng.choice(addrs)
        bit = rng.choice(sorted(nets))
        node = mc.by_addr[a]
        out.append((f"control word {a:03X} ({node.name}): {nets[bit]} flipped", (a, bit)))
    return out


def apply_ucode(change):
    a, bit = change
    roms = dict(v1b.roms())
    k, i = divmod(bit, 8)
    img = bytearray(roms[f"U_UC{k}"])
    for addr in (a, a | (1 << v1b.uc.IRQP_BIT)):
        img[addr] ^= 1 << i
    roms[f"U_UC{k}"] = bytes(img)
    return roms


# ---------------------------------------------------------------- the two checks

_ref = {}


def reference():
    if "ex" not in _ref:
        from heron.studies.v1b_hw import machine
        from heron.studies.v1b_hw.check import exercise_path
        _ref["ex"] = machine.run_isa(exercise_path(), b"")
    return _ref["ex"]


def suite():
    """The program suite's references: [(name, input, image, Reference)]."""
    if "suite" not in _ref:
        from heron.infra.hw import runner
        from heron.studies.v1b_hw import machine
        out = []
        for p in machine.program_paths():
            inp = runner.program_input(p)
            img, m = machine.run_isa(p, inp)
            out.append((os.path.basename(p), inp, img, m))
        _ref["suite"] = out
    return _ref["suite"]


def _run(nl_json, roms, img, m, inp):
    from heron import native
    from heron.studies.v1b_hw import machine
    cfg = {"period_ps": 340_000, "seed": 1, "we_start": 0.5, "we_end": 0.875,
           "max_cycles": m.cycles + 1000, "input": inp, "fetch_trace": 200_000,
           "zero_regs": True}
    cfg.update(machine.CONFIG)
    try:
        hw = native.hwsim.run(nl_json, cfg, roms, img.to_bytes(machine.RAM_BYTES))
    except Exception as e:                      # noqa: BLE001
        return f"the simulator stopped: {e}"[:200]
    diffs = machine.compare(m, hw, check_cycles=m.irqs == 0)
    return diffs[0] if diffs else None


def tests_catch(nl, roms, whole_suite=True):
    """The exercise program on the chip-level simulator, then (if it passes)
    the program suite: the first difference from the RTL model, or None."""
    from heron.infra.hw import chips
    nl_json = nl.export(variant=chips.DEFAULT_VARIANT, corner="max")
    img, m = reference()
    d = _run(nl_json, roms, img, m, b"")
    if d or not whole_suite:
        return f"exercise: {d}" if d else None
    for name, inp, img, m in suite():
        d = _run(nl_json, roms, img, m, inp)
        if d:
            return f"{name}: {d}"
    return None


PINS = os.path.join(BUILD, "formal", "v1b-pins-read.json")


def _pins_one(name):
    c = next(c for c in v1b.cases() if c.name() == name)
    try:
        reads, _ = v1b.pins_read(c, timeout_ms=60_000)
        return name, sorted(f"{r}.{p}" for r, p in reads)
    except Exception as e:                      # noqa: BLE001
        return name, repr(e)


def pin_map(jobs=4):
    """{case name: [part.pin read on any path]}, for the unmutated netlist:
    built once (minutes) and kept in build/."""
    import multiprocessing as mp
    if os.path.exists(PINS):
        with open(PINS) as f:
            return json.load(f)
    names = [c.name() for c in v1b.cases()]
    with mp.get_context("fork").Pool(jobs) as pool:
        out = dict(pool.map(_pins_one, names, chunksize=4))
    bad = {k: v for k, v in out.items() if isinstance(v, str)}
    if bad:
        raise RuntimeError(f"exploring failed: {list(bad.items())[:3]}")
    os.makedirs(os.path.dirname(PINS), exist_ok=True)
    with open(PINS, "w") as f:
        json.dump(out, f)
    return out


def relevant(changes, pins):
    """The decode cases that read a pin a netlist mutation changes."""
    nl = v1b.netlist()
    touched = {f"{r}.{p}" for (r, p) in _resolve(nl, changes)}
    return [c for c in v1b.cases() if touched & set(pins[c.name()])]


def proofs_catch(nl, roms, cases, jobs, budget, cap):
    """Prove `cases`, cheapest first, on the mutant
    until one fails or `cap` seconds have gone: (the failing case and what
    failed, or None; how many cases were run; those of them that ran out of
    their budget)."""
    v1b._cache["nl"], v1b._cache["roms"] = nl, roms
    try:
        todo = sorted(cases, key=cost)
        out = os.path.join(BUILD, "formal", "mutant-run.json")
        t0 = time.time()
        ran, unfinished = 0, []
        for i in range(0, len(todo), jobs):
            if time.time() - t0 > cap:
                break
            batch = todo[i:i + jobs]
            if os.path.exists(out):
                os.remove(out)
            res = prove.run(batch, jobs, budget, out, quiet=True)
            ran += len(batch)
            for c in batch:
                r = res[c.name()]
                err = r.get("error") or ""
                # the unmutated hardware simulates without errors, so one the
                # simulator finds on the mutant (a combinational loop, two
                # drivers on a bus) is the mutant's doing
                if r["status"] == "error" and err.startswith(("SimError", "CombLoop")):
                    return f"{c.name()}: {err}"[:200], ran, unfinished
                if r["status"] == "error":     # a fault in the tools, not a catch
                    raise RuntimeError(f"{c.name()}: {err}")
                if r["status"] == "fail":
                    detail = next((p[2] for p in r["paths"] if p[0] == "fail"), "")
                    return f"{c.name()}: {detail}"[:200], ran, unfinished
                if r["status"] != "proved":
                    unfinished.append(c.name())
        return None, ran, unfinished
    finally:
        del v1b._cache["nl"], v1b._cache["roms"]
        v1b.netlist()
        v1b.roms()


def _cases(kind, change, pins):
    if kind == "netlist":
        return apply_netlist(change), v1b.roms(), relevant(change, pins)
    return v1b.netlist(), apply_ucode(change), affected(change[0])


def resume(muts, pins, args):
    """--resume: the proofs of the mutants they missed, again from the
    start, with the time of this run (--cap, --budget)."""
    with open(args.out) as f:
        results = json.load(f)
    if [r["mutation"] for r in results] != [m[2] for m in muts]:
        raise SystemExit(f"{args.out} is from other mutants (another -n, --seed or --only)")
    for i, ((kind, origin, desc, change), r) in enumerate(zip(muts, results)):
        if r["proofs"] or (r["cases_run"] >= r["cases"] and r.get("unfinished") == []):
            continue
        t0 = time.time()
        nl, roms, cases = _cases(kind, change, pins)
        proved, ran, unfinished = proofs_catch(nl, roms, cases, args.jobs, args.budget, args.resume)
        r.update(proofs=proved, cases_run=ran, unfinished=unfinished, resumed=True)
        r["seconds"] += time.time() - t0
        print(f"[{i + 1}/{len(muts)}] {origin} {kind}: {desc}\n"
              f"    proofs: {proved or '-'} ({ran} of {len(cases)} cases, "
              f"{len(unfinished)} out of time)", flush=True)
        with open(args.out, "w") as f:
            json.dump(results, f, indent=1)
    return 0


def main(argv=None):
    p = argparse.ArgumentParser(prog="heron formal mutate")
    p.add_argument("-n", type=int, default=12, help="random mutants of each kind")
    p.add_argument("--seed", type=int, default=1)
    p.add_argument("--jobs", type=int, default=4)
    p.add_argument("--budget", type=int, default=300, help="seconds per decode case")
    p.add_argument("--cap", type=int, default=1200, help="seconds of proving per mutant")
    p.add_argument("--only", choices=("handmade", "random"), help="one set of mutants")
    p.add_argument("--out", default=OUT)
    p.add_argument("--continue", dest="cont", action="store_true",
                   help="keep the mutants already in --out, and run the rest")
    p.add_argument("--resume", type=int, metavar="CAP",
                   help="prove again the mutants that the last run's proofs (in --out) "
                        "didn't catch, CAP seconds each")
    args = p.parse_args(argv)
    rng = random.Random(args.seed)
    v1b.netlist()
    v1b.roms()
    reference()
    pins = pin_map(args.jobs)
    muts = []
    if args.only != "random":
        muts += [("netlist", "handmade", d, c) for d, c in HANDMADE]
        muts += [("ucode", "handmade", d, c) for d, c in handmade_ucode()]
    if args.only != "handmade":
        muts += [("netlist", "random", d, c) for d, c in netlist_mutants(args.n, rng)]
        muts += [("ucode", "random", d, c) for d, c in ucode_mutants(args.n, rng)]
    if args.resume:
        return resume(muts, pins, args)
    results = []
    if args.cont and os.path.exists(args.out):
        with open(args.out) as f:
            results = json.load(f)
        if [r["mutation"] for r in results] != [m[2] for m in muts[:len(results)]]:
            raise SystemExit(f"{args.out} is from other mutants (another -n, --seed or --only)")
    for i, (kind, origin, desc, change) in enumerate(muts):
        if i < len(results):
            continue
        t0 = time.time()
        nl, roms, cases = _cases(kind, change, pins)
        tested = tests_catch(nl, roms)
        proved, ran, unfinished = proofs_catch(nl, roms, cases, args.jobs, args.budget, args.cap)
        results.append({"kind": kind, "origin": origin, "mutation": desc, "tests": tested,
                        "proofs": proved, "cases_run": ran, "cases": len(cases),
                        "unfinished": unfinished, "seconds": time.time() - t0})
        print(f"[{i + 1}/{len(muts)}] {origin} {kind}: {desc}\n"
              f"    tests:  {tested or '-'}\n"
              f"    proofs: {proved or '-'} ({ran} of {len(cases)} cases)", flush=True)
        os.makedirs(os.path.dirname(args.out), exist_ok=True)
        with open(args.out, "w") as f:
            json.dump(results, f, indent=1)
    both = sum(1 for r in results if r["tests"] and r["proofs"])
    only_t = sum(1 for r in results if r["tests"] and not r["proofs"])
    only_p = sum(1 for r in results if r["proofs"] and not r["tests"])
    neither = sum(1 for r in results if not r["tests"] and not r["proofs"])
    print(f"caught by both {both}, tests only {only_t}, proofs only {only_p}, neither {neither}")
    return 0
