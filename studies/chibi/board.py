"""Chibi Heron's chip-level netlist: CPU, memory, video, UARTs, PS/2, boot
flash, on one board.

    build(sim=True)    for the chip-level simulator: the oscillators, the
                       power-on reset, the suite's I/O page (a fixture) and
                       a keyboard and mouse on the PS/2 ports
    build(sim=False)   for static timing analysis: the clock generator
                       replaced by a fixture that gives its phases as
                       functions of the period (sta.py)

Nets: D15-D0 the CPU's internal bus; MD15-MD0 the memory's data bus (the
RAM, the devices); A20-A0 and A31 the address bus; F15-F0 the ALU's
output; L15-L0 the operand latch; uXXn the control store's outputs (field
XX, bit n). The clock generator's phases (CK): CLK rises at tick 0 of
eight; PHW, phase W, is ticks 0-2; CLKW rises at tick 3, when PC and MAR
load; RWS, the register file's write strobe, is tick 1; PIX is the pixel
clock (every other tick) and VLD the video's load (ticks 1-2).
"""

from heron.infra.hw import gal as G
from heron.infra.hw.netlist import Netlist

from . import parts, ucode as uc  # noqa: F401  (parts registers the variant)

ZERO, ONE = G.ZERO, G.ONE
AND, OR = G.AND, G.OR

TICK_PS = 19860                 # 50.35 MHz, twice VGA's pixel clock


def lit(n, v=1):
    return [{n: v}]


def eq(nets, value):
    """The product term: the nets (low bit first) hold value."""
    return [{n: (value >> i) & 1 for i, n in enumerate(nets)}]


def anyof(nets, values, width=None):
    """A sum of products true when the nets hold any of the values."""
    used = range(1 << len(nets))
    return G.when(nets, list(values), used) if values else ZERO


def bus(name, n, start=0):
    return [f"{name}{i}" for i in range(start, start + n)]


def field(name):
    """A control field's nets, low bit first."""
    b, w, _ = uc._pos[name]
    suffix = "_n" if name in uc.INVERTED else ""
    return [f"u{name}{i}{suffix}" if w > 1 else f"u{name}{suffix}" for i in range(w)]


def control_nets():
    """Control word bit -> net."""
    out = {}
    for name, (b, w, _) in uc._pos.items():
        for i, n in enumerate(field(name)):
            out[b + i] = n
    for b in range(uc.WORD_BITS):
        out.setdefault(b, f"uNC{b}")
    return out


MOP = field("MOP")
DS = field("DS")


def mop_in(codes):
    return anyof(MOP, codes)


def ds_is(code):
    return eq(DS, code)


def toggle(bits, i, en):
    """Bit i of a counter over `bits` (low first) counting when en (a sum
    of products) holds: the next value when counting, as a sum of products."""
    q = bits[i]
    lower = bits[:i]
    stay = AND(en, lit(q, 1), OR(*[lit(b, 0) for b in lower])) if lower else ZERO
    flip = AND(en, lit(q, 0), [{b: 1 for b in lower}] if lower else ONE)
    return OR(stay, flip)


def counter_bit(bits, i, count, load=None, data=None):
    """A counter bit: loads `data` (a net) when `load` (one literal), else
    counts when `count` (one literal), else holds."""
    q = bits[i]
    if load is None:
        return OR(toggle(bits, i, count), AND(negate(count), lit(q)))
    nload = negate(load)
    return OR(AND(load, lit(data)), AND(nload, toggle(bits, i, count)),
              AND(nload, negate(count), lit(q)))


def negate(sop):
    """The complement of a sum of products of a few literals."""
    if sop == ONE:
        return ZERO
    if sop == ZERO:
        return ONE
    out = ONE
    for t in sop:
        out = AND(out, OR(*[lit(n, 1 - v) for n, v in t.items()]))
    return out


