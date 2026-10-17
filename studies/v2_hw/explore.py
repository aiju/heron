"""The design explorer: the draft 2 CPU as nested block diagrams that open
down to the chips, in one page.

    heron v2_hw explore [--out FILE] [--fragment]

The hierarchy comes from the netlist itself: the units below group its
sections (Netlist.section), and a section's blocks are the stretches of
cpu.py that one comment introduces, labelled with that comment. A block
holds its chips (numbered runs of one part, U_VAM0-15, as one array) and
its gates. Wires between whatever is shown are the nets that join them,
bundled into buses.

On top of the structure the page shows a run: the chip-level simulator's
trace of a program (every cycle's buses, at the microcode's real lengths),
and for each cycle's microinstruction what the static timing analysis'
case analysis knows: which nets carry data that something loads (the
cone of unknown values behind every register that loads), which
registers load, when each chip's outputs settle and the critical path.
The suite's profile weights the same analysis into how often each chip
works and how often it is on the critical path.
"""

import json
import math
import os
import re
import sys
from collections import Counter, defaultdict

from heron.infra.hw import chips, schematic, sta as hsta
from heron.infra.hw.netlist import Netlist

from . import cpu, parts, sta, ucode as uc

HERE = os.path.dirname(os.path.abspath(__file__))

# The units: (id, name, what it does, the sections in it)
UNITS = [
    ("clk", "Clock and reset",
     "A 50 MHz oscillator and a tick counter: each cycle is 4, 5, 6 or 9 ticks of 20 ns, as "
     "the uIR's length class says. It makes CLK, the register file's write phase RW and "
     "strobe, the memory write window and LATE.",
     ["Clock generator", "Reset"]),
    ("seq", "Sequencer",
     "The control store and what addresses it: the 144-bit microinstruction register (uIR), "
     "the next address (a branch, the decode table's entry, a dispatch, or a forced entry for "
     "a refill, an interrupt, a trace or a fault), and the instruction register.",
     ["Control store", "Next address", "Decode", "Instruction register", "Interrupt request"]),
    ("rf", "Register file",
     "Two copies of 16K x 32 SRAM, one for each ALU input, read through latches in the "
     "cycle's first part and written in its last tick. 16 registers per bank, 256 banks, and "
     "the microcode's own registers and constants above them.",
     ["Register file"]),
    ("ops", "Operand buses",
     "The ALU's inputs. A: the register file, PC, R, R x 2, MAR. B: the register file, R, "
     "memory data by byte lane, the prefetch queue's head parcel, the immediate unit, MQ and "
     "the special registers.",
     ["A bus", "B bus", "Immediate unit"]),
    ("alu", "ALU",
     "Eight 74F181s with 74F182 carry lookahead, the result multiplexer that shifts and "
     "rotates by 1, 8 or 16, and MQ for multiply and divide steps.",
     ["ALU control", "ALU", "Result multiplexer", "MQ"]),
    ("regs", "Registers",
     "R (the result register), T (memory data, latched as it is read), MAR, the loop counter, "
     "and SX and EX, which count through a register list.",
     ["R and T", "MAR", "Loop counter", "SX and EX"]),
    ("flags", "Flags and conditions",
     "N, Z, C, V and the system flags; the condition latches the microcode branches on; the "
     "instruction's branch condition.",
     ["Flags", "Condition latches", "Branch condition"]),
    ("mem", "Memory",
     "The virtual address, the page map (128 contexts x 4096 pages), the window, the fault "
     "checks that must settle before a write's window opens, 2 MB of RAM, the store data "
     "path, and the context and bank registers.",
     ["Memory", "Store data", "Faults"]),
    ("fetch", "Instruction fetch",
     "PC (the instruction the decode is at) and FPC (the next word to fetch), the kept "
     "translation of FPC's page, and the two-word prefetch queue filled in cycles that don't "
     "use memory.",
     ["PC", "Fetch translation", "Prefetch queue"]),
]


# Short names for blocks, where the comment's first words don't make one:
# (section, the comment's start) -> name
BLOCK_NAMES = {
    ("Instruction register", None): "IR and length",
    ("Instruction register", "TS <- T"): "Trace flag (TS)",
    ("Next address", None): "Condition and Y multiplexer",
    ("Next address", "SEQ 1 decode"): "Forced entries",
    ("Next address", "the refill entry"): "Refill entry",
    ("Next address", "for the PC's count"): "Decode goes ahead",
    ("Next address", "YOFF"): "Y off (a forced entry)",
    ("Next address", "a fault's entry"): "Fault entry address",
    ("Next address", "the queue holds"): "Instruction complete",
    ("Next address", "whether the instruction fits"): "Fits in Q0",
    ("Register file", None): "Write phase",
    ("Register file", "the write address"): "Write address",
    ("Register file", "the read address's bank"): "Read bank (EB)",
    ("Register file", "each copy's address"): "The two copies",
    ("B bus", "the enables straight"): "R, direct enables",
    ("B bus", "T by lanes"): "T and the queue head, by lanes",
    ("B bus", None): "MQ, flags, FSR, FAR, map",
    ("MQ", "4 x 74F299"): "MQ",
    ("ALU", None): "ALU and carry lookahead",
    ("R and T", None): "R",
    ("R and T", "T, and TL"): "T and TL latches",
    ("Flags", "Z is kept"): "Z",
    ("Flags", "S, T, I"): "S, T, I",
    ("Condition latches", "CL as four bits"): "CL",
    ("Condition latches", "SGN"): "SGN, S33",
    ("PC", None): "PC load",
    ("PC", "a decode that goes ahead"): "PC and FPC",
    ("PC", "PC[1] again"): "PC1F and FOK",
    ("Fetch translation", "FPC's page"): "Kept page (FPPN)",
    ("Prefetch queue", "a fetch:"): "Fetch decision",
    ("Prefetch queue", "two slots"): "Slots and head pointer",
    ("Prefetch queue", "the head parcel"): "Head parcel",
    ("Prefetch queue", "V0, V1"): "Valid bits",
    ("Store data", None): "Store data drivers",
    ("Store data", "it drives the data bus"): "The I/O page",
    ("Clock generator", None): "Oscillator and tick counter",
    ("Clock generator", "H2, H3"): "Write window",
    ("Clock generator", "(not in a cycle"): "Write window",
    ("Clock generator", "LATE"): "LATE",
    ("Reset", None): "Reset",
    ("Memory", "MEM's top bit"): "Access decode",
    ("Memory", "the virtual address"): "Virtual address",
    ("Memory", "the page map"): "Page map",
    ("Memory", "the entry from B"): "Map write data",
    ("Memory", "translation"): "Translation",
    ("Memory", "the translation fault, fast"): "Permission check",
    ("Memory", "alignment"): "Alignment",
    ("Memory", "what answers"): "Slot decode",
    ("Memory", "a fault:"): "Fault",
    ("Memory", "the translation fault where"): "Fault, fast path",
    ("Memory", "FK:"): "Fault registers",
    ("Memory", "byte enables"): "Byte enables",
    ("Memory", "the RAM"): "RAM",
}

