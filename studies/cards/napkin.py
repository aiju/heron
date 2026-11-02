"""Napkin designs for RFC 0049: Heron on double Eurocards, board first.

Not a netlist. Each design is a list of boards, each board a list of
blocks, each block the parts it needs (so a chip count is a parts list,
not a guess), and each key instruction a list of microcycles, each
microcycle the longest path it has to carry, summed from worst-case
datasheet delays and generous figures for wires and the backplane.

    heron cards napkin            print the tables
    heron cards napkin --write    write reports/0049-rfc-board-first/napkin.md
"""

import math
import os

from heron import ROOT

OUT = os.path.join(ROOT, "reports", "0049-rfc-board-first", "napkin.md")

TICK = 1000 / 50.35          # ns: the master clock, twice VGA's pixel clock
BUDGET = 70                  # area units a double Eurocard takes (see AREA)
MARGIN = 2.0                 # ns of slack every microcycle keeps, beyond the sums

# ---------------------------------------------------------------------------
# Parts: (package, area units). An area unit is a DIP-20's slot on a board
# soldered by hand (report 0044's tight packing); a double Eurocard
# (233.35 x 160 mm, less the guided edges, the front strip and the
# connectors) has about 70 of them.

PARTS = {
    "74ABT541": ("DIP-20", 1.0), "74ABT245": ("DIP-20", 1.0),
    "74ABT574": ("DIP-20", 1.0), "74F153": ("DIP-16", 0.9),
    "74F163": ("DIP-16", 0.9), "74F283": ("DIP-16", 0.9),
    "74F299": ("DIP-20", 1.0), "74F181": ("DIP-24W", 1.7),
    "74HCT14": ("DIP-14", 0.8), "22V10": ("DIP-24", 1.1),
    "SST39SF010A": ("PLCC-32 socket", 1.2), "IS61C6416": ("SOJ-44", 1.2),
    "AS7C4096A": ("SOJ-36", 1.2), "CDC341": ("SOIC-20", 0.8),
    "osc": ("DIP-14 can", 0.8), "TL16C550C": ("DIP-40", 2.4),
    "MAX232": ("DIP-16", 0.9), "82C54": ("DIP-24W", 1.7),
    "CF socket": ("CF", 3.0), "DAC0832": ("DIP-20", 1.0),
    "MCP6002": ("DIP-8", 0.6), "TL7705A": ("DIP-8", 0.6),
    "ADV7125": ("LQFP-48", 1.0), "IS61C256": ("SOJ-28", 1.0),
}


def block(name, parts, tax=False):
    """A block: its name, [(count, part)], and whether it is board tax
    (there only because the board is a board: its control slice, its
    clock buffer, its receivers for the backplane)."""
    for _, p in parts:
        assert p in PARTS, p
    return (name, parts, tax)


# The control slice every board but CTRL carries: k flashes on the
# broadcast microprogram address and k microinstruction registers.
def slice_(k, rx=2):
    return [block(f"control slice: {8 * k} bits", [(k, "SST39SF010A"), (k, "74ABT574")], tax=True),
            block("µPC receivers", [(rx, "74ABT541")], tax=True),
            block("clock buffer", [(1, "CDC341")], tax=True)]


CTRL_CORE = [
    block("clock generator: tick counter, phases, slots (state machines)",
          [(2, "22V10"), (1, "osc"), (2, "CDC341")]),
    block("µPC and next address (jump, branch, decode entry, interrupt)",
          [(2, "74ABT574"), (3, "22V10")]),
    block("CTRL's slice: 40 bits, the sequencer's from the flash, 16 more registered",
          [(5, "SST39SF010A"), (2, "74ABT574")]),
    block("instruction queue: 2 words as 8 parcel bytes on a parcel bus, its control",
          [(8, "74ABT574"), (2, "22V10")]),
    block("immediate unit: parcels, fill, quick constants onto B",
          [(6, "74ABT541"), (1, "22V10")]),
    block("decode IR: register numbers d, s, x onto control lines",
          [(2, "74ABT574")]),
    block("condition and interrupt decode", [(2, "22V10")]),
]
PC = block("PC: 22-bit counter, onto B or A", [(6, "74F163"), (3, "74ABT541")])
BRANCH = block("branch adder: PC + 2 x disp, its target register on A",
               [(6, "74F283"), (3, "74ABT574")])
FPC_ON_A = block("FPC: fetch counter onto A", [(6, "74F163"), (3, "74ABT541")])

ALU_CORE = [
    block("register file: two copies of 64K x 32", [(4, "IS61C6416")]),
    block("result registers Y_A, Y_B: write each copy, and drive its bus side", [(8, "74ABT574")]),
    block("register addresses: d, s, x, K, bank; read and write (decode)", [(3, "22V10")]),
    block("ALU: 8 x 181, carry lookahead, function decode", [(8, "74F181"), (2, "22V10")]),
    block("A side transceivers: copy A's net to and from the A bus", [(4, "74ABT245")], tax=True),
    block("B side transceivers: copy B's net to and from the B bus", [(4, "74ABT245")], tax=True),
    block("shift path: copy A's net, one bit right, onto copy B's", [(4, "74ABT541")]),
    block("flags: zero from Y, N Z C V and the microcode's flags (decode, register)", [(3, "22V10")]),
    block("bus enables by slot (decode)", [(1, "22V10")]),
    block("MQ: multiply and divide steps", [(4, "74F299")]),
]