def build(sim=True):
    nl = Netlist()
    cw = control_nets()
    nl.add("const", "X_RAIL", LO="GND", HI="VCC")

    # ---- clock and reset -------------------------------------------------
    nl.section("clock")
    T = ["T0", "T1", "T2"]
    if sim:
        nl.add("osc", "X_OSC", OUT="MCLK", params={"period_ps": TICK_PS, "phase_ps": 7000})
        nl.add("por", "U_POR", RST="RESET_n", params={"release_ps": 3_000_000})
        nl.add("pullup", "R_PU1", P1="RESET_n")

        def nxt(f):
            return G.table(T, lambda t0, t1, t2: f((t0 | t1 << 1 | t2 << 2) + 1 & 7))
        G.add(nl, "U_CK", {
            "T0": (lit("T0", 0), True, False),
            "T1": (OR(AND(lit("T1", 1), lit("T0", 0)), AND(lit("T1", 0), lit("T0", 1))), True,
                   False),
            "T2": (G.table(T, lambda a, b, c: c ^ (a & b)), True, False),
            "CLK0": (nxt(lambda k: k < 4), True, False),
            "PHW": (nxt(lambda k: k < 3), True, False),
            "CLKW": (nxt(lambda k: k >= 3), True, False),
            "RWS": (nxt(lambda k: k == 1), True, False),
            "PIX": (nxt(lambda k: k % 2 == 0), True, False),
            "VLD": (nxt(lambda k: k in (1, 2)), True, False),
            "YOE": (nxt(lambda k: k in (1, 2)), True, False),
        }, clock="MCLK")
    else:
        nl.add("chibiclk", "X_CLK", CLK="CLK0", PHW="PHW", CLKW="CLKW", RWS="RWS", PIX="PIX",
               VLD="VLD", YOE="YOE", MCLK="MCLK", T0="T0", T1="T1", T2="T2", RESET="RESET_n")
    # the CPU clock to its loads
    clk = [f"CLK{i}" for i in range(1, 9)]
    nl.add("541", "U_CLKB", OE1="GND", OE2="GND",
           **{f"A{i}": "CLK0" for i in range(1, 9)}, **{f"Y{i}": clk[i - 1] for i in range(1, 9)})

    # ---- control store and sequencer --------------------------------------
    nl.section("control store")
    step, op, nib, page = bus("STEP", 5), bus("OP", 8), bus("N", 4), bus("PAGE", 2)
    cs_addr = step + op + nib + page
    for k in range(uc.ROMS):
        nl.add("flash4", f"U_CS{k}", CE="GND", OE="GND", WE="VCC",
               **{f"A{i}": cs_addr[i] for i in range(19)},
               **{f"D{i}": cw[8 * k + i] for i in range(8)})

    nl.section("sequencer")
    seq, cnd, jt, pt = field("SEQ"), field("CND"), field("JT"), field("PT")
    # the instruction register: the opcode byte (in a 22V10 for its 4 ns
    # to the control store), the register byte; the control store's address
    # registers on the clock before its buffer
    G.add(nl, "U_IRL", {op[i]: (OR(AND(lit("LDIR"), lit(f"MD{i}")), AND(lit("LDIR", 0), lit(op[i]))),
                                True, False) for i in range(8)},
          clock="CLK0", ar=lit("RESET_n", 0))       # reset: opcode 00, for the boot (routines.boot)
    d, s = bus("IRD", 4), bus("IRS", 4)
    irop = field("IROP")
    incd, decs, ldx = eq(irop, uc.IR_INCD), eq(irop, uc.IR_DECS), eq(irop, uc.IR_LDX)
    ldir = lit("LDIR")
    nld = lit("LDIR", 0)
    irh = {}
    for i in range(4):
        irh[d[i]] = (OR(AND(ldir, lit(f"MD{12 + i}")),
                        AND(nld, toggle(d, i, incd)),
                        AND(nld, negate(incd), lit(d[i]))), True, False)
        sdec = OR(AND(decs, lit(s[i], 1), OR(*[lit(b, 1) for b in s[:i]])) if i else ZERO,
                  AND(decs, lit(s[i], 0), [{b: 0 for b in s[:i]}] if i else ONE))
        irh[s[i]] = (OR(AND(ldir, lit(f"MD{8 + i}")),
                        AND(nld, ldx, lit(f"MD{12 + i}")),
                        AND(nld, sdec),
                        AND(nld, negate(OR(ldx, decs)), lit(s[i]))), True, False)
    irh["NE"] = (OR(*[OR(AND(lit(d[i], 1), lit(s[i], 0)), AND(lit(d[i], 0), lit(s[i], 1)))
                      for i in range(4)]), False, False)
    G.add(nl, "U_IRH", irh, clock=clk[0])

    nop = field("NOP")
    ng = {}
    for i in range(4):
        ng[nib[i]] = (OR(AND(ldir, lit(f"MD{12 + i}")),
                         AND(nld, eq(nop, uc.N_S), lit(s[i])),
                         AND(nld, eq(nop, uc.N_MDZ), lit(f"MD{8 + i}")),
                         AND(nld, eq(nop, uc.N_HOLD), lit(nib[i]))), True, False)
    G.add(nl, "U_NG", ng, clock="CLK0", ar=lit("RESET_n", 0))

    # STEP and PAGE: next, jump if CT, end (decode, or page 3 if IRQP);
    # PAGE stored inverted, so that reset makes it 3
    nxt_ = eq(seq, uc.SEQ_NEXT)
    jmp = eq(seq, uc.SEQ_JUMP)
    end = lit(seq[1], 1)
    inc = OR(nxt_, AND(jmp, lit("CT", 0)))
    take = AND(jmp, lit("CT", 1))
    st = {}
    for i in range(5):
        st[step[i]] = (OR(toggle(step, i, inc), AND(take, lit(jt[i]))), True, False)
    for i in range(2):
        nextpage = OR(AND(inc, lit(page[i])), AND(take, lit(pt[i])), AND(end, lit("IRQP")))
        st[page[i]] = (negate_sop_pg(nextpage, inc, take, end, page[i], pt[i]), True, True)
    G.add(nl, "U_STEP", st, clock="CLK0", ar=lit("RESET_n", 0))

    # the condition: three partial sums, then CT
    f = {k: f"F_{k}" for k in ("N", "Z", "C", "V", "I", "IC", "ST")}
    conds = {
        "TRUE": ONE, "Z": lit(f["Z"]), "C": lit(f["C"]), "N": lit(f["N"]), "V": lit(f["V"]),
        "HI": AND(lit(f["C"]), lit(f["Z"], 0)),
        "LT": OR(AND(lit(f["N"]), lit(f["V"], 0)), AND(lit(f["N"], 0), lit(f["V"]))),
        "LE": OR(lit(f["Z"]), AND(lit(f["N"]), lit(f["V"], 0)), AND(lit(f["N"], 0), lit(f["V"]))),
        "IC": lit(f["IC"]), "ST": lit(f["ST"]), "INIT": lit("INIT"), "IRQP": lit("IRQP"),
        "NE": lit("NE"), "A0": lit("A0"), "MISW": OR(lit("A0"), lit("A1")), "I": lit(f["I"]),
    }
    terms = []
    for name, sop in conds.items():
        c = uc.COND_CODE[name]
        terms.append(AND(eq(cnd, c), sop))
        terms.append(AND(eq(cnd, c | 16), negate(sop)))
    parts_ = [[], [], []]
    for t in sorted(terms, key=len, reverse=True):
        min(parts_, key=len).extend(t)
    G.add(nl, "U_COND", {"CTA": (parts_[0], False, False), "CTB": (parts_[1], False, False),
                         "CTC": (parts_[2], False, False),
                         "CT": (OR(lit("CTA"), lit("CTB"), lit("CTC")), False, False)})

    # ---- flags ------------------------------------------------------------
    nl.section("flags")
    flags_gal(nl, f, clk[1])
    # IRQP, INIT, and the reset for the devices
    fl_ = field("FL")
    irqs = ["U0INT", "U1INT", "KIRQ", "MIRQ", "VIRQ", "CONIRQ"]
    G.add(nl, "U_SYS", {
        "IRQP": (AND(lit(f["I"]), OR(*[lit(n) for n in irqs])), True, False),
        "INIT": (OR(lit("INIT"), eq(fl_, uc.FL_CODE["SETINIT"])), True, False),
        "RESET": (lit("RESET_n", 0), False, False),
        # the video's slot on the address bus: phase W through a 22V10, as
        # PCSEL and MARSEL come, so that the drivers change over together
        "VSEL": (lit("PHW"), False, False),
    }, clock=clk[1], ar=lit("RESET_n", 0))

    # ---- register file ------------------------------------------------------
    nl.section("register file")
    rs, ws, kr, kw = field("RS"), field("WS"), field("KR"), field("KW")
    ra, wa = bus("RA", 6), bus("WA", 6)
    phw = lit("PHW")
    phr = lit("PHW", 0)
    for g, bits in ((0, (0, 1)), (1, (2, 3))):
        outs = {}
        for i in bits:
            def mux(sel, k):
                return OR(AND(eq(sel, uc.SEL_K), lit(k[i])), AND(eq(sel, uc.SEL_D), lit(d[i])),
                          AND(eq(sel, uc.SEL_S), lit(s[i])))
            outs[ra[i]] = (OR(AND(phw, lit(wa[i])), AND(phr, mux(rs, kr))), False, False)
            outs[wa[i]] = (mux(ws, kw), True, False)
        G.add(nl, f"U_RFA{g}", outs, clock=clk[1])
    hr, hw, wen = field("HR")[0], field("HW")[0], field("WEN")[0]
    G.add(nl, "U_RFA2", {
        ra[4]: (OR(AND(phw, lit(wa[4])), AND(phr, eq(rs, uc.SEL_K), lit(kr[4]))), False, False),
        ra[5]: (OR(AND(phw, lit(wa[5])), AND(phr, lit(hr))), False, False),
        wa[4]: (AND(eq(ws, uc.SEL_K), lit(kw[4])), True, False),
        wa[5]: (lit(hw), True, False),
        "WENQ": (lit(wen), True, False),
        "RFWE_n": (AND(lit("RWS"), lit("WENQ")), False, True),
    }, clock=clk[1])
    for k in range(2):
        nl.add("sram", f"U_RF{k}", CE="GND", OE="RFOE_n", WE="RFWE_n",
               **{f"A{i}": ra[i] for i in range(6)}, A6="GND",
               **{f"A{i}": "GND" for i in range(7, 15)},
               **{f"IO{i}": f"D{8 * k + i}" for i in range(8)})

    # ---- ALU -------------------------------------------------------------
    nl.section("ALU")
    for k in range(2):
        nl.add("377", f"U_L{k}", CLK=clk[1], EN=field("LDL")[0],
               **{f"D{i + 1}": f"D{8 * k + i}" for i in range(8)},
               **{f"Q{i + 1}": f"L{8 * k + i}" for i in range(8)})
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
    aluc_gal(nl, f)

    nl.section("result")
    rm = field("RM")
    yoe = lit("YOE")            # Y drives D in ticks 1-2 of phase W: the old source is off by then
    y = {}
    for i in range(8):
        y[f"D{i}"] = (OR(AND(eq(rm, uc.RM_SHR), lit(f"F{i + 1}")),
                         AND(negate(eq(rm, uc.RM_SHR)), lit(f"F{i}"))), True, False, yoe)
    G.add(nl, "U_YLO", y, clock=clk[2])
    y = {}
    for i in range(8, 16):
        nxt_bit = "SI" if i == 15 else f"F{i + 1}"
        y[f"D{i}"] = (OR(AND(eq(rm, uc.RM_PASS), lit(f"F{i}")),
                         AND(eq(rm, uc.RM_SHR), lit(nxt_bit)),
                         AND(eq(rm, uc.RM_SXB), lit("F7"))), True, False, yoe)
    G.add(nl, "U_YHI", y, clock=clk[2])
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

    # ---- the immediate unit, the bus's sources -----------------------------
    nl.section("immediate unit")
    imm_gals(nl, d, s)
    bus_gal(nl)

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
            nl.add("sram512", f"U_RAM{r}{b}", role="fastram", CE=f"RCE{r}_n", OE="RAMOE_n",
                   WE=f"WE{'LH'[b]}_n",
                   **{f"A{i}": f"A{i + 1}" for i in range(19)},
                   **{f"IO{i}": f"MD{8 * b + i}" for i in range(8)})

    # ---- I/O ---------------------------------------------------------------
    nl.section("I/O")
    io_gals(nl)
    for k in range(2):
        nl.add("16c550", f"U_UART{k}", CS0="VCC", CS1="VCC", CS2=f"U{k}CS_n", RD="IORD_n",
               WR="IOWR_n", MR="RESET", XIN="UCLK", INTR=f"U{k}INT",
               **{f"D{i}": f"MD{i}" for i in range(8)},
               **{f"A{i}": f"A{i + 1}" for i in range(3)})
    nl.add("flash", "U_BOOT", CE="FLCS_n", OE="IORD_n", WE="IOWR_n", part="SST39SF010A-55",
           **{f"A{i}": f"A{i + 1}" for i in range(17)}, **{f"D{i}": f"MD{i}" for i in range(8)})
    if sim:
        nl.add("osc", "X_UCLK", OUT="UCLK", params={"period_ps": 542535, "phase_ps": 1000})
        # the fixture takes a read at its clock's edge, which IORD_n's end
        # races: its read strobe a wire's 10 ns later
        w = nl.add("wire", "X_IORDW", A="IORD_n", Y="IORD_X")
        w.add_pin_delay("Y", 10000)
        nl.add("iodev32", "X_IO", CLK=clk[3], IOSEL="CONSEL_n", RD="IORD_X", WEL="IOWR_n",
               WEH="VCC", IRQ="CONIRQ",
               **{f"A{i}": f"A{i}" for i in range(8)}, **{f"D{i}": f"MD{i}" for i in range(16)})
        nl.add("ps2dev", "X_KBD", CLK="KCLK", DATA="KDATA", WAKE="KWAKE",
               params={"half_ps": 40_000_000, "gap_ps": 200_000_000, "start_ps": 50_000_000})
        nl.add("ps2dev", "X_MOUSE", CLK="MSCLK", DATA="MSDATA", WAKE="MWAKE",
               params={"half_ps": 40_000_000, "gap_ps": 200_000_000, "start_ps": 70_000_000})
    else:
        nl.add("const", "X_IOK", LO="CONIRQ", HI="UCLK")
    nl.add("pullup", "R_PS2", P1="KCLK", P2="KDATA", P3="MSCLK", P4="MSDATA")
    ps2_gals(nl)

    # ---- video -------------------------------------------------------------
    nl.section("video")
    video_gals(nl, clk)

    nl.finish()
    nl.check()
    return nl


