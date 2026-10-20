"""The two-halves machine's chip-level netlist: every chip on the board.

    build(sim=True)    for the chip-level simulator: the oscillators, the
                       power-on reset, the suite's console (a fixture at the
                       I/O space's 0xFFFF_F000, a slot the board leaves free), a
                       keyboard and a mouse on the PS/2 ports
    build(sim=False)   for static timing analysis (sta2.py): the same, with
                       the clock generator's two GALs replaced by a fixture
                       that gives the cycle's phases at their ticks

The cycle (ucode2.py): the master clock MCLK (50.35 MHz, a tick 19.86 ns)
drives the clock generator, U_CGA (the phase PH, F, L or H, and the tick
in it, TC; END, the phase's last tick) and U_CGB (the clocks: CLK0 rises
as phase F starts and loads the sequencer; HCKA at the low half's end,
HCKB at the high half's, HCK at either; HALF in the high half; PHW in
phase F; the register file's write strobes in F's ticks 1 and 2, and the
result registers' drives there). Phase F lasts 3 ticks, 2 more when the
video's buffer is empty (a second read for it), 1 more when a task starts
or ends; a half lasts LEN + 1 or HLEN ticks, 5 for an access to the I/O
space, and the slow devices hold it longer (HOLD).

Nets as the first cut's (board.py): D the internal bus, MD the memory's,
A the address bus, F the ALU's output, L the operand latch's (the low
half's register in the low half, the high half's in the high), uXXn the
control store's outputs.
"""

from heron.infra.hw import gal as G
from heron.infra.hw.cells import Reg, Setup, Width
from heron.infra.hw.netlist import Netlist

from . import draft, parts, ucode2 as uc  # noqa: F401  (parts registers the variant)
from .board import AND, OR, ONE, ZERO, TICK_PS, bus, counter_bit, eq, lit, negate, toggle

UCLK_PS = 542535                # 1.8432 MHz: the UARTs' and the timer's

# the 22V10s' grades (infra/hw/datasheets/timing_bus.json), where not the
# -5 in PLCC-28: the slowest in DIP-24 that leaves every microinstruction's
# ticks as they are (heron chibi hw grades), on the master clock at least
# the -15. The -7 for speed, the -15 and the zero-power CQZ-20 for power.
# Empty for now: the search's mix (RFC 0047, 18) fails at chip level
# (U_IRH's setup at -15, UART 0's select with U_IODEC a CQZ-20), so the
# analysis misses some paths (open).
GAL_GRADES = {}


def field(name):
    b, w, _ = uc._pos[name]
    suffix = "_n" if name in uc.INVERTED else ""
    return [f"u{name}{i}{suffix}" if w > 1 else f"u{name}{suffix}" for i in range(w)]


def control_nets():
    out = {}
    for name, (b, w, _) in uc._pos.items():
        for i, n in enumerate(field(name)):
            out[b + i] = n
    return out


MOP = field("MOP")
DS = field("DS")
HXF = field("HX")
SZ = field("SZ")[0]


def mop_in(codes):
    return G.when(MOP, list(codes), range(8)) if codes else ZERO


def ds_is(code):
    return eq(DS, code)


def tc_is(v):
    return eq(["TC0", "TC1", "TC2"], v)


def ph_is(p):
    return eq(["PH0", "PH1"], {"F": 0, "L": 1, "H": 2}[p])


RESET = lit("RESET_n", 0)


def build(sim=True, halt_ps=0):
    nl = Netlist()
    cw = control_nets()
    nl.add("const", "X_RAIL", LO="GND", HI="VCC")
    draft._types()
    _types()

    # ---- clock and reset --------------------------------------------------
    nl.section("clock")
    if sim:
        nl.add("osc", "X_OSC", OUT="MCLK", params={"period_ps": TICK_PS, "phase_ps": 7000})
        nl.add("por", "U_POR", RST="RESET_n", params={"release_ps": 3_000_000})
        clock_gen(nl)
    else:
        nl.add("chibiclk3", "X_CLK", MCLK="MCLK", RESET="RESET_n", **{n: n for n in CG_OUTS})
    nl.add("pullup", "R_PU1", P1="RESET_n")
    nl.add("conn", "J_CLK", P0="MCLK", P1="XCLK", P2="GND",
           part="clock jumper: the oscillator or an external clock")
    clk = [f"CLK{i}" for i in range(1, 9)]
    nl.add("541", "U_CLKB", OE1="GND", OE2="GND", part="74ABT541",
           **{f"A{i}": "CLK0" for i in range(1, 9)}, **{f"Y{i}": clk[i - 1] for i in range(1, 9)})
    hck = ["HCK1", "HCK2", "HCK3", "HCK4", "HCKA1", "HCKA2", "HCKB1", "HCKB2"]
    src = ["HCK"] * 4 + ["HCKA"] * 2 + ["HCKB"] * 2
    nl.add("541", "U_HCKB", OE1="GND", OE2="GND", part="74ABT541",
           **{f"A{i + 1}": src[i] for i in range(8)}, **{f"Y{i + 1}": hck[i] for i in range(8)})

    # ---- control store and sequencer --------------------------------------
    nl.section("control store")
    upc = bus("UPC", uc.ADDR_BITS)
    cs_addr = upc + ["GND"] * (17 - uc.ADDR_BITS)          # SST39SF010As, 128K x 8
    for k in range(uc.ROMS):
        nl.add("flash", f"U_CS{k}", CE="GND", OE="GND", WE="VCC",
               **{f"A{i}": cs_addr[i] for i in range(17)},
               **{f"D{i}": cw[8 * k + i] for i in range(8)})
    sequencer(nl, clk, upc)

    nl.section("flags")
    flags_gal(nl)
    fl_ = field("FL")
    flc = {n: eq(fl_, uc.FL_CODE[n]) for n in uc.SYS_FLOPS}
    G.add(nl, "U_SYS", {
        "IRQP": (OR(AND(lit("F_I"), lit("IRQ")), lit("HLTQ"), lit("TRACE")), True, False),
        "INIT": (OR(lit("INIT"), flc["SETINIT"]), True, False),
        "B": (OR(AND(flc["BNZ"], lit("Z16", 0)), AND(flc["ENTRY"], OR(lit("B"), lit("BI"))),
                 AND(negate(OR(flc["BNZ"], flc["ENTRY"])), lit("B"))), True, False),
        "BI": (OR(AND(flc["BINZ"], lit("Z16", 0)), AND(negate(flc["BINZ"]), lit("BI"))), True,
               False),
        "ODTQ": (OR(lit("HLTQ"), lit("TRACE")), False, False),
        "TASK_n": (AND(lit("TASK"), lit("TASKD")), False, True),   # the tasks' address drivers
        # the video's slot on the address bus: phase F through a 22V10, as
        # PCSEL and MARSEL come, so that the drivers change over together
        "VSEL": (lit("PHW"), False, False),
    }, clock=clk[1], ar=RESET)

    # ---- register file ------------------------------------------------------
    nl.section("register file")
    register_file(nl, clk)

    # ---- ALU and result ------------------------------------------------------
    nl.section("ALU")
    # the operand latch: the low half's register (U_LA) and the high half's
    # (U_LB), 574s on L, each on in its half, clocked by U_LCK's LCKA and
    # LCKB at their half's end when the word loads L (LDL)
    for nm, ck, oe in (("U_LA", "LCKA", "HALF"), ("U_LB", "LCKB", "LBOE_n")):
        for k in range(2):
            nl.add("574", f"{nm}{k}", CLK=ck, OE=oe,
                   **{f"D{i + 1}": f"D{8 * k + i}" for i in range(8)},
                   **{f"Q{i + 1}": f"L{8 * k + i}" for i in range(8)})
    lck_gal(nl)
    cn = ["CN0_n", "CNX", "CNY", "CNZ"]
    for k in range(4):
        nl.add("181", f"U_ALU{k}", M="AM", CN=cn[k], P=f"ALUP{k}", G=f"ALUG{k}",
               CN4="CO_n" if k == 3 else f"ALUCN4_{k}", AEQB=f"ALUEQ{k}",
               **{f"A{i}": f"D{4 * k + i}" for i in range(4)},
               **{f"B{i}": f"L{4 * k + i}" for i in range(4)},
               **{f"S{i}": f"AS{i}" for i in range(4)},
               **{f"F{i}": f"F{4 * k + i}" for i in range(4)})
    nl.add("182", "U_CLA", CN="CN0_n", CNX="CNX", CNY="CNY", CNZ="CNZ", P="CLAP", G="CLAG",
           **{f"P{i}": f"ALUP{i}" for i in range(4)}, **{f"G{i}": f"ALUG{i}" for i in range(4)})
    aluc_gal(nl)
    nl.section("result")
    result_gals(nl)

    # ---- the bus's sources ----------------------------------------------------
    nl.section("immediate unit")
    imm_gals(nl)
    bus_gals(nl)
    nl.add("541", "U_FWB", OE1="FWOE_n", OE2="FWOE_n",
           **{f"A{i + 1}": n for i, n in enumerate(["F_V", "F_C", "F_Z", "F_N", "F_I", "B", "BI",
                                                    "GND"])},
           **{f"Y{i + 1}": f"D{i}" for i in range(8)})

    # ---- address registers ------------------------------------------------
    nl.section("address")
    address_gals(nl)

    # ---- memory ------------------------------------------------------------
    nl.section("memory")
    for k in range(2):
        nl.add("245", f"U_X{k}", DIR="XDIR", OE=f"XOE{k}_n",
               **{f"A{i + 1}": f"D{8 * k + i}" for i in range(8)},
               **{f"B{i + 1}": f"MD{8 * k + i}" for i in range(8)})
    nl.add("245", "U_XS", DIR="XDIR", OE="XOES_n",
           **{f"A{i + 1}": f"D{i}" for i in range(8)},
           **{f"B{i + 1}": f"MD{8 + i}" for i in range(8)})
    for k in range(2):
        nl.add("541", f"U_RB{k}", OE1="RBOE_n", OE2="RBOE_n",
               **{f"A{i + 1}": f"A{8 * k + i}" for i in range(8)},
               **{f"Y{i + 1}": f"D{8 * k + i}" for i in range(8)})
    memc_gal(nl)
    for r in range(2):
        for b in range(2):
            nl.add("sram512", f"U_RAM{r}{b}", role="fastram", CE="A20" if r == 0 else "RCE1_n",
                   OE="RAMOE_n", WE=f"WE{'LH'[b]}_n",
                   **{f"A{i}": f"A{i + 1}" for i in range(19)},
                   **{f"IO{i}": f"MD{8 * b + i}" for i in range(8)})

    # ---- I/O ---------------------------------------------------------------
    nl.section("I/O")
    io(nl, sim, halt_ps)

    # ---- video -------------------------------------------------------------
    nl.section("video")
    video(nl, clk)

    for inst in nl.instances:
        if inst.type.name == "22v10" and inst.ref in GAL_GRADES:
            inst.part = GAL_GRADES[inst.ref]
    nl.finish()
    nl.check()
    return nl


