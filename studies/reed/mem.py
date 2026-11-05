"""The MEM board: 4 MB of RAM, the byte crossbar, MAR, FPC, MQ.

The RAM is two rows of four AS7C4096As (512K x 8), a byte lane each, on
the RAM's address net RA (bits 20-2 to every chip, bit 21 choosing the
row) from MAR or from FPC, and its data net MD.

  - MAR (three 574s) loads A, the effective address the ALU sends late in
    a cycle (MARLD), at the cycle's end (823s with a load enable);
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
# the virtual address's bits 25-12 (MAR's, FPC's), before the page map;
# RA21-RA12 are the physical address's, after it
RV = bus("RV", 26)


def vnet(i):
    """The net an address bit i from MAR or FPC drives: RA below 12, RV above."""
    return RA[i] if i < 12 else RV[i]


RENAME = {"uMARLD": "ALE", "uMSZ0": "SZ0", "uMSZ1": "SZ1"}


def f(name):
    return [RENAME.get(n, n) for n in F.nets("MEM", name)]


def build(sim=True):
    nl = Netlist()
    nl.add("const", "X_RAIL", LO="GND", HI="VCC")
    ck = clock_buffer(nl, src="CYC")
    nl.section("control store")
    control_slice(nl, "MEM", ck[0], rename={"uMARLD": "ALE", "uMSZ0": "MSZR0", "uMSZ1": "MSZR1"})
    nl.section("addresses")
    addresses(nl, ck)
    nl.section("page map")
    page_map(nl, ck)
    nl.section("RAM")
    ram(nl)
    nl.section("crossbar")
    crossbar(nl)
    nl.section("stores")
    stores(nl)
    nl.section("control")
    control(nl, ck)
    nl.section("faults")
    faults(nl, ck)
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
    # (823s on the clock the microinstruction's 574s take, loading while
    # ALE, this cycle's MARLD, is high)
    for k in range(3):
        nl.add("823", f"U_MAR{k}", OE="MAROE_n", CLK=ck[0], EN="ALE_n", CLR="VCC",
               **{f"D{i + 1}": AI[2 + 8 * k + i] for i in range(8)}, D9="GND",
               **{f"Q{i + 1}": vnet(2 + 8 * k + i) for i in range(8)}, Q9=f"MAR{k}_NC")
    fp = [f"FP{i}" for i in range(2, 22)]
    for k in range(5):
        q = fp[4 * k:4 * k + 4]
        d = AI[2 + 4 * k:6 + 4 * k]
        # (counting a word a fetch, a fetch that faults too: no fetch
        # follows it until a jump loads FPC, CTRL's FFQ)
        nl.add("163", f"U_FPC{k}", CLK=ck[1], CLR="VCC", LOAD="FPCLD_n",
               ENP="FETCH", ENT="FETCH" if k == 0 else f"FPRC{k - 1}",
               A=d[0], B=d[1], C=d[2], D=d[3], QA=q[0], QB=q[1], QC=q[2], QD=q[3], RCO=f"FPRC{k}")
    for k in range(3):
        src = fp[8 * k:8 * k + 8] + ["GND"] * 4
        dst = [vnet(i) for i in range(2 + 8 * k, 10 + 8 * k)]
        n = min(8, 22 - (2 + 8 * k))
        nl.add("541", f"U_FPA{k}", OE1="FETCH_n", OE2="GND",
               **{f"A{i + 1}": src[i] if i < n else "GND" for i in range(8)},
               **{f"Y{i + 1}": dst[i] if i < n else f"FPA_NC{k}{i}" for i in range(8)})


MAP_DATA = RA[12:22] + ["MV", "MW", "MX", "MSP5", "MSP6", "MSP7"]


def page_map(nl, ck):
    """The page map: two AS7C4096As (512K x 8) between the virtual address
    (RV21-RV12, from MAR or FPC) and the RAM's page bits (RA21-RA12), 128
    contexts of 1024 entries (a context is 4 MB: the virtual address's
    bits 21-12), each the physical page (bits 21-12) and V, W, X. CTX (an
    823 loaded from B by MOP CTXW: B6-B0, and B31 into bit 7) holds the
    context, its bit 7 the map's enable (reset clears it: the map is
    off). While the map translates (U_MAPC: enabled, and the address's
    bit 31 clear) it drives RA21-RA12; else the bypass's 541s pass the
    virtual address straight through (the map off, or the supervisor's
    window: bit 31 set). MOP MAPW writes the entry at CTX and MAR from B
    (bits 21-12, 2-0) through two 541s, in the write strobe's ticks.

    U_VA keeps what MAR and FPC don't hold: the address's bit 31 and
    whether its bits 30-22 are all 0, each loaded with MAR (ALE) or FPC
    (FLUSH); VA31 and VRNG are the access's (a fetch's, FPC's). U_PF
    gives the page map's reasons to fault (FSR's bits 0-4) and PF, any of
    them in an access: the entry isn't valid, a store to a page without
    W, a fetch from one without X, a translated address above 4 MB (bits
    30-22 not 0), a user's address with bit 31 set."""
    ctx = bus("CTX", 8)
    # (bit 7, the map's enable, from B31: ctx's bit 31)
    nl.add("823", "U_CTX", OE="GND", CLK=ck[1], EN="CTXW_n", CLR="RESET_n",
           **{f"D{i + 1}": BP.B[i] for i in range(7)}, D8=BP.B[31], D9="GND",
           **{f"Q{i + 1}": ctx[i] for i in range(8)}, Q9="CTX_NC")
    for k in range(2):
        nl.add("sram512", f"U_MAP{k}", role="fastram", CE="GND", OE="MAPOE_n", WE="MAPWE_n",
               **{f"A{i}": RV[12 + i] for i in range(10)},
               **{f"A{10 + i}": ctx[i] for i in range(7)}, A17="GND", A18="GND",
               **{f"IO{i}": MAP_DATA[8 * k + i] for i in range(8)})
    src = [RV[12 + i] for i in range(10)] + ["GND"] * 6
    for k in range(2):
        n = 8 if k == 0 else 2
        nl.add("541", f"U_BYP{k}", OE1="BYPOE_n", OE2="GND",
               **{f"A{i + 1}": src[8 * k + i] if i < n else "GND" for i in range(8)},
               **{f"Y{i + 1}": RA[12 + 8 * k + i] if i < n else f"BYP_NC{i}" for i in range(8)})
    wsrc = BP.B[12:20] + [BP.B[20], BP.B[21], BP.B[0], BP.B[1], BP.B[2], "GND", "GND", "GND"]
    wdst = RA[12:20] + [RA[20], RA[21], "MV", "MW", "MX", "MWD_NC5", "MWD_NC6", "MWD_NC7"]
    for k in range(2):
        nl.add("541", f"U_MW{k}", OE1="MAPWOE_n", OE2="GND",
               **{f"A{i + 1}": wsrc[8 * k + i] for i in range(8)},
               **{f"Y{i + 1}": wdst[8 * k + i] for i in range(8)})
    a = AI
    rng = OR(*[lit(a[i]) for i in range(22, 31)])
    outs = {
        "M31": (OR(AND(lit("ALE"), lit(a[31])), AND(lit("ALE", 0), lit("M31"))), True, False),
        "MRANGE": (OR(AND(lit("ALE"), rng), AND(lit("ALE", 0), lit("MRANGE"))), True, False),
        "F31": (OR(AND(lit("FLUSH"), lit(a[31])), AND(lit("FLUSH", 0), lit("F31"))), True, False),
        "FRANGE": (OR(AND(lit("FLUSH"), rng), AND(lit("FLUSH", 0), lit("FRANGE"))), True, False),
        "VA31": (OR(AND(lit("FETCH"), lit("F31")), AND(lit("FETCH", 0), lit("M31"))), False, False),
        "VRNG": (OR(AND(lit("FETCH"), lit("FRANGE")), AND(lit("FETCH", 0), lit("MRANGE"))), False, False),
    }
    G.add(nl, "U_VA", outs, clock=ck[0])
    mop = f("MOP")
    store = eq(mop, F.MOP["STORE"])
    acc = OR(lit("FETCH"), anyof(mop, [F.MOP["LOAD"], F.MOP["STORE"]]))
    en = lit("CTX7")
    tr = AND(en, lit("VA31", 0))
    why = {"PINV": AND(tr, lit("MV", 0)), "PWP": AND(tr, store, lit("MW", 0)),
           "PX": AND(tr, lit("FETCH"), lit("MX", 0)), "PRNG": AND(tr, lit("VRNG")),
           "PU31": AND(en, lit("VA31"), lit("S", 0))}
    outs = {n: (e, False, False) for n, e in why.items()}
    outs["PF"] = (AND(acc, OR(*why.values())), False, False)
    G.add(nl, "U_PF", outs)
    mapw = eq(mop, F.MOP["MAPW"])
    outs = {
        "MAPOE_n": (AND(tr, negate(mapw)), False, True),
        "BYPOE_n": (AND(negate(tr), negate(mapw)), False, True),
        "MAPWOE_n": (mapw, False, True),
        "MAPWE_n": (AND(mapw, lit("WRSE", 0), lit("KILL_n")), False, True),
        "CTXW_n": (AND(eq(mop, F.MOP["CTXW"]), lit("KILL_n")), False, True),
    }
    G.add(nl, "U_MAPC", outs)


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
    # U_SZ: the access's size (SZ, on the backplane too): the
    # microinstruction's, or for MSZ INDEX the index parcel's (IZ, from CTRL)
    G.add(nl, "U_SZ", {f"SZ{i}": (OR(AND(lit("MSZR0", 0), lit(f"MSZR{i}")),
                                     AND(lit("MSZR1", 0), lit(f"MSZR{i}")),
                                     AND(lit("MSZR0"), lit("MSZR1"), lit(BP.IZ[i]))), False, False)
                       for i in range(2)})
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
    # U_LN0, on MAR's clock: the address's bits 1-0 and A30, loading with
    # MAR (else held); lanes 0-1's selects
    def held(net, src):
        return (OR(AND(lit("ALE"), lit(src)), AND(lit("ALE", 0), lit(net))), True, False)
    outs = {"AL0": held("AL0", "AI0"), "AL1": held("AL1", "AI1"), "IOSP": held("IOSP", "AI30"),
            "FETCH_n": (lit("FETCH", 0), False, False)}
    for j in (0, 1):
        sa, sb, z = sel_fns(j)
        outs[f"XSA{j}"], outs[f"XSB{j}"], outs[f"XG{j}"] = (sa, False, False), (sb, False, False), (z, False, False)
    G.add(nl, "U_LN0", outs, clock=ck[0])
    outs = {}
    for j in (2, 3):
        sa, sb, z = sel_fns(j)
        outs[f"XSA{j}"], outs[f"XSB{j}"], outs[f"XG{j}"] = (sa, False, False), (sb, False, False), (z, False, False)
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
    # and two of MQ's (U_MC is full)
    mq = f("MQ")
    outs["MQS0"] = (eq(mq, F.MQ["LOAD"]), False, False)
    outs["MQOE_n"] = (eq(mq, F.MQ["DRIVE"]), False, True)
    G.add(nl, "U_ST", outs)
    # U_WE: each row's lanes' write strobes, while WRS is, in a store to RAM,
    # for the lanes the size and address choose
    # (WRSE: the strobe a tick into the write phase, which ends a tick
    # before the cycle does; the register file's WRS is half a tick later)
    st_w = AND(store, ram_, lit("WRSE", 0), lit("KILL_n"))
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
    # U_MC: MAR's load enable; the enables; the I/O space's strobes; MQ's S1
    outs = {"ALE_n": (lit("ALE"), False, True)}
    mq = f("MQ")
    outs.update({
        "MAROE_n": (lit("FETCH"), False, False),
        "FPCLD_n": (lit("FLUSH"), False, True),
        "MXOE_n": (OR(AND(load, ram_), lit("FETCH")), False, True),
        "IORD_n": (AND(load, io, lit("KILL_n")), False, True),
        "IOWR_n": (AND(store, io, lit("KILL_n")), False, True),
        "FAROE_n": (eq(mop, F.MOP["FARR"]), False, True),
        # 299 modes: hold 0, shift toward IO0 2, load 3 (S0 in U_ST); drive:
        # hold with the outputs on (MQOE_n, in U_ST)
        "MQS1": (anyof(mq, [F.MQ["LOAD"], F.MQ["SHIFT"]]), False, False),
    })
    G.add(nl, "U_MC", outs)




