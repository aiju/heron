"""The MEM board: 4 MB of RAM, the byte crossbar, MAR, FPC, MQ.

The RAM is two rows of four AS7C4096As (512K x 8), a byte lane each, on
the RAM's address net RA (bits 20-2 to every chip, bit 21 choosing the
row) from MAR or from FPC, and its data net MD.

  - MAR (three 574s) loads A, the effective address the ALU sends late in
    a cycle (MARLD), at the cycle's end, through a gated clock (MARCK);
    U_LN0 keeps the address's bits 1-0 and whether it's in the I/O space
    (A30). FPC (74F163s) loads A for a jump (MOP FPC) and counts a word a
    fetch.
  - Loads: MD through the crossbar (16 74F153s, each byte lane taking any
    of the four or zero, by U_LN0 and U_LN1 from the size and the
    address's bits 1-0) onto MX, and onto B (U_MX). A fetch (FETCH from
    CTRL) is a word, onto B for CTRL's queue.
  - Stores: the data comes on A (the address has gone into MAR the cycle
    before): through the A receivers onto the lanes, a byte or a half
    replicated so that the lane the address chooses has it (U_ST*, enabled
    by U_ST in the write phase); U_WE gives the lanes' write strobes, while
    WRS is.
  - An access with A30 set is the I/O space's: MEM leaves the RAM alone and
    gives IORD_n or IOWR_n to the I/O boards, which latched the address as
    MAR did (ALE).
  - MQ (four 74F299s) is the multiply and divide steps' shift register, on
    B: loaded, shifted right with QIN (the ALU's last result's bit 0) in at
    the top, driven back onto B; MQ0 tells the ALU board's function.
"""

from heron.infra.hw import gal as G
from heron.infra.hw.netlist import Netlist

from . import bus as BP, fields as F
from .common import AND, OR, ONE, ZERO, anyof, bus, clock_buffer, control_slice, eq, gated_clock, lit, negate, table

AI, RA, MD, MX = bus("AI", 32), bus("RA", 26), bus("MD", 32), bus("MX", 32)


RENAME = {"uMARLD": "ALE", "uMSZ0": "SZ0", "uMSZ1": "SZ1"}


def f(name):
    return [RENAME.get(n, n) for n in F.nets("MEM", name)]


def build(sim=True):
    nl = Netlist()
    nl.add("const", "X_RAIL", LO="GND", HI="VCC")
    ck = clock_buffer(nl, src="CYC")
    nl.section("control store")
    control_slice(nl, "MEM", ck[0], rename={"uMARLD": "ALE", "uMSZ0": "SZ0", "uMSZ1": "SZ1"})
    nl.section("addresses")
    addresses(nl, ck)
    nl.section("RAM")
    ram(nl)
    nl.section("crossbar")
    crossbar(nl)
    nl.section("stores")
    stores(nl)
    nl.section("control")
    control(nl, ck)
    nl.section("MQ")
    mq(nl, ck)
    BP.connectors(nl)
    nl.finish()
    return nl


def addresses(nl, ck):
    for k in range(4):
        nl.add("541", f"U_AR{k}", OE1="GND", OE2="GND",
               **{f"A{i + 1}": BP.A[8 * k + i] for i in range(8)},
               **{f"Y{i + 1}": AI[8 * k + i] for i in range(8)})
    # MAR: bits 25-2 onto RA, but while FPC drives it
    for k in range(3):
        nl.add("574", f"U_MAR{k}", OE="MAROE_n", CLK="MARCK",
               **{f"D{i + 1}": AI[2 + 8 * k + i] for i in range(8)},
               **{f"Q{i + 1}": RA[2 + 8 * k + i] for i in range(8)})
    fp = [f"FP{i}" for i in range(2, 22)]
    for k in range(5):
        q = fp[4 * k:4 * k + 4]
        d = AI[2 + 4 * k:6 + 4 * k]
        nl.add("163", f"U_FPC{k}", CLK=ck[1], CLR="VCC", LOAD="FPCLD_n",
               ENP="FETCH", ENT="FETCH" if k == 0 else f"FPRC{k - 1}",
               A=d[0], B=d[1], C=d[2], D=d[3], QA=q[0], QB=q[1], QC=q[2], QD=q[3], RCO=f"FPRC{k}")
    for k in range(3):
        src = fp[8 * k:8 * k + 8] + ["GND"] * 4
        dst = RA[2 + 8 * k:10 + 8 * k]
        n = min(8, 22 - (2 + 8 * k))
        nl.add("541", f"U_FPA{k}", OE1="FETCH_n", OE2="GND",
               **{f"A{i + 1}": src[i] if i < n else "GND" for i in range(8)},
               **{f"Y{i + 1}": dst[i] if i < n else f"FPA_NC{k}{i}" for i in range(8)})


