"""ODT, the console monitor in microcode: the two-halves machine's (RFC
0047). The halt button, or a step, enters it at an instruction's end; it
talks on UART 0, as the program left it (reset sets 115200 baud, 8N1),
and needs nothing in memory. Its syntax, in hex:

    @           ODT's prompt; on entry it prints the PC it stopped at first
    a/          open the word at a: ODT prints it
    %n/         open register n (0-F, in the bank the program was in)
    v CR        write v to what's open, and close it
    v LF        write v, and open the next word (memory)
    CR, LF      the same without writing
    G           go on, at the PC ODT stopped at
    a G         go to a
    S           step: one instruction, then back in ODT
    ?           what ODT didn't understand

Letters may be lower case; every character is echoed. ODT asserts RTS
only while it waits for a character, so a terminal that keeps to RTS
can't overrun it (reset turns the UART's FIFOs on, for one that doesn't). A word is read and
written as two halfwords, whatever a's alignment (A0 is ignored), so that
a device's registers can be poked; 32 bits at a time, so the second
halfword's device sees an access too.

How it works:

- it's one of flat.py's routines, in three parts as it was written for the
  paged store's blocks (9, 15 and 14, whose N <- s are now plain jumps);
- the interrupt's entry reads the interrupt controller's +4 into d and s
  (MOP_LDIRM): 0x9000 while ODT is asked for, so d 9 and s 0, which
  `regsel` counts from; ODT keeps TRACE on while it runs, so that the same
  read sets them again;
- its state is in the microcode's temporaries, dead between instructions;
  it changes the flags but puts V, C, Z and N back as it leaves; it
  leaves by fetching the next instruction itself, so that a step's TRACE
  isn't seen until that instruction's end.
"""

from .ucode2 import (
    AX_MARINC, AX_MARLO, AX_PCLO, DS_FLW, IMM_CODE, IRN_DECS, IRN_INCD, IRN_NS, LDL,
    MOP_FETCH, MOP_LDIRM, RD, RM_ZXB, SEQ_END, T, T_A, T_B, T_C, T_CNT, T_FW, T_Q, T_R, T_RET,
    T_VEC, W, alu, ax, fl, hx, imm, jump, label, mem, rd, store, u, wr,
)

T_MCR, T_V, T_IO4, T_FL, T_K, T_OPEN, T_W = T(6), T(7), T(11), T(12), T(13), T(14), T(15)
FLW = {"DS": DS_FLW, "IMMF": IMM_CODE["ZERO"]}


def irn(code):
    return {"IRN": code}


class _Labels:
    def __init__(self):
        self.n = 0

    def __call__(self, stem):
        self.n += 1
        return f"_{stem}{self.n}"


def putc(new, src, then=None):
    """UART 0's transmitter <- the byte that src puts on D (rd(T_C, 0), an
    immediate), once it's empty; `then` on the last microinstruction."""
    w = new("tx")
    return [u(rd(T_FW), alu("A"), ax(AX_MARLO), W),                       # LSR
            u(imm("C32"), LDL, alu("ZERO"), fl("STZ")),                   # THRE; ST <- 1
            u(mem("MAR", 1), alu("AND"), fl("STZ"), jump(w, "ST"), label(w)),   # not empty yet
            u(rd(T_VEC), alu("A"), ax(AX_MARLO), W),
            u(src, store(1), then or {})]


def to9(target):
    """Back to block 9, at target."""
    return [u(rd(T_IO4), alu("A"), ax(AX_MARLO), W),
            u({"MOP": MOP_LDIRM}, jump(target))]


def regsel(new):
    """d <- T_B's register number (d is 9): n + 7 steps of d + 1."""
    w = new("rs")
    return [u(imm("C6"), LDL),
            u(rd(T_B, 0), alu("ADD"), wr(T_CNT, 0), fl("STZ")),           # ST <- 0
            u(rd(T_CNT, 0), alu("DEC"), wr(T_CNT, 0), fl("STZ"), irn(IRN_INCD),
              jump(w, "ST", True), label(w))]