FAR = bus("FAR", 36)


def faults(nl, ck):
    """U_SYS: S, the supervisor's mode (set by reset, loaded from B31 by
    MOP SYSW); FAULT, a load or store that faults (misaligned: a word not
    on a word, a half not on a half; z 3, an index parcel's size that
    isn't one; or the page map's, PF), which cancels the cycle; KILLQ,
    FAULT a cycle late, which cancels the next; KILL_n, either (CTRL's and
    ALU's words clear, MEM's strobes don't come); FFLT, a fetch's fault
    (the page map's), whose word the queue doesn't take.
    FAR and FSR (four 823s) take the faulting access's address and why at
    the cycle's end; MOP FARR reads them onto B: the address's bits 21-0
    and 31 (B21-B0, B31), and FSR in B30-B22 (bits 0-4 the page map's
    reasons, 5 a store, 6 a fetch, 7 misaligned, 8 z 3)."""
    mop, sz = f("MOP"), BP.SZ
    acc = anyof(mop, [F.MOP["LOAD"], F.MOP["STORE"]])
    S = F.MSZ
    align = OR(AND(eq(sz, S["WORD"]), OR(lit("AL0"), lit("AL1"))), AND(eq(sz, S["HALF"]), lit("AL0")))
    z3 = AND(lit(sz[0]), lit(sz[1]))
    fault = AND(acc, OR(align, z3, lit("PF")), lit("KILLQ", 0))
    ffl = AND(lit("FETCH"), lit("PF"))
    sysw = AND(eq(mop, F.MOP["SYSW"]), lit("KILL_n"))
    outs = {
        "FAULT": (fault, False, False),
        "KILLQ": (AND(lit("RESET_n"), fault), True, False),
        "KILL_n": (OR(fault, lit("KILLQ")), False, True),
        "FAREN_n": (OR(fault, ffl), False, True),
        "S": (OR(lit("RESET_n", 0), AND(sysw, lit(BP.B[31])), AND(negate(sysw), lit("S"))), True, False),
        "FFLT": (ffl, False, False),
        "FSALIGN": (align, False, False),
        "FSZ3": (z3, False, False),
        "FSSTORE": (eq(mop, F.MOP["STORE"]), False, False),
    }
    G.add(nl, "U_SYS", outs, clock=ck[0])
    # (bits 21-12 the virtual address's, RV, not the page map's)
    src = (["AL0", "AL1"] + RA[2:12] + RV[12:22] + ["PINV", "PWP", "PX", "PRNG", "PU31"]
           + ["FSSTORE", "FETCH", "FSALIGN", "FSZ3", "VA31"] + ["GND"] * 4)
    for k in range(4):
        nl.add("823", f"U_FAR{k}", OE="FAROE_n", CLK=ck[1], EN="FAREN_n", CLR="VCC",
               **{f"D{i + 1}": src[9 * k + i] for i in range(9)},
               **{f"Q{i + 1}": BP.B[9 * k + i] if 9 * k + i < 32 else f"FAR_NC{9 * k + i}" for i in range(9)})


def mq(nl, ck):
    """MQ: chip k holds bits 8k-8k+7 (its IO0 the lowest); mode 2 (S1 high,
    S0 low) shifts toward IO0, DS7 coming in at IO7."""
    for k in range(4):
        nl.add("299", f"U_MQ{k}", S0="MQS0", S1="MQS1", OE1="MQOE_n", OE2="GND", MR="RESET_n",
               CP=ck[3], DS0="GND", DS7="QIN" if k == 3 else f"MQS{k + 1}_0",
               **{f"IO{i}": BP.B[8 * k + i] for i in range(8)},
               Q0S="MQ0" if k == 0 else f"MQS{k}_0", Q7S=f"MQS{k}_7")
