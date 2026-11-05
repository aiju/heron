"""Reed's system microcode: RFC 0029's exceptions, interrupts and system
instructions on Reed's hardware (ucode.py builds them in with the rest).

The special registers live in the system bank, EB 0x100 (SB below), r0-r15
of it; its K registers 16-31 are the microcode's constants as every bank's
are. Supervisor mode runs in bank 0, user mode in `bank`; a word reaches
the special registers by switching EB to 0x100 and back, which takes
effect for the next word's reads (and the word's own result, written in the
next cycle's write phase).

  SR    sr's S, I and T (bits 31-29): the flags are the ALU board's, IPL
        the interrupt controller's
  VBR   vbr                       BANK  `bank`
  CTX   ctx as written (bit 31: the page map's enable)
  MAPV  mapa's page << 12, ORed with 0xFFC0_0000 (an increment past page
        1023 carries out)         MAPC  mapa's context
  FAR   MEM's FAR and FSR as the last page fault or address error left
        them (FARR): far is its bits 21-0 and 31
  FSR   fsr, as the last page fault left it
  IC    0xC000_5800, the interrupt controller (through the window)
  SIT   0xE000_0000 (S, I, T)    B30   0x4000_0000 (I)
  FARM  0x803F_FFFF (far's bits)  MAPV0 0xFFC0_0000 (MAPV's page 0)
  PC, OFF, ST0  an exception's saved PC, its vector's offset, a temporary

One K a word, so the B side is MQ wherever a word needs a second register:
MQ also carries values from one bank to another.

An exception's entry (RFC 0029, 6): the saved PC (a fault's: PC less the
instruction's length, ILEN) into SB PC and the offset into SB OFF, then
`enter`: sr (SB SR, the flags and IPL from the controller's status
register) and the PC pushed on bank 0's sp, S set (MOP SYSW), I cleared,
the jump to vbr + the offset, EB 0. A fault comes to word 0 (FAULT sends
the next address there), which tells it from reset by KILL; an interrupt,
and a fetch's fault, to IVEC, a decode's diversion.
"""

from . import fields as F
from .ctrl import IVEC
from .ucode import (K_0100, K_0400, K_0800, K_80, K_FF, K_M1, K_SIGN, SP, T0, T1, W,
                    reset_constants, tail_word)

SB = 0x100
(SR, VBR, BANK, CTX, MAPV, MAPC, FAR, FSR, IC, SIT, B30, FARM, PC, OFF, ST0, MAPV0) = range(16)

# the vector offsets (RFC 0029, 6)
V_ILLEGAL, V_DIV, V_ADDR, V_PRIV, V_PAGE, V_SWI = 0x08, 0x10, 0x14, 0x1C, 0x20, 0x100

EB_SYS = f"RBS=K K={K_0100} BIN=RF BOUT=1 EBLD=1"
# S set (B31 from K_SIGN): an entry's first, before it reaches the window
S_ON = f"RBS=K K={K_SIGN} BIN=RF BOUT=1 MOP=SYSW"
EB_0 = "IMM=ZERO EBLD=1"


def chain(p, *items, label=None):
    """Words in a row from field strings (or Words): the last one's
    successor as it says, or "next" for the caller to set. Returns the
    words."""
    ws = [it if isinstance(it, type(W())) else W(None, it) for it in items]
    if label:
        ws[0].label = label
    for w, n in zip(ws, ws[1:]):
        if w.next == "next":
            w.next = ("jump", p._label(n))
    return ws


def go(target):
    """A word that only jumps (a pair's arm to a word placed elsewhere)."""
    return W(None, "", next=("jump", target if isinstance(target, str) else target.label))


def place(p, ws):
    for w in ws:
        if w.addr is None:
            p.place(w)
    return ws[0]


def const_words(k, value):
    """Words that make `value` in register k (in place: IMM ONE, then a
    shift and an add of ONE a bit)."""
    bits = bin(value)[2:]
    out = [f"AOP=PASSB BIN=BUS IMM=ONE WS=K K={k}" if bits[0] == "1" else f"AOP=ZERO WS=K K={k}"]
    for b in bits[1:]:
        out.append(f"RAS=K K={k} AOP=SHL CI=0 WS=K")
        if b == "1":
            out.append(f"RAS=K K={k} AOP=ADD CI=0 BIN=BUS IMM=ONE WS=K")
    return out