def block9(new):
    """The entry, the keyboard and the commands that don't need a location:
    s is 0 here and d 9."""
    return [
        label("entry"),
        u(imm("C1"), store(2)),                                   # +4: TRACE on, the halt latch off
        u(FLW, alu("A"), wr(T_FL), hx("ZERO")),
        u(imm("IOU0"), alu("A"), wr(T_VEC), W),                   # UART 0: RBR and THR
        u(imm("C8"), LDL, W),
        u(rd(T_VEC), alu("ADD"), wr(T_MCR), W),                   # +8: MCR
        u(imm("C2"), alu("ADD"), wr(T_K, 0)),                     # T_K: 10 (LF), and
        u(imm("C2"), LDL, W),
        u(rd(T_MCR), alu("ADD"), wr(T_FW), W),                    # +10: LSR
        u(imm("C32"), LDL, irn(IRN_DECS)),
        u(imm("C16"), alu("ADD"), wr(T_K, 1), irn(IRN_DECS)),     # '0' in its high half
        u(imm("ZERO"), alu("A"), wr(T_OPEN, 0), irn(IRN_NS), jump("o_entry")),
        label("in0"),                                             # a new number
        u(imm("ZERO"), alu("A"), wr(T_A), W),
        u(imm("ZERO"), alu("A"), wr(T_Q), W),                     # digits typed, '%' typed
        label("in"),
        u(rd(T_MCR), alu("A"), ax(AX_MARLO), W),
        u(imm("U7_3"), store(1)),                                 # RTS: the terminal may send
        u(rd(T_FW), alu("A"), ax(AX_MARLO), W, fl("STF0")),       # ST <- 0
        u(mem("MAR", 1), alu("A"), fl("STF0"), jump("in_w", "ST", True), label("in_w")),
        u(rd(T_VEC), alu("A"), ax(AX_MARLO), W),
        u(mem("MAR", 1), alu("A", rm=RM_ZXB), wr(T_C, 0)),
        u(rd(T_MCR), alu("A"), ax(AX_MARLO), W),
        u(imm("C1"), store(1)),                                   # not while ODT works
        u(imm("C64"), LDL),
        u(rd(T_C, 0), alu("AND"), fl("STZ")),                     # ST: not a letter
        u(imm("C32"), LDL, jump("echo", "ST")),
        u(rd(T_C, 0), alu("BIC"), wr(T_C, 0)),                    # upper case
        label("echo"),
    ] + putc(new, rd(T_C, 0)) + [
        # the character, by subtracting: c - 10, - 13 and so on (N and Z)
        u(rd(T_K, 0), LDL),
        u(rd(T_C, 0), alu("SUB"), wr(T_C, 0), fl("NZ16")),        # LF
        u(imm("U7_3"), LDL, jump("c_lf", "Z")),
        u(rd(T_C, 0), alu("SUB"), wr(T_C, 0), fl("NZ16")),        # CR
        u(imm("C16"), LDL, jump("c_cr", "Z")),
        u(rd(T_C, 0), alu("SUB"), wr(T_C, 0)),
        u(imm("C8"), LDL),
        u(rd(T_C, 0), alu("SUB"), wr(T_C, 0), fl("NZ16")),        # '%': 13 + 16 + 8
        u(rd(T_K, 0), LDL, jump("c_pct", "Z")),
        u(rd(T_C, 0), alu("SUB"), wr(T_C, 0), fl("NZ16")),        # '/' (N: below it)
        u(imm("C1"), LDL, jump("c_slash", "Z")),
        u(rd(T_C, 0), alu("SUB"), wr(T_C, 0), fl("NZ16"), jump("c_err", "N")),   # c - '0'
        u(rd(T_K, 0), LDL),
        u(rd(T_C, 0), alu("SUB"), fl("NZ16")),                    # N: '0'-'9'
        u(imm("U7_7"), LDL, jump("c_dig", "N")),
        u(rd(T_C, 0), alu("SUB"), wr(T_C, 0)),                    # c - 55: 'A' is 10
        u(rd(T_K, 0), LDL),
        u(rd(T_C, 0), alu("SUB"), fl("NZ16")),                    # N: ':'-'@'
        u(imm("C16"), LDL, jump("c_err", "N")),
        u(rd(T_C, 0), alu("SUB"), wr(T_CNT, 0), fl("NZ16")),      # N: 'A'-'F'; Z: 'G'
        u(rd(T_CNT, 0), LDL, jump("c_dig", "N")),
        u(imm("V_SWI"), alu("SUB"), fl("NZ16"), jump("c_go", "Z")),     # Z: 'S'
        u(jump("c_step", "Z")),
        label("c_err"),
        u(irn(IRN_DECS)),
        u(irn(IRN_DECS)),
        u(irn(IRN_NS), jump("o_err")),
        label("c_dig"),                                           # T_A <- T_A * 16 + the digit
        u(rd(T_A), alu("SHL"), wr(T_A), W),
        u(rd(T_A), alu("SHL"), wr(T_A), W),
        u(rd(T_A), alu("SHL"), wr(T_A), W),
        u(rd(T_A), alu("SHL"), wr(T_A), W),
        u(rd(T_C, 0), LDL),
        u(rd(T_A, 0), alu("OR"), wr(T_A, 0)),
        u(imm("C1"), alu("A"), wr(T_Q, 0), jump("in")),
        label("c_pct"),
        u(imm("C1"), alu("A"), wr(T_Q, 1), jump("in")),
        label("c_slash"),
        u(irn(IRN_DECS)),
        u(irn(IRN_NS), jump("x_slash")),
        label("c_cr"),
        u(irn(IRN_DECS)),
        u(irn(IRN_NS), jump("x_cr")),
        label("c_lf"),
        u(irn(IRN_DECS)),
        u(irn(IRN_NS), jump("x_lf")),
        label("c_go"),
        u(rd(T_Q, 0), alu("A"), fl("STZ")),                       # ST: no address typed
        u(jump("go", "ST")),
        u(rd(T_A), alu("A"), wr(T_RET), W),
        label("go"),
        u(rd(T_IO4), alu("A"), ax(AX_MARLO), W),
        u(imm("ZERO"), store(2)),                                 # TRACE off
        label("c_step"),                                          # (TRACE stays on)
        u(rd(T_FL, 0), LDL),
    ] + [u(imm(b), alu("AND"), fl(f))
         for b, f in (("C1", "VNZ"), ("C2", "CNZ"), ("C4", "ZNZ"), ("C8", "NNZ"))] + [
        u(rd(T_RET), alu("A"), ax(AX_PCLO), W),
        # the instruction's fetch and decode, but not the interrupt's
        # check: a step's TRACE is for its end
        u({"MOP": MOP_FETCH, "SEQ": SEQ_END, "_nochk": 1}),
    ]