# what a section is, where cpu.py has no comment before it
SECTION_DESC = {
    "Control store": "Nine 64K x 16 SRAMs hold the 144-bit microinstruction, addressed with the "
                     "next one's address and clocked into the uIR at every edge.",
    "Decode": "The decode table: a 64K x 16 SRAM indexed by the head parcel of the prefetch "
              "queue, giving the routine's entry and the instruction's length in parcels.",
    "Instruction register": "IR takes the head parcel when a decode goes ahead.",
    "Next address": "The control store's address: the next field, a branch on one of 16 "
                    "conditions, the decode table's entry or a dispatch, and the forced entries.",
    "A bus": "The ALU's A input: the register file's copy A (its latches drive it), PC, R, "
             "R x 2 and MAR, each through 74ABT541 buffers.",
    "B bus": "The ALU's B input: the register file's copy B, R, T by byte lane, the queue's "
             "head parcel, MQ, the flags, FSR, FAR and the page map's entry.",
    "Immediate unit": "Constants onto B: the parcel's quick constants, branch offsets, the "
                      "microinstruction's own byte and LC, with the fill above them.",
    "ALU": "Eight 74F181s with two levels of 74F182 carry lookahead.",
    "Result multiplexer": "RES: the ALU's output as it is, shifted right by one, or rotated "
                          "by 8 or 16, with any byte zeroed.",
    "MAR": "The memory address register: 74F161s that load from RES and count.",
    "Loop counter": "LC: an 8-bit counter for the microcode's loops.",
    "SX and EX": "SX counts through a register list (LDM, STM); EX is where it stops.",
    "PC": "PC, at the instruction being decoded, and FPC, at the next word to fetch.",
    "Fetch translation": "FPC's page, kept from the map so that prefetches needn't use it.",
    "Prefetch queue": "Two words, Q0 and Q1, in two slots and a head pointer, filled from the "
                      "card's RAM in cycles that don't use memory; the head parcel feeds the "
                      "decode table.",
    "Memory": "The virtual address, the page map and the window, the fault checks, and the "
              "card's 2 MB of RAM.",
    "Faults": "CTX, the page map's context, and BANK, the register file's bank.",
    "Store data": "The A bus onto the card's data bus, replicated by the access's size.",
    "Flags": "N, Z, C, V, I, S and T.",
    "Reset": "Power-on reset.",
    "Clock generator": "RFC 0024's tick counter: the cycle's length from the uIR's class, "
                       "and the phases within it.",
}

# nets the page draws only on request
CLOCK_NETS = {"CLK", "RW", "RW_n", "LATE", "MWIN", "MWIN_n", "T1", "T1_n", "RESET", "RESET_n",
              "MCLK", "H0", "H0_n", "H1", "H1_n", "H2", "H3", "TICK3"}
FAULT_NETS = {"FAULT", "FAULT_n"}

FAMILY = {
    "sram64k": "memory", "sram512": "memory",
    "377": "register", "823": "register", "573": "register", "161": "register",
    "16374h": "register", "16823h": "register", "16373h": "register", "16244h": "buffer",
    "163": "register", "74": "register", "175": "register", "109": "register",
    "299": "register",
    "541": "buffer",
    "151": "mux", "153": "mux", "157": "mux",
    "138": "decoder", "688": "decoder",
    "181": "alu", "182": "alu",
}
FAMILIES = [("memory", "SRAM"), ("register", "Registers and latches"), ("buffer", "Buffers"),
            ("mux", "Multiplexers"), ("decoder", "Decoders and comparators"),
            ("alu", "ALU"), ("gate", "Gates"), ("other", "Other")]


# ---- the netlist, with where in cpu.py each part comes from ---------------------------


def _caller_line():
    """The line in cpu.py that placed a part (a counter_chain's call, not its body)."""
    f = sys._getframe(2)
    while f is not None:
        if f.f_code.co_filename == cpu.__file__ and f.f_code.co_name != "counter_chain":
            return f.f_lineno
        f = f.f_back
    return 0


def capture():
    """cpu.build(sim=True)'s netlist (the parts list's: with the clock
    generator), and {ref or gate index: the line that placed it}."""
    lines = {"add": {}, "gate": []}
    add, gate = Netlist.add, Netlist.gate

    def add_(self, typ, ref=None, *a, **kw):
        inst = add(self, typ, ref, *a, **kw)
        lines["add"].setdefault(inst.ref, _caller_line())
        return inst

    def gate_(self, typ, inputs, output, part=None):
        n = len(self.gates)
        inst = gate(self, typ, inputs, output, part)
        if len(self.gates) > n:
            lines["gate"].append(_caller_line())
        return inst
    Netlist.add, Netlist.gate = add_, gate_
    try:
        nl = cpu.build(sim=True)
    finally:
        Netlist.add, Netlist.gate = add, gate
    return nl, lines