def offset_words(off):
    """SB OFF = off, from IMM FOUR by shifts and adds (EB the system bank's)."""
    if off == V_ILLEGAL:
        return [f"AOP=PASSB BIN=BUS IMM=FOUR WS=K K={OFF}", f"RAS=K K={OFF} AOP=SHL CI=0 WS=K"]
    if off == V_DIV:
        return [f"AOP=PASSB BIN=BUS IMM=FOUR WS=K K={OFF}"] + [f"RAS=K K={OFF} AOP=SHL CI=0 WS=K"] * 2
    if off == V_ADDR:
        return offset_words(V_DIV) + [f"RAS=K K={OFF} AOP=ADD CI=0 BIN=BUS IMM=FOUR WS=K"]
    if off == V_PAGE:
        return [f"AOP=PASSB BIN=BUS IMM=FOUR WS=K K={OFF}"] + [f"RAS=K K={OFF} AOP=SHL CI=0 WS=K"] * 3
    if off == V_PRIV:
        return offset_words(V_PAGE) + [f"RAS=K K={OFF} AOP=SUB CI=OWN BIN=BUS IMM=FOUR WS=K"]
    raise ValueError(off)


def ilen_pc(p, then):
    """SB PC -= 2 x ILEN (the executing instruction's length in parcels; 0
    is 4), then `then` (a label). Returns the first word."""
    dec2 = [f"RAS=K K={PC} AOP=DECA CI=0 WS=K"] * 2
    sub4 = f"RAS=K K={PC} AOP=SUB CI=OWN BIN=BUS IMM=FOUR WS=K"
    paths = {0: [sub4, sub4], 1: dec2, 2: [sub4], 3: [sub4] + dec2}
    leaf = {}
    for n, fs in paths.items():
        ws = chain(p, *fs)
        ws[-1].next = ("jump", then)
        leaf[n] = ws
    lo = W(None, "", next=("if", "ILEN0", p.pair(leaf[0][0], leaf[1][0])))
    hi = W(None, "", next=("if", "ILEN0", p.pair(leaf[2][0], leaf[3][0])))
    for ws in leaf.values():
        place(p, ws)
    first = W(None, "", next=("if", "ILEN1", p.pair(lo, hi)))
    p.place(first)
    return first


def system(p, entries):
    """Every routine; entries gets the decode table's (op, hi, lo) keys."""
    enter_sr = enter_tail(p)
    enter = place(p, chain(
        p,
        S_ON,
        # the status register: the flags and IPL, a byte's read (B15-B8 0;
        # IPL in B27-B24) into MQ; sr = SB SR | it
        f"RAS=K K={IC} AOP=ADD CI=0 BIN=BUS IMM=FOUR AOUT=F MARLD=1",
        "MOP=LOAD MSZ=BYTE DACC=1 MQ=LOAD",
        W(None, f"RAS=K K={SR} MQ=DRIVE BIN=BUS AOP=OR WS=K", next=("jump", enter_sr)),
        label="enter"))
    sync = {}
    for name, off in (("illegal", V_ILLEGAL), ("divzero", V_DIV), ("privilege", V_PRIV)):
        # (EB the system bank's already; the instruction's own PC)
        ws = chain(p, f"AIN=1 PCOP=DRIVE AOP=PASSA WS=K K={PC}", label=f"x_{name}")
        offs = chain(p, *offset_words(off))
        offs[-1].next = ("jump", enter.label)
        place(p, offs)
        ws[-1].next = ("jump", ilen_pc(p, offs[0].label).label)
        place(p, ws)
        # from any bank
        sync[name] = place(p, chain(p, W(name, EB_SYS, next=("jump", ws[0].label))))
    fault_entry(p, enter)
    interrupt_entry(p, enter, enter_sr)
    halt(p, entries, sync)
    rti(p, entries, sync)
    ei_di_spl(p, entries, sync)
    swi(p, entries, enter)
    special(p, entries, sync)
    user_regs(p, entries, sync)
    return sync


def enter_tail(p):
    """An exception's frame and jump, from SB SR holding the sr to push
    (EB the system bank's): returns the label of its first word."""
    push = lambda: [EB_0,
                    f"RAS=K K={SP} AOP=SUB CI=OWN BIN=BUS IMM=FOUR AOUT=F MARLD=1 WS=K",
                    "MQ=DRIVE BIN=BUS AOP=PASSB AOUT=F MOP=STORE MSZ=WORD DACC=1",
                    EB_SYS]
    ws = chain(
        p,
        f"RBS=K K={PC} BIN=RF BOUT=1 MQ=LOAD", *push(),
        f"RBS=K K={SR} BIN=RF BOUT=1 MQ=LOAD", *push(),
        # S set (B31 from K_SIGN), I clear, T clear: SB SR = S
        f"RBS=K K={K_SIGN} BIN=RF BOUT=1 MQ=LOAD MOP=SYSW IFL=CLEAR",
        f"MQ=DRIVE BIN=BUS AOP=PASSB WS=K K={SR}",
        f"RBS=K K={OFF} BIN=RF BOUT=1 MQ=LOAD",
        f"RAS=K K={VBR} MQ=DRIVE BIN=BUS AOP=ADD CI=0 AOUT=F PCOP=LOAD",
        W(None, EB_0, next=("brdec", "waitd")),
        label="enter_sr")
    place(p, ws)
    return ws[0].label