def ram(nl):
    for row in range(2):
        for lane in range(4):
            nl.add("sram512", f"U_RAM{row}{lane}", role="fastram",
                   CE=f"RCE{row}_n", OE="MXOE_n", WE=f"WE{row}{lane}_n",
                   **{f"A{i}": RA[2 + i] for i in range(19)},
                   **{f"IO{i}": MD[8 * lane + i] for i in range(8)})


def crossbar(nl):
    """Output lane j, bit 2k and 2k+1 of it, from each source lane's same
    bits: a 74F153 (its strobe forces 0)."""
    for j in range(4):
        for k in range(4):
            b0, b1 = 2 * k, 2 * k + 1
            nl.add("153", f"U_XB{j}{k}", A=f"XSA{j}", B=f"XSB{j}", **{"1G": f"XG{j}", "2G": f"XG{j}"},
                   **{f"1C{s}": MD[8 * s + b0] for s in range(4)},
                   **{f"2C{s}": MD[8 * s + b1] for s in range(4)},
                   **{"1Y": MX[8 * j + b0], "2Y": MX[8 * j + b1]})
    for k in range(4):
        nl.add("541", f"U_MX{k}", OE1="MXOE_n", OE2="GND",
               **{f"A{i + 1}": MX[8 * k + i] for i in range(8)},
               **{f"Y{i + 1}": BP.B[8 * k + i] for i in range(8)})


def stores(nl):
    """Lane l of MD from lane s of the data on A (AI): (l, s) for each
    driver, its enable ST{l}{s}_n."""
    for l, s in ((0, 0), (1, 1), (1, 0), (2, 2), (2, 0), (3, 3), (3, 1), (3, 0)):
        nl.add("541", f"U_ST{l}{s}", OE1=f"ST{l}{s}_n", OE2="GND",
               **{f"A{i + 1}": AI[8 * s + i] for i in range(8)},
               **{f"Y{i + 1}": MD[8 * l + i] for i in range(8)})