RAM = block("RAM: 4 MB, two rows of four lanes", [(8, "AS7C4096A")])
DATAPATH = [
    block("byte crossbar on loads: any lane to any lane, zero fill (16 x 153)",
          [(16, "74F153"), (2, "22V10")]),
    block("crossbar to and from B", [(4, "74ABT245")], tax=True),
    block("stores: lanes from B, replicated for bytes and halves", [(8, "74ABT541")]),
]

IO = [
    block("UARTs with RS-232 levels", [(2, "TL16C550C"), (2, "MAX232"), (1, "osc")]),
    block("timer", [(1, "82C54")]),
    block("boot flash", [(1, "SST39SF010A")]),
    block("CompactFlash: socket, data and control buffers", [(1, "CF socket"), (2, "74ABT245"), (1, "74ABT541")]),
    block("PS/2 ports", [(1, "74HCT14"), (1, "22V10")]),
    block("interrupt controller, I/O decode, slow devices' timing", [(3, "22V10")]),
    block("the devices' data bus from B, address latch from A", [(2, "74ABT245"), (2, "74ABT574")],
          tax=True),
    block("sound: sample latch, DAC, op-amp", [(1, "74ABT574"), (1, "DAC0832"), (1, "MCP6002")]),
    block("reset", [(1, "TL7705A")]),
]
VIDEO = [
    block("frame buffer: 2 MB, 32 bits wide", [(4, "AS7C4096A")]),
    block("CPU side: address latch from A, posted write data, read back onto B",
          [(3, "74ABT574"), (4, "74ABT574"), (4, "74ABT245")]),
    block("scan address: 20-bit counter onto the frame buffer", [(5, "74F163"), (3, "74ABT541")]),
    block("pixels: a word's bytes in turn, palette in SRAM, triple DAC",
          [(4, "74ABT574"), (3, "IS61C256"), (1, "74ABT541"), (1, "ADV7125")]),
    block("line and frame timing", [(4, "74F163"), (2, "22V10")]),
    block("decode, slots, WAIT and the frame interrupt", [(2, "22V10")]),
    block("clock buffer", [(1, "CDC341")], tax=True),
]

ARITH = slice_(3) + [
    block("operands X (bytes onto the x net) and Y", [(8, "74ABT574")]),
    block("product tables: 4 x (64K x 16) of 8 x 8 products, loaded at boot",
          [(4, "IS61C6416"), (8, "74ABT541")]),
    block("one 40-bit adder: a row's sum, then the accumulation",
          [(8, "74F181"), (1, "22V10"), (2, "74F283")]),
    block("accumulator and the product's retired bytes", [(9, "74ABT574")]),
    block("product onto A and B", [(8, "74ABT541")]),
    block("step and bus enables (decode)", [(1, "22V10")]),
]

DESIGNS = {
    "A": ("Spine", [
        ("CTRL", CTRL_CORE + [PC, BRANCH]),
        ("ALU", slice_(4) + ALU_CORE + [
            block("EA path: F onto A, so an address leaves in the cycle it's made", [(4, "74ABT541")],
                  tax=True)]),
        ("MEM", slice_(3) + [RAM] + DATAPATH + [
            block("MAR: loaded from A, its low 4 bits counting", [(3, "74ABT574"), (1, "74F163")]),
            block("FPC: fetch counter onto the RAM's address", [(6, "74F163"), (3, "74ABT541")]),
            block("A receivers: into MAR and FPC; A straight to the RAM's address",
                  [(3, "74ABT541"), (3, "74ABT541")], tax=True),
            block("address decode, alignment (decode)", [(1, "22V10")]),
        ]),
        ("IO+VIDEO", IO + VIDEO),
    ]),
    "B": ("Address board", [
        ("CTRL+IO", CTRL_CORE + IO),
        ("ADDR", slice_(4) + [
            block("register file copy: 64K x 32", [(2, "IS61C6416")]),
            block("remote-write register: EX's results broadcast on A, written next write tick",
                  [(4, "74ABT574")], tax=True),
            block("AGU: 8 x 181, lookahead, function decode", [(8, "74F181"), (2, "22V10")]),
            block("displacements and constants from B", [(4, "74ABT541")], tax=True),
            PC,
            block("FPC: fetch counter onto A", [(6, "74F163"), (3, "74ABT541")]),
            block("MAR: loaded from the AGU, onto A, its low 4 bits counting",
                  [(3, "74ABT574"), (1, "74F163"), (1, "74ABT541")]),
            block("mode decode for the hardwired operand stage, hazard compare", [(3, "22V10")]),
        ]),
        ("EX", slice_(4) + ALU_CORE),
        ("MEM", slice_(3) + [RAM] + DATAPATH + [
            block("A receivers: the address", [(3, "74ABT541")], tax=True),
            block("decode, alignment", [(1, "22V10")])]),
        ("VIDEO", VIDEO),
    ]),
    "C": ("Twin slices", [
        ("CTRL", CTRL_CORE + [PC, BRANCH, FPC_ON_A]),
        ("SLICE x2", slice_(4) + [
            block("register file: two copies of 64K x 16", [(2, "IS61C6416")]),
            block("result registers, half", [(4, "74ABT574")]),
            block("register addresses (decode)", [(3, "22V10")]),
            block("ALU half: 4 x 181, lookahead with C16 across, function decode",
                  [(4, "74F181"), (2, "22V10")]),
            block("A and B transceivers, half each", [(4, "74ABT245")], tax=True),
            block("shift path, half, the bit across on a control line", [(2, "74ABT541")]),
            block("MAR half, onto its half of A; loaded from F or from copy A's net",
                  [(2, "74ABT574"), (2, "74ABT541")]),
            block("A receivers: the RAM's address from the whole bus", [(3, "74ABT541")], tax=True),
            block("flags (the high slice's), zero of a half", [(2, "22V10")]),
            block("bus enables by slot", [(1, "22V10")]),
            block("MQ half", [(2, "74F299")]),
            block("RAM: 2 MB, two rows of this slice's two lanes", [(4, "AS7C4096A")]),
            block("crossbar half: own lanes from all four (the other two over B)",
                  [(8, "74F153"), (1, "22V10")]),
            block("own lanes onto B; stores, replicated", [(2, "74ABT245"), (4, "74ABT541")]),
        ]),
        ("IO+VIDEO", IO + VIDEO),
    ]),
}