def fsr_words(p, then):
    """SB FSR = fsr from SB FAR (FSR's bits 6-0 are its bits 28-22: FAR
    shifted left 3, right 25) and SB SR's S as bit 7; then `then`."""
    add = W(None, f"RAS=K K={ST0} MQ=DRIVE BIN=BUS AOP=ADD CI=0 WS=K")
    end = chain(p, f"RBS=K K={ST0} BIN=RF BOUT=1 MQ=LOAD",
                W(None, f"MQ=DRIVE BIN=BUS AOP=PASSB WS=K K={FSR}", next=("jump", then)))
    place(p, end)
    add.next = ("jump", end[0].label)
    p.place(add)
    ws = chain(p, f"RBS=K K={FAR} BIN=RF BOUT=1 MQ=LOAD",
               f"MQ=DRIVE BIN=BUS AOP=PASSB WS=K K={ST0}",
               *[f"RAS=K K={ST0} AOP=SHL CI=0 WS=K"] * 3,
               *[f"RAS=K K={ST0} BIN=SHIFT SI=0 AOP=PASSB WS=K"] * 25,
               f"RAS=K K={SR} AOP=PASSA STOP=F31",
               f"RBS=K K={K_80} BIN=RF BOUT=1 MQ=LOAD",
               W(None, "", next=("if", "ST", p.pair(go(end[0]), go(add)))))
    place(p, ws)
    return ws[0]


def fault_entry(p, enter):
    """Word 0's fault path: FAR and FSR (FARR) into MQ, the cause from
    FSR's bits 8 (z 3: illegal) and 7 (misaligned: address error), else
    the page map's (page fault, which sets SB FSR); SB FAR for either of
    those; the instruction's own PC."""
    offs = {}
    for off in (V_ILLEGAL, V_ADDR, V_PAGE):
        ws = chain(p, *offset_words(off))
        ws[-1].next = ("jump", enter.label)
        offs[off] = place(p, ws)
    page = fsr_words(p, offs[V_PAGE].label)
    x4 = W(None, f"MQ=DRIVE BIN=BUS AOP=PASSB WS=K K={FAR}",
           next=("if", "ST", p.pair(go(page), go(offs[V_ADDR]))))
    x3 = W(None, "", next=("if", "ST", p.pair(x4, go(offs[V_ILLEGAL]))))
    p.place(x3)
    ws = chain(
        p,
        "MOP=FARR MQ=LOAD",
        f"MQ=DRIVE BIN=BUS AOP=PASSB WS=K K={ST0}",
        # (bit 30 z 3, bit 29 misaligned, onto F31 for ST)
        f"RAS=K K={ST0} AOP=SHL CI=0 WS=K STOP=F31",
        W(None, f"RAS=K K={ST0} AOP=SHL CI=0 WS=K STOP=F31", next=("jump", x3.label)))
    place(p, ws)
    pcw = chain(p, f"AIN=1 PCOP=DRIVE AOP=PASSA WS=K K={PC}")
    pcw[-1].next = ("jump", ilen_pc(p, ws[0].label).label)
    place(p, pcw)
    # word 0's fault successor ("fault", ucode.build's pair): to the system bank
    p.place(W("fault_go", EB_SYS, next=("jump", pcw[0].label)))


def interrupt_entry(p, enter, enter_sr):
    """IVEC: a decode diverted, for an interrupt (pending and enabled) or
    for a fetch's fault (FFQ: the instruction at the decode pointer isn't
    all there). Either saves PC as it is: the next instruction's, or the
    one whose fetch faulted.

    An interrupt: sr pushed as it was, then the controller's vector
    register (the offset in bits 7-0, the level in 27-24) read and written
    back (IPL = the level), the offset 0xFF of it."""
    irq = chain(
        p,
        EB_SYS,
        S_ON,
        f"AIN=1 PCOP=DRIVE AOP=PASSA WS=K K={PC}",
        f"RAS=K K={IC} AOP=ADD CI=0 BIN=BUS IMM=FOUR AOUT=F MARLD=1",
        "MOP=LOAD MSZ=BYTE DACC=1 MQ=LOAD",
        f"RAS=K K={SR} MQ=DRIVE BIN=BUS AOP=OR WS=K",
        f"RAS=K K={IC} AOUT=OA MARLD=1",
        "MOP=LOAD MSZ=BYTE DACC=1 MQ=LOAD",
        f"RAS=K K={IC} AOUT=OA MARLD=1",
        "MQ=DRIVE BIN=BUS AOP=PASSB AOUT=F MOP=STORE MSZ=WORD DACC=1",
        f"MQ=DRIVE BIN=BUS AOP=PASSB WS=K K={OFF}",
        f"RBS=K K={K_FF} BIN=RF BOUT=1 MQ=LOAD",
        W(None, f"RAS=K K={OFF} MQ=DRIVE BIN=BUS AOP=AND WS=K", next=("jump", enter_sr)),
        label="irq")
    place(p, irq)
    offs = chain(p, *offset_words(V_PAGE))
    offs[-1].next = ("jump", enter.label)
    place(p, offs)
    page = fsr_words(p, offs[0].label)
    ff = chain(p, EB_SYS, f"AIN=1 PCOP=DRIVE AOP=PASSA WS=K K={PC}",
               "MOP=FARR MQ=LOAD",
               W(None, f"MQ=DRIVE BIN=BUS AOP=PASSB WS=K K={FAR}", next=("jump", page.label)),
               label="ffault")
    place(p, ff)
    # (CND FFQ: a fetch has faulted and the instruction at the decode
    # pointer isn't all there: an interrupt pending as well goes first)
    p.place(W("ivec", "", next=("if", "FFQ", p.pair(W(None, "", next=("jump", "irq")),
                                                  W(None, "", next=("jump", "ffault"))))), at=IVEC)