def source_blocks():
    """{line: (block start line, its comment or None)} over cpu.py, and
    {section: the comment just before its first nl.section call}."""
    with open(cpu.__file__) as f:
        src = f.read().splitlines()
    at, desc = {}, {}
    cur = (0, None)
    pending = None                  # the last comment, for a section that follows it
    i = 0
    while i < len(src):
        s = src[i].strip()
        if s.startswith("#"):
            j, texts = i, []
            while j < len(src) and src[j].strip().startswith("#"):
                texts.append(src[j].strip()[1:].strip())
                j += 1
            text = " ".join(texts)
            if text.startswith("----"):
                cur, pending = (i + 1, None), None
            elif re.search(r"\S {3,}\S", text):
                pass                # a table's column headings
            else:
                cur, pending = (i + 1, text), text
            for k in range(i, j):
                at[k + 1] = cur
            i = j
            continue
        m = re.search(r'nl\.section\("([^"]+)"\)', s)
        if m:
            if pending and m.group(1) not in desc:
                desc[m.group(1)] = pending
            cur, pending = (i + 1, None), None
        elif src[i].startswith("def "):
            cur, pending = (i + 1, None), None
        elif s:
            pending = None
        at[i + 1] = cur
        i += 1
    return at, desc


def _short(text):
    """A block's name from its comment: the words before the first break
    (outside brackets)."""
    depth, end = 0, len(text)
    for i, ch in enumerate(text):
        if ch in "([{":
            if ch == "(" and depth == 0 and i > 0:
                end = i
                break
            depth += 1
        elif ch in ")]}":
            depth -= 1
        elif depth == 0 and ch in ":;,." and text[i + 1:i + 2] in (" ", ""):
            end = i
            break
    t = text[:end].strip()
    if len(t) > 34:
        t = t[:32].rsplit(" ", 1)[0] + " …"
    return t[:1].upper() + t[1:]


NUM = re.compile(r"^(.*?)(\d+)([LH]?)$")


def _arrays(model, syms):
    """Runs of consecutively numbered chips of one part (an IS61C6416AL's
    two halves, U_CS0L and U_CS0H, as one): [(name, description, symbols)]."""
    runs = defaultdict(list)
    for sid in syms:
        s = model["symbols"][sid]
        m = NUM.match(s["ref"])
        if s["kind"] == "chip" and m and (not m.group(3) or s["type"] == "sram64k"):
            runs[(m.group(1), s["type"])].append((int(m.group(2)), sid))
    out = []
    for (pre, typ), members in runs.items():
        members.sort()
        nums = sorted({n for n, _ in members})
        # split into runs of consecutive numbers
        groups, cur = [], [nums[0]]
        for n in nums[1:]:
            if n == cur[-1] + 1:
                cur.append(n)
            else:
                groups.append(cur)
                cur = [n]
        groups.append(cur)
        for g in groups:
            ms = [sid for n, sid in members if n in g]
            if len(ms) < 2:
                continue
            part = model["symbols"][ms[0]]["part"]
            k = len(g)
            desc = f"{k} x {part}" + (" (each two 8-bit halves)" if typ == "sram64k" else
                                       " (halves)" if chips.TYPES[typ].per_package > 1 else "")
            out.append((f"{pre}{g[0]}–{g[-1]}" if k > 1 else f"{pre}{g[0]}", desc, ms))
    return out


def hierarchy(nl, lines, model):
    """The tree: units, sections, blocks, arrays, then the drawn symbols
    (schematic.model's gates and chips). Returns (nodes, parent of each
    symbol)."""
    at, sec_desc = source_blocks()
    insts = {i.ref: i for i in nl.instances}
    gate_refs = {g.ref for g in nl.gates}
    # each symbol's section and block
    sym_block = {}
    gate_sym = {}
    for g, line in zip(nl.gates, lines["gate"]):
        sid = f"{g.ref}#{g.sec + 1}"
        gate_sym[(g.ref, g.output)] = sid
        sym_block[sid] = (g.section, at.get(line, (0, None)))
    for inst in nl.instances:
        if inst.ref in gate_refs or inst.type.family in ("fixture", "passive"):
            continue
        sym_block[inst.ref] = (inst.section, at.get(lines["add"].get(inst.ref, 0), (0, None)))
    missing = set(model["symbols"]) - set(sym_block)
    if missing:
        raise ValueError(f"symbols without a place: {sorted(missing)[:5]}")

    nodes = {"root": {"id": "root", "kind": "root", "name": "Draft 2 CPU", "children": []}}

    def node(nid, kind, name, parent, desc=""):
        if nid not in nodes:
            nodes[nid] = {"id": nid, "kind": kind, "name": name, "parent": parent,
                          "desc": desc, "children": []}
            nodes[parent]["children"].append(nid)
        return nodes[nid]

    unit_of = {}
    for uid, name, desc, secs in UNITS:
        node(f"u:{uid}", "unit", name, "root", desc)
        for s in secs:
            unit_of[s] = uid
    by_sec = defaultdict(lambda: defaultdict(list))         # section -> block -> symbols
    for sid in model["symbols"]:
        sec, blk = sym_block[sid]
        by_sec[sec][blk].append(sid)
    order = [n for _, n in nl.sections]
    for sec in sorted(by_sec, key=lambda s: order.index(s) if s in order else 99):
        if sec not in unit_of:
            raise ValueError(f"section {sec!r} isn't in a unit")
        sn = node(f"s:{sec}", "section", sec, f"u:{unit_of[sec]}",
                  sec_desc.get(sec) or SECTION_DESC.get(sec, ""))
        blocks = sorted(by_sec[sec].items(), key=lambda kv: kv[0][0])
        for (start, text), syms in blocks:
            if len(blocks) > 1:
                name = None
                for (s_, pre), nm in BLOCK_NAMES.items():
                    if s_ == sec and (text.startswith(pre) if (text and pre) else pre is text):
                        name = nm
                name = name or (_short(text) if text else f"{sec}, the rest")
                bn = node(f"b:{sec}/{name}", "block", name, sn["id"], text or "")
                if text and text not in bn["desc"]:
                    bn["desc"] = (bn["desc"] + " " + text).strip()
                parent = bn["id"]
            else:
                parent = sn["id"]
                if text and not sn["desc"]:
                    sn["desc"] = text
            arrays = {}
            for name, desc, members in _arrays(model, syms):
                aid = f"a:{name}"
                node(aid, "array", name, parent, desc)
                for sid in members:
                    arrays[sid] = aid
            for sid in syms:
                p = arrays.get(sid, parent)
                nodes[p]["children"].append(sid)
                nodes[sid] = {"id": sid, "kind": "symbol", "parent": p}
    return nodes, gate_sym


