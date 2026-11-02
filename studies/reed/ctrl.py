"""The CTRL board: the clocks, the sequencer and its slice of the control
store, the decode table, the instruction queue, the instruction
registers, the immediate unit, PC.

The clocks. The master clock (50.35 MHz, a tick 19.86 ns) and its inverse
go onto the backplane (MCLK, MCLKN), each from a CDC341. U_CGA, on MCLK as
it comes back from the backplane, counts the cycle's ticks: a cycle is
4 + LEN ticks, held at its third-last tick while a WAIT line is up. CYC
rises as a cycle starts and is high for two ticks; WPH is high for the
cycle's last two ticks (the write phase: the register file and the RAM
write then). Every board, CTRL too, takes CYC from the backplane through
a CDC341 of its own, so that every register sees the same edge.

The sequencer. The µPC (two 574s) drives the backplane's UPC lines, which
every board's slice of the control store reads. CTRL's own slice gives
JT, SEQ and CND straight to the next-address GALs (U_NA0-2), which work
from the word being fetched while the one before executes:

  SEQ JUMP     JT, its bit 0 XORed with the condition CND chooses
  SEQ DECODE   the decode table's entry for the parcel at the queue's
               decode pointer; or the interrupt's entry (IVEC) when an
               interrupt is pending and enabled; or, while the
               instruction's parcels aren't all in the queue, WAITD, a
               word that decodes again
  reset        0

The decode table (U_DT0, U_DT1, 45 ns parts like the store's) maps an
instruction's first parcel (opcode and register byte) to its first
microinstruction's address and its length in parcels.

The queue. Two words, four parcels, each parcel held twice: in U_QD (onto
PD, the decode pointer's parcel) and U_QE (onto PE, the executing
instruction's extension pointer's parcel). The decode happens a cycle
before the instruction's first word executes, so the instruction's
registers come in two stages: U_NOP/U_NRB at the decode, U_OP/U_RB as it
starts (OP and the register byte on the backplane, d and s for the ALU
board), and the queue keeps the decoded instruction's start (NXP) beside
the executing one's (XP) and extension pointer (EP). A word is fetched
when a slot is free and the microinstruction leaves B free (FETCH, to
MEM); it lands in its slot at the cycle's end. A jump (PC loaded from A)
empties the queue.

PC is the address after the executing instruction: U_PCL holds bits 2-1
and the length the decode found (applied as the instruction starts), the
74F163s bits 21-3, counting on U_PCL's carry; both load from A on a jump.
"""

from heron.infra.hw import gal as G
from heron.infra.hw.netlist import Netlist

from . import bus as BP, fields as F
from .common import AND, OR, ONE, ZERO, anyof, bus, clock_buffer, control_slice, eq, gated_clock, lit, negate, table

TICK_PS = 19861
IVEC, WAITD = 0x0004, 0x0002


def f(name):
    return F.nets("CTRL", name)


def build(sim=True):
    nl = Netlist()
    nl.add("const", "X_RAIL", LO="GND", HI="VCC")
    clocks(nl, sim)
    ck = clock_buffer(nl, src="CYC")
    nl.section("control store")
    control_slice(nl, "CTRL", ck[0], direct=("JT", "SEQ", "CND", "CSPARE"))
    sequencer(nl, ck)
    nl.section("queue")
    queue(nl, ck)
    nl.section("immediates")
    immediates(nl)
    nl.section("PC")
    pc(nl, ck)
    BP.connectors(nl)
    nl.finish()
    return nl