def board_sums(blocks):
    chips = sum(n for _, parts, _ in blocks for n, _ in parts)
    area = sum(n * PARTS[p][1] for _, parts, _ in blocks for n, p in parts)
    tax = sum(n for _, parts, t in blocks if t for n, _ in parts)
    gals = sum(n for _, parts, _ in blocks for n, p in parts if p == "22V10")
    return chips, area, tax, gals


def copies(name):
    return 2 if name.endswith("x2") else 1


# ---------------------------------------------------------------------------
# Delays, ns, worst case. Datasheet figures from infra/hw/timing.json where
# it has the part; the backplane's and the wires' are generous on purpose.

D = dict(
    cq=7.1,      # 74ABT574 clock to Q
    oe=6.7,      # 74ABT574 output enable (541, 245: 6.2)
    buf=3.9,     # 74ABT541/245 through
    bp=10.0,     # the backplane: connector, flight, settling, 6-8 slots loaded
                 # (report 0022: 4.8-6.3 ns added for 8 slots at 20.32 mm)
    w=2.0,       # a heavy net on a board
    su=1.5,      # 74ABT574 setup
    sk=2.5,      # clock skew between boards (report 0022's 2.0-2.6 with CDC341s)
    sk1=1.0,     # clock skew on a board
    gal=7.5,     # ATF22V10C-7 (DIP-24) through
    sram=12.0,   # IS61C6416AL-12, AS7C4096A-12
    flash=55.0,  # SST39SF010A-55
    xbar=10.0,   # 74F153 data to Y, and a wire
    alu=29.5,    # 32 bits: 181 A,B to G,P 10.5, lookahead GAL 7.5, Cn to F 9.5, wire 2
    logic=15.0,  # 181 logic or pass, A,B to F 13, wire 2
    across=10.0, # a control line board to board: a GAL's or 574's output, the backplane, a GAL's input
    tdw=6.0,     # SRAM data setup to the end of its write
    addr=3.0,    # an address fanning out to 8 SRAMs
)


def derived(d):
    x = dict(d)
    x["XD"] = d["bp"] + d["buf"] + d["w"]             # from a part that drives the backplane to logic on another board
    x["X"] = d["buf"] + x["XD"]                       # the same through a driver of its own
    x["RF"] = TICK + d["gal"] + d["sram"] + d["w"]    # register file data, after the write tick
    x["END"] = d["su"] + d["sk1"]                     # into a register on the same board
    x["ENDX"] = d["su"] + d["sk"]                     # into a register on another board
    x["ON"] = d["cq"] + d["oe"]                       # a registered value put on a bus at the cycle's start
    x["ONX"] = x["ON"] + x["XD"]                      # ... and at another board
    x["RAM"] = d["cq"] + d["addr"] + d["sram"]        # from a MAR on the RAM's board to its data
    x["FLAGS"] = x["ON"] + 2 * d["gal"] + d["w"] + 3.5 + 4.5 + d["across"]  # flags of the cycle before, at CTRL
    x["FLASHLOOP"] = d["cq"] + x["XD"] + d["flash"] + d["su"] + d["sk"]
    return x


def flash_floor(d=D):
    """The shortest microcycle the control store allows: the µPC on the
    backplane to every board's flashes and into their registers."""
    return math.ceil((derived(d)["FLASHLOOP"] + MARGIN) / TICK)