# ---- what a microinstruction does, from the case analysis ------------------------------


class Probe(hsta.Case):
    """A Case that also records, for every net, the nets its arrival was
    worked out from: the inputs that can still change it once the known
    values have cut the rest (a multiplexer's selected input, an enabled
    buffer's)."""

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.deps = defaultdict(set)
        self.stack = []

    def net(self, n):
        if n in self.memo:
            return self.memo[n]
        self.stack.append(n)
        try:
            return super().net(n)
        finally:
            self.stack.pop()

    def latest(self, inst, terms):
        if self.stack:
            d = self.deps[self.stack[-1]]
            for p, _, _ in terms:
                if p in inst.conn:
                    d.add(inst.conn[p])
        return super().latest(inst, terms)


def _sinks(case, N, f):
    """What loads in this cycle: [(ref, kind, the nets it takes)], kind
    load, count or write."""
    out = []
    for inst in N.insts:
        m, pin = inst.type.model, case.pin
        if m in ("reg377", "dreg"):
            if pin(inst, "EN")[0] != 1:
                n = 8 if m == "reg377" else 9
                out.append((inst.ref, "load", [inst.conn[f"D{i}"] for i in range(1, n + 1)
                                               if f"D{i}" in inst.conn]))
        elif m in ("cnt161", "cnt163"):
            if pin(inst, "LOAD")[0] != 1:
                out.append((inst.ref, "load", [inst.conn[p] for p in "ABCD" if p in inst.conn]))
            elif pin(inst, "ENP")[0] != 0 and pin(inst, "ENT")[0] != 0:
                out.append((inst.ref, "count", []))
        elif m == "dff74":
            for s in "12":
                if pin(inst, f"{s}CLK")[1] != hsta.NEG:
                    out.append((inst.ref, "load", [inst.conn[f"{s}D"]]))
        elif m == "dff175":
            out.append((inst.ref, "load", [inst.conn[f"{i}D"] for i in range(1, 5)]))
        elif m == "latch573":
            if inst.conn["LE"] != "RW_n" and pin(inst, "LE")[0] != 0:
                out.append((inst.ref, "load", [inst.conn[f"D{i}"] for i in range(1, 9)]))
        elif m == "sr299":
            s0, s1 = pin(inst, "S0")[0], pin(inst, "S1")[0]
            if s0 == 1 and s1 == 1:
                out.append((inst.ref, "load", [inst.conn[f"IO{i}"] for i in range(8)]))
            elif s0 != 0 or s1 != 0:
                out.append((inst.ref, "count", [inst.conn["DS0"], inst.conn["DS7"]]))
        elif m == "sram":
            we = inst.conn["WE"]
            if inst.conn.get("WE") in ("VCC", "GND") or not N.drivers.get(we):
                continue
            if inst.conn["OE"] == "RW":            # the register file: written in the tail
                if f.get("RFWE"):
                    out.append((inst.ref, "write", [f"RES{i}" for i in range(32)]
                                + [f"RWA{i}" for i in range(13)] + ["GW_n"]))
            elif case.net(we)[0] != 1:
                out.append((inst.ref, "write", [inst.conn[p] for p in inst.conn
                                                if p[0] == "A" or p.startswith("IO")]))
    return out


def case_data(N, w, extra, f):
    """One microinstruction in one state: its period, the requirement that
    sets it and the path to it, what loads, and the nets that carry data
    to what loads (with their arrival times)."""
    c = Probe(N, hsta.constants_for(sta, w, dict(extra)), 1000.0, sta.WS, sta.WINDOWS,
              sta.TURNOFF, sta.SHARP)
    chk = hsta.checks(c, N, sta.WE) + sta.extra_checks(c, N)
    T = hsta.min_period(chk, sta.WS, sta.WE)
    worst = hsta.worst_check(chk, T if T < math.inf else 1000.0, sta.WS, sta.WE)
    path = c.path(worst[2]) if worst else []
    for n in list(N.drivers):
        try:
            c.net(n)
        except (hsta.LoopError, RecursionError):
            pass
    sinks = _sinks(c, N, f)

    def unknown(n):
        r = c.memo.get(n)
        return r is not None and r[0] is None and r[1] != hsta.NEG

    def cone(start):
        seen, todo = set(), [n for n in start if unknown(n)]
        while todo:
            n = todo.pop()
            if n in seen:
                continue
            seen.add(n)
            todo.extend(d for d in c.deps.get(n, ()) if d not in seen and unknown(d))
        return seen

    live, loads = set(), []
    by_ref = N.by_ref
    for ref, kind, nets in sinks:
        cn = cone(nets)
        if kind == "load":
            own = {by_ref[ref].conn[p] for p, k in by_ref[ref].type.pins
                   if k in ("out", "tri") and p in by_ref[ref].conn}
            leaves = {n for n in cn if not any(unknown(d) for d in c.deps.get(n, ()))}
            if not cn or leaves <= own:
                continue                    # it holds what it has
        live |= cn
        loads.append((ref, kind))
    arrival = {n: c.memo[n][1] for n in live}
    return {"T": T, "check": worst[1] if worst else "", "path": path,
            "loads": loads, "live": arrival}