def negate_sop_pg(nextpage, inc, take, end, p, ptb):
    """The complement of PAGE's next value, as its register stores it."""
    return OR(AND(inc, lit(p, 0)), AND(take, lit(ptb, 0)), AND(end, lit("IRQP", 0)))


def flags_gal(nl, f, clk):
    """N, Z, C, V, I, IC, ST from the flag operation (FL) and the cycle's
    result: Z16, N15, N7 (its bits), CO_n (the ALU's carry out), F0 (the
    bit a right shift moves out), D15 and L15 (the operands' signs)."""
    fl_ = field("FL")
    ins = {"z": "Z16", "n15": "N15", "n7": "N7", "co": "CO_n", "f0": "F0", "a15": "D15",
           "b15": "L15"}

    def nextf(flag, opname, v):
        """A flag's next value under an operation, from the input values v."""
        z, n15, n7, co, f0 = v["z"], v["n15"], v["n7"], 1 - v["co"], v["f0"]
        a15, b15 = v["a15"], v["b15"]
        cur = v["self"]
        F = dict(v["flags"])

        def ov(sub, b):
            return int((a15 != b if sub else a15 == b) and n15 != a15)
        sets = {
            "ADDLO": {"C": co, "Z": z},
            "ADDHI": {"C": co, "Z": F["Z"] & z, "N": n15, "V": ov(0, b15)},
            "SUBHI": {"C": co, "Z": F["Z"] & z, "N": n15, "V": ov(1, b15)},
            "ADDHIZ": {"C": co, "Z": F["Z"] & z, "N": n15, "V": ov(0, 0)},
            "SUBHIZ": {"C": co, "Z": F["Z"] & z, "N": n15, "V": ov(1, 0)},
            "ADCLO": {"C": co, "Z": F["Z"] & z},
            "ICLO": {"IC": co}, "ICLOZ": {"IC": co, "Z": z}, "ICSTZ": {"IC": co, "ST": z},
            "LOGLO": {"Z": z}, "LOGHI": {"Z": F["Z"] & z, "N": n15},
            "NZ16": {"N": n15, "Z": z}, "NZ8": {"N": n7, "Z": z},
            "SHR": {"C": f0, "V": 0}, "SHL": {"C": co, "V": 0},
            "STN": {"ST": n15}, "STZ": {"ST": z},
            "ICN": {"IC": F["N"]}, "ICZ": {"IC": F["Z"]}, "ICC": {"IC": F["C"]},
            "ICV": {"IC": F["V"]}, "ICI": {"IC": F["I"]},
            "CNZ": {"C": 1 - z}, "VNZ": {"V": 1 - z}, "ZNZ": {"Z": 1 - z}, "NNZ": {"N": 1 - z},
            "INZ": {"I": 1 - z}, "SETI": {"I": 1}, "CLRI": {"I": 0},
        }.get(opname, {})
        return sets.get(flag, cur)

    deps = {"N": ["n15", "n7", "z"], "Z": ["z"], "C": ["co", "f0", "z"],
            "V": ["a15", "b15", "n15", "z"], "I": ["z"], "IC": ["co", "z"], "ST": ["n15", "z"]}
    others = {"Z": ["Z"], "N": [], "C": [], "V": [], "I": [], "IC": ["N", "Z", "C", "V", "I"],
              "ST": []}
    outs = {}
    for flag in ("N", "Z", "C", "V", "I", "IC", "ST"):
        dn = deps[flag]
        on = [o for o in others[flag] if o != flag]
        nets = fl_ + [ins[k] for k in dn] + [f[flag]] + [f[o] for o in on]

        def fn(*bits, flag=flag, dn=dn, on=on):
            code = sum(b << i for i, b in enumerate(bits[:5]))
            if code not in uc.FL_NAME:
                return None
            name = uc.FL_NAME[code]
            v = {k: bits[5 + i] for i, k in enumerate(dn)}
            for k in ins:
                v.setdefault(k, 0)
            v["self"] = bits[5 + len(dn)]
            fl = {k: 0 for k in ("N", "Z", "C", "V", "I")}
            fl[flag] = v["self"] if flag in fl else 0
            for i, o in enumerate(on):
                fl[o] = bits[6 + len(dn) + i]
            v["flags"] = fl
            return nextf(flag, name, v)
        outs[f[flag]] = (G.table(nets, fn), True, False)
    G.add(nl, "U_FLG", outs, clock=clk, ar=lit("RESET_n", 0))