def block15(new):
    """Opening a location and writing it: s is 15, d 9."""
    return [
        label("x_slash"),
        u(rd(T_A), alu("A"), wr(T_B), W),                         # the location
        u(rd(T_Q, 1), alu("A"), fl("STZ")),                       # ST: no '%': memory
        u(imm("C1"), alu("A"), wr(T_OPEN, 0), jump("x_om", "ST")),
        u(imm("C2"), alu("A"), wr(T_OPEN, 0)),
    ] + regsel(new) + [
        u(rd(RD), alu("A"), wr(T_V), W, irn(IRN_DECS)),
        u(irn(IRN_NS), jump("o_open")),
        label("x_om"),
        u(rd(T_B), alu("A"), ax(AX_MARLO), W, irn(IRN_DECS)),
        u(mem("MAR", 4), alu("A"), wr(T_V), ax(AX_MARINC), W, irn(IRN_NS), jump("o_open")),
        label("x_lf"),
        u(imm("C1"), alu("A"), wr(T_R, 0), jump("x_dep")),
        label("x_cr"),
        u(imm("ZERO"), alu("A"), wr(T_R, 0)),
        label("x_dep"),
        u(rd(T_Q, 0), alu("A"), fl("STZ")),                       # ST: nothing typed
        u(rd(T_OPEN, 0), alu("DEC"), fl("STZ"), jump("x_next", "ST")),   # ST: memory open
        u(jump("x_dm", "ST")),
        u(rd(T_OPEN, 0), alu("A"), fl("STZ")),                    # ST: nothing open
        u(jump("x_next", "ST")),
    ] + regsel(new) + [
        u(rd(T_A), alu("A"), wr(RD), W, jump("x_next")),
        label("x_dm"),
        u(rd(T_B), alu("A"), ax(AX_MARLO), W),
        u(rd(T_A), store(4), ax(AX_MARINC), W),
        label("x_next"),
        u(rd(T_R, 0), alu("A"), fl("STZ")),                       # ST: CR
        u(rd(T_OPEN, 0), alu("DEC"), fl("STZ"), jump("x_close", "ST")),   # ST: memory open
        u(jump("x_close", "ST", True)),
        u(imm("C4"), LDL, W),
        u(rd(T_B), alu("ADD"), wr(T_B), ax(AX_MARLO), W),          # the next word
        u(rd(T_B), alu("A"), wr(T_V), W),                          # its address, to print
        u(mem("MAR", 4), alu("A"), wr(T_W), ax(AX_MARINC), W, irn(IRN_DECS)),
        u(irn(IRN_NS), jump("o_next")),
        label("x_close"),
        u(imm("ZERO"), alu("A"), wr(T_OPEN, 0), irn(IRN_DECS)),
        u(irn(IRN_NS), jump("o_prompt")),
    ]