def recipes(design, d=D):
    """{instruction: [(what the microcycle does, its longest path in ns or
    None for one of the floor's length)]}"""
    x = derived(d)
    RF, X, XD, END, ENDX, ON, ONX, RAM = (x[k] for k in ("RF", "X", "XD", "END", "ENDX", "ON", "ONX", "RAM"))
    alu, logic, xbar, buf, tdw, sk1 = d["alu"], d["logic"], d["xbar"], d["buf"], d["tdw"], d["sk1"]
    gal = d["gal"]
    FLOOR = None
    r = {}
    if design == "C":
        add = d["alu"] - 9.5 - 2 + d["across"] + d["gal"] + 9.5 + 2   # the carry crosses to the high slice
    else:
        add = alu
    cond = x["FLAGS"] + gal + gal + END                # flags at CTRL, cc, next address, into µPC

    # register and constant operands
    r["ADD r1, r2"] = [("read both copies, add, into Y; the flags from Y next cycle", RF + add + END)]
    r["AND r1, r2"] = [("read, a logic operation, into Y", RF + logic + END)]
    r["CMP r1, #5"] = [("read r1; the constant over B from CTRL; subtract", max(RF, ONX) + add + END)]
    r["MOV r1, #0x12345678"] = [("two parcels over B from CTRL; pass", ONX + logic + END)]
    r["LEA r1, [r2 + 100]"] = [("read r2; d16 over B; add", max(RF, ONX) + add + END)]

    if design in ("A", "C"):
        if design == "A":
            ea = max(RF, ONX) + alu + buf + XD + ENDX           # F onto A, into MAR on MEM
            load = RAM + xbar + X                               # MAR to the RAM, crossbar, over B to the ALU
            ea_r = RF + buf + XD + ENDX                         # a register straight onto A, into MAR
            store = RF + X + d["buf"] + tdw + sk1               # rs over B, a lane buffer, the RAM's write
        else:
            ea = max(RF, ONX) + add + END                       # the EA into the slices' MAR halves
            load = ONX + buf + d["addr"] + d["sram"] + xbar     # MAR halves on A, back to both slices' RAMs
            ea_r = RF + buf + END                               # a register from copy A's net into MAR
            store = max(RF + buf + tdw + sk1, ONX + buf + d["addr"])
        r["MOV r1, [r2 + 8]"] = [("r2 + d16 into MAR", ea), ("load, crossbar, pass into Y", load + logic + END)]
        r["MOV r1, [r2]"] = [("r2 into MAR", ea_r), ("load into Y", load + logic + END)]
        r["ADD r1, [r2 + 8]"] = [("r2 + d16 into MAR", ea), ("load, add into Y", load + add + END)]
        r["MOV [r2 + 8], r1"] = [("r2 + d16 into MAR", ea), ("r1 to the RAM, write", store)]
        r["MOV [abs16], r1"] = [("abs16 over B, pass, into MAR", ONX + logic + (buf + XD + ENDX if design == "A" else END)),
                                ("r1 to the RAM, write", store)]
        r["PUSH r1"] = [("sp - 4 into MAR and sp", ea), ("r1 to the RAM, write", store)]
        if design == "A":
            r["POP r1"] = [("sp onto A into MAR; sp + 4 into sp", max(ea_r, RF + alu + END)),
                           ("load into r1", load + logic + END)]
        else:
            r["POP r1"] = [("sp from copy A into the MAR halves; sp + 4 into sp", max(ea_r, RF + add + END)),
                           ("load into r1", load + logic + END)]
        r["MOVS r1, byte [r2]+"] = list(r["POP r1"])
        r["MOV r1, [r2 + r3*4 + 8]"] = [("r3 + r3", RF + add + END), ("2r3 + 2r3", RF + add + END),
                                        ("+ d8", RF + add + END), ("+ r2 into MAR", ea - max(RF, ONX) + RF),
                                        ("load into Y", load + logic + END)]
        r["INC [r2]"] = [("r2 into MAR", ea_r), ("load, + 1, into Y", load + add + END),
                         ("Y to the RAM, write", ON + X + buf + tdw + sk1)]
        bcc = max(cond, x["ON"] + XD + buf + d["addr"] + d["sram"] + xbar + X + gal + END) if design == "A" else \
            max(cond, x["ON"] + XD + buf + d["addr"] + d["sram"] + buf + XD + gal + END)
        r["Bcc, not taken"] = [("flags to CTRL; target fetched anyway; decode the next", bcc)]
        r["Bcc, taken"] = [("flags; the target (from the branch adder) on A, its word over B, decode", bcc),
                           ("the target's first microinstruction from the flashes", FLOOR)]
        r["BSR / CALL label"] = [("as a taken Bcc, and PC over B into r7", max(bcc, ONX + logic + END)),
                                 ("the target's first microinstruction", FLOOR)]
        ret = RF + buf + XD + buf + d["addr"] + d["sram"] + (xbar + X if design == "A" else buf + XD) + gal + END
        r["RET (JMP r7)"] = [("r7 on A to the RAM, its word over B, decode", ret),
                             ("the target's first microinstruction", FLOOR)]
        r["JMP [table + r2*4]"] = [("r2 + r2", RF + add + END), ("+ 2r2", RF + add + END),
                                   ("+ table into MAR", ea), ("load the target into FPC and PC", RAM + xbar + END + 10),
                                   ("fetch at FPC, decode", RAM + xbar + X + gal + END),
                                   ("the target's first microinstruction", FLOOR)]
        rot = RF + X + xbar + X + logic + END if design == "A" else RF + X + xbar + logic + END
    else:  # B: the operand stage on ADDR, during the instruction before
        # In the decode cycle (the previous instruction's last): ADDR's copy, AGU, MAR.
        decode_ea = max(RF, ONX) + alu + END
        load = ONX + buf + d["addr"] + d["sram"] + xbar + X     # MAR (ADDR) on A, MEM's RAM, over B to EX
        store = max(RF + X + buf + tdw + sk1, ONX + buf + d["addr"])
        pre = ("(before: the operand's address on ADDR, in the last cycle of the instruction before)", decode_ea)
        r["MOV r1, [r2 + 8]"] = [pre, ("load into EX's Y", load + logic + END)]
        r["MOV r1, [r2]"] = [pre, ("load into EX's Y", load + logic + END)]
        r["ADD r1, [r2 + 8]"] = [pre, ("load, add into Y", load + add + END)]
        r["MOV [r2 + 8], r1"] = [pre, ("r1 from EX over B, write", store)]
        r["MOV [abs16], r1"] = [pre, ("r1 from EX over B, write", store)]
        r["PUSH r1"] = [pre, ("r1 from EX over B, write; EX's ALU, idle, writes sp - 4", store)]
        r["POP r1"] = [pre, ("load into r1 (ADDR has sp + 4 in its own copy already)", load + logic + END),
                       ("sp + 4 on EX", RF + add + END)]
        r["MOVS r1, byte [r2]+"] = list(r["POP r1"])
        r["MOV r1, [r2 + r3*4 + 8]"] = [("r3 + r3 on ADDR", decode_ea), ("+ 2r3, through A and back", decode_ea + 20),
                                        ("+ d8", decode_ea), ("+ r2 into MAR", decode_ea),
                                        ("load into Y", load + logic + END)]
        r["INC [r2]"] = [pre, ("load, + 1, into Y", load + add + END),
                         ("Y to the RAM, write", ON + X + buf + tdw + sk1)]
        bcc = max(cond, ONX + buf + d["addr"] + d["sram"] + xbar + X + gal + END)
        r["Bcc, not taken"] = [pre, ("flags to CTRL; target (ADDR's AGU) fetched anyway; decode the next", bcc)]
        r["Bcc, taken"] = [pre, ("flags; the target from MAR, its word over B, decode", bcc),
                           ("the target's first microinstruction", FLOOR)]
        r["BSR / CALL label"] = [pre, ("as a taken Bcc, and PC over B into r7", max(bcc, ONX + logic + END)),
                                 ("the target's first microinstruction", FLOOR)]
        r["RET (JMP r7)"] = [pre, ("fetch at r7 (ADDR's copy, in MAR), decode", bcc),
                             ("the target's first microinstruction", FLOOR)]
        r["JMP [table + r2*4]"] = [("r2 + r2", decode_ea), ("+ 2r2, through A and back", decode_ea + 20),
                                   ("+ table into MAR", decode_ea), ("load the target over B into MAR", load + END),
                                   ("fetch at MAR, decode", bcc), ("the target's first microinstruction", FLOOR)]
        rot = RF + X + xbar + X + logic + END
    r["LSL r1, #1"] = [("r1 + r1", RF + add + END)]
    r["LSR r1, #8"] = [("r1 over B, crossbar, back over B, into Y" if design != "C" else
                        "both halves over B, crossbar, into Y", rot)]
    r["ROR r1, #13"] = [("rotate by 16 in the crossbar", rot)] + [("rotate left a bit", RF + add + END)] * 3
    step = RF + add + END
    r["MULU r0:r1, r2 (MQ)"] = [("load MQ", step)] + [("a step", step)] * 32 + [("write r0", step), ("write r1", step)]
    r["MULU r0:r1, r2 (ARITH board)"] = (
        [("r1 on A, r2 on B, into X and Y", RF + X + ENDX)] +
        [("table, a row's sum", x["ON"] + d["w"] + d["sram"] + d["w"] + alu + END),
         ("accumulate", d["cq"] + alu + 6 + END)] * 4 +
        [("the high word on A into r0", ONX + logic + END), ("the low word on B into r1", ONX + logic + END)])
    r["DIVU r0:r1, r2"] = [("set up", step)] * 3 + [("a step", step)] * 32 + [("fix up, write", step)] * 2
    if design == "B":
        r["SAVE r8-r14"] = [pre, ("r8 over B, write; MAR + 4; EX writes sp - 28", store)] + \
                           [("the next register, write", store)] * 6
        r["RESTORE r8-r14"] = [pre] + [("load into a register; MAR + 4", load + logic + END)] * 7 + \
                              [("sp + 28 on EX", RF + add + END)]
    else:
        r["SAVE r8-r14"] = [("sp - 28 into MAR and sp", r["PUSH r1"][0][1])] + \
                           [("a register to the RAM, write; MAR + 4", r["PUSH r1"][1][1])] * 7
        r["RESTORE r8-r14"] = [("sp into MAR", r["POP r1"][0][1])] + \
                              [("load into a register; MAR + 4", r["POP r1"][-1][1] if design == "A" else
                                r["MOV r1, [r2]"][1][1])] * 7 + [("sp + 28", RF + add + END)]
    r["SETcc r1"] = [("flags to CTRL, 0 or 1 over B, pass", x["FLAGS"] + gal + XD + logic + END)]
    return r