_N = None


def _init():
    global _N
    sys.setrecursionlimit(20000)
    _N = hsta.Netlist(sta.build(), parts.VARIANT, sta.CORNER)


def _one(item):
    w, extra, f = item
    d = case_data(_N, w, extra, f)
    d["path"] = [list(p) for p in d["path"]]
    return d


def analyse_cases(items, jobs=4):
    """case_data for [(word, extra, fields)], in parallel."""
    from concurrent.futures import ProcessPoolExecutor
    with ProcessPoolExecutor(jobs, initializer=_init) as ex:
        return list(ex.map(_one, items, chunksize=8))


# ---- a run at chip level ----------------------------------------------------------------

# (program, first cycle, cycles; None: all of it, from reset to HALT)
TRACE_PROGRAMS = [("hello", 0, None), ("sieve", 30_000, 400), ("bignum", 9_000, 400)]


def trace_buses():
    def b(name, n, start=0):
        return [f"{name}{i}" for i in range(start, start + n)]
    return {"Y": b("Y", uc.Y_BITS), "UA": b("UA", 3), "PC": ["GND"] + b("PC", 31, 1),
            "FPC": ["GND", "GND"] + b("FPC", 30, 2), "QH": b("QH", 16), "IR": b("IR", 16),
            "ABUS": b("ABUS", 32), "BBUS": b("BBUS", 32), "RES": b("RES", 32), "F": b("F", 32),
            "R": b("RQ", 32), "T": b("TQ", 32), "VA": b("VA", 32),
            "PA": b("VA", 12) + b("PA", 20, 12),
            "MD": b("MD", 24), "DB": b("DB", 32), "MAR": b("MAR", 32), "LC": b("LC", 8),
            "S0": b("QS0_", 32), "S1": b("QS1_", 32), "V": ["V0", "V1"],
            "FL": ["NFLAG", "ZFLAG", "CFLAG", "VFLAG", "IFLAG", "SFLAG", "TFLAG"],
            "ST": ["FAULT", "FOK", "TSQ", "PEND", "PC1F", "DECGO", "JUMP", "FETCHED", "HS"]}


def run_trace(name, start=0, n=None):
    """The chip-level run of one suite program (n cycles from `start`, or
    all of it): every cycle's buses as they are at its end, the word it
    runs, its length in ticks, and the decodes."""
    from heron import native
    from heron.infra import asm as asmcore, isas
    from heron.infra.programs import metadata
    from . import check as chk, hw, iop
    path = chk.program_paths([name])[0]
    img = asmcore.assemble_file(isas.get("v2"), path)
    inp = metadata(path)["input"]
    mem = iop.boot_image(img)
    end = start + n if n else 200_000
    cfg = hw.config(end + 1, (start - 1, end - 1))
    cfg["trace_buses"] = trace_buses()
    out = native.hwsim.run_system(hw.netlist(), cfg, hw.preloads(mem, inp))
    names = list(cfg["trace_buses"])
    cycles = []
    lines = out["trace"]
    first = max(i for i, ln in enumerate(lines) if ln.startswith(f"{start - 1} "))
    for line in lines[first:]:
        parts_ = line.split()
        d = {"t": int(parts_[1][2:])}
        for kv in parts_[2:]:
            k, v = kv.split("=")
            d[k] = int(v, 16)
        cycles.append(d)
    # each cycle runs the word the one before addressed: {UA, Y}
    for prev, c in zip(cycles, cycles[1:]):
        c["u"] = prev["Y"] | (prev["UA"] << uc.U_SHIFT)
        c["ticks"] = (c["t"] - prev["t"]) // cpu.TICK_PS
    for i, c in enumerate(cycles):
        c["cycle"] = start - 1 + i
    return img, mem, cycles[1:], out, names


# ---- a microinstruction in words ----------------------------------------------------------

_INV = {k: {v: n for n, v in d.items() if n is not None}
        for k, d in (("BL", uc.BL), ("BX", uc.BX), ("MEM", uc.MEM), ("SIZE", uc.SIZE),
                     ("COND", uc.CONDS), ("V8", uc.V8), ("RMS", uc.RMS), ("LDSX", uc.LDSX),
                     ("LDEX", uc.LDEX), ("PCCOND", uc.PCCOND), ("FNZ", uc.FNZ), ("FC", uc.FC),
                     ("FV", uc.FV), ("FI", uc.FI), ("CLSRC", uc.CLSRC))}
# the 74F181's functions, active-high data
_LOGIC = ["not A", "A nor B", "not A and B", "0", "A nand B", "not B", "A xor B", "A and not B",
          "not A or B", "A xnor B", "B", "A and B", "1", "A or not B", "A or B", "A"]
_ARITH = {0b0000: "A", 0b1001: "A + B", 0b0110: "A − B − 1", 0b1111: "A − 1", 0b1100: "A + A"}
_CIN = ["", " + 1", " + C", " + A31", " + MQ31", " + SGN", " + MQ0", " + not S33"]