def aluc_gal(nl, f):
    """S3-S0, M and the carry in (CN0_n, active low) from the ALU operation,
    the carry sources and ST; SI, the bit a right shift brings in."""
    aop, sisel = field("AOP"), field("SISEL")

    def resolve(code, st):
        if code not in uc.AOP_NAME:
            return None
        return uc.aop_resolve(uc.AOP_NAME[code], st)
    outs = {}
    for i in range(4):
        outs[f"AS{i}"] = (G.table(aop + [f["ST"]], lambda *b, i=i: None if resolve(
            sum(x << j for j, x in enumerate(b[:5])), b[5]) is None else
            resolve(sum(x << j for j, x in enumerate(b[:5])), b[5])[0] >> i & 1), False, False)
    outs["AM"] = (G.table(aop + [f["ST"]], lambda *b: None if resolve(
        sum(x << j for j, x in enumerate(b[:5])), b[5]) is None else
        resolve(sum(x << j for j, x in enumerate(b[:5])), b[5])[1]), False, False)

    def cin(*b):
        r = resolve(sum(x << j for j, x in enumerate(b[:5])), b[5])
        if r is None:
            return None
        c = {"0": 0, "1": 1, "C": b[6], "IC": b[7]}[r[2]]
        return 1 - c                    # CN0_n: active low
    outs["CN0_n"] = (G.table(aop + [f["ST"], f["C"], f["IC"]], cin), False, False)
    outs["SI"] = (OR(AND(eq(sisel, uc.SI_C), lit(f["C"])), AND(eq(sisel, uc.SI_D15), lit("D15")),
                     AND(eq(sisel, uc.SI_CO), lit("CO_n", 0))), False, False)
    G.add(nl, "U_ALUC", outs)


