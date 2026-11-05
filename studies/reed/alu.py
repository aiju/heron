"""The ALU board: the register file, the ALU, the flags.

The register file is two copies of 64K x 32 (four IS61C6416s, each as two
8-bit halves), one per read port, both written with every result. Its
read and write share each cycle, through latches:

  - from the board's clock (CK2, Y's) until the write phase, LE is high:
    the copies read (their addresses from U_RAG0-1 and U_RBG0-1: d, s, x
    or the microinstruction's K), and the 74ABT573 latches pass their
    data to the ALU's inputs, OA and OB. Opening on CK2, the latches
    can't pass the next read before the board has taken the result;
  - otherwise (from the write phase, WPH, the cycle's last three ticks,
    until the board's clock) the latches hold, and since the addresses
    and enables take LEW (LE's copy), they change only after the latches have closed:
    the copies' addresses switch to W (the last cycle's destination, held
    in U_WG), and Y_A and Y_B (574s that
    took the last cycle's result) write it, RFWEA_n and RFWEB_n low while WRS
    is (the write phase's middle tick) and once each copy's address is W;
  - a read of the register the write phase is about to write takes Y
    instead of the copy (U_BYP compares both ports' addresses with W and
    drives the copies', Y's and the latches' enables), so a result is
    readable in the next cycle. The address muxes and U_BYP are the
    22V10's 5 ns grade: the read and the bypass then fit a 5-tick cycle.

The ALU is eight 74F181s with their carry lookahead in U_CLA; U_ALUF gives
their function and carry from the microinstruction's AOP and CI alone
(the opcode doesn't reach this board: each operation's microcode names
its function, carry and flags). OA comes from copy A or from the
A bus (U_XA); OB from copy B, the B bus (U_XB), or OA shifted right a bit
(U_SH, the bit in from U_BUS). F goes to Y_A and Y_B, and onto A (U_FA),
an address that leaves in the cycle it's made.

The flags: U_ZL and U_ZH register whether each half of F is zero; U_FLA
keeps C and V, and QIN, the result's bit 0, for MQ; U_FLB keeps N, the
microcode's ST and Z (FZ, from the zero halves of the cycle before when it
set Z, else held).
"""

from heron.infra.hw import gal as G
from heron.infra.hw.netlist import Netlist

from . import bus as BP, fields as F
from .parts import FAST_GAL
from .common import AND, OR, ONE, ZERO, anyof, bus, clock_buffer, control_slice, eq, lit, negate, table


def f(name):
    return F.nets("ALU", name)


def build(sim=True):
    nl = Netlist()
    nl.add("const", "X_RAIL", LO="GND", HI="VCC")
    ck = clock_buffer(nl, src="CYC")
    nl.section("control store")
    control_slice(nl, "ALU", ck[0], clear="KILL_n")
    nl.section("register file")
    register_file(nl, ck)
    nl.section("ALU")
    alu(nl, ck)
    nl.section("buses")
    buses(nl)
    nl.section("flags")
    flags(nl, ck)
    BP.connectors(nl)
    nl.finish()
    return nl


RAD, RBD = bus("RAD", 32), bus("RBD", 32)
OA, OB, FN = bus("OA", 32), bus("OB", 32), bus("F", 32)
RFA, RFB, W = bus("RFA", 5), bus("RFB", 5), bus("W", 5)


EB = bus("EB", 9)