def _types():
    from heron.infra.hw import chips
    if "dac0832" in chips.TYPES:
        return
    chips.T("dac0832", "dreg", [("CLK", "in")] + [(f"D{i}", "in") for i in range(1, 9)]
            + [(f"Q{i}", "out") for i in range(1, 9)] + [("VREFIN", "pull"), ("VOUT", "pull")],
            arcs=[(["CLK"], [f"Q{i}" for i in range(1, 9)], "CLK->Q")],
            checks=[([f"D{i}" for i in range(1, 9)], "CLK", "rise", "setup D", "hold D")],
            family="device",
            desc="DAC0832 with its input latch open (CS and WR1 low, ILE high), its DAC latch "
                 "on WR2 (XFER low), taken as a register on WR2's rise; the converter in "
                 "voltage mode (the reference in at IOUT1, the output at VREF); Q the code "
                 "converted",
  regs={f"Q{i}": Reg("CLK", f"D{i}", "CLK->Q") for i in range(1, 9)},
  timing=[Setup("D1-D8", "CLK", "setup D", "hold D"), Width("CLK", 0, "tW")],)
    chips.T("mcp6002", "passive", [(p, "pull") for p in ("REF", "DIV", "IN", "OUT")],
            family="device", desc="dual op-amp: a follower giving the DAC its reference from "
                                  "a divider (DIV), a follower buffering its output")
    chips.FIXED_PARTS.update({"mcp6002": "MCP6002", **{f"_b2_{i}": n for i, n in enumerate(CONNS)}})
    chips.T("chibiclk3", "chibiclk3",
            [(p, "out") for p in ("MCLK", "RESET")]
            + [(p, "out") for p in CG_OUTS], family="fixture",
            desc="for static timing analysis: the two-halves machine's clock generator, its "
                 "outputs at the ticks the case gives (studies/chibi/sta2.py)")


# the connectors' and switches' part names (no timing)
CONNS = ["clock jumper: the oscillator or an external clock", "DE-15 (VGA) with its sync resistors",
         "3.5 mm jack, the reference's divider, the mixing resistors (the timer's OUT2 as a "
         "beeper too)",
         "push button (SPDT): halt to ODT", "push buttons: interrupt, reset", "DE-9 male"]

# the clock generator's outputs (U_CGA's and U_CGB's)
CG_OUTS = ("TC0", "TC1", "TC2", "PH0", "PH1", "VEXTQ", "HWQ", "END", "HLZ", "LASTH",
           "CLK0", "PHW", "HALF", "HCKA", "HCKB", "HCK", "RFWL_n", "RFWH_n", "YAOE", "YBOE")


def clock_gen(nl):
    """U_CGA: the phase and its tick, END, and HWQ (the cycle's HW, for phase
    F's writes); U_CGB: the clocks and strobes, each registered from the
    state's next value."""
    tc, ph = ["TC0", "TC1", "TC2"], ["PH0", "PH1"]
    LEN, HLEN = field("LEN"), field("HLEN")

    def end_fn(p0, p1, t0, t1, t2, vx, tchg, l0, l1, h0, h1, ioacc, hold):
        p, t = p0 | p1 << 1, t0 | t1 << 1 | t2 << 2
        if p == 0:
            return t == 2 + 2 * vx + tchg
        if p == 3:
            return True
        n = (l0 | l1 << 1) if p == 1 else (h0 | h1 << 1) - 1
        if t < 2:
            return t == n
        if hold:
            return False
        return t >= 5 if ioacc else t == n          # an I/O half: 6 ticks
    END = G.table(ph + tc + ["VEXTQ", "TCHG"] + LEN + HLEN + ["IOACC", "HOLD"], end_fn)
    hlz = AND(lit(HLEN[0], 0), lit(HLEN[1], 0))
    last = OR(ph_is("H"), AND(ph_is("L"), lit("HLZ")))
    outs = {"END": (END, False, False), "HLZ": (hlz, False, False),
            "LASTH": (last, False, False)}

    def nxt(i):
        def f(p0, p1, t0, t1, t2, e, hz):
            p, t = p0 | p1 << 1, t0 | t1 << 1 | t2 << 2
            if p == 3:
                return 0                # (power-up) on to phase F
            if e:
                np_, nt = ({0: 1, 1: 0 if hz else 2, 2: 0}[p], 0)
            else:
                np_, nt = p, min(t + 1, 7)
            return (np_ | nt << 2) >> i & 1
        return G.table(ph + tc + ["END", "HLZ"], f)
    for i, n in enumerate(ph + tc):
        outs[n] = (nxt(i), True, False)
    f0 = AND(ph_is("F"), tc_is(0))
    outs["VEXTQ"] = (OR(AND(f0, lit("VEXT")), AND(negate(f0), lit("VEXTQ"))), True, False)
    cyc_end = AND(lit("END"), last)
    outs["HWQ"] = (OR(AND(cyc_end, lit(field("HW")[0])), AND(negate(cyc_end), lit("HWQ"))),
                   True, False)
    # not reset: the clocks run through reset, as the sequencer's registers
    # (reset) and the chip-level simulator's runner want
    G.add(nl, "U_CGA", outs, clock="MCLK")
    e = lit("END")
    to_f = AND(e, OR(ph_is("H"), AND(ph_is("L"), lit("HLZ"))))
    outs = {
        "CLK0": (to_f, True, False),
        "PHW": (OR(AND(ph_is("F"), lit("END", 0)), to_f), True, False),
        "HALF": (OR(AND(ph_is("H"), lit("END", 0)), AND(e, ph_is("L"), lit("HLZ", 0))), True, False),
        "HCKA": (AND(e, ph_is("L")), True, False),
        "HCKB": (AND(e, ph_is("H")), True, False),
        "HCK": (AND(e, OR(ph_is("L"), ph_is("H"))), True, False),
        "RFWL_n": (AND(ph_is("F"), tc_is(0)), True, True),
        "RFWH_n": (AND(ph_is("F"), tc_is(1)), True, True),
        "YAOE": (AND(ph_is("F"), OR(AND(tc_is(0), lit("HWQ", 0)), AND(tc_is(1), lit("HWQ")))),
                 True, False),
        "YBOE": (AND(ph_is("F"), OR(AND(tc_is(1), lit("HWQ", 0)), AND(tc_is(0), lit("HWQ")))),
                 True, False),
    }
    G.add(nl, "U_CGB", outs, clock="MCLK")


def sequencer(nl, clk, upc):
    """µPC (ucode2.py has its next addresses): U_UPCL its bits 3-0, U_UPCM
    8-4, U_UPCH 12-9, loaded at CLK0 and held while a task runs; U_NG the
    16-way branch's nibble, d, s or z (MD11-8) by CND's low bits; U_IRH the
    register byte (d, s), from a fetch's parcel or LDIRM's read; U_COND the
    condition: the flags, IRQP, d != s, A0, ODT and I."""
    seq, cnd, jt = field("SEQ"), field("CND"), field("JT")
    irn = field("IRN")
    ldir, nld = lit("LDIR"), lit("LDIR", 0)
    d, s = bus("IRD", 4), bus("IRS", 4)
    incd, decs, idx = eq(irn, uc.HIRN_INCD), eq(irn, uc.HIRN_DECS), eq(irn, uc.HIRN_IDX)
    irh = {}
    for i in range(4):
        irh[d[i]] = (OR(AND(ldir, lit(f"MD{12 + i}")), AND(nld, toggle(d, i, incd)),
                        AND(nld, negate(incd), lit(d[i]))), True, False)
        sdec = OR(AND(decs, lit(s[i], 1), OR(*[lit(b, 1) for b in s[:i]])) if i else ZERO,
                  AND(decs, lit(s[i], 0), [{b: 0 for b in s[:i]}] if i else ONE))
        irh[s[i]] = (OR(AND(ldir, lit(f"MD{8 + i}")), AND(nld, idx, lit(f"MD{12 + i}")),
                        AND(nld, sdec), AND(nld, negate(OR(idx, decs)), lit(s[i]))), True, False)
    irh["NE"] = (OR(*[OR(AND(lit(d[i], 1), lit(s[i], 0)), AND(lit(d[i], 0), lit(s[i], 1)))
                      for i in range(4)]), False, False)
    G.add(nl, "U_IRH", irh, clock=clk[0])
    nx = bus("NX", 4)
    src = cnd[:2]
    ng = {nx[i]: (OR(AND(eq(src, uc.MW_D), lit(d[i])), AND(eq(src, uc.MW_S), lit(s[i])),
                     AND(eq(src, uc.MW_Z), lit(f"MD{8 + i}"))), False, False) for i in range(4)}
    ng["RCE1_n"] = (lit("A20", 0), False, False)       # the RAM's row 1 (a spare macrocell)
    G.add(nl, "U_NG", ng)
    # the next address: a jump (SEQ's bits equal) JT ^ CT; a branch JT | NX;
    # the decode 0x100 + MD7-0 (MD7-0 alone if IRQP, unless JT12)
    jmp = OR(eq(seq, uc.HSEQ_JUMP), eq(seq, uc.HSEQ_JUMPT))
    mw, end = eq(seq, uc.HSEQ_MW), eq(seq, uc.HSEQ_END)
    notask = lit("TASK", 0)
    outs = {}
    for i in range(uc.ADDR_BITS):
        if i == 0:
            j = OR(AND(jmp, lit(jt[0]), lit("CT", 0)), AND(jmp, lit(jt[0], 0), lit("CT")),
                   AND(mw, lit(jt[0])), AND(mw, lit(nx[0])))
        elif i < 4:
            j = OR(AND(negate(end), lit(jt[i])), AND(mw, lit(nx[i])))
        else:
            j = AND(negate(end), lit(jt[i]))
        if i < 8:
            dec = AND(end, lit(f"MD{i}"))
        elif i == 8:
            dec = AND(end, OR(lit("IRQP", 0), lit(jt[12])))
        else:
            dec = ZERO
        # bits 6-0 give way to U_TASK's, 12-7 to U_TOP's (break before make)
        oe = notask if i < 7 else lit("TASKOR", 0)
        outs[upc[i]] = (OR(AND(OR(j, dec), notask), AND(lit("TASK"), lit(upc[i]))), True, False, oe)
    for name, bits in (("U_UPCL", range(0, 4)), ("U_UPCM", range(4, 9)),
                       ("U_UPCH", range(9, uc.ADDR_BITS))):
        G.add(nl, name, {upc[i]: outs[upc[i]] for i in bits}, clock="CLK0", ar=RESET)
    f = {k: f"F_{k}" for k in ("N", "Z", "C", "V", "I", "IC", "ST")}
    conds = {
        "TRUE": ONE, "Z": lit(f["Z"]), "C": lit(f["C"]), "N": lit(f["N"]), "V": lit(f["V"]),
        "HI": AND(lit(f["C"]), lit(f["Z"], 0)),
        "LT": OR(AND(lit(f["N"]), lit(f["V"], 0)), AND(lit(f["N"], 0), lit(f["V"]))),
        "LE": OR(lit(f["Z"]), AND(lit(f["N"]), lit(f["V"], 0)), AND(lit(f["N"], 0), lit(f["V"]))),
        "IC": lit(f["IC"]), "ST": lit(f["ST"]), "INIT": lit("INIT"), "IRQP": lit("IRQP"),
        "NE": lit("NE"), "A0": lit("A0"), "ODT": lit("ODTQ"), "I": lit(f["I"]),
    }
    terms = []
    for name, sop in conds.items():
        terms.append(AND(eq(cnd, uc.COND_CODE[name]), sop))
    parts_ = [[], []]
    for t in sorted(terms, key=len, reverse=True):
        min(parts_, key=len).extend(t)
    G.add(nl, "U_COND", {"CTA": (parts_[0], False, False), "CTB": (parts_[1], False, False),
                         "CT": (OR(lit("CTA"), lit("CTB")), False, False)})
    tasks(nl, seq, jt, upc)