def priv(p, label, body, sync):
    """A privileged instruction: EB to the system bank, ST = SB SR's S,
    then body's words (field strings or Words). The decision is at the
    body's second word (two after the ST's), so the first two run in user
    mode too and must leave nothing behind; user mode then goes to the
    privilege violation. EB is the system bank's as the body starts.
    Returns the first word."""
    first = chain(p, EB_SYS, f"RAS=K K={SR} AOP=PASSA STOP=F31", label=label)
    rest = chain(p, *body)
    while len(rest) < 3:
        filler = W(None, "", next="decode")
        if rest:
            rest[-1].next = ("jump", p._label(filler))
        rest.append(filler)
    a, go = rest[1], rest[2]
    a.next = ("if", "ST", p.pair(W(None, "", next=("jump", sync["privilege"].label)),
                                 W(None, "", next=("jump", p._label(go)))))
    first[-1].next = ("jump", p._label(rest[0]))
    place(p, first)
    for w in rest:
        if w.addr is None:
            p.place(w)
    return first[0]


def halt(p, entries, sync):
    """HALT: with I clear, stop (the halt words, which a run stops at);
    with I set, wait for an interrupt (IRQP), whose entry saves the PC
    after the HALT."""
    wait = W("hwait", "", next=None)
    wait.next = ("if", "IRQP", p.pair(W(None, "", next=("jump", "hwait")), W(None, "", next=("jump", "irq"))))
    p.place(wait)
    body = [f"RBS=K K={SR} BIN=RF BOUT=1 MQ=LOAD",
            f"RAS=K K={B30} MQ=DRIVE BIN=BUS AOP=AND STOP=C32",
            EB_0,
            W(None, "", next=("if", "ST", p.pair(W(None, "", next=("jump", "halt")),
                                                W(None, "", next=("jump", "hwait")))))]
    priv(p, "HALT", body, sync)
    entries[(0xFE, 0, 3)] = ("HALT", 1)


def rti(p, entries, sync):
    """RTI: pop sr, then PC (precise: sp changes after both loads); the
    flags and S from sr, IPL (a write of sr to the controller's register
    0), I and T; then the mode's bank, and the jump."""
    def back(user):
        jump = [EB_0] if not user else [f"RBS=K K={BANK} BIN=RF BOUT=1 MQ=LOAD", EB_0]
        out = jump + [f"RAS=K K={T0} AOUT=OA PCOP=LOAD",
                      W(None, "MQ=DRIVE EBLD=1" if user else "BFREE=1", next=("brdec", "waitd"))]
        return chain(p, *out)
    tails = {}
    for user in (0, 1):
        for i_on in (0, 1):
            g = back(user)
            place(p, g)
            w = W(None, "IFL=SET" if i_on else "IFL=CLEAR", next=("jump", g[0].label))
            p.place(w)
            tails[user, i_on] = w
    paths = {}
    for user in (0, 1):
        a = W(None, f"RBS=K K={SIT} BIN=RF BOUT=1 MQ=LOAD")
        b = W(None, f"RAS=K K={SR} MQ=DRIVE BIN=BUS AOP=AND WS=K",
              next=("if", "ST", p.pair(go(tails[user, 0]), go(tails[user, 1]))))
        a.next = ("jump", p._label(b))
        p.place(a), p.place(b)
        paths[user] = a
    body = [EB_0,
            f"RAS=K K={SP} AOUT=OA MARLD=1",
            "MOP=LOAD MSZ=WORD DACC=1 MQ=LOAD",
            f"RAS=K K={SP} AOP=ADD CI=0 BIN=BUS IMM=FOUR AOUT=F MARLD=1",
            f"MOP=LOAD MSZ=WORD DACC=1 BIN=BUS AOP=PASSB WS=K K={T0}",
            f"RAS=K K={SP} AOP=ADD CI=0 BIN=BUS IMM=FOUR WS=K",
            f"RAS=K K={SP} AOP=ADD CI=0 BIN=BUS IMM=FOUR WS=K",
            # the flags from sr's bits 3-0
            "MQ=DRIVE BIN=BUS AOP=PASSB NSZ=LOAD",
            EB_SYS,
            f"RAS=K K={IC} AOUT=OA MARLD=1",
            # IPL from sr's bits 27-24; ST = S (F31)
            "MQ=DRIVE BIN=BUS AOP=PASSB AOUT=F MOP=STORE MSZ=WORD DACC=1 STOP=F31",
            # S from its bit 31, after the microcode's last access to the
            # window
            "MQ=DRIVE MOP=SYSW",
            f"MQ=DRIVE BIN=BUS AOP=PASSB WS=K K={SR}",
            # ST = I (sr << 1's F31), and S decides (set two words before)
            W(None, f"RAS=K K={SR} AOP=SHL CI=0 STOP=F31",
              next=("if", "ST", p.pair(go(paths[1]), go(paths[0]))))]
    priv(p, "RTI", body, sync)
    entries[(0xFE, 0, 2)] = ("RTI", 1)


