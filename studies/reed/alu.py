"""The ALU board: the register file, the ALU, the flags.

The register file is two copies of 64K x 32 (four IS61C6416s, each as two
8-bit halves), one per read port, both written with every result. Its
read and write share each cycle, through latches:

  - from the cycle's start the copies read (their addresses from U_RAG and
    U_RBG: d, s, x or the microinstruction's K), and the 74ABT573 latches
    pass their data to the ALU's inputs, OA and OB;
  - in the write phase (WPH, the cycle's last two ticks) the latches hold,
    the copies' addresses switch to W (the last cycle's destination, held
    in U_WG, onto them through U_WA and U_WB), and Y_A and Y_B (574s that
    took the last cycle's result) write it, RFWE_n low for one master
    clock period from U_RFT, on MCLKN;
  - a read of the register the write phase is about to write takes Y
    instead of the copy (a 74F521 per port compares the read address with
    W: U_BYA, U_BYB), so a result is readable in the next cycle.

The ALU is eight 74F181s with their carry lookahead in U_CLA; U_ALUF gives
their function and carry from the microinstruction's AOP and CI, or, for
AOP ROW, from the instruction's opcode (MOV, MOVS, ADD, SUB, CMP, AND, OR,
XOR, ADC, SBC, BIC and TST by their rows). OA comes from copy A or from the
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
from .common import AND, OR, ONE, ZERO, anyof, bus, clock_buffer, control_slice, eq, lit, negate, table


def f(name):
    return F.nets("ALU", name)


def build(sim=True):
    nl = Netlist()
    nl.add("const", "X_RAIL", LO="GND", HI="VCC")
    ck = clock_buffer(nl, src="CYC")
    nl.section("control store")
    control_slice(nl, "ALU", ck[0])
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


def register_file(nl, ck):
    for copy, addr, data, oe in (("A", RFA, RAD, "RFOEA_n"), ("B", RFB, RBD, "RFOEB_n")):
        a = {f"A{i}": addr[i] for i in range(5)}
        a.update({f"A{i}": "GND" for i in range(5, 16)})
        for k in range(4):
            nl.add("sram64k", f"U_RF{copy}{k}", CE="GND", OE=oe, WE="RFWE_n", **a,
                   **{f"IO{i}": data[8 * k + i] for i in range(8)})
            out = OA if copy == "A" else OB
            nl.add("573", f"U_L{copy}{k}", OE=f"L{copy}OE_n", LE="LE",
                   **{f"D{i + 1}": data[8 * k + i] for i in range(8)},
                   **{f"Q{i + 1}": out[8 * k + i] for i in range(8)})
            nl.add("574", f"U_Y{copy}{k}", OE=f"Y{copy}OE_n", CLK=ck[1 + k // 2],
                   **{f"D{i + 1}": FN[8 * k + i] for i in range(8)},
                   **{f"Q{i + 1}": data[8 * k + i] for i in range(8)})
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
    wph_n = lit("WPH", 0)
    # port A: d, s or K; drives the copy's address outside the write phase
    ra = sel(f("RAS"), {F.RAS["d"]: rd, F.RAS["s"]: rs, F.RAS["K"]: "K"})
    outs = {RFA[i]: (ra[i], False, False, wph_n) for i in range(5)}
    G.add(nl, "U_RAG", outs)
    # port B: s, x or K (d, a store's data, is read on port A and goes out on A)
    rb = sel(f("RBS"), {F.RBS["s"]: rs, F.RBS["x"]: rx, F.RBS["K"]: "K"})
    outs = {RFB[i]: (rb[i], False, False, wph_n) for i in range(5)}
    G.add(nl, "U_RBG", outs)
    # W: this cycle's destination, for the next cycle's write phase
    wsel = sel(f("WS"), {F.WS["d"]: rd, F.WS["s"]: rs, F.WS["K"]: "K"})
    outs = {W[i]: (wsel[i], True, False) for i in range(5)}
    outs["WEN"] = (negate(eq(f("WS"), F.WS["NONE"])), True, False)
    G.add(nl, "U_WG", outs, clock=ck[1])
    for copy, addr in (("A", RFA), ("B", RFB)):
        nl.add("541", f"U_W{copy}", OE1="WPH_n", OE2="GND",
               **{f"A{i + 1}": W[i] for i in range(5)}, A6="GND", A7="GND", A8="GND",
               **{f"Y{i + 1}": addr[i] for i in range(5)},
               Y6=f"W{copy}_NC6", Y7=f"W{copy}_NC7", Y8=f"W{copy}_NC8")
        # the bypass: the read address is W, and W is to be written
        nl.add("521", f"U_BY{copy}", G="GND", PEQ=f"BYP{copy}_n",
               **{f"P{i}": W[i] for i in range(5)}, P5="WEN", P6="GND", P7="GND",
               **{f"Q{i}": addr[i] for i in range(5)}, Q5="VCC", Q6="GND", Q7="GND")
    # U_RFT, on MCLKN: the write strobe, the latches' enable, WPH_n; the
    # copies' outputs, off in the write phase and when Y bypasses them, and Y's
    outs = {"RFWE_n": (AND(lit("WPH"), lit("WEN"), lit("RFWE_n")), True, True),
            "LE": (lit("WPH", 0), False, False),
            "WPH_n": (lit("WPH"), False, True)}
    for c in "AB":
        outs[f"RFOE{c}_n"] = (OR(lit("WPH"), lit(f"BYP{c}_n", 0)), False, False)
        outs[f"Y{c}OE_n"] = (OR(lit("WPH"), lit(f"BYP{c}_n", 0)), False, True)
    G.add(nl, "U_RFT", outs, clock="MCLKN")


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
    # U_ALUF: the function, from AOP, or the opcode for ROW
    aop, ci, op = f("AOP"), f("CI"), BP.OP
    A = F.AOP
    # (S3-S0, M, carry in as the 181 takes it: 1 = none) for each AOP
    FUN = {"ADD": (0b1001, 0, 1), "SUB": (0b0110, 0, 0), "AND": (0b1011, 1, 1), "OR": (0b1110, 1, 1),
           "XOR": (0b0110, 1, 1), "PASSA": (0b1111, 1, 1), "PASSB": (0b1010, 1, 1),
           "INCA": (0b0000, 0, 0), "DECA": (0b1111, 0, 1), "SHL": (0b1100, 0, 1),
           "BIC": (0b0111, 1, 1), "NOTA": (0b0000, 1, 1), "ZERO": (0b0011, 1, 1),
           "ONES": (0b1100, 1, 1)}
    # the rows' operations, as AOPs
    ROW = {0x1: "PASSB", 0x3: "PASSB", 0x4: "ADD", 0x5: "SUB", 0x6: "SUB", 0x8: "AND", 0x9: "OR",
           0xA: "XOR"}
    ROW_E = {0x0: "ADD", 0x1: "SUB", 0x2: "BIC", 0x3: "AND", 0xA: "BIC", 0xB: "AND"}   # ADC, SBC, BIC, TST
    ins = aop + op + ["MQ0"]

    def fun(a0, a1, a2, a3, o0, o1, o2, o3, o4, o5, o6, o7, mq0):
        code = a0 | a1 << 1 | a2 << 2 | a3 << 3
        opc = o0 | o1 << 1 | o2 << 2 | o3 << 3 | o4 << 4 | o5 << 5 | o6 << 6 | o7 << 7
        name = {v: k for k, v in A.items()}[code]
        if name == "ROW":
            row, col = opc >> 4, opc & 15
            name = ROW.get(row) or (ROW_E.get(col) if row == 0xE else None) or "PASSB"
        if name == "MQSTEP":
            name = "ADD" if mq0 else "PASSA"
        return FUN[name]
    outs = {}
    for i in range(4):
        outs[f"AS{i}"] = (table(ins, lambda *b, i=i: (fun(*b)[0] >> i) & 1), False, False)
    outs["AM"] = (table(ins, lambda *b: fun(*b)[1]), False, False)
    # the carry in (CN0 is active low): CI's, or for ROW the operation's own
    # (a subtract and an increment carry in), but ADC and SBC (E0, E1) take C
    opc_e = AND(eq(op[4:], 0xE), eq(op[1:4], 0))
    terms = [
        eq(ci, F.CI["1"]),
        AND(eq(ci, F.CI["C"]), lit("FC")),
        AND(eq(ci, F.CI["ROW"]), anyof(aop, [A["SUB"], A["INCA"]])),
        AND(eq(ci, F.CI["ROW"]), eq(aop, A["ROW"]), anyof(op[4:], [0x5, 0x6])),
        AND(eq(ci, F.CI["ROW"]), eq(aop, A["ROW"]), opc_e, lit("FC")),
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
    for name, half in (("U_ZL", FN[:16]), ("U_ZH", FN[16:])):
        net = "ZL" if name == "U_ZL" else "ZH"
        G.add(nl, name, {net: ([{n: 0 for n in half}], True, False)}, clock=ck[2])
    fl, aop, stop, si, op = f("FL"), f("AOP"), f("STOP"), f("SI"), BP.OP
    row = op[4:]
    # which flags the operation sets: FL's, or for ROW the row's
    nz_rows = [0x3, 0x8, 0x9, 0xA]
    nzcv_rows = [0x4, 0x5, 0x6]
    set_nz = OR(eq(fl, F.FL["NZ"]), eq(fl, F.FL["NZCV"]),
                AND(eq(fl, F.FL["ROW"]), anyof(row, nz_rows + nzcv_rows + [0xE])))
    set_cv = OR(eq(fl, F.FL["NZCV"]), AND(eq(fl, F.FL["ROW"]), anyof(row, nzcv_rows + [0xE])))
    # an add or a subtract (for V and C): SUB, and ROW's SUB, CMP and SBC
    sub = OR(eq(aop, F.AOP["SUB"]), AND(eq(aop, F.AOP["ROW"]), anyof(row, [0x5, 0x6])))
    # C: the carry out (the 181's CN4, active low: C32_n); for a subtract,
    # "no borrow" is the carry out itself
    c = lit("C32_n", 0)
    # V: the operands' signs agree (add) or differ (sub), and the result's differs
    v_add = OR(AND(lit("OA31"), lit("OB31"), lit("F31", 0)), AND(lit("OA31", 0), lit("OB31", 0), lit("F31")))
    v_sub = OR(AND(lit("OA31"), lit("OB31", 0), lit("F31", 0)), AND(lit("OA31", 0), lit("OB31"), lit("F31")))
    # SETCV, SUBOP and SETNZ: helpers, so that each flag is a few terms
    scv, sop_, snz = lit("SETCV"), lit("SUBOP"), lit("SETNZ")
    outs = {
        "SETCV": (set_cv, False, False),
        "SUBOP": (sub, False, False),
        "FC": (OR(AND(scv, c), AND(lit("SETCV", 0), lit("FC"))), True, False),
        "FV": (OR(AND(scv, sop_, v_sub), AND(scv, lit("SUBOP", 0), v_add), AND(lit("SETCV", 0), lit("FV"))),
               True, False),
        "QIN": (lit("F0"), True, False),
    }
    G.add(nl, "U_FLA", outs, clock=ck[2])
    outs = {
        "SETNZ": (set_nz, False, False),
        "FN": (OR(AND(snz, lit("F31")), AND(lit("SETNZ", 0), lit("FN"))), True, False),
        "ZPEND": (snz, True, False),
        "FZH": (OR(AND(lit("ZPEND"), lit("ZL"), lit("ZH")), AND(lit("ZPEND", 0), lit("FZH"))), True, False),
        "FST": (OR(AND(eq(stop, F.STOP["F31"]), lit("F31")), AND(eq(stop, F.STOP["C32"]), c),
                   AND(eq(stop, F.STOP["HOLD"]), lit("FST"))), True, False),
        "FZ": (OR(AND(lit("ZPEND"), lit("ZL"), lit("ZH")), AND(lit("ZPEND", 0), lit("FZH"))), False, False),
    }
    G.add(nl, "U_FLB", outs, clock=ck[2])