def imm_gals(nl, d, s):
    """The immediate unit: a format (IMMF) of the register byte, or a
    constant, onto D when IMMOE (the low byte) and IMMOEH (the high);
    ZH: the high byte 0 whatever the format (a byte load's)."""
    immf = field("IMMF")
    names = list(uc.IMMS)
    lo, hi = {}, {}
    for i in range(8):
        terms = []
        for code, name in enumerate(names):
            flo, fhi = uc.IMMS[name]
            if flo is None:
                continue
            # the bit as a function of d and s: constant, or one of their bits (or its complement)
            vals = {(dd, ss): flo(dd, ss) >> i & 1 for dd in range(16) for ss in range(16)}
            if all(v == 1 for v in vals.values()):
                terms += eq(immf, code)
                continue
            if all(v == 0 for v in vals.values()):
                continue
            found = False
            for src, nets in (("d", d), ("s", s)):
                for j in range(4):
                    for pol in (1, 0):
                        if all(v == (((dd if src == "d" else ss) >> j & 1) ^ (1 - pol))
                               for (dd, ss), v in vals.items()):
                            terms += AND(eq(immf, code), lit(nets[j], pol))
                            found = True
                            break
                    if found:
                        break
                if found:
                    break
            assert found, (name, i)
        oe = lit("IMMOE") if i >= 5 else AND(lit("IMMOE"), negate(eq(immf, uc.IMM_CODE["Z5"])))
        lo[f"D{i}"] = (merge_codes(terms, immf), False, False, oe)
    G.add(nl, "U_IMML", lo)
    for i in range(8):
        terms = []
        for code, name in enumerate(names):
            fhi = uc.IMMS[name][1]
            vals = {dd: fhi(dd, 0) >> i & 1 for dd in range(16)}
            if all(v == 1 for v in vals.values()):
                terms += eq(immf, code)
            elif any(vals.values()):
                assert all(v == (dd >> 3) for dd, v in vals.items()), name
                terms += AND(eq(immf, code), lit(d[3]))
        hi[f"D{8 + i}"] = (AND(lit("ZH", 0), merge_codes(terms, immf)), False, False,
                           lit("IMMOEH"))
    G.add(nl, "U_IMMH", hi)


def merge_codes(terms, code_nets):
    """Merge terms that differ only in the code's bits where the rest is
    the same and the codes form a cube (a light minimisation)."""
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