def ticks(ns, floor):
    if ns is None:
        return floor
    return max(floor, math.ceil((ns + MARGIN) / TICK))


def cost(cycles, floor):
    """Ticks of an instruction: the operand stage's cycle (marked with its
    text in parentheses) runs inside the instruction before, so it adds
    only what it lengthens that cycle by beyond the floor."""
    t = 0
    for what, ns in cycles:
        n = ticks(ns, floor)
        if what.startswith("(before"):
            t += n - floor
        else:
            t += n
    return t


# ---------------------------------------------------------------------------
# A weighting, not a benchmark: the compiled C programs' dynamic
# instruction mix on draft 2 (each program weighted equally), and facts
# from their traces. Made with
#   heron c_compiler cc --isa v2 P.c --run --stats   (the mix)
#   heron v2_isa run P.out --trace                   (the rest)
# over studies/c_compiler/programs/*.c, 2026-11-02.

MIX = {
    "Bcc": 18.6, "MOV r": 6.6, "CMP #q": 5.3, "CMP r": 4.9, "INC": 4.0, "ADD r": 3.3,
    "CMPI": 3.1, "BRA": 3.1, "MOV #q": 2.4, "JMP": 2.3, "ADD b[r+d]": 2.2, "LEA [r+d]": 2.1,
    "ST [abs]": 2.0, "XOR r": 1.9, "ST [sp+n]": 1.9, "LSL": 1.8, "MOV [sp+n]": 1.7,
    "AND r": 1.4, "MOV [r]": 1.4, "MOVS b[r]+": 1.3, "RET": 1.3, "MULS": 1.2, "DEC": 1.1,
    "CLR b[r]": 1.0, "DBNZ": 1.0, "BSR": 1.0, "ADD #q": 0.9, "TST": 0.9, "LEA [r+x]": 0.9,
    "DIVU": 0.8, "LSR": 0.8, "ZXH": 0.8, "ROR": 0.7, "MOV b[r]": 0.7, "ASR": 0.7,
    "ST [r]": 0.7, "NOT": 0.7, "SAVE": 0.6, "RESTORE": 0.6, "INC [abs]": 0.6, "ADD b[r]+": 0.6,
    "ST b[r]+": 0.5, "CALL": 0.5, "MOV b[r+d]": 0.5, "OR r": 0.5, "CMP [r+x]": 0.4,
    "MOVS [sp+n]": 0.4, "OR b[r+d]": 0.4, "SETcc": 0.4, "ST [r+d]": 0.4, "MOVS [r]": 0.4,
    "ST b[r]": 0.4, "ADD b[r]": 0.4, "ST [r]+": 0.4, "MOV [r+d]": 0.4, "MOV [r]+": 0.3,
    "MOV #i16": 0.3, "CMP [r]": 0.3, "MOV b[r+x]": 0.3, "SUB r": 0.3, "LEA [sp+n]": 0.3,
    "MOV [abs]": 0.3, "NEG": 0.2, "ADD [r]+": 0.2, "SUB #q": 0.2, "CMP [r+d]": 0.2,
}
TAKEN = 0.45          # conditional branches taken (Bcc, Jcc, DBNZ)
DEP1 = 0.10           # memory operands whose base the instruction before wrote
DEP2 = 0.05           # ... or the one before that
SHIFTS = {1: 0.25, 2: 0.023, 3: 0.017, 4: 0.019, 6: 0.023, 7: 0.035, 8: 0.436, 9: 0.018,
          10: 0.017, 11: 0.023, 13: 0.023, 16: 0.007, 17: 0.017, 18: 0.017, 19: 0.017,
          22: 0.023, 24: 0.006, 25: 0.023, 31: 0.004}