def tasks(nl, seq, jt, upc):
    """Microcode tasks: at a task point (SEQ END or JUMPT: SEQ's bit 1)
    while DREQ (the device task's) or COPREQ (the copper's) asks, TASK
    sets; µPC holds with its outputs off, and U_TASK's bits 6-0 with
    U_TOP's ones above them (TASK_BASE) address the control store, from
    DEVICE_BASE if DREQ asked (it goes first), else COPPER_BASE. A task's
    SEQ END ends it. (TCHG, TASK changed at the cycle's start, is U_LCK's.)"""
    task = lit("TASK")
    end = eq(seq, uc.HSEQ_END)
    start = AND(lit("TASK", 0), lit(seq[1]), OR(lit("COPREQ"), lit("DREQ")))
    outs = {}
    for i in range(7):
        nx_ = OR(AND(lit(jt[0]), lit("CT", 0)), AND(lit(jt[0], 0), lit("CT"))) if i == 0 \
            else lit(jt[i])
        first = (uc.COPPER_BASE >> i & 1, uc.DEVICE_BASE >> i & 1)
        assert first[1] == 0 and (i == 6 or first[0] == 0)
        go = AND(start, lit("DREQ", 0)) if first[0] else ZERO
        outs[upc[i]] = (OR(AND(task, nx_), go), True, False, task)
    outs["TASK"] = (OR(AND(task, negate(end)), start), True, False)
    G.add(nl, "U_TASK", outs, clock="CLK0", ar=RESET)
    assert uc.TASK_BASE >> 7 == (1 << uc.ADDR_BITS - 7) - 1
    nl.add("541", "U_TOP", OE1="TASK_n", OE2="TASK_n", part="74ABT541",
           **{f"A{i + 1}": "VCC" if i < 6 else "GND" for i in range(8)},
           **{f"Y{i + 1}": upc[7 + i] for i in range(6)})


def flags_gal(nl):
    """N, Z, C, V, I, IC, ST from the flag operation and the half's result;
    in the high half each operation is FL_HIGH's."""
    fl_ = field("FL")
    f = {k: f"F_{k}" for k in ("N", "Z", "C", "V", "I", "IC", "ST")}
    ins = {"z": "Z16", "n15": "N15", "co": "CO_n", "f0": "F0", "f1": "F1",
           "a15": "D15", "b15": "L15"}

    def nextf(flag, name, v, F):
        z, n15, co, f0, f1 = v["z"], v["n15"], 1 - v["co"], v["f0"], v["f1"]
        a15, b15 = v["a15"], v["b15"]

        def ov(sub):
            return int((a15 != b15 if sub else a15 == b15) and n15 != a15)
        sets = {
            "ADDLO": {"C": co, "Z": z}, "SUBLO": {"C": co, "Z": z},
            "ADCLO": {"C": co, "Z": F["Z"] & z}, "SBCLO": {"C": co, "Z": F["Z"] & z},
            "ADDHI": {"C": co, "Z": F["Z"] & z, "N": n15, "V": ov(0)},
            "SUBHI": {"C": co, "Z": F["Z"] & z, "N": n15, "V": ov(1)},
            "ICLO": {"IC": co}, "ICLOZ": {"IC": co, "Z": z}, "ICSTZ": {"IC": co, "ST": z},
            "LOGLO": {"Z": z}, "LOGHI": {"Z": F["Z"] & z, "N": n15},
            "NZ16": {"N": n15, "Z": z},
            "SHR": {"C": f0, "V": 0}, "SHL": {"C": co, "V": 0},
            "STN": {"ST": n15}, "STZ": {"ST": z}, "STZ32": {"ST": F["ST"] & z},
            "STF0": {"ST": f0}, "STA4": {"ST": f0 | f1}, "STC": {"ST": F["C"]},
            "CNZ": {"C": 1 - z}, "VNZ": {"V": 1 - z}, "ZNZ": {"Z": 1 - z}, "NNZ": {"N": 1 - z},
            "INZ": {"I": 1 - z}, "SETI": {"I": 1}, "CLRI": {"I": 0}, "ENTRY": {"I": 0},
        }.get(name, {})
        return sets.get(flag, F[flag])

    deps = {"N": ["n15", "z"], "Z": ["z"], "C": ["co", "f0", "z"],
            "V": ["a15", "b15", "n15", "z"], "I": ["z"], "IC": ["co"],
            "ST": ["n15", "z", "f0", "f1"]}
    others = {"Z": [], "N": [], "C": [], "V": [], "I": [], "IC": [], "ST": ["C"]}
    outs = {}
    for flag in ("N", "Z", "C", "V", "I", "IC", "ST"):
        dn, on = deps[flag], others[flag]
        nets = fl_ + [ins[k] for k in dn] + [f[flag]] + [f[o] for o in on] + ["HALFD"]

        def fn(*bits, flag=flag, dn=dn, on=on):
            code = sum(b << i for i, b in enumerate(bits[:5]))
            if code not in uc.FL_NAME:
                return None
            name = uc.FL_NAME[code]
            if bits[-1]:
                name = uc.FL_HIGH.get(name, "NONE")
            v = {k: 0 for k in ins}
            for i, k in enumerate(dn):
                v[k] = bits[5 + i]
            F = {k: 0 for k in f}
            F[flag] = bits[5 + len(dn)]
            for i, o in enumerate(on):
                F[o] = bits[6 + len(dn) + i]
            return nextf(flag, name, v, F)
        outs[f[flag]] = (G.table(nets, fn), True, False)
    G.add(nl, "U_FLG", outs, clock="HCK1", ar=RESET)


def register_file(nl, clk):
    """Two 64K x 16 SRAMs, one for the registers' low halves and one for the
    high halves (each modelled as its two bytes, a "pair"), on D. Phase F writes the low pair in tick 1 and the high
    pair in tick 2 (RFWL_n, RFWH_n from the clock generator), the result
    register for each pair on D then (YAOE, YBOE), the pairs a write
    doesn't take kept out by their chip enables. A read takes the half's
    pair (HR, inverted in the high half)."""
    rk, wk = field("RK"), field("WK")
    d, s = bus("IRD", 4), bus("IRS", 4)
    ra, wa = bus("RA", 8), bus("WA", 8)
    phw, phr = lit("PHW"), lit("PHW", 0)
    for g, bits in ((0, (0, 1)), (1, (2, 3))):
        outs = {}
        for i in bits:
            def mux(k):
                # K (bit 5 clear): its bits; d (32) or s (33) by bit 0
                return OR(AND(lit(k[5], 0), lit(k[i])), AND(lit(k[5]), lit(k[0], 0), lit(d[i])),
                          AND(lit(k[5]), lit(k[0]), lit(s[i])))
            outs[ra[i]] = (OR(AND(phw, lit(wa[i])), AND(phr, mux(rk))), False, False)
            outs[wa[i]] = (mux(wk), True, False)
        G.add(nl, f"U_RFA{g}", outs, clock=clk[1])
    rk4 = AND(lit(rk[5], 0), lit(rk[4]))
    wk4 = AND(lit(wk[5], 0), lit(wk[4]))
    G.add(nl, "U_RFA2", {
        "RA4": (OR(AND(phw, lit("WA4")), AND(phr, rk4)), False, False),
        "WA4": (wk4, True, False),
        "RA6": (OR(AND(phw, lit("WA6")), AND(phr, lit("TASK"))), False, False),
        "WA6": (lit("TASK"), True, False),
        "RA7": (OR(AND(phw, lit("WA7")), AND(phr, lit("B"), negate(rk4))), False, False),
        "WA7": (AND(lit("B"), negate(wk4)), True, False),
    }, clock=clk[1])
    wen = negate(AND(lit(wk[5]), lit(wk[4])))         # WK_NONE: 63
    hw = lit("HWQ")
    G.add(nl, "U_RFW", {
        "WENQ": (wen, True, False),
        "WENBQ": (AND(wen, lit("HLZ", 0)), True, False),
        "CE_LO_n": (OR(phr, AND(lit("WENQ"), negate(hw)), AND(lit("WENBQ"), hw)), False, True),
        "CE_HI_n": (OR(phr, AND(lit("WENQ"), hw), AND(lit("WENBQ"), negate(hw))), False, True),
    }, clock=clk[1])
    addr = {f"A{i}": f"RA{i}" for i in range(5)}
    addr.update(A5="RA6", A6="RA7", **{f"A{i}": "GND" for i in range(7, 16)})
    # each pair one 64K x 16 part (its byte enables low): its bytes, U_RFx0 and U_RFx1
    for p, ce, oe, we in (("L", "CE_LO_n", "RFOE_LO_n", "RFWL_n"),
                          ("H", "CE_HI_n", "RFOE_HI_n", "RFWH_n")):
        for k in range(2):
            nl.add("sram64k", f"U_RF{p}{k}", CE=ce, OE=oe, WE=we, **addr,
                   **{f"IO{i}": f"D{8 * k + i}" for i in range(8)})