def _alu_text(m, s, cin):
    if m:
        return _LOGIC[s]
    base = _ARITH.get(s, f"S={s:04b}")
    if cin == 1 and s == 0b0110:
        return "A − B"
    if cin == 1 and s == 0b1111:
        return "A"
    return base + _CIN[cin]


def _reg(sel, k, write=False):
    if sel == 0:
        return "d"
    if sel == 1:
        return "r"
    if sel == 2:
        return "SX"
    if k in uc.RF_NAMES:
        return uc.RF_NAMES[k]
    return f"r{k}" if k < 16 else f"G+{k - uc.G}" if k >= uc.G else f"k{k}"


def describe(f):
    """A microinstruction as register transfers: [(what, text)]."""
    out = []
    a = []
    if f.get("ARF"):
        a.append(f"RF[{_reg(f.get('RFA', 0), f.get('RFK', 0))}]")
    if f.get("APC"):
        a.append("PC" + ("+1" if f.get("PCK") else ""))
    if f.get("AR"):
        a.append("R")
    if f.get("AR2"):
        a.append("R x 2")
    if f.get("AMAR"):
        a.append("MAR")
    b = []
    if f.get("BRF"):
        b.append(f"RF[{_reg(f.get('RFB', 0), f.get('RFK', 0))}]")
    if f.get("BR"):
        b.append("R")
    if f.get("BL"):
        b.append({"t": "T", "thalf": "T (half)", "tbyte": "T (byte)", "qh": "QH", "qh2": "QH x 2",
                  "qhh": "QH << 16", "qhb": "QH's low byte"}[_INV["BL"][f["BL"]]])
    if f.get("BX"):
        b.append(_INV["BX"][f["BX"]].upper() if f["BX"] != 2 else "flags")
    if f.get("BS0"):
        v8 = _INV["V8"].get(f.get("V8", 0), "?")
        b.append({"k": f"#{f.get('KONST', 0)}", "bcc": "branch offset", "fill": "fill",
                  "lc": "LC", "q": "#q", "nq": "#-(q+1)", "u7": "#u7", "s4": "#4q"}[v8])
    if a:
        out.append(("A", " ".join(a)))
    if b:
        out.append(("B", " ".join(b)))
    if f.get("MQM") or f.get("MS"):
        steps = {(1, 1): "multiply step", (2, 2): "divide step", (3, 0): "MQ load",
                 (0, 3): "fix-up", (1, 0): "64-bit shift right"}
        alu = steps.get((f.get("MQM", 0), f.get("MS", 0)), "MQ step")
    else:
        alu = _alu_text(f.get("M", 0), f.get("S", 0), f.get("CIN", 0))
    rms = _INV["RMS"].get(f.get("RMS", 0), "f")
    dests = []
    if f.get("LDR"):
        dests.append("R")
    if f.get("RFWE"):
        dests.append(f"RF[{_reg(f.get('RFW', 0), f.get('RFKW', 0))}]")
    if f.get("LDMAR"):
        dests.append("MAR")
    if f.get("LDPC"):
        cond = _INV["PCCOND"].get(f.get("PCCOND", 0))
        dests.append("PC" + (f" if {cond}" if cond else ""))
    if f.get("LDLC"):
        dests.append("LC")
    if f.get("LDCTX"):
        dests.append("CTX")
    if f.get("LDBANK"):
        dests.append("BANK")
    if dests or f.get("FNZ") or f.get("FC") or f.get("LDCL"):
        res = {"f": "", "shr": " >> 1", "ror8": " ror 8", "ror16": " ror 16"}[rms]
        out.append(("ALU", f"{alu}{res}" + (f" → {', '.join(dests)}" if dests else "")))
    if f.get("MEM"):
        mem = _INV["MEM"][f["MEM"]]
        size = _INV["SIZE"].get(f.get("SIZE", 0), "")
        where = {"read": "[MAR]", "write": "[MAR] ← A", "fetch": "[FPC] (refill)",
                 "mapr": "map[MAR]", "mapw": "map[MAR] ← B", "reada": "[A]"}[mem]
        verb = {"read": "read", "write": "write", "fetch": "fetch", "mapr": "read",
                "mapw": "write", "reada": "read"}[mem]
        out.append(("MEM", f"{verb} {size + ' ' if size and mem != 'fetch' else ''}{where}"))
    elif f.get("VAS") in (1, 3):
        out.append(("MEM", "prefetch [FPC]"))
    if f.get("MARINC"):
        out.append(("MAR", "MAR + size"))
    if f.get("CONSUME"):
        out.append(("Q", "consume a parcel"))
    flags = []
    if f.get("FNZ"):
        nz = {"nz": "N Z", "sticky": "N Z (sticky)", "loadf": "load"}
        flags.append(nz[_INV["FNZ"][f["FNZ"]]])
    if f.get("FC"):
        flags.append("C")
    if f.get("FV"):
        flags.append("V")
    if f.get("LDCL"):
        flags.append(f"CL ← {_INV['CLSRC'].get(f.get('CLSRC', 0), '?')}")
    if flags:
        out.append(("Flags", " ".join(flags)))
    seq = f.get("SEQ", 0)
    if seq == uc.SEQ_DECODE:
        out.append(("Next", "decode"))
    elif seq == uc.SEQ_DISPATCH:
        out.append(("Next", "dispatch on QH"))
    elif seq == uc.SEQ_HALT:
        out.append(("Next", "halt"))
    elif f.get("COND"):
        out.append(("Next", f"branch on {_INV['COND'].get(f['COND'], f['COND'])}"))
    return out


# ---- the page's data ------------------------------------------------------------------------