def bus_gal(nl):
    """Who drives D in phase R (and which way the transceivers point)."""
    sz = field("SZ")[0]
    phr = lit("PHW", 0)
    mem_ = ds_is(uc.DS_MEM)
    wr_ = eq(MOP, uc.MOP_WRM)
    w16, w8 = AND(wr_, lit(sz, 0)), AND(wr_, lit(sz, 1))
    G.add(nl, "U_BUS", {
        "RFOE_n": (AND(phr, ds_is(uc.DS_RF)), False, True),
        "XOE0_n": (AND(phr, OR(AND(mem_, lit(sz, 0)), AND(mem_, lit("A0", 0)), wr_)), False, True),
        "XOE1_n": (AND(phr, OR(AND(mem_, lit(sz, 0)), w16)), False, True),
        "XOES_n": (AND(phr, OR(AND(mem_, lit(sz), lit("A0")), w8)), False, True),
        "XDIR": (wr_, False, False),
        "IMMOE": (AND(phr, OR(ds_is(uc.DS_IMM), ds_is(uc.DS_PCH))), False, False),
        "IMMOEH": (AND(phr, OR(ds_is(uc.DS_IMM), ds_is(uc.DS_PCH), AND(mem_, lit(sz)))),
                   False, False),
        "ZH": (AND(mem_, lit(sz)), False, False),
        "RBOE_n": (AND(phr, ds_is(uc.DS_ADR)), False, True),
        "RBC": (AND(phr, ds_is(uc.DS_PCH)), False, False),
    })


def address_gals(nl):
    """PC (bits 20-1) and MAR (20-0, 31): counters in 22V10s that load from
    D (Y, in phase W) at CLKW, and drive the address bus in phase R when
    selected (PCSEL, MARSEL); their operations, deferred from the cycle
    before, from U_ADC."""
    axp, axm = field("AXP"), field("AXM")
    atpc = mop_in([uc.MOP_RDP, uc.MOP_FETCH, uc.MOP_PCS])
    notpc = mop_in([m for m in range(8) if m not in (uc.MOP_RDP, uc.MOP_FETCH, uc.MOP_PCS)])
    G.add(nl, "U_ADC", {
        "PCLO": (eq(axp, uc.AXP_LO), True, False),
        "PCHI": (eq(axp, uc.AXP_HI), True, False),
        "PCINC": (mop_in([uc.MOP_RDP, uc.MOP_FETCH]), True, False),
        "MARLO": (eq(axm, uc.AXM_LO), True, False),
        "MARHI": (eq(axm, uc.AXM_HI), True, False),
        "MARINC": (eq(axm, uc.AXM_INC), True, False),
        "PCSEL": (AND(lit("PHW", 0), atpc), False, False),
        "MARSEL": (AND(lit("PHW", 0), notpc), False, False),
        "LDIR": (mop_in([uc.MOP_FETCH, uc.MOP_LDIRM]), False, False),
    }, clock="CLK8")
    pc = bus("PC", 21)              # the registers' own nets (PC1-PC20 on A1-A20)
    sel = lit("PCSEL")
    # PC bits 1-8
    bits = [f"A{i}" for i in range(1, 9)]
    outs = {}
    for k, b in enumerate(bits):
        outs[b] = (counter_bit(bits, k, lit("PCINC"), lit("PCLO"), f"D{k + 1}"), True, False, sel)
    outs["A0"] = (ZERO, False, False, sel)
    outs["PCCO"] = (AND(lit("PCINC"), [{b: 1 for b in bits}]), False, False)
    G.add(nl, "U_PCA", outs, clock="CLKW")
    bits = [f"A{i}" for i in range(9, 16)]
    outs = {b: (counter_bit(bits, k, lit("PCCO"), lit("PCLO"), f"D{9 + k}"), True, False, sel)
            for k, b in enumerate(bits)}
    outs["PCBCO"] = (AND(lit("PCCO"), [{b: 1 for b in bits}]), False, False)
    G.add(nl, "U_PCB", outs, clock="CLKW")
    bits = [f"A{i}" for i in range(16, 21)]
    outs = {b: (counter_bit(bits, k, lit("PCBCO"), lit("PCHI"), f"D{k}"), True, False, sel)
            for k, b in enumerate(bits)}
    for k, b in enumerate(bits):
        outs[f"D{k}"] = (lit(b), False, False, lit("RBC"))
    G.add(nl, "U_PCC", outs, clock="CLKW")
    del pc
    # MAR bits 0-7 (bit 0 doesn't count: MAR + 2)
    sel = lit("MARSEL")
    bits = [f"A{i}" for i in range(0, 8)]
    outs = {"A0": (OR(AND(lit("MARLO"), lit("D0")), AND(negate(lit("MARLO")), lit("A0"))),
                   True, False, sel)}
    cbits = bits[1:]
    for k, b in enumerate(cbits):
        outs[b] = (counter_bit(cbits, k, lit("MARINC"), lit("MARLO"), f"D{k + 1}"), True, False,
                   sel)
    outs["MARACO"] = (AND(lit("MARINC"), [{b: 1 for b in cbits}]), False, False)
    G.add(nl, "U_MARA", outs, clock="CLKW")
    bits = [f"A{i}" for i in range(8, 16)]
    outs = {b: (counter_bit(bits, k, lit("MARACO"), lit("MARLO"), f"D{8 + k}"), True, False, sel)
            for k, b in enumerate(bits)}
    outs["MARBCO"] = (AND(lit("MARACO"), [{b: 1 for b in bits}]), False, False)
    G.add(nl, "U_MARB", outs, clock="CLKW")
    # bits 16-20: 16 and 17 on the bus; 18-20 buried, the bus's A18-A20 the
    # video's in phase W (A20 = A19 = 1, A18 = FB: the frame buffers at
    # 0x18_0000 and 0x1C_0000); 31 always out
    regs = ["A16", "A17", "MAR18", "MAR19", "MAR20"]
    outs = {}
    for k, b in enumerate(regs):
        outs[b] = (counter_bit(regs, k, lit("MARBCO"), lit("MARHI"), f"D{k}"), True, False,
                   *([sel] if k < 2 else []))
    outs["A18"] = (OR(AND(vsel(), lit("FB")), AND(vsel(0), lit("MAR18"))), False, False,
                   OR(vsel(), sel))
    outs["A19"] = (OR(vsel(), lit("MAR19")), False, False, OR(vsel(), sel))
    outs["A20"] = (OR(vsel(), lit("MAR20")), False, False, OR(vsel(), sel))
    outs["A31"] = (OR(AND(lit("MARHI"), lit("D15")), AND(negate(lit("MARHI")), lit("A31"))), True,
                   False)
    G.add(nl, "U_MARC", outs, clock="CLKW")