KIND = {  # mix entry -> the recipe that stands for it
    "MOV r": "AND r1, r2", "CMP r": "ADD r1, r2", "INC": "ADD r1, r2", "ADD r": "ADD r1, r2",
    "XOR r": "AND r1, r2", "AND r": "AND r1, r2", "DEC": "ADD r1, r2", "TST": "AND r1, r2",
    "NOT": "AND r1, r2", "OR r": "AND r1, r2", "SUB r": "ADD r1, r2", "NEG": "ADD r1, r2",
    "ZXH": "AND r1, r2",
    "CMP #q": "CMP r1, #5", "CMPI": "CMP r1, #5", "MOV #q": "CMP r1, #5", "ADD #q": "CMP r1, #5",
    "SUB #q": "CMP r1, #5", "MOV #i16": "MOV r1, #0x12345678",
    "LEA [r+d]": "LEA r1, [r2 + 100]", "LEA [sp+n]": "LEA r1, [r2 + 100]",
    "ADD b[r+d]": "ADD r1, [r2 + 8]", "OR b[r+d]": "ADD r1, [r2 + 8]", "CMP [r+d]": "ADD r1, [r2 + 8]",
    "MOV [sp+n]": "MOV r1, [r2 + 8]", "MOVS [sp+n]": "MOV r1, [r2 + 8]", "MOV b[r+d]": "MOV r1, [r2 + 8]",
    "MOV [r+d]": "MOV r1, [r2 + 8]", "MOV [abs]": "MOV r1, [r2 + 8]",
    "MOV [r]": "MOV r1, [r2]", "MOV b[r]": "MOV r1, [r2]", "MOVS [r]": "MOV r1, [r2]",
    "ADD b[r]": "ADD r1, [r2 + 8]", "CMP [r]": "ADD r1, [r2 + 8]",
    "ST [abs]": "MOV [abs16], r1", "ST [sp+n]": "MOV [r2 + 8], r1", "ST [r+d]": "MOV [r2 + 8], r1",
    "ST [r]": "MOV [r2 + 8], r1", "CLR b[r]": "MOV [r2 + 8], r1", "ST b[r]": "MOV [r2 + 8], r1",
    "ST b[r]+": "PUSH r1", "ST [r]+": "PUSH r1",
    "MOVS b[r]+": "MOVS r1, byte [r2]+", "ADD b[r]+": "MOVS r1, byte [r2]+", "MOV [r]+": "POP r1",
    "ADD [r]+": "MOVS r1, byte [r2]+",
    "LEA [r+x]": "MOV r1, [r2 + r3*4 + 8]", "CMP [r+x]": "MOV r1, [r2 + r3*4 + 8]",
    "MOV b[r+x]": "MOV r1, [r2 + r3*4 + 8]", "INC [abs]": "INC [r2]",
    "BRA": "Bcc, taken", "JMP": "Bcc, taken", "BSR": "BSR / CALL label", "CALL": "BSR / CALL label",
    "RET": "RET (JMP r7)", "MULS": "MULU r0:r1, r2 (MQ)", "DIVU": "DIVU r0:r1, r2",
    "SAVE": "SAVE r8-r14", "RESTORE": "RESTORE r8-r14", "SETcc": "SETcc r1",
}