def register_file(nl, ck):
    # the bank (EB): the copies' address bits 5-13, from B as a word with
    # EBLD ends (an 823 on the board's clock); 0-255 r0-r15 and the
    # microcode's registers of a bank, 256 the system's (the special
    # registers, bank 0x100)
    nl.add("823", "U_EB", OE="GND", CLK=ck[1], EN="EBLD_n", CLR="VCC",
           **{f"D{i + 1}": BP.B[i] for i in range(9)}, **{f"Q{i + 1}": EB[i] for i in range(9)})
    for copy, addr, data, oe in (("A", RFA, RAD, "RFOEA_n"), ("B", RFB, RBD, "RFOEB_n")):
        a = {f"A{i}": addr[i] for i in range(5)}
        a.update({f"A{i}": EB[i - 5] for i in range(5, 14)})
        a.update({f"A{i}": "GND" for i in range(14, 16)})
        for k in range(4):
            nl.add("sram64k", f"U_RF{copy}{k}", CE="GND", OE=oe, WE=f"RFWE{copy}_n", **a,
                   **{f"IO{i}": data[8 * k + i] for i in range(8)})
            out = OA if copy == "A" else OB
            nl.add("573", f"U_L{copy}{k}", OE=f"L{copy}OE_n", LE="LE",
                   **{f"D{i + 1}": data[8 * k + i] for i in range(8)},
                   **{f"Q{i + 1}": out[8 * k + i] for i in range(8)})
            nl.add("574", f"U_Y{copy}{k}", OE=f"Y{copy}OE_n", CLK=ck[1 + k // 2],
                   **{f"D{i + 1}": FN[8 * k + i] for i in range(8)},
                   **{f"Q{i + 1}": data[8 * k + i] for i in range(8)})
    # the executing instruction's d and s: CTRL's U_RB's copy, from the
    # decoded ones on the backplane, a cycle before they're needed
    nl.add("377", "U_RB", CLK=ck[1], EN="DEC1_n",
           **{f"D{i + 1}": (BP.NRS + BP.NRD)[i] for i in range(8)},
           **{f"Q{i + 1}": (BP.RS + BP.RD)[i] for i in range(8)})
    rd, rs, rx, k = BP.RD, BP.RS, BP.RX, f("K")

    def sel(field, choices):
        """{address bit: sum of products} of a port's select."""
        out = []
        for i in range(5):
            terms = []
            for code, src in choices.items():
                if src == "K":
                    terms.append(AND(eq(field, code), lit(k[i])))
                elif i < 4:
                    terms.append(AND(eq(field, code), lit(src[i])))
            out.append(OR(*terms))
        return out
    # the copies' addresses: the port's register outside the write phase, W
    # in it (U_RAG0-1 for copy A, U_RBG0-1 for copy B, bits 0-2 and 3-4)
    w = W
    ra = sel(f("RAS"), {F.RAS["d"]: rd, F.RAS["s"]: rs, F.RAS["K"]: "K"})
    rb = sel(f("RBS"), {F.RBS["s"]: rs, F.RBS["x"]: rx, F.RBS["K"]: "K"})
    for name, addr, fn in (("U_RAG", RFA, ra), ("U_RBG", RFB, rb)):
        for part, bits in enumerate((range(0, 3), range(3, 5))):
            # (with the consensus terms, W's bit and the read's: a bit
            # that's the same on both sides doesn't glitch as LEW switches)
            outs = {addr[i]: (OR(AND(lit("LEW", 0), lit(w[i])), AND(lit("LEW"), fn[i]),
                                 AND(lit(w[i]), fn[i])), False, False)
                    for i in bits}
            if (name, part) == ("U_RAG", 1):
                latch_enables(outs, ck)
            if (name, part) == ("U_RBG", 1):
                # the bank's load enable (EBLD is 0 in a cancelled word)
                outs["EBLD_n"] = (lit(f("EBLD")[0]), False, True)
            G.add(nl, f"{name}{part}", outs).part = FAST_GAL
    # W: this cycle's destination, for the next cycle's write phase
    wsel = sel(f("WS"), {F.WS["d"]: rd, F.WS["s"]: rs, F.WS["K"]: "K"})
    outs = {W[i]: (wsel[i], True, False) for i in range(5)}
    outs["WEN"] = (negate(eq(f("WS"), F.WS["NONE"])), True, False)
    G.add(nl, "U_WG", outs, clock=ck[1])
    # U_BYP: the bypass (the port's address is W, and W is to be written),
    # straight from the addresses: each copy's outputs, off in the write
    # phase and when Y bypasses it, and Y's
    outs = {}
    for c, addr in (("A", RFA), ("B", RFB)):
        # reading, and not W's: the copy drives, Y doesn't
        own = [AND(lit("LEW"), lit("WEN", 0))]
        for i in range(5):
            own += [AND(lit("LEW"), lit(addr[i]), lit(W[i], 0)),
                    AND(lit("LEW"), lit(addr[i], 0), lit(W[i]))]
        outs[f"RFOE{c}_n"] = (OR(*own), False, True)
        outs[f"Y{c}OE_n"] = (OR(*own), False, False)
    G.add(nl, "U_BYP", outs).part = FAST_GAL
    # U_RFW: each copy's write strobe, while WRS is and W is to be written,
    # and only once the copy's address is W: each address bit changes once
    # in the write phase, so the address can't match before its last bit
    # has come, and the strobe can't start before the address is there
    outs = {}
    for c, addr in (("A", RFA), ("B", RFB)):
        terms = [AND(lit("WRS")), AND(lit("WEN", 0))]
        for i in range(5):
            terms += [AND(lit(addr[i]), lit(W[i], 0)), AND(lit(addr[i], 0), lit(W[i]))]
        outs[f"RFWE{c}_n"] = (OR(*terms), False, False)
    G.add(nl, "U_RFW", outs).part = FAST_GAL



def latch_enables(outs, ck):
    """LE, the latches' enable, opened by this board's clock (Y's) and held
    open (its own pin, fed back) until the write phase, so that the next
    read can't reach the ALU before the board has taken the result, and a
    longer cycle gives the read longer; LEW, the same, for the copies'
    addresses and the copies' and Y's enables, which so change only while
    the latches are closed (sta.EXCEPTIONS). In U_RAG1, beside RFA3-4.
    (WPA: the ALU's write phase, from half a tick after WPH to half a
    tick into the next cycle; clockcard.py)"""
    le = OR(AND(lit("WPA", 0), lit(ck[1])), AND(lit("WPA", 0), lit("LE")))
    outs["LE"] = (le, False, False)
    outs["LEW"] = (le, False, False)


def alu(nl, ck):
    cn = [f"CN{i}" for i in range(8)]
    for k in range(8):
        nl.add("181", f"U_ALU{k}", M="AM", S0="AS0", S1="AS1", S2="AS2", S3="AS3", CN=cn[k],
               **{f"A{i}": OA[4 * k + i] for i in range(4)}, **{f"B{i}": OB[4 * k + i] for i in range(4)},
               **{f"F{i}": FN[4 * k + i] for i in range(4)}, G=f"G{k}", P=f"P{k}",
               CN4="C32_n" if k == 7 else f"ALU_CN4_{k}", AEQB=f"ALU_AEQB{k}")
    # the lookahead: CN_k (active low, as the 181 takes it) from the slices'
    # G and P (active low) and CN0
    outs = {}
    for kk in range(1, 8):
        # carry into slice kk: some slice j < kk generates and the ones
        # between propagate, or the carry in propagates through all
        terms = []
        for j in range(kk):
            terms.append({f"G{j}": 0, **{f"P{m}": 0 for m in range(j + 1, kk)}})
        terms.append({"CN0": 0, **{f"P{m}": 0 for m in range(kk)}})
        outs[cn[kk]] = (terms, False, True)
    G.add(nl, "U_CLA", outs)
    # U_ALUF: the function, from AOP
    aop, ci = f("AOP"), f("CI")
    A = F.AOP
    # (S3-S0, M, carry in as the 181 takes it: 1 = none) for each AOP
    FUN = {"ADD": (0b1001, 0, 1), "SUB": (0b0110, 0, 0), "AND": (0b1011, 1, 1), "OR": (0b1110, 1, 1),
           "XOR": (0b0110, 1, 1), "PASSA": (0b1111, 1, 1), "PASSB": (0b1010, 1, 1),
           "INCA": (0b0000, 0, 0), "DECA": (0b1111, 0, 1), "SHL": (0b1100, 0, 1),
           "BIC": (0b0111, 1, 1), "NOTA": (0b0000, 1, 1), "ZERO": (0b0011, 1, 1),
           "ONES": (0b1100, 1, 1)}
    ins = aop + ["MQ0"]

    def fun(a0, a1, a2, a3, mq0):
        code = a0 | a1 << 1 | a2 << 2 | a3 << 3
        name = {v: k for k, v in A.items()}[code]
        if name == "RES":
            name = "PASSB"
        if name == "MQSTEP":
            # (the step that doesn't add is A in arithmetic mode, whose
            # carry out is 0: the shift that follows takes it in)
            name = "ADD" if mq0 else "INCA"
        return FUN[name]
    outs = {}
    for i in range(4):
        outs[f"AS{i}"] = (table(ins, lambda *b, i=i: (fun(*b)[0] >> i) & 1), False, False)
    outs["AM"] = (table(ins, lambda *b: fun(*b)[1]), False, False)
    # the carry in (CN0 is active low): CI's, OWN the function's own (a
    # subtract and an increment carry in); ADC and SBC take C (CI C)
    terms = [
        eq(ci, F.CI["1"]),
        AND(eq(ci, F.CI["C"]), lit("FC")),
        AND(eq(ci, F.CI["OWN"]), anyof(aop, [A["SUB"], A["INCA"]])),
    ]
    outs["CN0"] = (OR(*terms), False, True)
    G.add(nl, "U_ALUF", outs)


def buses(nl):
    """The ALU's way to A and B: U_XA (OA and A), U_XB (OB and B), U_FA (F
    onto A), U_SH (OA shifted onto OB); U_BUS their enables."""
    for k in range(4):
        nl.add("245", f"U_XA{k}", DIR="XADIR", OE="XAOE_n",
               **{f"A{i + 1}": OA[8 * k + i] for i in range(8)},
               **{f"B{i + 1}": BP.A[8 * k + i] for i in range(8)})
        nl.add("245", f"U_XB{k}", DIR="XBDIR", OE="XBOE_n",
               **{f"A{i + 1}": OB[8 * k + i] for i in range(8)},
               **{f"B{i + 1}": BP.B[8 * k + i] for i in range(8)})
        nl.add("541", f"U_FA{k}", OE1="FAOE_n", OE2="GND",
               **{f"A{i + 1}": FN[8 * k + i] for i in range(8)},
               **{f"Y{i + 1}": BP.A[8 * k + i] for i in range(8)})
        src = [OA[8 * k + i + 1] if 8 * k + i + 1 < 32 else "SIN" for i in range(8)]
        nl.add("541", f"U_SH{k}", OE1="SHOE_n", OE2="GND",
               **{f"A{i + 1}": src[i] for i in range(8)},
               **{f"Y{i + 1}": OB[8 * k + i] for i in range(8)})
    ain, bin_, aout, bout, si = f("AIN")[0], f("BIN"), f("AOUT"), f("BOUT")[0], f("SI")
    out_oa = eq(aout, F.AOUT["OA"])
    outs = {
        "LAOE_n": (lit(ain), False, False),
        "LBOE_n": (negate(eq(bin_, F.BIN["RF"])), False, False),
        "XADIR": (out_oa, False, False),
        "XAOE_n": (OR(lit(ain), out_oa), False, True),
        "XBDIR": (lit(bout), False, False),
        "XBOE_n": (OR(eq(bin_, F.BIN["BUS"]), lit(bout)), False, True),
        "SHOE_n": (eq(bin_, F.BIN["SHIFT"]), False, True),
        "FAOE_n": (eq(aout, F.AOUT["F"]), False, True),
        # the bit a right shift brings in
        "SIN": (OR(AND(eq(si, F.SI["C"]), lit("FC")), AND(eq(si, F.SI["SIGN"]), lit("OA31")),
                   AND(eq(si, F.SI["ROT"]), lit("OA0"))), False, False),
    }
    G.add(nl, "U_BUS", outs)


def flags(nl, ck):
    # U_ZL: the low half zero, and the low byte (ZB); U_ZH the high half
    G.add(nl, "U_ZL", {"ZL": ([{n: 0 for n in FN[:16]}], True, False),
                       "ZB": ([{n: 0 for n in FN[:8]}], True, False)}, clock=ck[2])
    # (and ST, the microcode's flag: F31, the carry out, or held, by STOP)
    stop = f("STOP")
    G.add(nl, "U_ZH", {"ZH": ([{n: 0 for n in FN[16:]}], True, False),
                       "FST": (OR(AND(eq(stop, F.STOP["F31"]), lit("F31")),
                                  AND(eq(stop, F.STOP["C32"]), lit("C32_n", 0)),
                                  AND(eq(stop, F.STOP["HOLD"]), lit("FST"))), True, False)}, clock=ck[2])
    fl, aop, stop, si, nsz, bin_ = f("FL"), f("AOP"), f("STOP"), f("SI"), f("NSZ"), f("BIN")
    # which flags the operation sets: FL's
    set_nz = OR(eq(fl, F.FL["SH"]), eq(fl, F.FL["NZ"]), eq(fl, F.FL["NZCV"]))
    set_cv = eq(fl, F.FL["NZCV"])
    set_sh = eq(fl, F.FL["SH"])
    # an add or a subtract (for V and C)
    sub = eq(aop, F.AOP["SUB"])
    # C: the carry out (the 181's CN4, active low: C32_n); for a subtract,
    # "no borrow" is the carry out itself
    c = lit("C32_n", 0)
    # V: the operands' signs agree (add) or differ (sub), and the result's differs
    v_add = OR(AND(lit("OA31"), lit("OB31"), lit("F31", 0)), AND(lit("OA31", 0), lit("OB31", 0), lit("F31")))
    v_sub = OR(AND(lit("OA31"), lit("OB31", 0), lit("F31", 0)), AND(lit("OA31", 0), lit("OB31"), lit("F31")))
    # SETCV: a helper, so that each flag is a few terms
    scv = lit("SETCV")
    # a shift's C (FL SH): OA's bit 0 on the shift path, else the carry out
    shifting = eq(bin_, F.BIN["SHIFT"])
    # NSZ LOAD: every flag from F's bits 3-0 (V 0, C 1, Z 2, N 3, as ccr has
    # them), for MTSR and RTI; a word that loads sets no flag otherwise
    ld = lit(nsz[1])
    nld = lit(nsz[1], 0)
    keep_cv = AND(lit("SETCV", 0), negate(set_sh), nld)
    outs = {
        "SETCV": (set_cv, False, False),
        "FC": (OR(AND(nld, scv, c), AND(nld, set_sh, shifting, lit("OA0")),
                  AND(nld, set_sh, negate(shifting), c), AND(ld, lit("F1")),
                  AND(keep_cv, lit("FC"))), True, False),
        "FV": (OR(AND(nld, scv, sub, v_sub), AND(nld, scv, negate(sub), v_add), AND(ld, lit("F0")),
                  AND(keep_cv, lit("FV"))), True, False),
        "QIN": (lit("F0"), True, False),
    }
    G.add(nl, "U_FLA", outs, clock=ck[2])
    # N from the operand's top bit: NSZ SZ takes the access's size from
    # MEM's SZ lines (0 byte, 1 half, 2 word); Z, a cycle later, from ZL,
    # ZH and ZB as the size registered with it (ZSZ, in SZ's code) says
    sz = BP.SZ
    by_sz = lit(nsz[0])
    nbit = OR(AND(negate(by_sz), lit("F31")), AND(by_sz, eq(sz, 0), lit("F7")),
              AND(by_sz, eq(sz, 1), lit("F15")), AND(by_sz, lit(sz[1]), lit("F31")))
    zsz = ["ZSZ0", "ZSZ1"]
    znow = OR(AND(lit(zsz[1]), lit("ZL"), lit("ZH")), AND(eq(zsz, 1), lit("ZL")), AND(eq(zsz, 0), lit("ZB")))
    # (SETNZ written out: the pins went to NSZ LOAD's)
    nz = AND(set_nz, nld)
    outs = {
        "FN": (OR(AND(nz, nbit), AND(negate(set_nz), nld, lit("FN")), AND(ld, lit("F3"))), True, False),
        "ZPEND": (nz, True, False),
        # (the size Z is taken at, in SZ's code: the word's, 2, unless NSZ SZ)
        "ZSZ0": (AND(by_sz, lit(sz[0])), True, False),
        "ZSZ1": (OR(negate(by_sz), AND(by_sz, lit(sz[1]))), True, False),
        "FZH": (OR(AND(nld, lit("ZPEND"), znow), AND(nld, lit("ZPEND", 0), lit("FZH")), AND(ld, lit("F2"))),
                True, False),
        "FZ": (OR(AND(lit("ZPEND"), znow), AND(lit("ZPEND", 0), lit("FZH"))), False, False),
    }
    G.add(nl, "U_FLB", outs, clock=ck[2])