def ei_di_spl(p, entries, sync):
    """EI and DI: I and SB SR's I (EI's decode doesn't take an interrupt:
    never straight after EI). SPL #n: IPL = n, a write of n to the
    controller's register 4."""
    body = [f"RBS=K K={B30} BIN=RF BOUT=1 MQ=LOAD",
            W(None, ""),
            f"RAS=K K={SR} MQ=DRIVE BIN=BUS AOP=OR WS=K IFL=SET",
            W(None, EB_0, next="decode_noirq")]
    priv(p, "EI", body, sync)
    body = [f"RBS=K K={B30} BIN=RF BOUT=1 MQ=LOAD",
            W(None, ""),
            f"RAS=K K={SR} MQ=DRIVE BIN=BUS AOP=BIC WS=K IFL=CLEAR",
            W(None, EB_0, next="decode")]
    priv(p, "DI", body, sync)
    entries[(0xFE, 0, 0)] = ("EI", 1)
    entries[(0xFE, 0, 1)] = ("DI", 1)
    body = [f"RAS=K K={IC} AOP=ADD CI=0 BIN=BUS IMM=FOUR AOUT=F MARLD=1",
            W(None, ""),
            "AOP=PASSB BIN=BUS IMM=Q AOUT=F MOP=STORE MSZ=WORD DACC=1",
            W(None, EB_0, next="decode")]
    priv(p, "SPL", body, sync)
    for n in range(9):
        entries[(0xFE, 1, n)] = ("SPL", 1)


def swi(p, entries, enter):
    """SWI #n: vbr + 0x100 + 4n, the PC the next instruction's. 4n is twice
    S8X2 (2 x n sign-extended), and 0x400 more for n of 128 and up (ST,
    from the first word's F31); the flags stay."""
    yes = W(None, f"RAS=K K={T0} MQ=DRIVE BIN=BUS AOP=ADD CI=0 WS=K")
    rest = chain(p, f"RBS=K K={K_0100} BIN=RF BOUT=1 MQ=LOAD",
                 f"RAS=K K={T0} MQ=DRIVE BIN=BUS AOP=ADD CI=0 WS=K",
                 f"RBS=K K={T0} BIN=RF BOUT=1 MQ=LOAD",
                 EB_SYS,
                 f"MQ=DRIVE BIN=BUS AOP=PASSB WS=K K={OFF}",
                 W(None, f"AIN=1 PCOP=DRIVE AOP=PASSA WS=K K={PC}", next=("jump", enter.label)))
    place(p, rest)
    yes.next = ("jump", rest[0].label)
    no = W(None, "", next=("jump", rest[0].label))
    ws = chain(p, f"AOP=PASSB BIN=BUS IMM=S8X2 WS=K K={T0} STOP=F31",
               f"RAS=K K={T0} AOP=ADD CI=0 BIN=BUS IMM=S8X2 WS=K",
               W(None, f"RBS=K K={K_0400} BIN=RF BOUT=1 MQ=LOAD", next=("if", "ST", p.pair(no, yes))),
               label="SWI")
    place(p, ws)
    entries[(0xFC, None, None)] = ("SWI", 1)


def to_rd(p, label_words=None):
    """Words ending an MFSR: MQ holds the value (EB the system bank's): rd
    = MQ in bank 0."""
    return [EB_0, W(None, "MQ=DRIVE BIN=BUS AOP=PASSB WS=d", next="decode")]