BUSES = {
    "ABUS": "the ALU's A input", "BBUS": "the ALU's B input", "F": "the ALU's output",
    "RES": "the result bus", "VA": "the virtual address", "PA": "the physical address",
    "MD": "the page map's data (V, W, X and the physical page)", "DB": "the card's memory data",
    "QH": "the queue's head parcel", "UD": "the control store's data", "Y": "the next microaddress",
    "RQ": "R", "TQ": "T", "QS0_": "queue slot 0", "QS1_": "queue slot 1", "MAR": "MAR",
    "PC": "PC", "FPC": "FPC", "IR": "the instruction register", "DEC": "the decode table's entry",
    "RFAIO": "register file copy A's data", "RFBIO": "register file copy B's data",
    "RFAM": "register file copy A's address", "RFBM": "register file copy B's address",
    "RWA": "the register write address", "EB": "the read bank", "BANK": "the register bank",
    "CTX": "the map's context", "LC": "the loop counter", "SX": "SX", "EX": "EX",
    "NZR": "a byte of RES nonzero", "MA": "the page map's address", "V8": "the immediate byte",
    "SE": "the ALU's function", "CC": "the condition", "FPPN": "the kept page",
}

# traced buses as the nets they are: name -> nets, bit 0 first
def _trace_nets():
    return {k: v for k, v in trace_buses().items() if k not in ("V", "FL", "ST", "UA")}


def _state(c, f):
    """The case analysis' extra constants for a traced cycle."""
    v0, fok = c["V"] & 1, (c["ST"] >> 1) & 1
    q = (("V0", v0), ("V0_n", 1 - v0), ("FOK", fok), ("FOK_n", 1 - fok))
    if f.get("SEQ") in (uc.SEQ_DECODE, uc.SEQ_HALT):
        tsq, pend = (c["ST"] >> 2) & 1, (c["ST"] >> 3) & 1
        q += (("TSQ", 1), ("TSQ_n", 0)) if tsq else \
            (("TSQ", 0), ("TSQ_n", 1), ("PEND", pend), ("PEND_n", 1 - pend))
    return q


def _common_state(f):
    """The state a microinstruction meets most: the queue holding words, FOK
    set, no trace or interrupt pending."""
    sts = sta.states(f)
    for q in sts:
        d = dict(q)
        if d.get("V0") == 1 and d.get("FOK") == 1 and not d.get("TSQ") and not d.get("PEND"):
            return q
    return sts[-1]