def aluc_gal(nl):
    """S3-S0, M and the carry in (CN0_n) from the ALU operation, the carry
    sources and ST; in the high half the carry in is HC, the low half's
    carry out (registered here at HCKA); SI, the bit a right shift brings in."""
    aop, sisel = field("AOP"), field("SISEL")

    def resolve(code, st):
        if code not in uc.AOP_NAME:
            return None
        return uc.aop_resolve(uc.AOP_NAME[code], st)
    outs = {}
    for i in range(4):
        outs[f"AS{i}"] = (G.table(aop + ["F_ST"], lambda *b, i=i: None if resolve(
            sum(x << j for j, x in enumerate(b[:5])), b[5]) is None else
            resolve(sum(x << j for j, x in enumerate(b[:5])), b[5])[0] >> i & 1), False, False)
    outs["AM"] = (G.table(aop + ["F_ST"], lambda *b: None if resolve(
        sum(x << j for j, x in enumerate(b[:5])), b[5]) is None else
        resolve(sum(x << j for j, x in enumerate(b[:5])), b[5])[1]), False, False)

    def cin(*b):
        if b[8]:
            return 1 - b[9]                 # the high half: HC
        r = resolve(sum(x << j for j, x in enumerate(b[:5])), b[5])
        if r is None:
            return None
        c = {"0": 0, "1": 1, "C": b[6], "IC": b[7]}[r[2]]
        return 1 - c
    outs["CN0_n"] = (G.table(aop + ["F_ST", "F_C", "F_IC", "HALF", "HC"], cin), False, False)
    outs["SI"] = (OR(AND(eq(sisel, uc.SI_C), lit("F_C")), AND(eq(sisel, uc.SI_D15), lit("D15")),
                     AND(eq(sisel, uc.SI_CO), lit("CO_n", 0))), False, False)
    outs["HC"] = (lit("CO_n", 0), True, False)
    alu = G.add(nl, "U_ALUC", outs, clock="HCKA2")
    # HC's setup matters only to a high half that takes the carry, and the
    # timing analysis gives those low halves their ticks (sta2.carry_used);
    # elsewhere CO_n may still be settling at HCKA, harmlessly
    alu.nocheck = True


def lck_gal(nl):
    """U_LCK, on the master clock: LCKA and LCKB, the operand latch's
    clocks (HCKA and HCKB when the word loads L: LDL); LBOE_n, the high
    half's latch's enable (HALF's complement, registered from the same
    next state as U_CGB's HALF); SREQ, the PCM's request, set as the
    timer's OUT1 rises (TS, synchronised, rising, SARM its last value's
    complement: the DAC's latch has taken the sample) and cleared by the
    sample's write (SDACW), which so comes while OUT1 is high; DREQ, the device task's request: SREQ
    or a PS/2 port's edge (KBD_E, MOUSE_E); TCHG, TASK changed at the
    cycle's start (phase F a tick longer, for the address drivers'
    enables), against TASKP, TASK as the last phase F ended."""
    e, ldl = lit("END"), lit(field("LDL")[0], 0)
    half = OR(AND(ph_is("H"), lit("END", 0)), AND(e, ph_is("L"), lit("HLZ", 0)))
    sdacw = lit("SDACWR_n", 0)
    fend = AND(ph_is("F"), e)
    G.add(nl, "U_LCK", {
        "LCKA": (AND(e, ph_is("L"), ldl), True, False),
        "LCKB": (AND(e, ph_is("H"), ldl), True, False),
        "LBOE_n": (half, True, True),
        "SARM": (AND(lit("RESET_n"), lit("TS", 0)), True, False),
        "SREQ": (AND(lit("RESET_n"), OR(AND(lit("TS"), lit("SARM")),
                                        AND(lit("SREQ"), negate(sdacw)))), True, False),
        "DREQ": (OR(lit("SREQ"), lit("KBD_E"), lit("MOUSE_E")), False, False),
        "TASKP": (OR(AND(fend, lit("TASK")), AND(negate(fend), lit("TASKP"))), True, False),
        "TCHG": (OR(AND(lit("TASK"), lit("TASKP", 0)), AND(lit("TASK", 0), lit("TASKP"))),
                 False, False),
    }, clock="MCLK")


def result_gals(nl):
    rm = field("RM")
    y = {}
    for i in range(8):
        y[f"D{i}"] = (OR(AND(eq(rm, uc.RM_SHR), lit(f"F{i + 1}")),
                         AND(negate(eq(rm, uc.RM_SHR)), lit(f"F{i}"))), True, False, lit("YAOE"))
    G.add(nl, "U_YLO", y, clock="HCKA1")
    y = {}
    for i in range(8, 16):
        nxt_bit = "SI" if i == 15 else f"F{i + 1}"
        y[f"D{i}"] = (OR(AND(eq(rm, uc.RM_PASS), lit(f"F{i}")), AND(eq(rm, uc.RM_SHR), lit(nxt_bit)),
                         AND(eq(rm, uc.RM_SXB), lit("F7"))), True, False, lit("YAOE"))
    G.add(nl, "U_YHI", y, clock="HCKA1")
    # the high half's result: F, or 0 (HX ZERO), or ST's copies (FILL)
    for nm, base in (("U_YBLO", 0), ("U_YBHI", 8)):
        y = {}
        for i in range(base, base + 8):
            y[f"D{i}"] = (OR(AND(eq(HXF, uc.HX_NAT), lit(f"F{i}")),
                             AND(eq(HXF, uc.HX_IMMH), lit(f"F{i}")),
                             AND(eq(HXF, uc.HX_FILL), lit("F_ST"))), True, False, lit("YBOE"))
        G.add(nl, nm, y, clock="HCKB2")
    allz = {f"F{i}": 0 for i in range(16)}
    G.add(nl, "U_ZERO", {
        "Z16": (OR([dict(allz, **{rm[0]: 0, rm[1]: 0})],
                   [dict({f"F{i}": 0 for i in range(1, 16)}, SI=0, **{rm[0]: 1, rm[1]: 0})],
                   [dict({f"F{i}": 0 for i in range(8)}, **{rm[1]: 1})]), False, False),
        "N15": (OR(AND(eq(rm, uc.RM_PASS), lit("F15")), AND(eq(rm, uc.RM_SHR), lit("SI")),
                   AND(eq(rm, uc.RM_SXB), lit("F7"))), False, False),
        "N7": (OR(AND(eq(rm, uc.RM_SHR), lit("F8")), AND(negate(eq(rm, uc.RM_SHR)), lit("F7"))),
               False, False),
    })


def imm_gals(nl):
    """The immediate unit: U_IMML the low half's bits 7-0 (of the register
    byte or a constant), U_IMMH bits 15-8 of either half, U_IMMX the high
    half's bits 7-0; ZH: bits 15-8 zero (a byte read's)."""
    immf = field("IMMF")
    d, s = bus("IRD", 4), bus("IRS", 4)
    names = list(uc.IMMS)
    lo = {}
    for i in range(8):
        terms = []
        for code, name in enumerate(names):
            flo = uc.IMMS[name][0]
            if flo is None:
                continue
            vals = {(dd, ss): flo(dd, ss) >> i & 1 for dd in range(16) for ss in range(16)}
            if all(v == 1 for v in vals.values()):
                terms += eq(immf, code)
                continue
            if all(v == 0 for v in vals.values()):
                continue
            found = False
            for srcn, nets in (("d", d), ("s", s)):
                for j in range(4):
                    for pol in (1, 0):
                        if all(v == (((dd if srcn == "d" else ss) >> j & 1) ^ (1 - pol))
                               for (dd, ss), v in vals.items()):
                            terms += AND(eq(immf, code), lit(nets[j], pol))
                            found = True
                            break
                    if found:
                        break
                if found:
                    break
            assert found, (name, i)
        lo[f"D{i}"] = (merge_codes(terms, immf), False, False, lit("IMMOE"))
    G.add(nl, "U_IMML", lo)

    def hi_bit(name, i, half):
        """A function of (d3, ST) for bit i of the half's high byte (half 0)
        or of the high half's (half 1, bits 0-15)."""
        def f(d3, st):
            dd = d3 << 3
            if half == 0:
                return uc.IMMS[name][0](dd, 0) >> (8 + i) & 1 if uc.IMMS[name][0] else 0
            return uc.imm_value(name, dd, 0, 1, st) >> i & 1
        return f
    hi = {}
    for i in range(8):
        terms = []
        for code, name in enumerate(names):
            for half in (0, 1):
                fn = hi_bit(name, 8 + i if half else i, half)
                for d3 in (0, 1):
                    for st in (0, 1):
                        if fn(d3, st):
                            terms.append({**{immf[k]: code >> k & 1 for k in range(5)},
                                          "HALF": half, d[3]: d3, "F_ST": st})
        hi[f"D{8 + i}"] = (AND(lit("ZH", 0), table_min(terms, immf + ["HALF", d[3], "F_ST"])),
                           False, False, lit("IMMOEH"))
    G.add(nl, "U_IMMH", hi)
    x = {}
    for i in range(8):
        terms = []
        for code, name in enumerate(names):
            fn = hi_bit(name, i, 1)
            for d3 in (0, 1):
                for st in (0, 1):
                    if fn(d3, st):
                        terms.append({**{immf[k]: code >> k & 1 for k in range(5)}, d[3]: d3,
                                      "F_ST": st})
        oe = lit("IMMOEX") if i >= 5 else AND(lit("IMMOEX"), negate(eq(immf, uc.IMM_CODE["Z5"])))
        x[f"D{i}"] = (table_min(terms, immf + [d[3], "F_ST"]), False, False, oe)
    G.add(nl, "U_IMMX", x)