def block14(new):
    """What ODT prints: s is 14."""
    dput = new("dput")
    return [
        label("o_entry"),                                         # LF, CR, the PC; the prompt
        u(rd(T_RET), alu("A"), wr(T_V), W),
        u(imm("C2"), alu("A"), wr(T_R, 0)),
    ] + putc(new, rd(T_K, 0)) + [
        label("o_crhex"),
        u(imm("V_SWI"), alu("INC"), wr(T_C, 0)),                  # CR
    ] + putc(new, rd(T_C, 0)) + [
        label("o_hex"),                                           # T_V's 8 digits; then by T_R
        u(imm("C8"), alu("A"), wr(T_CNT, 0)),
        label("o_dig"),
        u(rd(T_V), alu("SHL"), wr(T_V), W, fl("SHL")),            # C: the next bit
        u(imm("ZERO"), alu("SHLC"), wr(T_C, 0)),
    ] + [u(rd(T_V), alu("SHL"), wr(T_V), W, fl("SHL")),
         u(rd(T_C, 0), alu("SHLC"), wr(T_C, 0))] * 3 + [
        u(rd(T_K, 0), LDL),
        u(rd(T_C, 0), alu("SUB"), fl("STN")),                     # ST: 0-9
        u(rd(T_K, 1), LDL),
        u(rd(T_C, 0), alu("ADD"), wr(T_C, 0), jump(dput, "ST")),
        u(imm("C6"), LDL),
        u(rd(T_C, 0), alu("ADDB1"), wr(T_C, 0)),                  # A-F
        label(dput),
    ] + putc(new, rd(T_C, 0)) + [
        u(rd(T_CNT, 0), alu("DEC"), wr(T_CNT, 0), fl("STZ")),
        u(rd(T_R, 0), alu("A"), fl("STZ"), jump("o_dig", "ST", True)),   # ST: T_R 0, the open's
        u(rd(T_R, 0), alu("DEC"), fl("STZ"), jump("o_sp", "ST")),        # ST: 1, LF's
        u(jump("o_crlf", "ST", True)),                                    # 2, the entry's
        u(rd(T_W), alu("A"), wr(T_V), W),                         # the word, after its address
        u(imm("ZERO"), alu("A"), wr(T_R, 0)),
        u(imm("C31"), LDL),
        u(imm("C16"), alu("ADD"), wr(T_C, 0)),                    # '/'
    ] + putc(new, rd(T_C, 0), jump("o_hex")) + [
        label("o_sp"),
    ] + putc(new, imm("C32")) + to9("in0") + [
        label("o_err"),
        u(imm("C64"), alu("DEC"), wr(T_C, 0)),                    # '?'
    ] + putc(new, rd(T_C, 0)) + [
        label("o_crlf"),
        u(imm("V_SWI"), alu("INC"), wr(T_C, 0)),                  # CR
    ] + putc(new, rd(T_C, 0)) + [
        label("o_prompt"),
    ] + putc(new, rd(T_K, 0)) + putc(new, imm("C64")) + to9("in0") + [
        label("o_open"),
        u(imm("ZERO"), alu("A"), wr(T_R, 0), jump("o_hex")),
        label("o_next"),
        u(imm("C1"), alu("A"), wr(T_R, 0), jump("o_crhex")),
    ]


def routine():
    """ODT as one of flat.py's routines: its three parts in a row."""
    new = _Labels()
    return block9(new) + block15(new) + block14(new)