def special(p, entries, sync):
    """MFSR rd, n and MTSR n, rs, RFC 0029's special registers: 0 ccr (the
    flags, user mode's too), 8 sr, 9 far, 10 fsr, 11 ctx, 12 mapa, 13
    mapd (writes; it reads 0), 14 bank, 15 vbr; the rest reserved (0)."""
    mf, mt = 0x06, 0x07
    # ---- ccr: the flags by four tests (ST-free: CND N, Z, C, V), into rd
    bits = [("N", "FOUR", 2), ("Z", "FOUR", 1), ("C", "ONE", 2), ("V", "ONE", 1)]
    nxt = W(None, "", next="decode")
    p.place(nxt)
    for flag, imm, times in reversed(bits):
        add = chain(p, *[f"RAS=d AOP=ADD CI=0 BIN=BUS IMM={imm} WS=d"] * times)
        add[-1].next = ("jump", nxt.label)
        place(p, add)
        nxt = W(None, "", next=("if", flag, p.pair(W(None, "", next=("jump", nxt.label)),
                                                  W(None, "", next=("jump", add[0].label)))))
        p.place(nxt)
    first = W("MFSR_ccr", "AOP=ZERO WS=d", next=("jump", nxt.label))
    p.place(first)
    entries[(mf, None, 0)] = ("MFSR_ccr", 1)
    p.place(W("MTSR_ccr", "RAS=s AOP=PASSA NSZ=LOAD", next="decode"))
    entries[(mt, 0, None)] = ("MTSR_ccr", 1)
    # reserved: 0, and writes ignored
    p.place(W("MFSR_res", "AOP=ZERO WS=d", next="decode"))
    p.place(W("MTSR_res", "", next="decode"))
    for n in range(1, 8):
        entries[(mf, None, n)] = ("MFSR_res", 1)
        entries[(mt, n, None)] = ("MTSR_res", 1)
    # ---- sr: SB SR | the status register; MTSR sr: all but S
    priv(p, "MFSR_sr", [f"RAS=K K={IC} AOP=ADD CI=0 BIN=BUS IMM=FOUR AOUT=F MARLD=1",
                        "MOP=LOAD MSZ=BYTE DACC=1 MQ=LOAD",
                        f"MQ=DRIVE BIN=BUS AOP=PASSB WS=K K={ST0}",
                        f"RBS=K K={SR} BIN=RF BOUT=1 MQ=LOAD",
                        f"RAS=K K={ST0} MQ=DRIVE BIN=BUS AOP=OR WS=K",
                        f"RBS=K K={ST0} BIN=RF BOUT=1 MQ=LOAD"] + to_rd(p, None), sync)
    entries[(mf, None, 8)] = ("MFSR_sr", 1)
    # MTSR sr: the flags (NSZ LOAD), IPL (rs written to the controller's
    # register 0), SB SR = S | (rs & (I | T)), I from rs's bit 30
    seti = W(None, "IFL=SET", next=("jump", "_mtsr_end"))
    clri = W(None, "IFL=CLEAR", next=("jump", "_mtsr_end"))
    end = W("_mtsr_end", EB_0, next="decode")
    p.place(end)
    body = [f"RAS=K K={IC} AOUT=OA MARLD=1",
            EB_0,
            # (EB 0: rs; the test at this word sees ST from the second)
            "RAS=s AOP=PASSA AOUT=F MOP=STORE MSZ=WORD DACC=1 NSZ=LOAD",
            "RBS=s BIN=RF BOUT=1 MQ=LOAD",
            EB_SYS,
            f"MQ=DRIVE BIN=BUS AOP=PASSB WS=K K={ST0}",
            f"RBS=K K={SIT} BIN=RF BOUT=1 MQ=LOAD",
            f"RAS=K K={ST0} MQ=DRIVE BIN=BUS AOP=AND WS=K",
            f"RBS=K K={K_SIGN} BIN=RF BOUT=1 MQ=LOAD",
            f"RAS=K K={ST0} MQ=DRIVE BIN=BUS AOP=OR WS=K",
            f"RBS=K K={ST0} BIN=RF BOUT=1 MQ=LOAD",
            f"MQ=DRIVE BIN=BUS AOP=PASSB WS=K K={SR}",
            f"RAS=K K={SR} AOP=SHL CI=0 STOP=F31",
            W(None, ""),
            W(None, "", next=("if", "ST", p.pair(clri, seti)))]
    priv(p, "MTSR_sr", body, sync)
    entries[(mt, 8, None)] = ("MTSR_sr", 1)
    # ---- far (SB FAR's bits 21-0 and 31) and fsr
    priv(p, "MFSR_far", [f"RBS=K K={FAR} BIN=RF BOUT=1 MQ=LOAD",
                         f"MQ=DRIVE BIN=BUS AOP=PASSB WS=K K={ST0}",
                         f"RBS=K K={FARM} BIN=RF BOUT=1 MQ=LOAD",
                         f"RAS=K K={ST0} MQ=DRIVE BIN=BUS AOP=AND WS=K",
                         f"RBS=K K={ST0} BIN=RF BOUT=1 MQ=LOAD"] + to_rd(p, None), sync)
    entries[(mf, None, 9)] = ("MFSR_far", 1)
    priv(p, "MFSR_fsr", [f"RBS=K K={FSR} BIN=RF BOUT=1 MQ=LOAD"] + to_rd(p), sync)
    entries[(mf, None, 10)] = ("MFSR_fsr", 1)
    # ---- ctx, bank, vbr: as written; MTSR ctx loads CTX too (B6-B0, B31)
    for n, reg in ((11, CTX), (14, BANK), (15, VBR)):
        priv(p, f"MFSR_{n}", [f"RBS=K K={reg} BIN=RF BOUT=1 MQ=LOAD"] + to_rd(p, None), sync)
        entries[(mf, None, n)] = (f"MFSR_{n}", 1)
    for n, reg in ((11, CTX), (15, VBR)):
        extra = ["MQ=DRIVE MOP=CTXW"] if n == 11 else []
        body = [EB_0, "RBS=s BIN=RF BOUT=1 MQ=LOAD", EB_SYS,
                f"MQ=DRIVE BIN=BUS AOP=PASSB WS=K K={reg}", *extra, W(None, EB_0, next="decode")]
        priv(p, f"MTSR_{n}", body, sync)
        entries[(mt, n, None)] = (f"MTSR_{n}", 1)
    # MTSR bank: SB BANK = rs & 0xFF; the bank's constants made if they
    # aren't there (K_M1 isn't -1)
    made = W(None, EB_0, next="decode")
    p.place(made)
    consts = reset_constants(p, made.label)
    body = [EB_0,
            f"RBS=K K={K_FF} BIN=RF BOUT=1 MQ=LOAD",
            f"RAS=s MQ=DRIVE BIN=BUS AOP=AND WS=K K={T0}",
            f"RBS=K K={T0} BIN=RF BOUT=1 MQ=LOAD",
            EB_SYS,
            f"MQ=DRIVE BIN=BUS AOP=PASSB WS=K K={BANK}",
            "MQ=DRIVE EBLD=1",
            f"RAS=K K={K_M1} AOP=INCA CI=OWN STOP=C32",
            W(None, ""),
            W(None, "", next=("if", "ST", p.pair(W(None, "", next=("jump", consts)),
                                                W(None, "", next=("jump", made.label)))))]
    priv(p, "MTSR_14", body, sync)
    entries[(mt, 14, None)] = ("MTSR_14", 1)
    # ---- mapa: SB MAPV = page << 12 | 0xFFC0_0000, SB MAPC the context
    # (a context is 1024 pages, Reed's 4 MB); MFSR mapa composes it
    shl = lambda n: [f"RAS=K K={ST0} AOP=SHL CI=0 WS=K"] * n
    shr = lambda n: [f"RAS=K K={ST0} BIN=SHIFT SI=0 AOP=PASSB WS=K"] * n
    rs_to_st0 = [EB_0, "RBS=s BIN=RF BOUT=1 MQ=LOAD", EB_SYS, f"MQ=DRIVE BIN=BUS AOP=PASSB WS=K K={ST0}"]
    body = [*rs_to_st0, *shl(15), *shr(25),
            f"RBS=K K={ST0} BIN=RF BOUT=1 MQ=LOAD",
            f"MQ=DRIVE BIN=BUS AOP=PASSB WS=K K={MAPC}",
            *rs_to_st0, *shl(22), *shr(10),
            f"RBS=K K={MAPV0} BIN=RF BOUT=1 MQ=LOAD",
            f"RAS=K K={ST0} MQ=DRIVE BIN=BUS AOP=OR WS=K",
            f"RBS=K K={ST0} BIN=RF BOUT=1 MQ=LOAD",
            f"MQ=DRIVE BIN=BUS AOP=PASSB WS=K K={MAPV}",
            W(None, EB_0, next="decode")]
    priv(p, "MTSR_12", body, sync)
    entries[(mt, 12, None)] = ("MTSR_12", 1)
    body = [f"RBS=K K={MAPC} BIN=RF BOUT=1 MQ=LOAD",
            f"MQ=DRIVE BIN=BUS AOP=PASSB WS=K K={ST0}",
            *shl(10),
            f"RBS=K K={ST0} BIN=RF BOUT=1 MQ=LOAD",
            f"MQ=DRIVE BIN=BUS AOP=PASSB WS=K K={PC}",
            f"RBS=K K={MAPV} BIN=RF BOUT=1 MQ=LOAD",
            f"MQ=DRIVE BIN=BUS AOP=PASSB WS=K K={ST0}",
            *shl(10), *shr(22),
            f"RBS=K K={PC} BIN=RF BOUT=1 MQ=LOAD",
            f"RAS=K K={ST0} MQ=DRIVE BIN=BUS AOP=OR WS=K",
            f"RBS=K K={ST0} BIN=RF BOUT=1 MQ=LOAD"] + to_rd(p, None)
    priv(p, "MFSR_12", body, sync)
    entries[(mf, None, 12)] = ("MFSR_12", 1)
    # mapd: written through MAR (SB MAPV) and CTX (SB MAPC; CTX back to
    # SB CTX after), mapa moved on; it reads 0 (Reed's map can't be read)
    wrap = chain(p, f"RBS=K K={MAPV0} BIN=RF BOUT=1 MQ=LOAD",
                 f"MQ=DRIVE BIN=BUS AOP=PASSB WS=K K={MAPV}",
                 f"RAS=K K={MAPC} AOP=INCA CI=OWN WS=K",
                 W(None, EB_0, next="decode"))
    place(p, wrap)
    done = W(None, EB_0, next="decode")
    p.place(done)
    body = [f"RAS=K K={MAPV} AOUT=OA MARLD=1",
            "",
            f"RBS=K K={MAPC} BIN=RF BOUT=1 MOP=CTXW DACC=1",
            EB_0,
            "RBS=s BIN=RF BOUT=1 MOP=MAPW DACC=1",
            EB_SYS,
            f"RBS=K K={CTX} BIN=RF BOUT=1 MOP=CTXW DACC=1",
            f"RBS=K K={K_0800} BIN=RF BOUT=1 MQ=LOAD",
            f"RAS=K K={MAPV} MQ=DRIVE BIN=BUS AOP=ADD CI=0 WS=K",
            f"RAS=K K={MAPV} MQ=DRIVE BIN=BUS AOP=ADD CI=0 WS=K STOP=C32",
            W(None, ""),
            W(None, "", next=("if", "ST", p.pair(W(None, "", next=("jump", done.label)),
                                                W(None, "", next=("jump", wrap[0].label)))))]
    priv(p, "MTSR_13", body, sync)
    entries[(mt, 13, None)] = ("MTSR_13", 1)
    priv(p, "MFSR_13", ["", "", EB_0, W(None, "AOP=ZERO WS=d", next="decode")], sync)
    entries[(mf, None, 13)] = ("MFSR_13", 1)
    # far and fsr are read only: MTSR ignores them (privileged still)
    for n in (9, 10):
        priv(p, f"MTSR_{n}", ["", "", W(None, EB_0, next="decode")], sync)
        entries[(mt, n, None)] = (f"MTSR_{n}", 1)