def table_min(terms, nets):
    """The minimal sum of products of these full terms over nets."""
    on = sorted({sum(t[n] << k for k, n in enumerate(nets)) for t in terms})
    return [{nets[k]: v for k, v in t.items()} for t in G.minimise_qm(on, [], len(nets))]


def merge_codes(terms, code_nets):
    groups = {}
    for t in terms:
        rest = tuple(sorted((k, v) for k, v in t.items() if k not in code_nets))
        code = sum(t[n] << i for i, n in enumerate(code_nets))
        groups.setdefault(rest, set()).add(code)
    out = []
    n = len(code_nets)
    for rest, codes in groups.items():
        unused = set(range(1 << n)) - set(range(len(uc.IMMS)))
        for cube in G.minimise(sorted(codes), sorted(unused), n):
            out.append(dict(rest, **{code_nets[i]: v for i, v in cube.items()}))
    return G._tidy(out)


def bus_gals(nl):
    """Who drives D: U_BUS the register file's pairs and the memory's
    transceivers, U_SRC the immediate unit, the readbacks and the flags
    word; and SUPH, a variant's high half (no memory
    access in it)."""
    phr = lit("PHW", 0)
    h, l_ = lit("HALF"), lit("HALF", 0)
    nat = eq(HXF, uc.HX_NAT)
    suph = AND(h, negate(nat))
    keep = OR(l_, nat)                          # the source is DS's

    def dsx(code):
        """D's source is `code` in this half."""
        if code == uc.DS_IMM:
            return OR(AND(keep, ds_is(code)), AND(h, eq(HXF, uc.HX_IMMH)))
        return AND(keep, ds_is(code))
    hr = lit(field("HR")[0])
    sz = lit(SZ)
    mem_ = dsx(uc.DS_MEM)
    wr_ = AND(eq(MOP, uc.MOP_WRM), negate(suph))
    w16, w8 = AND(wr_, lit(SZ, 0)), AND(wr_, sz)
    pair_hi = OR(AND(hr, l_), AND(lit(field("HR")[0], 0), h))
    rf = dsx(uc.DS_RF)
    G.add(nl, "U_BUS", {
        "RFOE_LO_n": (AND(phr, rf, negate(pair_hi)), False, True),
        "RFOE_HI_n": (AND(phr, rf, pair_hi), False, True),
        "XOE0_n": (AND(phr, OR(AND(mem_, lit(SZ, 0)), AND(mem_, lit("A0", 0)), wr_)), False, True),
        "XOE1_n": (AND(phr, OR(AND(mem_, lit(SZ, 0)), w16)), False, True),
        "XOES_n": (AND(phr, OR(AND(mem_, sz, lit("A0")), w8)), False, True),
        "XDIR": (eq(MOP, uc.MOP_WRM), False, False),
        "SUPH": (suph, False, False),
    })
    adr = ds_is(uc.DS_ADR)
    G.add(nl, "U_SRC", {
        "IMMOE": (AND(phr, l_, OR(ds_is(uc.DS_IMM), ds_is(uc.DS_PCH))), False, False),
        "IMMOEH": (AND(phr, OR(dsx(uc.DS_IMM), dsx(uc.DS_PCH), dsx(uc.DS_FLW), AND(mem_, sz),
                               AND(h, nat, adr))), False, False),
        "IMMOEX": (AND(phr, h, OR(dsx(uc.DS_IMM), AND(nat, adr))), False, False),
        "ZH": (AND(mem_, sz), False, False),
        "RBOE_n": (AND(phr, l_, adr), False, True),
        "RBC": (AND(phr, OR(dsx(uc.DS_PCH), AND(h, nat, adr))), False, False),
        "FWOE_n": (AND(phr, dsx(uc.DS_FLW)), False, True),
    })


def address_gals(nl):
    """PC (bits 20-1) and MAR (20-0, and 30 as AIO, the I/O space's select): counters in 22V10s that load from
    the ALU (F) at a half's end (HCK), the low halves' registers in the low
    half and the high halves' in the high; U_ADC decodes this half's
    operations. PC counts at a read there (a fetch: the cycle's last half's)."""
    axp, axm = field("AXP"), field("AXM")
    h, l_ = lit("HALFD"), lit("HALFD", 0)
    atpc = mop_in([uc.MOP_RDP, uc.MOP_FETCH, uc.MOP_PCS])
    notpc = mop_in([m for m in range(8) if m not in (uc.MOP_RDP, uc.MOP_FETCH, uc.MOP_PCS)])
    G.add(nl, "U_ADC", {
        "PCLO": (AND(eq(axp, uc.AXP_LO), l_), False, False),
        "PCHI": (OR(AND(eq(axp, uc.AXP_HI), l_), AND(eq(axp, uc.AXP_LO), h)), False, False),
        "PCINC": (OR(AND(eq(MOP, uc.MOP_RDP), lit("SUPH", 0)),
                     AND(eq(MOP, uc.MOP_FETCH), lit("LASTH"))), False, False),
        "MARLO": (AND(eq(axm, uc.AXM_LO), l_), False, False),
        "MARHI": (OR(AND(eq(axm, uc.AXM_HI), l_), AND(eq(axm, uc.AXM_LO), h)), False, False),
        "MARINC": (eq(axm, uc.AXM_INC), False, False),
        "PCSEL": (AND(lit("PHW", 0), atpc), False, False),
        "MARSEL": (AND(lit("PHW", 0), notpc), False, False),
        "LDIR": (mop_in([uc.MOP_FETCH, uc.MOP_LDIRM]), False, False),
    })
    sel = lit("PCSEL")
    bits = [f"A{i}" for i in range(1, 9)]
    outs = {b: (counter_bit(bits, k, lit("PCINC"), lit("PCLO"), f"F{k + 1}"), True, False, sel)
            for k, b in enumerate(bits)}
    outs["A0"] = (ZERO, False, False, sel)
    outs["PCCO"] = (AND(lit("PCINC"), [{b: 1 for b in bits}]), False, False)
    G.add(nl, "U_PCA", outs, clock="HCK1")
    bits = [f"A{i}" for i in range(9, 16)]
    outs = {b: (counter_bit(bits, k, lit("PCCO"), lit("PCLO"), f"F{9 + k}"), True, False, sel)
            for k, b in enumerate(bits)}
    outs["PCBCO"] = (AND(lit("PCCO"), [{b: 1 for b in bits}]), False, False)
    # HALFD: HALF as the registers loading at a half's end must see it,
    # changing after their clock (HALF from the clock generator changes with it)
    outs["HALFD"] = (AND(lit("HALFD", 0), lit("HLZ", 0)), True, False)
    G.add(nl, "U_PCB", outs, clock="HCK1", ar=RESET)
    bits = [f"A{i}" for i in range(16, 21)]
    outs = {b: (counter_bit(bits, k, lit("PCBCO"), lit("PCHI"), f"F{k}"), True, False, sel)
            for k, b in enumerate(bits)}
    for k, b in enumerate(bits):
        outs[f"D{k}"] = (lit(b), False, False, lit("RBC"))
    G.add(nl, "U_PCC", outs, clock="HCK2")
    sel = lit("MARSEL")
    cbits = [f"A{i}" for i in range(1, 8)]
    outs = {"A0": (OR(AND(lit("MARLO"), lit("F0")), AND(lit("MARLO", 0), lit("A0"))), True, False,
                   sel)}
    for k, b in enumerate(cbits):
        outs[b] = (counter_bit(cbits, k, lit("MARINC"), lit("MARLO"), f"F{k + 1}"), True, False, sel)
    outs["MARACO"] = (AND(lit("MARINC"), [{b: 1 for b in cbits}]), False, False)
    G.add(nl, "U_MARA", outs, clock="HCK2")
    bits = [f"A{i}" for i in range(8, 16)]
    outs = {b: (counter_bit(bits, k, lit("MARACO"), lit("MARLO"), f"F{8 + k}"), True, False, sel)
            for k, b in enumerate(bits)}
    outs["MARBCO"] = (AND(lit("MARACO"), [{b: 1 for b in bits}]), False, False)
    G.add(nl, "U_MARB", outs, clock="HCK3")
    regs = ["A16", "A17", "MAR18", "MAR19", "MAR20"]
    vs = lit("VSEL")
    outs = {}
    for k, b in enumerate(regs):
        outs[b] = (counter_bit(regs, k, lit("MARBCO"), lit("MARHI"), f"F{k}"), True, False,
                   *([sel] if k < 2 else []))
    outs["A18"] = (OR(AND(vs, lit("FB")), AND(lit("VSEL", 0), lit("MAR18"))), False, False,
                   OR(vs, sel))
    outs["A19"] = (OR(vs, lit("MAR19")), False, False, OR(vs, sel))
    outs["A20"] = (OR(vs, lit("MAR20")), False, False, OR(vs, sel))
    outs["AIO"] = (OR(AND(lit("MARHI"), lit("F14")), AND(lit("MARHI", 0), lit("AIO"))), True, False)

    G.add(nl, "U_MARC", outs, clock="HCK4")


