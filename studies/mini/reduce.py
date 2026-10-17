"""What Heron Mini could leave out (RFC 0041, Part II): each reduction
taken from the overbuilt netlist as the chips it removes (by reference)
and the packages it adds, and what it costs in time: measured on the
register-transfer model where the model has the variant (the queue),
else estimated from the suite's profile, from how often the
microinstructions it slows run and by how much.
"""

from collections import Counter, defaultdict

from . import board, parts, perf, ucode as uc


def inventory():
    """{ref: (section, part, packages)}: every chip of the simulation
    netlist; a gate package's share split by its gates."""
    nl = board.build(sim=True)
    gate_refs = {g.ref for g in nl.gates}
    out = {}
    for inst in nl.instances:
        if inst.type.family in ("fixture", "passive") or inst.ref in gate_refs:
            continue
        out[inst.ref] = (inst.section, inst.part_number(parts.VARIANT), 1.0 / inst.type.per_package)
    per = defaultdict(list)
    for g in nl.gates:
        per[g.ref].append(g.section)
    for ref, secs in per.items():
        for k, s in enumerate(secs):
            out[f"{ref}.{k}"] = (s, "gate", 1.0 / len(secs))
    return out


def gate_parts():
    """The part numbers of the netlist's gate packages, with how many."""
    nl = board.build(sim=True)
    gate_refs = {g.ref for g in nl.gates}
    return Counter(i.part_number(parts.VARIANT) for i in nl.instances if i.ref in gate_refs)


def sections(inv=None):
    """{section: packages}."""
    inv = inv or inventory()
    out = Counter()
    for sec, _, n in inv.values():
        out[sec] += n
    return out


# ---- the time a change costs, from the suite's profile -------------------------------------

def _profile(c):
    rows = perf.profile()
    rows = [r for r in rows if r["name"].startswith("c/") == c and r["name"] not in perf.SKIP]
    mc = uc.built()
    cnt = perf.counts(rows)
    base = sum(n * mc.lengths[mc.word(mc.by_addr[a], a).get("LCL", 0)] for a, n in cnt.items())
    base += sum(r["hold"] for r in rows)
    return mc, cnt, base


def extra_ticks(fn, c=False):
    """(base ticks, extra ticks) for the suite (c: the C programs): fn(f,
    ticks) gives a microinstruction's extra ticks."""
    mc, cnt, base = _profile(c)
    extra = 0
    for a, n in cnt.items():
        f = mc.word(mc.by_addr[a], a)
        extra += n * fn(f, mc.lengths[f.get("LCL", 0)])
    return base, extra


# ---- the reductions ------------------------------------------------------------------------
#
# Each: (key, what, the chips it removes, the packages it adds (part, n), its
# time: "queue" measured on the model, a rule over the profile (a
# microinstruction's fields and ticks -> its extra ticks), or None; what's
# lost). The gates that go with a reduction aren't counted: the numbers
# are what goes at least.

def _r(prefix, n, start=0):
    return [f"{prefix}{k}" for k in range(start, start + n)]


def _mem(f):
    return f.get("MEM", 0)


REDUCTIONS = [
    ("queue1", "a prefetch queue of one word",
     _r("U_QS1", 4) + _r("U_QB1", 4), [], "queue",
     "the second word: the queue refills more often"),
    ("noreada", "no reads at the A bus: the address from MAR or FPC only",
     _r("U_VAM", 13), [("74F157", 7)],
     lambda f, k: 6 if _mem(f) == 6 else 0,
     "a load at [R] (and [R]+) takes a cycle more, to load MAR (6 ticks)"),
    ("nomq", "no MQ: multiply and divide by shifts and adds of registers",
     _r("U_MQ", 4) + ["U_SM0", "U_SM1"], [],
     lambda f, k: 15 if (f.get("MQM") or f.get("MS")) else 0,
     "a multiply or divide step takes three cycles more (about 15 ticks)"),
    ("lanes", "byte and half lanes in microcode: loads moved down, stores "
     "replicated, by rotations",
     ["U_BT20", "U_BT31", "U_BT10", "U_BT30", "U_BT1E", "U_BT20E", "U_TH1E", "U_TB1E",
      "U_TB3E", "U_SDB1", "U_SDB2", "U_SDH3", "U_SDB3"], [],
     lambda f, k: 18 if (f.get("BL", 0) in (2, 3) or (_mem(f) == 2 and f.get("SIZE", 0) in (1, 2)))
     else 0,
     "a byte or half load or store takes three cycles more (rotating by the "
     "address's low bits)"),
    ("noror", "no rotations by 8 and 16 in the result multiplexer",
     _r("U_RES", 16), [("74F157", 8)],
     lambda f, k: {2: 7 * 5, 3: 15 * 5}.get(f.get("RMS", 0), 0),
     "a rotation by 8 is 8 shifts, by 16 sixteen"),
]