def user_regs(p, entries, sync):
    """MFUR rd, rs (rd = register rs of bank `bank`) and MTUR rd, rs
    (register rd of bank `bank` = rs): EB to SB BANK for the one word."""
    body = [f"RBS=K K={BANK} BIN=RF BOUT=1 EBLD=1",
            "RBS=s BIN=RF BOUT=1 MQ=LOAD",
            EB_0,
            W(None, "MQ=DRIVE BIN=BUS AOP=PASSB WS=d", next="decode")]
    priv(p, "MFUR", ["", ""] + body, sync)
    entries[(0x31, None, None)] = ("MFUR", 1)
    body = [EB_0, "RBS=s BIN=RF BOUT=1 MQ=LOAD", EB_SYS,
            f"RBS=K K={BANK} BIN=RF BOUT=1 EBLD=1",
            "MQ=DRIVE BIN=BUS AOP=PASSB WS=d",
            W(None, EB_0, next="decode")]
    priv(p, "MTUR", ["", ""] + body, sync)
    entries[(0x3D, None, None)] = ("MTUR", 1)


def system_constants(p, then):
    """Reset's system bank: its constants (as every bank's), then the
    special registers' reset values and the system's own constants (EB
    the system bank's from here), then EB 0 and `then`."""
    words = []
    words += const_words(IC, 0xC0005800)
    words += const_words(SIT, 0xE0000000)
    words += const_words(B30, 0x40000000)
    words += const_words(FARM, 0x803FFFFF)
    words += const_words(VBR, 0x80000000)
    words += const_words(SR, 0x80000000)
    words += [f"AOP=ZERO WS=K K={BANK}", f"AOP=ZERO WS=K K={CTX}", f"AOP=ZERO WS=K K={MAPC}"]
    words += const_words(MAPV0, 0xFFC00000)
    words += [f"RBS=K K={MAPV0} BIN=RF BOUT=1 MQ=LOAD", f"MQ=DRIVE BIN=BUS AOP=PASSB WS=K K={MAPV}"]
    words += [f"AOP=ZERO WS=K K={FAR}", f"AOP=ZERO WS=K K={FSR}"]
    ws = chain(p, *words, W(None, EB_0, next=("jump", then)))
    place(p, ws)
    return ws[0].label