MEMOPS = {"MOV r1, [r2 + 8]", "MOV r1, [r2]", "ADD r1, [r2 + 8]", "MOV [r2 + 8], r1",
          "MOV [abs16], r1", "PUSH r1", "POP r1", "MOVS r1, byte [r2]+", "INC [r2]"}


def shift_ticks(design, floor):
    """A shift by #n, weighted by the traces' counts: bit steps below 8, a
    crossbar pass and the remaining bit steps from there."""
    r = recipes(design)
    bit = cost(r["LSL r1, #1"], floor)
    byte = cost(r["LSR r1, #8"], floor)
    t = 0
    for n, p in SHIFTS.items():
        t += p * (n * bit if n < 8 else byte + (n % 8) * bit)
    return t / sum(SHIFTS.values())


def weighted(design, floor, arith=False):
    r = recipes(design)
    c = {k: cost(v, floor) for k, v in r.items()}
    if arith:
        c["MULU r0:r1, r2 (MQ)"] = c["MULU r0:r1, r2 (ARITH board)"]
    total = 0.0
    for name, share in MIX.items():
        if name == "Bcc" or name == "DBNZ":
            t = TAKEN * c["Bcc, taken"] + (1 - TAKEN) * c["Bcc, not taken"]
            if name == "DBNZ":
                t += c["ADD r1, r2"]
        elif name in ("LSL", "LSR", "ASR", "ROR"):
            t = shift_ticks(design, floor)
        else:
            k = KIND[name]
            t = c[k]
            if k == "SAVE r8-r14" or k == "RESTORE r8-r14":
                t = t * 4 / 7          # four registers, not seven
            if design == "B" and k in MEMOPS:
                # EX's result reaches ADDR's copy a cycle after the next: a base from the
                # instruction before stalls the operand stage two cycles, from the one before that one
                t += (2 * DEP1 + DEP2) * floor
        total += share * t
    return total / sum(MIX.values())


# ---------------------------------------------------------------------------
# The tables

KEY = ["ADD r1, r2", "AND r1, r2", "CMP r1, #5", "MOV r1, #0x12345678", "LEA r1, [r2 + 100]",
       "MOV r1, [r2 + 8]", "MOV r1, [r2]", "ADD r1, [r2 + 8]", "MOV [r2 + 8], r1", "MOV [abs16], r1",
       "PUSH r1", "POP r1", "MOVS r1, byte [r2]+", "MOV r1, [r2 + r3*4 + 8]", "INC [r2]",
       "Bcc, not taken", "Bcc, taken", "BSR / CALL label", "RET (JMP r7)", "JMP [table + r2*4]",
       "LSL r1, #1", "LSR r1, #8", "ROR r1, #13", "MULU r0:r1, r2 (MQ)", "MULU r0:r1, r2 (ARITH board)",
       "DIVU r0:r1, r2", "SAVE r8-r14", "RESTORE r8-r14", "SETcc r1"]


