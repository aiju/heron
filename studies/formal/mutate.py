"""Mutation testing: small mistakes put into the 1b hardware on purpose,
and which of them the tests catch and which the proofs do.

    heron formal mutate [-n 30] [--seed 1] [--jobs 4] [--budget 120]

A mutant is the netlist with one input pin stuck at 0 or 1, two input
pins of a part swapped, or one pin moved to the next wire of its bus; or
the microcode with one bit of one control word flipped. For each:

  - the tests: the exercise program (every instruction class, 1.5 million
    cycles) on the chip-level simulator, against the RTL model, as
    `heron v1b_hw hw test` compares (results, cycles, every fetch);
  - the proofs: a fixed sample of decode cases (SAMPLE), cheapest first,
    until one fails.

The mutants are random, so some change nothing that matters (a pin of an
unused part, a control bit no path reads): those survive both.
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

# the decode cases the proofs run on a mutant: a few of each kind, quick ones
SAMPLE = [
    "sys 1 0 0", "sys 2 0 0", "sys 3 0 0", "sys 4 0 0", "sys 7 0 0", "sys 8 0 0", "sys 9 0 0",
    "sys 10 0 0", "sys 10 0 1", "sys 11 0 0", "sys 11 1 0", "sys 12 0 0", "sys 13 0 0",
    "sys 13 0 1", "sys 5 1 1", "sys 6 1 1", "sys 5 3 4", "sys 6 3 4",
    "un 0", "un 1", "un 2", "un 3", "un 4", "un 5", "un 6", "un 7", "un 8", "un 9", "un 10",
    "rr 0", "rr 1", "rr 2", "rr 3",
    "bcc 0", "bcc 1", "jcc cond 0 0", "jcc cond 0 1", "jcc jmp 1 0", "jcc call 0 0",
    "shift 0 1", "shift 1 7", "shift 2 9", "shift 3 16", "shift 0 24", "shift 2 31",
    "ea 1 None 0 None", "ea 1 None 1 5", "ea 1 None 13 3", "ea 1 None 2 None",
    "ea 1 None 3 None", "ea 1 None 6 None", "ea 1 None 7 None", "ea 1 None 8 None",
    "ea 1 None 10 None", "ea 1 None 11 None", "ea 1 None 15 0", "ea 1 None 15 3",
    "ea 2 None 2 None", "ea 2 None 8 None", "ea 2 None 11 None", "ea 2 None 7 None",
    "ea 3 None 3 None", "ea 4 None 0 None", "ea 4 None 1 3", "ea 4 None 2 None",
    "ea 5 None 0 None", "ea 6 None 0 None", "ea 7 None 0 None", "ea 8 None 0 None",
    "ea 9 None 0 None", "ea 11 0 0 None", "ea 11 1 0 None", "ea 11 0 15 4",
]

OUT = os.path.join(BUILD, "formal", "mutants.json")


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
    for (ref, pin), net in changes.items():
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


def tests_catch(nl, roms):
    """The exercise program on the chip-level simulator: the first
    difference from the RTL model, or None."""
    from heron import native
    from heron.infra.hw import chips
    from heron.studies.v1b_hw import machine
    img, m = reference()
    cfg = {"period_ps": 340_000, "seed": 1, "we_start": 0.5, "we_end": 0.875,
           "max_cycles": m.cycles + 1000, "input": b"", "fetch_trace": 200_000,
           "zero_regs": True}
    cfg.update(machine.CONFIG)
    try:
        nl.finish()
        hw = native.hwsim.run(nl.export(variant=chips.DEFAULT_VARIANT, corner="max"), cfg,
                              roms, img.to_bytes(machine.RAM_BYTES))
    except Exception as e:                      # noqa: BLE001
        return f"the simulator stopped: {e}"[:200]
    diffs = machine.compare(m, hw)
    return diffs[0] if diffs else None


def proofs_catch(nl, roms, jobs, budget):
    """The sample of decode cases, until one fails: (its name and what failed,
    cases run), or (None, cases run)."""
    v1b._cache["nl"], v1b._cache["roms"] = nl, roms
    try:
        cases = {c.name(): c for c in v1b.cases()}
        todo = [cases[k] for k in SAMPLE]
        out = os.path.join(BUILD, "formal", "mutant-run.json")
        if os.path.exists(out):
            os.remove(out)
        first = None
        ran = 0
        for i in range(0, len(todo), jobs):
            batch = todo[i:i + jobs]
            res = prove.run(batch, jobs, budget, out, quiet=True)
            ran += len(batch)
            for c in batch:
                r = res[c.name()]
                if r["status"] in ("fail", "error"):
                    detail = r.get("error") or next((p[2] for p in r["paths"] if p[0] != "proved"), "")
                    first = f"{c.name()}: {r['status']}: {detail}"[:200]
                    break
            if first:
                break
        return first, ran
    finally:
        del v1b._cache["nl"], v1b._cache["roms"]
        v1b.netlist()
        v1b.roms()


def main(argv=None):
    p = argparse.ArgumentParser(prog="heron formal mutate")
    p.add_argument("-n", type=int, default=30, help="mutants of each kind")
    p.add_argument("--seed", type=int, default=1)
    p.add_argument("--jobs", type=int, default=4)
    p.add_argument("--budget", type=int, default=120, help="seconds per decode case")
    p.add_argument("--kind", choices=("netlist", "ucode", "both"), default="both")
    p.add_argument("--out", default=OUT)
    args = p.parse_args(argv)
    rng = random.Random(args.seed)
    v1b.netlist()
    v1b.roms()
    reference()
    muts = []
    if args.kind in ("netlist", "both"):
        muts += [("netlist", d, c) for d, c in netlist_mutants(args.n, rng)]
    if args.kind in ("ucode", "both"):
        muts += [("ucode", d, c) for d, c in ucode_mutants(args.n, rng)]
    results = []
    for i, (kind, desc, change) in enumerate(muts):
        t0 = time.time()
        if kind == "netlist":
            nl, roms = apply_netlist(change), v1b.roms()
        else:
            nl, roms = copy.deepcopy(v1b.netlist()), apply_ucode(change)
        tested = tests_catch(copy.deepcopy(nl), roms)
        proved, ran = proofs_catch(nl, roms, args.jobs, args.budget)
        results.append({"kind": kind, "mutation": desc, "tests": tested, "proofs": proved,
                        "cases_run": ran, "seconds": time.time() - t0})
        print(f"[{i + 1}/{len(muts)}] {kind:<7} {desc}\n"
              f"    tests:  {tested or '-'}\n    proofs: {proved or '-'} ({ran} cases)",
              flush=True)
        os.makedirs(os.path.dirname(args.out), exist_ok=True)
        with open(args.out, "w") as f:
            json.dump(results, f, indent=1)
    both = sum(1 for r in results if r["tests"] and r["proofs"])
    only_t = sum(1 for r in results if r["tests"] and not r["proofs"])
    only_p = sum(1 for r in results if r["proofs"] and not r["tests"])
    neither = sum(1 for r in results if not r["tests"] and not r["proofs"])
    print(f"caught by both {both}, tests only {only_t}, proofs only {only_p}, neither {neither}")
    return 0