def memc_gal(nl):
    """The memory's and the devices' strobes, on the master clock: from a
    half's second tick to its end (END), the RAM's write enables; from its
    third (IOQ), IORD_n and IOWR_n; the RAM's output enable (the video's
    read in phase F, the CPU's in a half); IOACC, an access to the I/O
    space (a half of five ticks); ADS, the UARTs' address strobe. Row 1's
    chip enable is U_NG's, row 0's A20."""
    half = lit("PHW", 0)
    on = AND(half, lit("END", 0), lit("SUPH", 0))
    write = eq(MOP, uc.MOP_WRM)
    rdm = mop_in([uc.MOP_RDM, uc.MOP_LDIRM])
    ram_w = AND(on, write, lit("AIO", 0))
    outs = {
        "WEL_n": (AND(ram_w, lit("A0", 0)), True, True),
        "WEH_n": (OR(AND(ram_w, lit(SZ, 0), lit("A0", 0)), AND(ram_w, lit(SZ), lit("A0"))), True,
                  True),
        "IORD_n": (AND(on, rdm, lit("AIO"), lit("IOQ")), True, True),
        "IOWR_n": (AND(on, write, lit("AIO"), lit("IOQ")), True, True),
        "RAMOE_n": (OR(lit("VRD"),
                       AND(half, eq(MOP, uc.MOP_RDP), lit("SUPH", 0)),
                       AND(half, eq(MOP, uc.MOP_FETCH), lit("LASTH")),
                       AND(half, rdm, lit("AIO", 0), lit("SUPH", 0))), False, True),
        "IOACC": (AND(half, OR(rdm, write), lit("AIO"), lit("SUPH", 0)), False, False),
        # the UARTs' address strobe: the strobes a tick late, so that the
        # UARTs hold their address and chip select from a tick into the
        # strobe to a tick after it (the address bus changes as it ends)
        "ADS": (OR(lit("IORD_n", 0), lit("IOWR_n", 0)), True, False),
        # IOACC a tick late: the I/O strobes and U_SLOW wait for it, so that
        # the selects, decoded from the address bus, have settled
        "IOQ": (lit("IOACC"), True, False),
    }
    G.add(nl, "U_MEMC", outs, clock="MCLK", ar=RESET)


def io(nl, sim, halt_ps=0):
    """The I/O space (system2.py has the map: U_IODEC decodes AIO, MAR20,
    A16 and A14-A12), draft.py's devices with the
    clock generator's timing: the UARTs, the boot flash, the slow devices
    (the timer, the CF card, the palette) behind U_SLOW's wait states, the
    interrupt controller, ODT's hooks, the scanline and the PS/2 ports; the
    PCM's DAC; the logic analyser's headers."""
    def slot(v):
        """A device's 4 KB in the top 64 KB (A20 and A16 set): by A14-A12,
        from the address bus (settled a tick into the half, and the I/O
        strobes start a tick later)."""
        return AND(lit("AIO"), lit("RESET_n"), lit("MAR20"), lit("A16"),
                   eq(["A12", "A13", "A14"], v))
    G.add(nl, "U_IODEC", {
        "CONSEL_n": (slot(7), False, True), "U0CS_n": (slot(6), False, True),
        "IRQCS": (slot(5), False, False), "VCCS": (slot(4), False, False),
        "PS2CS": (slot(3), False, False), "SLOWCS": (slot(2), False, False),
        "U1CS_n": (slot(1), False, True),
        "FLCS_n": (AND(lit("AIO"), lit("RESET_n"), lit("MAR20", 0)), False, True),
        "PBWR_n": (AND(slot(4), lit("A1"), lit("IOWR_n", 0)), False, True),
        # the copper's target line's register (U_LCMP), written at +6
        "LSWR_n": (AND(slot(5), lit("A2"), lit("A1"), lit("IOWR_n", 0)), False, True),
    })
    for k in range(2):
        nl.add("16c550x", f"U_UART{k}", CS0="VCC", CS1="VCC", CS2=f"U{k}CS_n", ADS="ADS",
               RD="IORD_n",
               WR="IOWR_n", MR="RESET", XIN="UCLK", INTR=f"U{k}INT", SOUT=f"U{k}TX",
               SIN=f"U{k}RX", RTS=f"U{k}RTS", CTS=f"U{k}CTS",
               **{f"D{i}": f"MD{i}" for i in range(8)}, **{f"A{i}": f"A{i + 1}" for i in range(3)})
        sig = ("TX", "RTS", "RX", "CTS")
        nl.add("jmp4", f"J_SER{k}", **{f"A{i}": f"U{k}{s}" for i, s in enumerate(sig)},
               **{f"B{i}": f"U{k}{s}J" for i, s in enumerate(sig)})
        nl.add("ftdi6", f"J_TTL{k}", TXD=f"U{k}TX", RXD=f"U{k}RX", RTS=f"U{k}RTS", CTS=f"U{k}CTS")
        nl.add("max232", f"U_RS{k}", T1IN=f"U{k}TXJ", T2IN=f"U{k}RTSJ", R1OUT=f"U{k}RXJ",
               R2OUT=f"U{k}CTSJ", T1OUT=f"P{k}TXD", T2OUT=f"P{k}RTS", R1IN=f"P{k}RXD",
               R2IN=f"P{k}CTS")
        nl.add("conn", f"J_DB9{k}", P0=f"P{k}TXD", P1=f"P{k}RTS", P2=f"P{k}RXD", P3=f"P{k}CTS",
               part="DE-9 male")
        nl.add("pullup", f"R_U{k}", P1=f"U{k}RX", P2=f"U{k}CTS")
    nl.add("flash", "U_BOOT", CE="FLCS_n", OE="IORD_n", WE="IOWR_n", part="SST39SF010A-55",
           **{f"A{i}": f"A{i + 1}" for i in range(17)}, **{f"D{i}": f"MD{i}" for i in range(8)})
    if sim:
        nl.add("osc", "X_UCLK", OUT="UCLK", params={"period_ps": UCLK_PS, "phase_ps": 1000})
        w = nl.add("wire", "X_IORDW", A="IORD_n", Y="IORD_X")
        w.add_pin_delay("Y", 10000)
        # (a read takes its byte as its strobe ends: two reads a cycle)
        nl.add("iodev32", "X_IO", CLK="CLK3", IOSEL="CONSEL_n", RD="IORD_X", WEL="IOWR_n",
               WEH="VCC", IRQ="CONIRQ", params={"read_at_strobe": 1},
               **{f"A{i}": f"A{i}" for i in range(8)}, **{f"D{i}": f"MD{i}" for i in range(16)})
        nl.add("ps2dev", "X_KBD", CLK="KCLK", DATA="KDATA", WAKE="KWAKE",
               params={"half_ps": 40_000_000, "gap_ps": 200_000_000, "start_ps": 50_000_000})
        nl.add("ps2dev", "X_MOUSE", CLK="MSCLK", DATA="MSDATA", WAKE="MWAKE",
               params={"half_ps": 40_000_000, "gap_ps": 200_000_000, "start_ps": 70_000_000})
        nl.add("button", "S_BTNX", OUT="BTN_n")
        if halt_ps:
            # the halt button, held through reset to halt_ps: ODT from the start
            nl.add("button", "S_HLTXA", OUT="HLTA_n", params={"press_ps": 1, "release_ps": halt_ps})
            nl.add("button", "S_HLTXB", OUT="HLTB_n", params={"press_ps": halt_ps + 1000})
    else:
        nl.add("const", "X_IOK", LO="CONIRQ", HI="UCLK")
        nl.add("const", "X_BTN", LO="BTNLO", HI="BTN_n")
    slow_devices(nl)
    interrupts(nl)
    odt(nl)
    scanline(nl)
    draft.ps2(nl, spare={"5A": "RESET_n", "5Y": "RESET", "6A": "GND"})
    sound(nl)
    debug(nl)


# the slow devices' timing in ticks from a half's second (U_SLOW counts
# from IOQ, once the select has settled): (the address before the strobe,
# the write strobe, the access's end for a read, for a write). A read's
# strobe lasts to the half's end, when the CPU takes the data; a write's
# ends a tick before it, for the data's hold. The half lasts end + 2 ticks.
SLOW = {"cf0": (3, 9, 30, 30),          # PIO mode 0, at boot (the display off): 600 ns
        "cf4": (1, 4, 6, 6),            # PIO mode 4: 25, 70, 10 ns; 120 ns a cycle
        "other": (2, 6, 9, 9)}          # the 82C54 (its tAR, 25 ns) and the RAMDAC