REDUCTIONS += [
    ("vram", "the video in the one RAM: its address through the address "
     "multiplexer's fourth input, its words on the data bus",
     _r("U_B1C", 3) + _r("U_B1V", 3) + _r("U_B1X", 4) + ["U_T1F"], [("74F32", 1)], None,
     "the video then can't read in an I/O access (the data bus is the I/O's): "
     "a long access, or several in a row, can starve it; two ORs on the "
     "address multiplexer's select"),
    ("nodesc", "no line descriptors: one frame buffer from bank 1's word 0",
     _r("U_VADM", 3) + ["U_VML"], [], None,
     "per-line addresses (scrolling, repeated or split screens), per-line "
     "palette banks, line interrupts"),
    ("pal8", "an 8-bit palette (RGB 3:3:2)",
     ["U_PAL1", "U_RGB1", "U_PWD1"], [], None, "colours: 256 of 65536 become 256 of 256"),
    ("ioal", "no latch for the devices' address and selects",
     ["U_IOAL", "U_IOSL"], [], None,
     "the address holds 12 ns after a strobe at worst, not the 16C550's "
     "and the CF card's 20 (26 typically); the expansion ports see VA"),
    ("isr", "no interrupt status register",
     ["U_ISR"], [], None, "an interrupt handler polls the devices"),
    ("ctl", "no control register (the speaker, the LEDs)",
     ["U_CTL"], [], None, "the speaker; the 82C54's counter 2 then just counts"),
    ("uart1", "one UART", ["U_UART1"], [], None, "the second serial port"),
]


def chips(red, inv):
    """Packages a reduction removes (net of what it adds)."""
    _key, _what, refs, adds, _time, _lost = red
    gone = 0.0
    for r in refs:
        if r not in inv:
            raise KeyError(f"{_key}: no chip {r}")
        gone += inv[r][2]
    return gone - sum(n for _, n in adds)


def queue_time():
    """The suite's and the C programs' ticks, with the queue of two words and
    of one, on the register-transfer model."""
    import os
    from heron.infra import asm as asmcore
    from heron.infra import isas
    from heron.infra.programs import metadata
    from . import check
    tot = {2: [0, 0], 1: [0, 0]}
    for p in check.program_paths():
        if os.path.basename(p)[:-2] in perf.SKIP:
            continue
        img = asmcore.assemble_file(isas.get("v2"), p)
        for q in (2, 1):
            tot[q][0] += check.run_rtl(img, metadata(p)["input"], queue=q).ticks
    for _name, img, inp in check.c_programs():
        for q in (2, 1):
            tot[q][1] += check.run_rtl(img, inp, queue=q).ticks
    return tot


def table():
    """[(key, what, packages, suite %, C %, lost)]."""
    inv = inventory()
    out = []
    qt = None
    for red in REDUCTIONS:
        key, what, _refs, _adds, time, lost = red
        n = chips(red, inv)
        if time is None:
            s = c = None
        elif time == "queue":
            qt = qt or queue_time()
            s = 100 * (qt[1][0] / qt[2][0] - 1)
            c = 100 * (qt[1][1] / qt[2][1] - 1)
        else:
            b, e = extra_ticks(time)
            s = 100 * e / b
            b, e = extra_ticks(time, c=True)
            c = 100 * e / b
        out.append((key, what, n, s, c, lost))
    return out