def clocks(nl, sim):
    nl.section("clocks")
    if sim:
        nl.add("osc", "X_OSC", OUT="MCLK0", params={"period_ps": TICK_PS, "phase_ps": 5000})
    nl.add("04", "U_INV", part="74F04", **{"1A": "MCLK0", "1Y": "MCLKN0",
                                         **{f"{i}A": "GND" for i in range(2, 7)}})
    nl.add("clkdrv", "U_CKM", A="MCLK0", Y1="MCLK", **{f"Y{i}": f"MCLK_x{i}" for i in range(2, 9)})
    nl.add("clkdrv", "U_CKN", A="MCLKN0", Y1="MCLKN", **{f"Y{i}": f"MCLKN_x{i}" for i in range(2, 9)})
    nl.add("clkdrv", "U_CKC", A="CYC0", Y1="CYC", **{f"Y{i}": f"CYC_x{i}" for i in range(2, 9)})
    # U_CGA: the tick TC, CYC0 for ticks 0-1, WPH0 for the last two
    tc = ["TC0", "TC1", "TC2"]
    ins = tc + f("LEN") + ["WAIT_IO", "WAIT_V"]

    def nxt(t0, t1, t2, l0, l1, w0, w1):
        t, n = t0 | t1 << 1 | t2 << 2, 4 + (l0 | l1 << 1)
        if t >= n:
            return 0
        if t == n - 1:
            return 0
        if (w0 or w1) and t == n - 3:
            return t
        return t + 1

    def cyc_len(t0, t1, t2, l0, l1, w0, w1):
        return 4 + (l0 | l1 << 1)

    outs = {}
    for i in range(3):
        outs[f"TC{i}"] = (table(ins, lambda *b, i=i: (nxt(*b) >> i) & 1), True, False)
    outs["CYC0"] = (table(ins, lambda *b: nxt(*b) in (0, 1)), True, False)
    outs["WPH0"] = (table(ins, lambda *b: nxt(*b) >= cyc_len(*b) - 2), True, False)
    G.add(nl, "U_CGA", outs, clock="MCLK")


def sequencer(nl, ck):
    nl.section("sequencer")
    upcd = bus("UPCD", F.ADDR_BITS)
    for k in range(2):
        lo = 8 * k
        n = min(8, F.ADDR_BITS - lo)
        nl.add("574", f"U_UPC{k}", OE="GND", CLK=ck[0],
               **{f"D{i + 1}": upcd[lo + i] if i < n else "GND" for i in range(8)},
               **{f"Q{i + 1}": BP.UPC[lo + i] if i < n else f"UPC_NC{lo + i}" for i in range(8)})
    # the decode table: the parcel at the decode pointer -> entry, length
    dt = bus("DT", 14) + ["DLEN0", "DLEN1"]
    for k in range(2):
        nl.add("flash", f"U_DT{k}", CE="GND", OE="GND", WE="VCC",
               **{f"A{i}": f"PD{i}" for i in range(16)}, A16="GND",
               **{f"D{i}": dt[8 * k + i] for i in range(8)})
    jt, seq = f("JT"), f("SEQ")
    jump = eq(seq, F.SEQ_JUMP)
    for k, bits in enumerate((range(0, 5), range(5, 10), range(10, 14))):
        outs = {}
        for i in bits:
            take_jt = AND(jump, lit(jt[i], 1))
            if i == 0:
                take_jt = OR(AND(jump, lit(jt[0], 1), lit("COND", 0)),
                             AND(jump, lit(jt[0], 0), lit("COND", 1)))
            dec = negate(jump)
            irq = AND(dec, lit("IRQT")) if (IVEC >> i) & 1 else ZERO
            wait = AND(dec, lit("IRQT", 0), lit("READY", 0)) if (WAITD >> i) & 1 else ZERO
            entry = AND(dec, lit("IRQT", 0), lit("READY"), lit(f"DT{i}"))
            outs[upcd[i]] = (AND(lit("RESET_n"), OR(take_jt, irq, wait, entry)), False, False)
        G.add(nl, f"U_NA{k}", outs)
    # the condition: flags, MQ0, the address error, the instruction's cc.
    # A cc is a base condition (cc's bits 3-1) XORed with cc's bit 0: CCBO
    # and CCBD are the bases for the opcode's cc and d's
    cnd, op, rd = f("CND"), BP.OP, BP.RD
    flags = {"N": "FN", "Z": "FZ", "C": "FC", "V": "FV"}

    def base(code, n, z, c, v):
        return [z, c, n, v, c & (1 - z), int(n == v), int(z == 0 and n == v), 1][code]
    outs = {}
    for name, src in (("CCBO", op[1:4]), ("CCBD", rd[1:4])):
        nets = src + ["FN", "FZ", "FC", "FV"]
        outs[name] = (table(nets, lambda a, b, c_, n, z, c, v: base(a | b << 1 | c_ << 2, n, z, c, v)),
                      False, False)
    terms = []
    for name, code in F.CND.items():
        sel = eq(cnd, code)
        if name in flags:
            terms.append(AND(sel, lit(flags[name])))
        elif name in ("ST", "MQ0", "AERR"):
            terms.append(AND(sel, lit({"ST": "FST", "MQ0": "MQ0", "AERR": "AERR"}[name])))
        elif name in ("CC_OP", "CC_D"):
            b0, base_net = (op[0], "CCBO") if name == "CC_OP" else (rd[0], "CCBD")
            terms.append(AND(sel, OR(AND(lit(base_net), lit(b0, 0)), AND(lit(base_net, 0), lit(b0)))))
    outs["COND"] = (OR(*terms), False, False)
    G.add(nl, "U_COND", outs)


