"""Where the chips go: the system's netlist by card and by the sections
its netlists name (schematic sheets), what 16-bit parts would save, how
much of the CPU only serves the upper half of the datapath, and how much
of the microinstruction the microcode actually uses.
"""

import math
import re
from collections import Counter, defaultdict

from heron.studies.v1b_hw import cpu
from heron.studies.v1b_hw import ucode as uc
from heron.studies.v1b_system import machine


def system():
    return machine.build(machine.default_lengths())


def chips_by_section(nl=None):
    """{(card, section): chips}. A gate package that serves several
    sections is shared out by its gates."""
    nl = nl or system()
    gates = defaultdict(Counter)
    for g in nl.gates:
        gates[g.ref][g.section] += 1
    out = Counter()
    for inst in nl.instances:
        if inst.type.family in ("fixture", "passive"):
            continue
        card = getattr(inst, "card", None) or "BP"
        if inst.ref in gates:
            tot = sum(gates[inst.ref].values())
            for s, n in gates[inst.ref].items():
                out[(card, s)] += n / tot
        else:
            out[(card, inst.section)] += 1
    return out


# Octal parts that a 16-bit ("Widebus") part replaces two of: their halves
# have separate clocks, enables and directions, so any two pair up. And
# the register file's 32K x 8 SRAMs, two of which a 64K x 16 one replaces.
# (The 512K x 8 RAMs have no 5 V x16 part as deep: 256K x 16 is the
# largest, so they stay.)
WIDEBUS = {"377": "74ABT16823", "823": "74ABT16823", "574": "74ABT16374",
           "541": "74ABT16244", "540": "74ABT16240", "245": "74ABT16245",
           "sram": "IS61C6416AL (64K x 16)"}


def widebus(nl=None):
    """{card: (chips, pairable {type: count}, chips saved)}."""
    nl = nl or system()
    total, pairable = Counter(), defaultdict(Counter)
    for inst in nl.instances:
        if inst.type.family in ("fixture", "passive"):
            continue
        card = getattr(inst, "card", None) or "BP"
        total[card] += 1
        if inst.type.name in WIDEBUS:
            pairable[card][inst.type.name] += 1
    return {card: (total[card], dict(pairable[card]),
                   sum(c // 2 for c in pairable[card].values()))
            for card in total}


DATAPATH = re.compile(r"^(ABUS|BBUS|F|RES|RQ|TQ|MARIN|MAR|PC|MQS|MQ)(\d+)$")


def upper_only(bits=16):
    """The CPU core's chips whose datapath nets are all at bit `bits` or
    above (they would go with a narrower datapath, except where the
    narrow design still keeps 32-bit registers such as the PC and MAR):
    {section: chips}."""
    nl = cpu.build(card=True, stub=True)
    out = Counter()
    for inst in nl.instances:
        if inst.type.family == "fixture":
            continue
        idx = [int(m.group(2)) for m in (DATAPATH.match(n) for n in inst.conn.values()) if m]
        if idx and min(idx) >= bits:
            out[inst.section] += 1
    return out


GROUPS = {
    "sequencer": ["NEXT", "SEQ", "COND", "GOIRQ", "HALT"],
    "A bus": ["ARF", "APC", "AR", "AR2", "ABR", "SINA"],
    "B bus": ["BRF", "BR", "BT0", "BT1", "BT23", "BS0", "BF1", "BF23", "BMQ", "BFL", "BT2", "TLANE"],
    "store data": ["DSRC"],
    "register file": ["RFA", "RFB", "LDX", "RFK", "RFWE", "WR0"],
    "ALU": ["S", "M", "CIN", "MQM", "MS"],
    "result multiplexer": ["RMS", "RZ", "SIN"],
    "immediate unit": ["V8", "FSEL", "KONST", "LDSGN"],
    "register loads": ["LDR", "LDMAR", "MARSRC", "LDTL", "LDTH", "LDIR", "LDPC", "PCCOND",
                       "LDLC", "LCINC", "CCB"],
    "memory": ["MEMRD", "MEMWR", "ADDRMAR", "SIZE", "HIWORD"],
    "flags": ["FNZ", "FC", "CZERO", "CSRC", "FV", "FI", "LDCL", "CLSRC"],
}


def microword():
    """Per field group of the 120-bit microinstruction: (bits, distinct
    values the microcode uses, bits to number them)."""
    mc = uc.built()
    words = [uc.unpack(uc.pack(mc.word(n, False))) for n in mc.nodes]
    width = {n: w for n, w, _ in uc.FIELDS}
    out = {}
    for g, fs in GROUPS.items():
        used = Counter(tuple(w[f] for f in fs) for w in words)
        out[g] = (sum(width[f] for f in fs), len(used), math.ceil(math.log2(len(used))))
    return len(words), out