def control(nl, ck):
    mop, msz = f("MOP"), f("MSZ")
    load, store = eq(mop, F.MOP["LOAD"]), eq(mop, F.MOP["STORE"])
    S = F.MSZ
    al = ["AL0", "AL1"]
    io = lit("IOSP")
    ram_ = lit("IOSP", 0)

    def lane_src(j, size, a0, a1):
        """The source lane for output lane j of a load, or None for 0."""
        if size == S["WORD"]:
            return j
        if size == S["HALF"]:
            return (2 * a1 + j) if j < 2 else None
        return (2 * a1 + a0) if j == 0 else None

    def sel_fns(j):
        ins = msz + al
        sa = table(ins, lambda s0, s1, a0, a1: None if (s0 | s1 << 1) == 3 else (
            (lane_src(j, s0 | s1 << 1, a0, a1) or 0) & 1))
        sb = table(ins, lambda s0, s1, a0, a1: None if (s0 | s1 << 1) == 3 else (
            ((lane_src(j, s0 | s1 << 1, a0, a1) or 0) >> 1) & 1))
        zero = table(ins, lambda s0, s1, a0, a1: None if (s0 | s1 << 1) == 3 else int(
            lane_src(j, s0 | s1 << 1, a0, a1) is None))
        # a fetch is a word: lane j from lane j
        sa = OR(AND(lit("FETCH", 0), sa), AND(lit("FETCH"), [{}] if j & 1 else ZERO))
        sb = OR(AND(lit("FETCH", 0), sb), AND(lit("FETCH"), [{}] if j & 2 else ZERO))
        zero = AND(lit("FETCH", 0), zero)
        return sa, sb, zero
    # U_LN0, clocked by MARCK: the address's bits 1-0 and A30; lanes 0-1's selects
    outs = {"AL0": (lit("AI0"), True, False), "AL1": (lit("AI1"), True, False),
            "IOSP": (lit("AI30"), True, False), "FETCH_n": (lit("FETCH", 0), False, False)}
    for j in (0, 1):
        sa, sb, z = sel_fns(j)
        outs[f"XSA{j}"], outs[f"XSB{j}"], outs[f"XG{j}"] = (sa, False, False), (sb, False, False), (z, False, False)
    G.add(nl, "U_LN0", outs, clock="MARCK")
    outs = {}
    for j in (2, 3):
        sa, sb, z = sel_fns(j)
        outs[f"XSA{j}"], outs[f"XSB{j}"], outs[f"XG{j}"] = (sa, False, False), (sb, False, False), (z, False, False)
    # the address error: a misaligned word or half
    outs["AERR"] = (OR(AND(OR(load, store), eq(msz, S["WORD"]), OR(lit("AL0"), lit("AL1"))),
                       AND(OR(load, store), eq(msz, S["HALF"]), lit("AL0"))), False, False)
    # the rows' chip enables (row 1 for RA21 set; neither while the access is the I/O space's)
    outs["RCE0_n"] = (OR(lit("RA21", 0), AND(io, lit("FETCH", 0))), False, True)
    outs["RCE1_n"] = (OR(lit("RA21"), AND(io, lit("FETCH", 0))), False, True)
    G.add(nl, "U_LN1", outs)
    # the store lanes' drivers, in the write phase of a store to RAM
    st = AND(store, ram_, lit("WPH"))
    word, half, byte = eq(msz, S["WORD"]), eq(msz, S["HALF"]), eq(msz, S["BYTE"])
    en = {(0, 0): ONE, (1, 1): OR(word, half), (1, 0): byte, (2, 2): word, (2, 0): OR(half, byte),
          (3, 3): word, (3, 1): half, (3, 0): byte}
    outs = {f"ST{l}{s}_n": (AND(st, e), False, True) for (l, s), e in en.items()}
    G.add(nl, "U_ST", outs)
    # U_WE: each row's lanes' write strobes, while WRS is, in a store to RAM,
    # for the lanes the size and address choose
    st_w = AND(store, ram_, lit("WRS", 0))
    outs = {}
    for row in range(2):
        rsel = lit("RA21", row)
        for lane in range(4):
            sel = table(msz + al, lambda s0, s1, a0, a1, lane=lane: None if (s0 | s1 << 1) == 3 else int(
                (s0 | s1 << 1) == S["WORD"] or ((s0 | s1 << 1) == S["HALF"] and lane // 2 == a1)
                or ((s0 | s1 << 1) == S["BYTE"] and lane == 2 * a1 + a0)))
            n = f"WE{row}{lane}_n"
            outs[n] = (AND(st_w, rsel, sel), False, True)
    G.add(nl, "U_WE", outs)
    # U_MC, on MCLK: MAR's gated clock; the enables; the I/O space's strobes; MQ's mode
    outs = {}
    gated_clock(outs, "MARCK", lit("ALE"), clk=ck[2])
    mq = f("MQ")
    outs.update({
        "MAROE_n": (lit("FETCH"), False, False),
        "FPCLD_n": (eq(mop, F.MOP["FPC"]), False, True),
        "MXOE_n": (OR(AND(load, ram_), lit("FETCH")), False, True),
        "IORD_n": (AND(load, io), False, True),
        "IOWR_n": (AND(store, io), False, True),
        # 299 modes: hold 0, shift toward IO0 2, load 3; drive: hold with the outputs on
        "MQS0": (eq(mq, F.MQ["LOAD"]), False, False),
        "MQS1": (anyof(mq, [F.MQ["LOAD"], F.MQ["SHIFT"]]), False, False),
        "MQOE_n": (eq(mq, F.MQ["DRIVE"]), False, True),
    })
    G.add(nl, "U_MC", outs, clock="MCLK")




def mq(nl, ck):
    """MQ: chip k holds bits 8k-8k+7 (its IO0 the lowest); mode 2 (S1 high,
    S0 low) shifts toward IO0, DS7 coming in at IO7."""
    for k in range(4):
        nl.add("299", f"U_MQ{k}", S0="MQS0", S1="MQS1", OE1="MQOE_n", OE2="GND", MR="RESET_n",
               CP=ck[3], DS0="GND", DS7="QIN" if k == 3 else f"MQS{k + 1}_0",
               **{f"IO{i}": BP.B[8 * k + i] for i in range(8)},
               Q0S="MQ0" if k == 0 else f"MQS{k}_0", Q7S=f"MQS{k}_7")