def vsel(v=1):
    return lit("VSEL", v)


def memc_gal(nl):
    """The memory's and the devices' strobes, on the master clock at the
    ticks: the RAM's write enables (ticks 4-6), IORD_n (4-7), IOWR_n
    (4-6); the RAM's output enable (the video's read, ticks 1-2; a read in
    phase R) and its two rows' chip enables (A20)."""
    T = ["T0", "T1", "T2"]
    sz = field("SZ")[0]
    write = eq(MOP, uc.MOP_WRM)
    rdm = mop_in([uc.MOP_RDM, uc.MOP_LDIRM])

    def at(ticks):
        return G.table(T, lambda a, b, c: ((a | b << 1 | c << 2) + 1 & 7) in ticks)
    w46, r47 = at((4, 5, 6)), at((4, 5, 6, 7))
    ram_w = AND(write, lit("A31", 0))
    outs = {
        "WEL_n": (AND(w46, ram_w, lit("A0", 0)), True, True),
        "WEH_n": (OR(AND(w46, ram_w, lit(sz, 0), lit("A0", 0)),
                     AND(w46, ram_w, lit(sz, 1), lit("A0", 1))), True, True),
        "IORD_n": (AND(r47, rdm, lit("A31")), True, True),
        "IOWR_n": (AND(w46, write, lit("A31")), True, True),
        # the video's read from tick 1, when a device read in the cycle before has let go
        "RAMOE_n": (OR(lit("VLD"), AND(mop_in([uc.MOP_RDP, uc.MOP_FETCH]), lit("PHW", 0)),
                       AND(rdm, lit("A31", 0), lit("PHW", 0))), False, True),
        "RCE0_n": (lit("A20"), False, False),
        "RCE1_n": (lit("A20", 0), False, False),
    }
    G.add(nl, "U_MEMC", outs, clock="MCLK")


def io_gals(nl):
    """The I/O space's selects, from MAR's own bits 20-18 (U_MARC's buried
    registers, there from CLKW, not the address bus, which is the video's
    until tick 3) and A31."""
    m = ["MAR18", "MAR19", "MAR20"]
    io = lit("A31")

    def sel(v):
        return AND(io, eq(m, v))
    G.add(nl, "U_IODEC", {
        "U0CS_n": (sel(0b000), False, True),
        "U1CS_n": (sel(0b001), False, True),
        "PS2CS": (sel(0b010), False, False),
        "VCCS": (sel(0b011), False, False),
        "FLCS_n": (AND(io, lit("MAR20"), lit("MAR19", 0)), False, True),
        "CONSEL_n": (AND(io, lit("MAR20"), lit("MAR19")), False, True),
    })


def ps2_gals(nl):
    """Two PS/2 receivers, each a 22V10 clocked by its port's clock line:
    eight registers for the byte, on MD7-0 when read at +0 (the keyboard)
    or +2 (the mouse), and the frame's marker, the port's interrupt; and
    the ports' control, clocked by IOWR_n's end, at +4 (the keyboard's) and
    +6 (the mouse's): MD0 and MD1 written pull the clock and data lines low;
    read, MD0 and MD1 are the lines' levels and MD2 the frame's marker.

    A receiver's registers start clear (reset, and a write to its address,
    clear them: AR). Each rising edge of the clock shifts the inverted data line
    in at the top; the start bit, a 0, arrives as a 1 and reaches the
    marker after nine edges, with the byte's bits (inverted: the pins show
    them true) above it. Then the registers hold, ignoring the line (the
    frame's parity and stop bits, and any byte after it), until the byte
    is read and cleared. Holding the device off with the clock line low
    would have to wait for the frame's eleventh edge, or the device sends
    the byte again: two more registers than the 22V10 has (RFC 0047's
    open questions)."""
    for port, clk, dat, irq, a1 in (("KBD", "KCLK", "KDATA", "KIRQ", 0),
                                    ("MOUSE", "MSCLK", "MSDATA", "MIRQ", 1)):
        sel = AND(lit("PS2CS"), lit("A1", a1), lit("A2", 0))
        done = lit(irq)
        held = [irq] + [f"MD{i}" for i in range(8)]
        outs = {}
        for i in range(9):
            # the registers in pin terms: the marker true, the byte's pins
            # the registers' complements
            if i == 0:
                shift_in = lit(held[1], 0)                  # the register above: ~its pin
                outs[irq] = (OR(AND(done, lit(irq)), AND(lit(irq, 0), shift_in)), True, False)
            else:
                above = lit(dat, 0) if i == 8 else lit(held[i + 1], 0)
                outs[held[i]] = (OR(AND(done, lit(held[i], 0)), AND(lit(irq, 0), above)), True,
                                 True, AND(sel, lit("IORD_n", 0)))
        G.add(nl, f"U_{port}", outs, clock=clk,
              ar=OR(AND(sel, lit("IOWR_n", 0)), lit("RESET_n", 0)))
        del outs
    # the ports' control: each line pulled low by a register (the pin
    # combinational, so that it reads the line back), the lines' levels and
    # the frame's marker read on MD2-0
    for port, clk, dat, irq, a1 in (("KBD", "KCLK", "KDATA", "KIRQ", 0),
                                    ("MOUSE", "MSCLK", "MSDATA", "MIRQ", 1)):
        wsel = AND(lit("PS2CS"), lit("A2"), lit("A1", a1))
        rsel = AND(wsel, lit("IORD_n", 0))
        outs = {}
        for i, (ln, bit) in enumerate(((clk, "MD0"), (dat, "MD1"))):
            q = f"{ln}_PULL"
            outs[q] = (OR(AND(wsel, lit(bit)), AND(negate(wsel), lit(q))), True, False)
            outs[ln] = (ZERO, False, False, lit(q))
        outs["MD0"] = (lit(clk), False, False, rsel)
        outs["MD1"] = (lit(dat), False, False, rsel)
        outs["MD2"] = (lit(irq), False, False, rsel)
        G.add(nl, f"U_{port}C", outs, clock="IOWR_n", ar=lit("RESET_n", 0))