def tables():
    out = []
    p = out.append
    p("# Napkin tables for RFC 0049\n")
    p("Generated by `heron cards napkin --write` ([studies/cards](../../studies/cards/README.md));"
      " don't edit by hand. Every number here is a sum from the parts lists and the delay table"
      " below: a napkin, not a netlist.\n")
    p("## The boards\n")
    p(f"A double Eurocard takes about {BUDGET} area units: a unit is a DIP-20's slot on a"
      " board soldered by hand, and wider parts take more (the table at the end). *Tax* is what"
      " a board carries only because it is a board of its own: its slice of the control store,"
      " its µPC receivers, its clock buffer, and its drivers and receivers on the backplane"
      " (some of which also serve as an operand's multiplexer).\n")
    for key, (title, boards) in DESIGNS.items():
        p(f"### Design {key}: {title}\n")
        p("| Board | Packages | Area units | Of which tax | 22V10s |")
        p("|---|---:|---:|---:|---:|")
        tc = ta = tt = tg = 0
        for name, blocks in boards:
            c, a, t, g = board_sums(blocks)
            n = copies(name)
            flag = " **over**" if a > BUDGET else ""
            p(f"| {name} | {c} | {a:.0f}{flag} | {t} | {g} |")
            tc += n * c; ta += n * a; tt += n * t; tg += n * g
        p(f"| **total** | **{tc}** | **{ta:.0f}** | **{tt}** | **{tg}** |")
        c, a, t, g = board_sums(ARITH)
        p(f"| *ARITH (optional)* | *{c}* | *{a:.0f}* | *{t}* | *{g}* |")
        p("")
    p("### The parts, block by block\n")
    for key, (title, boards) in DESIGNS.items():
        for name, blocks in boards:
            p(f"<details><summary>Design {key}, {name}</summary>\n")
            p("| Block | Parts | Packages |")
            p("|---|---|---:|")
            for bname, parts, tax in blocks:
                s = ", ".join(f"{n} × {pt}" for n, pt in parts)
                p(f"| {bname}{' (tax)' if tax else ''} | {s} | {sum(n for n, _ in parts)} |")
            p("\n</details>\n")
    p("<details><summary>The ARITH board (any design)</summary>\n")
    p("| Block | Parts | Packages |")
    p("|---|---|---:|")
    for bname, parts, tax in ARITH:
        s = ", ".join(f"{n} × {pt}" for n, pt in parts)
        p(f"| {bname}{' (tax)' if tax else ''} | {s} | {sum(n for n, _ in parts)} |")
    p("\n</details>\n")

    x = derived(D)
    p("## Delays\n")
    p(f"A tick is {TICK:.2f} ns (50.35 MHz). Every microcycle keeps {MARGIN:.0f} ns beyond its"
      " longest path. Worst-case figures, ns:\n")
    p("| | ns | |")
    p("|---|---:|---|")
    notes = {"bp": "the backplane, generous: report 0022 has 4.8–6.3 for 8 slots",
             "alu": "32-bit add: 181 to G,P, a GAL's lookahead, 181 carry to F, wire",
             "across": "one control line from board to board"}
    for k, v in D.items():
        p(f"| `{k}` | {v:g} | {notes.get(k, '')} |")
    for k, why in (("XD", "a value driven onto the backplane, at logic on another board"),
                   ("X", "the same through a driver of its own"),
                   ("RF", "register file data, after the cycle's write tick"),
                   ("ONX", "a register put on a bus at the cycle's start, at another board"),
                   ("FLAGS", "the flags of the cycle before, at CTRL"),
                   ("FLASHLOOP", "µPC over the backplane, through a flash, into a register")):
        p(f"| {k} | {x[k]:.1f} | {why} |")
    p("")
    p(f"The flash loop makes the floor {flash_floor()} ticks with 55 ns flashes; with 45 ns ones,"
      f" or a control store in SRAM, nothing in the control store stops at 4.\n")

    p("## Instruction timings\n")
    p("Ticks per instruction, with the shortest microcycle 4 ticks / 5 ticks (the flash"
      " floor). An instruction's decode overlaps its predecessor's last cycle, so these are"
      " the instructions' own cycles. Design B's operand stage runs in the cycle before and"
      " counts only where it lengthens it; a base register written by one of the two"
      " instructions before stalls it (not in this table, but in the weighting).\n")
    p("| Instruction | A | B | C |")
    p("|---|---:|---:|---:|")
    R = {k: recipes(k) for k in DESIGNS}
    for ins in KEY:
        cells = []
        for k in DESIGNS:
            cells.append(f"{cost(R[k][ins], 4)} / {cost(R[k][ins], 5)}")
        p(f"| `{ins}` | " + " | ".join(cells) + " |")
    p("")
    p("### Weighted\n")
    p("Ticks per instruction weighted by the compiled C programs' dynamic mix (a weighting,"
      f" not a benchmark: conditional branches {TAKEN:.0%} taken, shifts by the traces'"
      f" counts, SAVE and RESTORE of four registers; B's operand stage stalls two cycles on the"
      f" {DEP1:.0%} of memory operands whose base the instruction before wrote, one on the {DEP2:.0%}"
      " whose base the one before that wrote):\n")
    p("| | A | B | C |")
    p("|---|---:|---:|---:|")
    for fl in (4, 5):
        for ar in (False, True):
            row = [weighted(k, fl, ar) for k in DESIGNS]
            lab = f"floor {fl}" + (", ARITH board" if ar else ", MQ")
            p(f"| {lab} | " + " | ".join(f"{t:.2f} ({t * TICK:.0f} ns)" for t in row) + " |")
    p("")
    p("## Cycle by cycle\n")
    p("Each microcycle's longest path (ns) and its ticks at the 4-tick floor.\n")
    for k, (title, _) in DESIGNS.items():
        p(f"<details><summary>Design {k}: {title}</summary>\n")
        p("| Instruction | Microcycle | Path, ns | Ticks |")
        p("|---|---|---:|---:|")
        for ins in KEY:
            cyc = R[k][ins]
            # collapse repeated identical cycles
            i = 0
            first = True
            while i < len(cyc):
                j = i
                while j + 1 < len(cyc) and cyc[j + 1] == cyc[i]:
                    j += 1
                what, ns = cyc[i]
                rep = f" (× {j - i + 1})" if j > i else ""
                nst = "floor" if ns is None else f"{ns:.1f}"
                p(f"| {'`' + ins + '`' if first else ''} | {what}{rep} | {nst} | {ticks(ns, 4)} |")
                first = False
                i = j + 1
        p("\n</details>\n")
    p("## Area units\n")
    p("| Part | Package | Units |")
    p("|---|---|---:|")
    for k, (pkg, a) in PARTS.items():
        p(f"| {k} | {pkg} | {a:g} |")
    p("")
    return "\n".join(out)


def write(path=OUT):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write(tables())
    return path