def slow_devices(nl):
    """U_SLOW counts an access's ticks in its half (W) until SDONE, at the
    device's length (the CF card's by CFFAST: PIO 0 until the boot sets
    PIO 4); HOLD holds the half until then; SRD_n and SWR_n are the
    strobes, CFOE_n the CF card's buffers (74ABT245s, quick to let go of
    MD). By A6-A4: 000 the timer, 001 the palette, 010 the PCM's sample
    latch (U_PCM), 011 CFFAST (bit 0); A6 set, the CF card: A5 0 its
    command block, 1 its control block."""
    w = bus("W", 5)
    acc = AND(lit("SLOWCS"), lit("IOACC"), lit("IOQ"))
    cf = lit("A6")

    def kind(a6, a5, a4, fast):
        if a6:
            return "cf4" if fast else "cf0"
        return "other"
    knets = ["A6", "A5", "A4", "CFFAST"]
    wn = w + knets + ["XDIR", "SDONE"]

    def tab(f):
        def g(*b):
            ww = sum(x << i for i, x in enumerate(b[:5]))
            su, st, end_r, end_w = SLOW[kind(*b[5:9])]
            return f(ww, su, st, end_r, end_w, b[9], b[10])
        return AND(acc, G.table(wn, g))
    outs = {}
    for i in range(5):
        outs[w[i]] = (AND(acc, lit("SDONE", 0), draft._inc(w, i)), True, False)
    outs["SDONE"] = (tab(lambda ww, su, st, er, ew, wr, done:
                         done or ww == (ew if wr else er) - 1), True, False)
    outs["HOLD"] = (AND(acc, lit("SDONE", 0)), False, False)
    outs["SRD_n"] = (tab(lambda ww, su, st, er, ew, wr, done: not wr and not done and ww >= su - 1),
                     True, True)
    outs["SWR_n"] = (tab(lambda ww, su, st, er, ew, wr, done:
                         wr and not done and su - 1 <= ww < su + st - 1), True, True)
    outs["CFOE_n"] = (AND(acc, cf, lit("SDONE", 0)), True, True)
    G.add(nl, "U_SLOW", outs, clock="MCLK", ar=RESET)
    dev = {"TMR": (0, 0, 0), "DAC": (0, 0, 1), "SDAC": (0, 1, 0), "CF0": (1, 0, None),
           "CF1": (1, 1, None)}

    def is_(name):
        a6, a5, a4 = dev[name]
        return AND(lit("SLOWCS"), lit("A6", a6), lit("A5", a5), lit("A4", a4) if a4 is not None
                   else ONE)
    ff = AND(lit("SLOWCS"), lit("A6", 0), lit("A5"), lit("A4"))
    G.add(nl, "U_SLOWD", {
        "TMRCS_n": (is_("TMR"), False, True),
        "CFCS0_n": (is_("CF0"), False, True),
        "CFCS1_n": (is_("CF1"), False, True),
        "CFRD_n": (AND(cf, lit("SLOWCS"), lit("SRD_n", 0)), False, True),
        "CFWR_n": (AND(cf, lit("SLOWCS"), lit("SWR_n", 0)), False, True),
        "DACRD_n": (AND(is_("DAC"), lit("SRD_n", 0)), False, True),
        "DACWR_n": (AND(is_("DAC"), lit("SWR_n", 0)), False, True),
        "SDACWR_n": (AND(is_("SDAC"), lit("SWR_n", 0)), False, True),
        "CFFAST": (OR(AND(ff, lit("MD0")), AND(negate(ff), lit("CFFAST"))), True, False),
    }, clock="IOWR_n", ar=RESET)
    nl.add("82c54", "U_TMR", CS="TMRCS_n", RD="SRD_n", WR="SWR_n", A0="A1", A1="A2",
           CLK0="UCLK", CLK1="UCLK", CLK2="UCLK", GATE0="VCC", GATE1="VCC", GATE2="VCC",
           OUT0="TIRQ", OUT1="TOUT1", OUT2="SPK", **{f"D{i}": f"MD{i}" for i in range(8)})
    for k in range(2):
        nl.add("245", f"U_CFD{k}", DIR="XDIR", OE="CFOE_n", part="74ABT245",
               **{f"A{i + 1}": f"MD{8 * k + i}" for i in range(8)},
               **{f"B{i + 1}": f"CFB{8 * k + i}" for i in range(8)})
        nl.add("rser8", f"R_CFD{k}", **{f"A{i}": f"CFB{8 * k + i}" for i in range(8)},
               **{f"B{i}": f"CFD{8 * k + i}" for i in range(8)}, part="33 ohm x 8")
    ctl = ["A1", "A2", "A3", "CFCS0_n", "CFCS1_n", "CFRD_n", "CFWR_n", "RESET_n"]
    nl.add("541", "U_CFA", OE1="GND", OE2="GND", part="74HCT541",
           **{f"A{i + 1}": n for i, n in enumerate(ctl)},
           **{f"Y{i + 1}": f"CFX{i}" for i in range(8)})
    nl.add("rser8", "R_CFA", **{f"A{i}": f"CFX{i}" for i in range(8)},
           **{f"B{i}": f"CFY{i}" for i in range(8)}, part="33 ohm x 8")
    nl.add("cf", "J_CF", A0="CFY0", A1="CFY1", A2="CFY2", CS0="CFY3", CS1="CFY4",
           IORD="CFY5", IOWR="CFY6", RESET="CFY7", INTRQ="CFIRQ", WAKE="CFWAKE",
           **{f"D{i}": f"CFD{i}" for i in range(16)})
    nl.add("g171", "U_DAC", RS0="A1", RS1="A2", RD="DACRD_n", WR="DACWR_n", PCLK="PIX",
           BLANK="VBLANK_n", IOR="VGA_R", IOG="VGA_G", IOB="VGA_B",
           **{f"P{i}": f"PX{i}" if i < 4 else f"PB{i - 4}" for i in range(8)},
           **{f"D{i}": f"MD{i}" for i in range(8)})
    nl.add("conn", "J_VGA", P0="VGA_R", P1="VGA_G", P2="VGA_B", P3="HS_n",
           part="DE-15 (VGA) with its sync resistors")


SOURCES = ["TIRQ", "VIRQ", "U0INT", "U1INT", "KIRQ", "MIRQ", "CFIRQ", "BTNQ"]   # by priority


def interrupts(nl):
    """U_IRQ: IRQ (the sources' OR and the fixture's), the sources' status at
    +0, the vector at +2 (0x40 + 4 x the first source pending, or 0x04),
    MD7-0 zero at +4 (beside ODT's MD15-8); BTNQ the button's latch."""
    rd = AND(lit("IRQCS"), lit("IORD_n", 0), lit("A2", 0))
    rd4 = AND(lit("IRQCS"), lit("IORD_n", 0), lit("A2"), lit("A1", 0))     # MD7-0 0 there
    outs = {"IRQ": (OR(*[lit(s) for s in SOURCES[:-1]], lit("BTNQ"), lit("CONIRQ")), False, False)}
    first = []
    for k, s in enumerate(SOURCES):
        first.append(AND(*[lit(x, 0) for x in SOURCES[:k]], lit(s)))
    none = AND(*[lit(x, 0) for x in SOURCES])
    for i in range(8):
        status = lit(SOURCES[i])
        if i == 6:
            vec = negate(none)
        elif 2 <= i <= 4:
            vec = OR(*[first[k] for k in range(8) if (k >> (i - 2)) & 1], none if i == 2 else ZERO)
        else:
            vec = ZERO
        outs[f"MD{i}"] = (AND(lit("A2", 0), OR(AND(lit("A1", 0), status), AND(lit("A1"), vec))),
                          False, False, OR(rd, rd4))
    G.add(nl, "U_IRQ", outs)
    nl.add("conn", "S_BTN", P0="BTN_n", P1="RESET_n", part="push buttons: interrupt, reset")


def odt(nl):
    """ODT's hooks: U_ODT latches the halt button (an SPDT's two contacts:
    HLTQ); TRACE (U_VC's) is written at the controller's +4, MD0, the write
    clearing the button's latch too: both ask for ODT (ODTQ, U_SYS's), which
    the I flag doesn't mask. At +4, MD15-8 read 0x90 when ODT is asked for
    (OP 00, N 9 once loaded with MOP_LDIRM: ODT's blocks), else 0, and
    MD7-0 0; the interrupt button's latch BTNQ, cleared by a write at +0."""
    wr = AND(lit("IRQCS"), lit("A2"), lit("A1", 0), lit("IOWR_n", 0))
    rd = AND(lit("IRQCS"), lit("A2"), lit("A1", 0), lit("IORD_n", 0))
    wr0 = AND(lit("IRQCS"), lit("A2", 0), lit("IOWR_n", 0))
    outs = {
        "HLTQ": (OR(lit("HLTA_n", 0), AND(lit("HLTQ"), lit("HLTB_n", 0), negate(wr),
                                         lit("RESET_n"))), False, False),
        "BTNQ": (OR(lit("BTN_n", 0), AND(lit("BTNQ"), negate(wr0), lit("RESET_n"))), False, False),
    }
    for i in range(8):
        outs[f"MD{8 + i}"] = (OR(lit("HLTQ"), lit("TRACE")) if i in (4, 7) else ZERO, False,
                              False, rd)
    G.add(nl, "U_ODT", outs)
    nl.add("pullup", "R_HLT", P1="HLTA_n", P2="HLTB_n", P3="BTN_n")
    nl.add("conn", "S_HLT", P0="HLTA_n", P1="HLTB_n", part="push button (SPDT): halt to ODT")


def scanline(nl):
    """The scanline: U_LINE counts the lines as U_VV does, LN8-LN0, read at
    the controller's +6 (LN7-LN0 through U_LRB, LN8 from U_LINE). U_LCMP
    (a 574, on LSWR_n) holds the copper's target line's bits 7-0 (written
    at +6, MD7-0), U_LREQ its bit 8 (TL8, MD8) and, with the 74HCT688's
    match, asks for the task (COPREQ) for the whole target line if the
    copper is on (CEN, MD15 of that write)."""
    l = bus("LN", 9)
    rd = AND(lit("IRQCS"), lit("A2"), lit("A1"), lit("IORD_n", 0))
    outs = {l[k]: (draft._inc(l, k), True, False) for k in range(9)}
    outs["MD8"] = (lit("LN8"), False, False, rd)
    G.add(nl, "U_LINE", outs, clock="HS_n", ar=AND(lit("VBL"), eq(l, 13)))
    nl.add("541", "U_LRB", OE1="LRB_n", OE2="LRB_n",
           **{f"A{i + 1}": f"LN{i}" for i in range(8)}, **{f"Y{i + 1}": f"MD{i}" for i in range(8)})
    nl.add("574", "U_LCMP", CLK="LSWR_n", OE="GND",
           **{f"D{i + 1}": f"MD{i}" for i in range(8)}, **{f"Q{i + 1}": f"TL{i}" for i in range(8)})
    wsel = AND(lit("IRQCS"), lit("A2"), lit("A1"))
    nl.add("688", "U_LEQ", G="GND", **{f"P{i}": f"LN{i}" for i in range(8)},
           **{f"Q{i}": f"TL{i}" for i in range(8)}, PEQ="LEQ_n", part="74HCT688")
    G.add(nl, "U_LREQ", {
        "COPREQ": (AND(lit("CEN"), lit("LEQ_n", 0), OR(AND(lit("LN8"), lit("TL8")),
                                                       AND(lit("LN8", 0), lit("TL8", 0)))),
                   False, False),
        "LRB_n": (rd, False, True),
        "CEN": (OR(AND(wsel, lit("MD15")), AND(negate(wsel), lit("CEN"))), True, False),
        "TL8": (OR(AND(wsel, lit("MD8")), AND(negate(wsel), lit("TL8"))), True, False),
        # the sequencer's: TASK a stage later, and either
        "TASKD": (lit("TASK"), False, False),
        "TASKOR": (OR(lit("TASK"), lit("TASKD")), False, False),
    }, clock="IOWR_n", ar=RESET)
    nl.add("175", "U_PB", CLK="PBWR_n", CLR="RESET_n", part="74HCT175",
           **{f"{i + 1}D": f"MD{i}" for i in range(4)}, **{f"{i + 1}Q": f"PB{i}" for i in range(4)})