def video_gals(nl, clk):
    """640 x 480 x 4 at 60 Hz: H counts the CPU's cycles (four pixels each),
    0-199, its pixels 0-159; V the lines, 0-524, its pixels 0-479 (VBL from
    480). In phase W they address the RAM: A8-A1 = H, A17-A9 = V, A20-A18
    from U_MARC; the shifter loads the word at tick 2 and shifts a pixel
    (4 bits, pixel 0 the low ones) each tick of the pixel clock."""
    h = bus("A", 8, 1)                          # H7-H0 on A8-A1
    v = bus("A", 9, 9)                          # V8-V0 on A17-A9
    hv = list(range(8))

    def hval(val):
        return eq(h, val)
    outs = {}
    for k in hv:
        outs[h[k]] = (toggle(h, k, ONE), True, False, lit("VSEL"))
    # HSYNC for H in 164-187, from the count before (registered on the same edge)
    outs["HS_n"] = (G.table(h, lambda *b: (sum(x << i for i, x in enumerate(b)) + 1) in
                            range(164, 188)), True, True)
    outs["LD"] = (AND(lit("VLD"), lit("DEN"), lit("VBL", 0), OR(lit(h[7], 0),
                      AND(lit(h[6], 0), lit(h[5], 0)))), False, False)
    G.add(nl, "U_VH", outs, clock=clk[4], ar=hval(200))
    outs = {}
    for k in range(9):
        outs[v[k]] = (toggle(v, k, ONE), True, False, lit("VSEL"))
    outs["VBL"] = (OR(lit("VBL"), eq(v, 479)), True, False)
    G.add(nl, "U_VV", outs, clock="HS_n", ar=AND(lit("VBL"), eq(v, 13)))
    # the CPU-side: VSYNC, the frame interrupt, the control register
    c = bus("VCNT", 4)
    line = AND(lit("HS_n"), lit("HSQ", 0))
    wr_ = AND(lit("VCCS"), eq(MOP, uc.MOP_WRM))
    outs = {"HSQ": (lit("HS_n"), True, False)}
    for k in range(4):
        sat = [{b: 1 for b in c}]
        outs[c[k]] = (AND(lit("VBL"), OR(AND(line, negate(sat), toggle(c, k, ONE)),
                                         AND(OR(negate(line), sat), lit(c[k])))), True, False)
    outs["VS_n"] = (AND(lit("VBL"), OR(eq(c, 10), eq(c, 11))), True, True)
    # the frame interrupt: set at the first line of the blank (the count
    # still 0) if enabled, cleared by any write of the register
    outs["VIRQ"] = (OR(AND(lit("VIE"), lit("VBL"), line, eq(c, 0)),
                       AND(lit("VIRQ"), negate(wr_))), True, False)
    for q, bit in (("FB", "MD0"), ("DEN", "MD1"), ("VIE", "MD2")):
        outs[q] = (OR(AND(wr_, lit(bit)), AND(negate(wr_), lit(q))), True, False)
    G.add(nl, "U_VC", outs, clock=clk[5], ar=lit("RESET_n", 0))
    # the shifter: SHB the word's high byte, SHA its low, shifting 4 bits a pixel
    sb = bus("SB", 8)
    sa = bus("PX", 8)                           # PX3-PX0: the pixel, to the DAC's resistors
    outs = {}
    for k in range(8):
        nxt = lit(sb[k + 4]) if k < 4 else ZERO
        outs[sb[k]] = (OR(AND(lit("LD"), lit(f"MD{8 + k}")), AND(lit("LD", 0), nxt)), True, False)
    G.add(nl, "U_SHB", outs, clock="PIX")
    outs = {}
    for k in range(8):
        nxt = lit(sa[k + 4]) if k < 4 else lit(sb[k - 4])
        outs[sa[k]] = (OR(AND(lit("LD"), lit(f"MD{k}")), AND(lit("LD", 0), nxt)), True, False)
    G.add(nl, "U_SHA", outs, clock="PIX")


# the clock generator as static timing analysis sees it (sta.py)
from heron.infra.hw import chips as _chips  # noqa: E402

if "chibiclk" not in _chips.TYPES:
    _chips.T("chibiclk", "chibiclk",
             [(p, "out") for p in ("CLK", "PHW", "CLKW", "RWS", "PIX", "VLD", "YOE", "MCLK", "T0",
                                   "T1", "T2", "RESET")], family="fixture",
             desc="for static timing analysis: Chibi Heron's clock generator, its phases as "
                  "functions of the period (studies/chibi/sta.py)")