def queue(nl, ck):
    """The queue's registers, the instruction registers, and the GALs that
    keep the pointers (U_IQP), the parcels' valid bits (U_IQV), the slots'
    clocks (U_IQK) and the parcels' enables onto PD and PE (U_IQO)."""
    pd, pe = bus("PD", 16), bus("PE", 16)
    for p in range(4):
        src = BP.B[0:16] if p % 2 == 0 else BP.B[16:32]
        clk = f"QCK{p // 2}"
        for half in range(2):
            d = src[8 * half:8 * half + 8]
            nl.add("574", f"U_QD{p}{half}", OE=f"PDOE{p}_n", CLK=clk,
                   **{f"D{i + 1}": d[i] for i in range(8)},
                   **{f"Q{i + 1}": pd[8 * half + i] for i in range(8)})
            nl.add("574", f"U_QE{p}{half}", OE=f"PEOE{p}_n", CLK=clk,
                   **{f"D{i + 1}": d[i] for i in range(8)},
                   **{f"Q{i + 1}": pe[8 * half + i] for i in range(8)})
    # the instruction registers: decoded (at the decode), executing (as it starts)
    nop, nrb = bus("NOP", 8), bus("NRB", 8)
    nl.add("377", "U_NOP", CLK=ck[1], EN="DECODING_n",
           **{f"D{i + 1}": pd[i] for i in range(8)}, **{f"Q{i + 1}": nop[i] for i in range(8)})
    nl.add("377", "U_NRB", CLK=ck[1], EN="DECODING_n",
           **{f"D{i + 1}": pd[8 + i] for i in range(8)}, **{f"Q{i + 1}": nrb[i] for i in range(8)})
    rb = BP.RS + BP.RD                       # the register byte: s in its low nibble, d high
    nl.add("377", "U_OP", CLK=ck[1], EN="DEC1_n",
           **{f"D{i + 1}": nop[i] for i in range(8)}, **{f"Q{i + 1}": BP.OP[i] for i in range(8)})
    nl.add("377", "U_RB", CLK=ck[1], EN="DEC1_n",
           **{f"D{i + 1}": nrb[i] for i in range(8)}, **{f"Q{i + 1}": rb[i] for i in range(8)})
    # x: the index parcel's bits 15-12 as PE has them; and WPH onto the backplane
    nl.add("541", "U_XL", OE1="GND", OE2="GND",
           **{f"A{i + 1}": pe[12 + i] for i in range(4)}, A5="WPH0", A6="GND", A7="GND", A8="GND",
           **{f"Y{i + 1}": BP.RX[i] for i in range(4)}, Y5="WPH", Y6="XL_NC6", Y7="XL_NC7",
           Y8="XL_NC8")

    dp, ep, xp, nxp = ["DP0", "DP1"], ["EP0", "EP1"], ["XP0", "XP1"], ["NXP0", "NXP1"]
    pv = ["PV0", "PV1", "PV2", "PV3"]
    iqc, pcop = f("IQC"), f("PCOP")
    flush = eq(pcop, F.PCOP_LOAD)
    consume = anyof(iqc, [F.IQC_NEXT, F.IQC_H])

    def add2(a, k):
        return (a + k) & 3

    # U_IQP: the pointers, on the cycle's clock
    ins = dp + ["DLEN0", "DLEN1", "DECODING", "A1"] + pcop + ["RESET_n"]
    outs = {}
    for i in range(2):
        def dp_next(d0, d1, l0, l1, dec, a1, p0, p1, rst, i=i):
            if not rst:
                return 0
            if (p0 | p1 << 1) == F.PCOP_LOAD:
                return (a1 >> 0) & 1 if i == 0 else 0
            v = d0 | d1 << 1
            if dec:
                v = add2(v, l0 | l1 << 1)
            return (v >> i) & 1
        outs[dp[i]] = (table(ins, dp_next), True, False)
    # NXP: the decoded instruction's start (DP at the decode)
    for i in range(2):
        outs[nxp[i]] = (OR(AND(lit("DECODING"), lit(dp[i])), AND(lit("DECODING", 0), lit(nxp[i]))),
                        True, False)
    outs["DEC1"] = (AND(lit("DECODING"), lit("RESET_n"), negate(flush)), True, False)
    outs["DEC1_n"] = (AND(lit("DECODING"), lit("RESET_n"), negate(flush)), True, True)
    # XP: the executing instruction's start, from NXP as it starts; a jump
    # sets it where it sets DP, so that nothing is released before the
    # first decode
    for i in range(2):
        tgt = lit("A1") if i == 0 else ZERO
        outs[xp[i]] = (OR(AND(flush, tgt),
                          AND(negate(flush), OR(AND(lit("DEC1"), lit(nxp[i])),
                                                AND(lit("DEC1", 0), lit(xp[i]))))), True, False)
    G.add(nl, "U_IQP", outs, clock=ck[2])
    # U_IQE: the extension pointer: NXP + 1 as an instruction starts, + 1 a
    # parcel consumed
    ins = ep + nxp + ["DEC1"] + iqc

    def ep_next(e0, e1, n0, n1, d1, c0, c1, i=0):
        if d1:
            return add2(n0 | n1 << 1, 1)
        v = e0 | e1 << 1
        if (c0 | c1 << 1) in (F.IQC_NEXT, F.IQC_H):
            v = add2(v, 1)
        return v
    outs = {ep[i]: (table(ins, lambda *b, i=i: (ep_next(*b) >> i) & 1), True, False) for i in range(2)}
    # the parcels' enables onto PE (always: x is read from it) and PD
    for p in range(4):
        outs[f"PEOE{p}_n"] = (negate(eq(ep, p)), False, False)
    G.add(nl, "U_IQE", outs, clock=ck[2])
    # U_IQR: the parcels released as an instruction ends (those from XP up
    # to NXP, when DEC1 says the decoded one starts); the slot the next
    # word goes to (FS: DP's own if it holds no valid parcel, else the
    # other); READY, the decoded instruction's parcels all in the queue
    ins_r = xp + nxp + ["DEC1"] + dp + pv + ["DLEN0", "DLEN1"]

    def rel(x0, x1, n0, n1, d1, i):
        if not d1:
            return 0
        k, n = x0 | x1 << 1, n0 | n1 << 1
        while k != n:
            if k == i:
                return 1
            k = add2(k, 1)
        return 0
    outs = {}
    for i in range(4):
        outs[f"REL{i}"] = (table(xp + nxp + ["DEC1"], lambda *b, i=i: rel(*b, i)), False, False)
    outs["FS"] = (table(dp + pv, lambda d0, d1, *v: int(bool(v[2 * d1] or v[2 * d1 + 1])) ^ d1),
                  False, False)
    outs["READY"] = (table(dp + ["DLEN0", "DLEN1"] + pv, lambda d0, d1, l0, l1, *v: all(
        v[add2(d0 | d1 << 1, k)] for k in range(max(1, l0 | l1 << 1)))), False, False)
    G.add(nl, "U_IQR", outs)
    # U_IQV: the parcels' valid bits, and FETCH: a fetched word sets its
    # slot's (but a parcel before DP in DP's own slot: a jump's target may
    # be a word's second parcel)

    outs = {}
    for i in range(4):
        keep = AND(lit(pv[i]), lit(f"REL{i}", 0), lit("RESET_n"), negate(flush))
        fill = AND(lit("FETCH"), lit("FS", i // 2), lit("RESET_n"), negate(flush))
        if i % 2 == 0:
            # parcel 0 of a slot: not when DP is the slot's parcel 1
            fill = AND(fill, OR(lit("DP1", 1 - i // 2), lit("DP0", 0)))
        outs[pv[i]] = (OR(keep, fill), True, False)
    free = OR(AND(lit("FS", 0), lit("PV0", 0), lit("PV1", 0)), AND(lit("FS"), lit("PV2", 0), lit("PV3", 0)))
    outs["FETCH"] = (AND(free, lit(f("BFREE")[0]), lit(f("DACC")[0], 0), negate(flush), lit("RESET_n")),
                     False, False)
    G.add(nl, "U_IQV", outs, clock=ck[2])
    seq = f("SEQ")
    dec = anyof(seq, [F.SEQ_DECODE, F.SEQ_DECODE_NOIRQ])
    irqt = AND(eq(seq, F.SEQ_DECODE), lit("IRQ"), lit("IFLAG"))
    decoding = AND(dec, negate(irqt), lit("READY"), lit("RESET_n"))
    outs = {"IRQT": (irqt, False, False), "DECODING": (decoding, False, False),
            "DECODING_n": (decoding, False, True)}
    for p in range(4):
        outs[f"PDOE{p}_n"] = (negate(eq(dp, p)), False, False)
    G.add(nl, "U_IQO", outs)
    # U_IQK: the slots' clocks (QCK0, QCK1) and H's, gated at the cycle's end
    outs = {}
    gated_clock(outs, "QCK0", AND(lit("FETCH"), lit("FS", 0)), clk=ck[3])
    gated_clock(outs, "QCK1", AND(lit("FETCH"), lit("FS")), clk=ck[3])
    gated_clock(outs, "HCK", eq(iqc, F.IQC_H), clk=ck[3])
    G.add(nl, "U_IQK", outs, clock="MCLK")


def immediates(nl):
    """What CTRL drives onto B: the extension parcel at PE (sign- or zero-
    extended, or as the high half), H and PE (a 32-bit constant, H loaded
    a cycle before), and constants from the executing instruction's fields
    or fixed ones (U_IMMG drives B0-B8, and FILL to the bits above)."""
    imm = f("IMM")
    I = F.IMM
    pe = bus("PE", 16)
    rd, rs, op = BP.RD, BP.RS, BP.OP
    gal_forms = [I[n] for n in ("Q", "NQ", "U7", "S8X2", "R4", "ZERO", "ONE", "FOUR", "VEC", "PE_HI")]

    outs = {}
    oe = anyof(imm, gal_forms)
    oe_no_s8 = anyof(imm, [c for c in gal_forms if c != I["S8X2"]])
    for b in range(9):
        terms = []
        if b < 4:
            terms.append(AND(eq(imm, I["Q"]), lit(rs[b])))
            terms.append(AND(eq(imm, I["NQ"]), lit(rs[b], 0)))
        else:
            terms.append(eq(imm, I["NQ"]))
        if b < 3:
            terms.append(AND(eq(imm, I["U7"]), lit(op[b])))
        elif b < 7:
            terms.append(AND(eq(imm, I["U7"]), lit(rs[b - 3])))
        if 2 <= b <= 5:
            terms.append(AND(eq(imm, I["R4"]), lit(rs[b - 2])))
        for name, value in (("ONE", 1), ("FOUR", 4), ("VEC", 0x40)):
            if (value >> b) & 1:
                terms.append(eq(imm, I[name]))
        # S8X2: B8-B1 from U_S8 (the register byte), B0 here
        outs[BP.B[b]] = (OR(*terms), False, False, oe if b == 0 else oe_no_s8)
    G.add(nl, "U_IMMG", outs)
    # FILL (B's bits above a form's) and the drivers' enables (U_IMMO),
    # PC's onto A among them
    outs = {}
    fill_ins = imm + rd[3:] + [pe[15]]

    def fill(i0, i1, i2, i3, d3, p15):
        c = i0 | i1 << 1 | i2 << 2 | i3 << 3
        if c == I["PE_SX"]:
            return p15
        if c == I["NQ"]:
            return 1
        if c == I["S8X2"]:
            return d3
        return 0
    outs["FILL"] = (table(fill_ins, fill), False, False)
    pcop = f("PCOP")
    outs.update({
        "OES8_n": (eq(imm, I["S8X2"]), False, True),
        "OEF9_n": (anyof(imm, gal_forms), False, True),
        "OEFH_n": (anyof(imm, [c for c in gal_forms if c != I["PE_HI"]] + [I["PE_SX"], I["PE_ZX"]]),
                   False, True),
        "OEPL_n": (anyof(imm, [I["PE_SX"], I["PE_ZX"]]), False, True),
        "OEPH_n": (anyof(imm, [I["PE_HI"], I["H_PE"]]), False, True),
        "OEH_n": (eq(imm, I["H_PE"]), False, True),
        "OEPC_n": (eq(pcop, F.PCOP_DRIVE), False, True),
    })
    G.add(nl, "U_IMMO", outs)
    nl.add("541", "U_S8", OE1="OES8_n", OE2="GND", **{f"A{i + 1}": (rs + rd)[i] for i in range(8)},
           **{f"Y{i + 1}": BP.B[1 + i] for i in range(8)})
    nl.add("541", "U_F9", OE1="OEF9_n", OE2="GND", **{f"A{i + 1}": "FILL" for i in range(8)},
           **{f"Y{i + 1}": BP.B[9 + i] for i in range(7)}, Y8="F9_NC")
    for k in range(2):
        nl.add("541", f"U_FH{k}", OE1="OEFH_n", OE2="GND", **{f"A{i + 1}": "FILL" for i in range(8)},
               **{f"Y{i + 1}": BP.B[16 + 8 * k + i] for i in range(8)})
        nl.add("541", f"U_PL{k}", OE1="OEPL_n", OE2="GND", **{f"A{i + 1}": pe[8 * k + i] for i in range(8)},
               **{f"Y{i + 1}": BP.B[8 * k + i] for i in range(8)})
        nl.add("541", f"U_PH{k}", OE1="OEPH_n", OE2="GND", **{f"A{i + 1}": pe[8 * k + i] for i in range(8)},
               **{f"Y{i + 1}": BP.B[16 + 8 * k + i] for i in range(8)})
        nl.add("574", f"U_H{k}", OE="OEH_n", CLK="HCK", **{f"D{i + 1}": pe[8 * k + i] for i in range(8)},
               **{f"Q{i + 1}": BP.B[8 * k + i] for i in range(8)})


def _n(bits):
    return sum(b << i for i, b in enumerate(bits))


def pc(nl, ck):
    """PC: bits 2-1 and the pending length in U_PCL, the interrupt flag I
    there too; bits 21-3 in 74F163s, counting on U_PCL's carry; onto A
    through 541s."""
    pcl = ["PC1", "PC2"]
    pnl = ["PNL0", "PNL1"]
    pcop, ifl = f("PCOP"), f("IFL")
    load = eq(pcop, F.PCOP_LOAD)
    ins = pcl + pnl + ["DEC1"] + pcop + ["A1", "A2"]

    def nxt(p1, p2, n0, n1, d1, o0, o1, a1, a2):
        if (o0 | o1 << 1) == F.PCOP_LOAD:
            return a1 | a2 << 1
        v = p1 | p2 << 1
        if d1:
            v = (v + (n0 | n1 << 1)) & 3
        return v
    outs = {pcl[i]: (table(ins, lambda *b, i=i: (nxt(*b) >> i) & 1), True, False) for i in range(2)}
    for i in range(2):
        outs[pnl[i]] = (OR(AND(lit("DECODING"), lit(f"DLEN{i}")), AND(lit("DECODING", 0), lit(pnl[i]))),
                        True, False)
    outs["IFLAG"] = (AND(lit("RESET_n"), OR(eq(ifl, F.IFL_SET), AND(negate(eq(ifl, F.IFL_CLEAR)), lit("IFLAG")))),
                     True, False)
    carry = table(pcl + pnl + ["DEC1"], lambda p1, p2, n0, n1, d1: int(
        d1 and (p1 | p2 << 1) + (n0 | n1 << 1) > 3))
    outs["PCCY"] = (carry, False, False)
    outs["PCLD_n"] = (load, False, True)
    G.add(nl, "U_PCL", outs, clock=ck[4])
    hi = [f"PC{i}" for i in range(3, 22)] + ["PC_NC22"]
    for k in range(5):
        q = hi[4 * k:4 * k + 4]
        d = BP.A[3 + 4 * k:7 + 4 * k]
        nl.add("163", f"U_PC{k}", CLK=ck[4], CLR="VCC", LOAD="PCLD_n",
               ENP="PCCY", ENT="PCCY" if k == 0 else f"PCRC{k - 1}",
               A=d[0], B=d[1], C=d[2], D=d[3], QA=q[0], QB=q[1], QC=q[2], QD=q[3], RCO=f"PCRC{k}")
    a_src = ["GND"] + pcl + hi[:19] + ["GND"] * 10
    for k in range(4):
        nl.add("541", f"U_PCA{k}", OE1="OEPC_n", OE2="GND",
               **{f"A{i + 1}": a_src[8 * k + i] for i in range(8)},
               **{f"Y{i + 1}": BP.A[8 * k + i] for i in range(8)})