def sound(nl):
    """PCM through a DAC0832 (an 8-bit DAC with two latches) and an op-amp.
    The device task (routines2.device) writes each sample to U_PCM, a
    574, at the slow devices' 0x20 (SDACWR_n); the DAC's input latch is
    open, and its DAC latch takes U_PCM's sample on the timer's OUT1
    (counter 1 in mode 3, a square wave at the sample rate): open while
    OUT1 is low, held while it's high. The task writes in the high half
    (SREQ, U_LCK's, rises with OUT1), so the sample comes out as OUT1
    falls, at the timer's steady rate however late the task wrote it, and
    WR2's low half is far longer than the DAC's 900 ns. The DAC in voltage
    mode (the reference on IOUT1, the output at VREF), one of the
    MCP6002's op-amps giving it the reference and the other buffering its
    output; the analog side is a sketch (open)."""
    nl.add("574", "U_PCM", CLK="SDACWR_n", OE="GND",
           **{f"D{i + 1}": f"MD{i}" for i in range(8)},
           **{f"Q{i + 1}": f"SDQ{i}" for i in range(8)})
    nl.add("dac0832", "U_SDAC", CLK="TOUT1", VREFIN="SREF", VOUT="SDACV",
           **{f"D{i + 1}": f"SDQ{i}" for i in range(8)},
           **{f"Q{i + 1}": f"SND{i}" for i in range(8)})
    nl.add("mcp6002", "U_SAMP", REF="SREF", DIV="SDIV", IN="SDACV", OUT="SND")
    nl.add("conn", "J_SND", P0="SND", P1="SDIV", P2="SPK",
           part="3.5 mm jack, the reference's divider, the mixing resistors (the timer's "
                "OUT2 as a beeper too)")


DEBUG = [
    [f"UPC{i}" for i in range(uc.ADDR_BITS)] + ["CLK0", "LDIR", "TASK"],
    [f"IRD{i}" for i in range(4)] + ["HALF", "PHW"] + [f"F_{f}" for f in ("N", "Z", "C", "V", "I",
                                                                           "IC", "ST")]
    + ["IRQP", "AIO", "HCK"],
    [f"D{i}" for i in range(16)],
]


def debug(nl):
    """Three 32-pin headers for a Saleae Logic Pro 16 or any analyser with
    flying leads, through 100-ohm resistors."""
    for h, sigs in enumerate(DEBUG):
        for k in range(2):
            nl.add("rser8", f"R_LA{h}{k}", **{f"A{i}": sigs[8 * k + i] for i in range(8)},
                   **{f"B{i}": f"LA{h}_{8 * k + i}" for i in range(8)}, part="100 ohm x 8")
        nl.add("hdr32", f"J_LA{h}", **{f"S{i}": f"LA{h}_{i}" for i in range(16)})


def video(nl, clk):
    """640 x 480 x 4 at 60 Hz, decoupled from the CPU's cycle. U_VQ divides
    the master clock by 8 (VT: a word of 4 pixels a 8 ticks; PIX, the pixel
    clock, is VT0's complement, WCLK VT2's) and keeps a two-word buffer: A
    (U_VA0, U_VA1) loads from MD at a video read, B (U_VB0, U_VB1) from A
    when it's empty or the shifter takes its word, at a word's end, while
    the line is shown (VDISP). The reads: in phase F's ticks 1-2, and 3-4
    when the clock generator lengthens it because the buffer is empty
    (VEXT), while U_VF's fetch counter hasn't reached the line's 160 words;
    U_VF drives A8-A1 then, U_VV (the line) A17-A9, U_MARC A20-A18 (the
    frame buffer FB). U_VH counts the words shown (0-199; HSYNC at 164-187)."""
    tc = ["TC0", "TC1", "TC2"]
    inf = ph_is("F")
    tcv = {v: eq(tc, v) for v in range(8)}
    slot = AND(inf, OR(tcv[1], tcv[2], AND(lit("VEXTQ"), OR(tcv[3], tcv[4]))))
    first = AND(inf, OR(tcv[1], AND(lit("VEXTQ"), tcv[3])))
    fon = lit("FETCH_ON")
    vt7 = AND(lit("PIX", 0), lit("VT1"), lit("WCLK", 0))          # VT = 7
    consume = AND(vt7, lit("VDISP"))
    av, bv = lit("AV"), lit("BV")
    moves = AND(av, OR(lit("BV", 0), consume))
    load = AND(first, fon, OR(lit("AV", 0), moves))
    vt0 = lit("PIX", 0)
    outs = {"PIX": (lit("PIX", 0), True, False),
            "VT1": (OR(AND(lit("VT1"), lit("PIX")), AND(lit("VT1", 0), vt0)), True, False),
            "WCLK": (OR(AND(lit("WCLK"), negate(AND(lit("VT1"), vt0))),
                        AND(lit("WCLK", 0), lit("VT1"), vt0)), True, False)}
    outs["AV"] = (OR(AND(av, negate(moves)), load), True, False)
    outs["BV"] = (OR(AND(bv, negate(consume)), moves), True, False)
    outs["VCK"] = (load, True, False)
    outs["BCK"] = (moves, True, False)
    outs["VEXT"] = (AND(lit("AV", 0), lit("BV", 0), fon), False, False)
    outs["VRD"] = (AND(slot, fon), False, False)
    outs["VUF"] = (AND(consume, lit("BV", 0)), False, False)
    G.add(nl, "U_VQ", outs, clock="MCLK", ar=RESET)
    for k in range(2):
        nl.add("574", f"U_VA{k}", CLK="VCK", OE="GND",
               **{f"D{i + 1}": f"MD{8 * k + i}" for i in range(8)},
               **{f"Q{i + 1}": f"VA{8 * k + i}" for i in range(8)})
        nl.add("574", f"U_VB{k}", CLK="BCK", OE="GND",
               **{f"D{i + 1}": f"VA{8 * k + i}" for i in range(8)},
               **{f"Q{i + 1}": f"VD{8 * k + i}" for i in range(8)})
    # the fetch counter: the line's next word; cleared in HSYNC
    fc = bus("A", 8, 1)
    outs = {fc[k]: (toggle(fc, k, ONE), True, False, lit("VSEL")) for k in range(8)}
    outs["FETCH_ON"] = (AND(lit("FDONE", 0), lit("VBL", 0), lit("DEN")), False, False)
    outs["FDONE"] = (OR(lit("FDONE"), eq(fc, 159)), True, False)       # the 160th word
    G.add(nl, "U_VF", outs, clock="VCK", ar=lit("HS_n", 0))
    h = bus("H", 8)
    outs = {}
    for k in range(8):
        outs[h[k]] = (toggle(h, k, ONE), True, False)
    outs["HS_n"] = (G.table(h, lambda *b: (sum(x << i for i, x in enumerate(b)) + 1) in
                            range(164, 188)), True, True)
    outs["VDISP"] = (AND(OR(lit(h[7], 0), AND(lit(h[6], 0), lit(h[5], 0))), lit("VBL", 0),
                         lit("DEN")), False, False)
    G.add(nl, "U_VH", outs, clock="WCLK", ar=eq(h, 200))
    v = bus("A", 9, 9)
    outs = {v[k]: (toggle(v, k, ONE), True, False, lit("VSEL")) for k in range(9)}
    outs["VBL"] = (OR(lit("VBL"), eq(v, 479)), True, False)
    G.add(nl, "U_VV", outs, clock="HS_n", ar=AND(lit("VBL"), eq(v, 13)))
    # the CPU's side: U_VC, on IOWR_n, the control register (FB, DEN, VIE at
    # +0) and TRACE (the interrupt controller's +4, MD0; ODT's); VACK takes
    # VSET at a write of the control register. U_VS, on HSYNC: VCNT counts
    # the blank's lines, VSYNC at its 11th and 12th; VSET toggles at the
    # blank's start if VIE and no frame interrupt is pending; VIRQ is
    # pending while VSET and VACK differ
    vw = AND(lit("VCCS"), lit("A1", 0))
    tw = AND(lit("IRQCS"), lit("A2"), lit("A1", 0))
    outs = {"VACK": (OR(AND(vw, lit("VSET")), AND(negate(vw), lit("VACK"))), True, False),
            "TRACE": (OR(AND(tw, lit("MD0")), AND(negate(tw), lit("TRACE"))), True, False)}
    for q, bit in (("FB", "MD0"), ("DEN", "MD1"), ("VIE", "MD2")):
        outs[q] = (OR(AND(vw, lit(bit)), AND(negate(vw), lit(q))), True, False)
    G.add(nl, "U_VC", outs, clock="IOWR_n", ar=RESET)
    c = bus("VCNT", 4)
    sat = [{b: 1 for b in c}]
    outs = {c[k]: (AND(lit("VBL"), OR(AND(negate(sat), toggle(c, k, ONE)), AND(sat, lit(c[k])))),
                   True, False) for k in range(4)}
    outs["VS_n"] = (AND(lit("VBL"), OR(eq(c, 9), eq(c, 10))), True, True)
    pending = OR(AND(lit("VSET"), lit("VACK", 0)), AND(lit("VSET", 0), lit("VACK")))
    start = AND(lit("VIE"), lit("VBL"), eq(c, 0), negate(pending))
    outs["VSET"] = (OR(AND(start, lit("VSET", 0)), AND(negate(start), lit("VSET"))), True, False)
    outs["VIRQ"] = (pending, False, False)
    G.add(nl, "U_VS", outs, clock="HS_n", ar=RESET)
    # the shifter: SB the word's high byte, PX its low, shifting 4 bits a pixel;
    # loads from the buffer's B at a word's end (VT 7: WCLK low and VT1)
    sb = bus("SB", 8)
    sa = bus("PX", 8)
    ld = lit("LD")
    outs = {"LD": (AND(lit("WCLK", 0), lit("VT1")), False, False)}
    for k in range(8):
        nxt = lit(sb[k + 4]) if k < 4 else ZERO
        outs[sb[k]] = (OR(AND(ld, lit(f"VD{8 + k}")), AND(negate(ld), nxt)), True, False)
    outs["VBLANK_n"] = (OR(AND(ld, lit("VDISP")), AND(negate(ld), lit("VBLANK_n"))), True, False)
    G.add(nl, "U_SHB", outs, clock="PIX")
    outs = {}
    for k in range(8):
        nxt = lit(sa[k + 4]) if k < 4 else lit(sb[k - 4])
        outs[sa[k]] = (OR(AND(ld, lit(f"VD{k}")), AND(negate(ld), nxt)), True, False)
    G.add(nl, "U_SHA", outs, clock="PIX")