def build_model(programs=TRACE_PROGRAMS, jobs=4, log=print):
    """Everything the page shows, as JSON-able data."""
    import heron.studies.v2_isa  # noqa: F401
    from heron.studies.v2_isa import v2
    from . import perf
    log("netlist and hierarchy")
    nl, lines = capture()
    model = schematic.model(nl, "Draft 2 CPU", variant=parts.VARIANT)
    nodes, _ = hierarchy(nl, lines, model)
    insts = {i.ref: i for i in nl.instances}
    gate_type = {f"{g.ref}#{g.sec + 1}": g.typ for g in nl.gates}
    from heron.infra.hw.netlist import GATE_SECTIONS
    for sid, sy in model["symbols"].items():
        sy["parent"] = nodes[sid]["parent"]
        if sy["kind"] == "gate":
            sy["fam"], sy["pkg"] = "gate", 1 / GATE_SECTIONS[gate_type[sid]][0]
        else:
            t = sy["type"]
            sy["fam"] = FAMILY.get(t, "other")
            sy["pkg"] = 1 / chips.TYPES[t].per_package
        sy.pop("sheet", None)
    names = sorted(model["nets"])
    idx = {n: i for i, n in enumerate(names)}
    out_sym = {sy["ports"][-1]["nets"][0]: sid for sid, sy in model["symbols"].items()
               if sy["kind"] == "gate"}

    def sym_of(ref, net):
        return ref if ref in model["symbols"] else out_sym.get(net)

    clock_refs = {i.ref for i in nl.instances if i.section == "Clock generator"}
    nets = []
    for n in names:
        d = model["nets"][n]
        drv = [e[0] for e in d["drivers"]]
        cls = "data"
        if n in FAULT_NETS:
            cls = "fault"
        elif n in CLOCK_NETS or any(r in clock_refs or r.split("#")[0] in clock_refs for r in drv):
            cls = "clock"
        elif any(r.startswith("U_UIR") for r in drv):
            cls = "control"
        nets.append({"n": n, "d": d["drivers"], "l": d["loads"], "c": cls,
                     **({"tied": d["tied"]} if "tied" in d else {})})

    mc = uc.built()
    rom = mc.rom()
    mask = sta._mask()
    field_cache = {}

    def fields(a):
        if a not in field_cache:
            field_cache[a] = uc.unpack(rom[a]) if a in rom else uc.unpack(uc.IDLE)
        return field_cache[a]

    # ---- runs
    traces, items, case_index = [], [], {}
    tnets = _trace_nets()
    for prog, start, n in programs:
        log(f"chip-level run: {prog}")
        img, mem, cyc, out, _ = run_trace(prog, start, n)
        syms = {a: n for n, a in img.symbols.items()} if hasattr(img, "symbols") else {}
        cols = {k: [] for k in ["u", "ticks", "case"] + list(tnets) + ["V", "FL", "ST"]}
        for c in cyc:
            f = fields(c["u"])
            key = (uc.pack(f) & mask, _state(c, f))
            if key not in case_index:
                case_index[key] = len(items)
                items.append((key[0], key[1], f))
            cols["case"].append(case_index[key])
            for k in cols:
                if k not in ("case",):
                    cols[k].append(c[k])

        def parcels(pc, n=3):
            src = mem if pc >= 0x80000000 else img.mem
            base = pc & 0x7FFFFFFF if pc >= 0x80000000 else pc
            return [src.get(base + 2 * i, 0) | (src.get(base + 2 * i + 1, 0) << 8)
                    for i in range(n)]
        decodes = []
        first, last = cyc[0]["cycle"], cyc[-1]["cycle"]
        before = [x for x in out["fetches"] if x[0] < first]
        for cy, pc, _w in before[-1:] + [x for x in out["fetches"] if first <= x[0] <= last]:
            try:
                text, _n = v2.disassemble(parcels(pc), pc, syms)
            except Exception:                       # noqa: BLE001  (data, not code)
                text = "?"
            decodes.append([cy - first, pc, text, syms.get(pc, "")])
        traces.append({"name": prog, "start": first, "whole": n is None,
                       "output": bytes(out["dumps"]["X_IO"]).decode("latin-1") if n is None else "",
                       "cols": cols, "decodes": decodes})

    # ---- the suite: every word in its common state, weighted by the profile
    log("the suite's profile")
    rows = perf.profile()
    count = Counter()
    for r in rows:
        if r["name"] in perf.SKIP:
            continue
        for a, k in r["ucount"].items():
            count[a] += k
    by_word = defaultdict(lambda: [0, 0])          # word -> [cycles, ticks]
    word_fields = {}
    for a, k in count.items():
        f = fields(a)
        w = uc.pack(f) & mask
        by_word[w][0] += k
        by_word[w][1] += k * mc.lengths[f.get("LCL", 0)]
        word_fields[w] = f
    suite_items = [(w, _common_state(f), f) for w, f in word_fields.items()]
    log(f"case analysis: {len(items)} traced, {len(suite_items)} for the suite")
    res = analyse_cases(items + suite_items, jobs)
    traced, suite = res[:len(items)], res[len(items):]

    def case_out(d):
        live = []
        for n, t in sorted(d["live"].items()):
            if n in idx:
                live += [idx[n], round(t * 10)]
        path = []
        for net, t, ref, dn in d["path"]:
            path.append([idx.get(net, -1), round(t, 1), sym_of(ref, net) if ref else None, dn])
        loads = [[sym_of(ref, None) or ref, kind] for ref, kind in d["loads"]]
        return {"T": round(d["T"], 1), "check": d["check"], "path": path, "loads": loads,
                "live": live}
    cases = [case_out(d) for d in traced]

    total_c = sum(v[0] for v in by_word.values())
    total_t = sum(v[1] for v in by_word.values())
    work, crit = Counter(), Counter()
    for (w, _q, _f), d in zip(suite_items, suite):
        k, t = by_word[w]
        active = set()
        for n in d["live"]:
            for e in model["nets"].get(n, {}).get("drivers", []):
                active.add(e[0])
        for ref, _kind in d["loads"]:
            s_ = sym_of(ref, None)
            if s_:
                active.add(s_)
        for s_ in active:
            work[s_] += k
        for s_ in {sym_of(ref, net) for net, _t, ref, _dn in d["path"] if ref}:
            if s_:
                crit[s_] += t
    suite_out = {"cycles": total_c, "ticks": total_t,
                 "work": {s_: round(v / total_c, 4) for s_, v in work.items() if v},
                 "crit": {s_: round(v / total_t, 4) for s_, v in crit.items() if v}}

    # ---- the microinstructions the runs use
    used = sorted({a for t in traces for a in t["cols"]["u"]})
    nt = sta.node_ticks(sta.analyse())
    words = {}
    for a in used:
        f = fields(a)
        node_ = mc.by_addr.get(a)
        words[a] = {"name": node_.name if node_ else f"{a:04X}", "rt": describe(f),
                    "fields": uc.explain(f), "cls": mc.lengths[f.get("LCL", 0)],
                    "ns": round(nt[a][0], 1) if a in nt else None}

    packages = sum(nl.packages(parts.VARIANT).values())
    return {"title": "Draft 2 CPU", "variant": parts.VARIANT, "packages": round(packages),
            "families": FAMILIES, "buses": BUSES, "tnets": tnets,
            "nodes": {k: v for k, v in nodes.items() if v["kind"] != "symbol"},
            "symbols": model["symbols"], "nets": nets,
            "traces": traces, "cases": cases, "words": {f"{a}": w for a, w in words.items()},
            "suite": suite_out, "lengths": list(mc.lengths), "tick_ns": cpu.TICK_PS / 1000}


# ---- the page -------------------------------------------------------------------------------


def page(data, standalone=False):
    """The explorer as HTML: a fragment (for a page host that adds the
    document around it) or, with standalone, a whole document. The data
    goes in gzipped, as base64."""
    import base64
    import gzip
    with open(os.path.join(HERE, "explore.html")) as f:
        tpl = f.read()
    blob = gzip.compress(json.dumps(data, separators=(",", ":")).encode(), 9, mtime=0)
    body = tpl.replace("%%ELK%%", schematic.ELK_URL).replace(
        "%%DATA%%", base64.b64encode(blob).decode())
    if standalone:
        return ('<!doctype html>\n<html lang="en"><head><meta charset="utf-8">\n'
                '<meta name="viewport" content="width=device-width, initial-scale=1, '
                'viewport-fit=cover">\n</head><body>\n' + body + '\n</body></html>\n')
    return body


def main(argv=None):
    import argparse
    from heron import BUILD
    p = argparse.ArgumentParser(prog="heron v2_hw explore",
                                description="the design explorer, as one HTML page")
    p.add_argument("--out", help="where to write it (default build/v2_hw/explorer.html)")
    p.add_argument("--fragment", action="store_true",
                   help="without the document around it, for a page host that adds it")
    p.add_argument("--jobs", type=int, default=4)
    args = p.parse_args(argv)
    out = args.out or os.path.join(BUILD, "v2_hw", "explorer.html")
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    html = page(build_model(jobs=args.jobs), standalone=not args.fragment)
    with open(out, "w") as f:
        f.write(html)
    print(f"{out}: {len(html) // 1024} KB")
    return 0
