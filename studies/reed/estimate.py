"""A rough estimate of Reed's time an instruction, for comparing front ends
and cycle lengths, not a measurement: each kind of instruction in the
napkin's mix (studies/cards: the compiled C programs' dynamic mix on
draft 2, conditional branches 45% taken) as a list of microcycles, each
the ticks `heron reed sta` gives that kind of microcycle. There is no
microcode yet; the sequences are as RFC 0049 section 14 describes them.

  heron reed estimate
"""

from heron.studies.cards import napkin as N

TICK_NS = 19.861

# a microcycle's ticks, by kind (sta.WORDS), for a variant
CYCLES = {
    # the netlist before the clock card: everything 6, a load and add 7
    "netlist, 6 ticks": dict(R=6, A=6, M=6, L=6, LA=7, S=6, F=6),
    # the clock card (U_CGA on the oscillator, WPH half a tick late)
    "clock card": dict(R=5, A=6, M=5, L=6, LA=6, S=5, F=6),
    # as microcoded (ucode.py): a word that may fetch (BFREE) takes the
    # fetch's 6, so the register ops that fetch are 6 too
    "clock card, as microcoded": dict(R=6, A=6, M=5, L=6, LA=6, S=5, F=6),
    # a register file with no write phase in its cycle (dual-ported): a
    # register op in 4, as the read and the ALU need (estimate)
    "clock card, RF without a write phase": dict(R=4, A=5, M=4, L=6, LA=6, S=4, F=6),
}

# front ends: what a redirect costs
FRONT = {
    # PC + disp in the ALU, test, PC/FPC from A, fetch, decode from the queue
    "today": {"Bcc taken": "R R R F F", "Bcc not taken": "R R", "RET": "R F F",
              "CALL": "R R R F F R", "JMP table": "R R A L R F F"},
    # two transfers a cycle on A: the target goes out in the cycle it's made
    "slots": {"Bcc taken": "R R F F", "Bcc not taken": "R R", "RET": "R F F",
              "CALL": "R R F F R", "JMP table": "R R A L R F F"},
    # a branch adder on CTRL: the target at the decode, tested and sent in
    # the branch's one word (the condition in hardware)
    "adder": {"Bcc taken": "R F F", "Bcc not taken": "R", "RET": "R F F",
              "CALL": "R F F", "JMP table": "R R A L R F F"},
    # the branch adder as built (ucode.py, measured at chip level: a taken
    # Bcc 4 microcycles, ~22 ticks): the branch's word, its tail (which
    # fetches), WAITD twice; not taken, the word and its tail
    "adder, as built": {"Bcc taken": "R F F R", "Bcc not taken": "R F", "RET": "R F F R",
                        "CALL": "R R F F R", "JMP table": "R R A L R F F R"},
    # and the fetched word bypassed into the decode table: fetch and decode
    # in one longer cycle (F+1 ticks)
    "adder + bypass": {"Bcc taken": "R FD", "Bcc not taken": "R", "RET": "R FD",
                       "CALL": "R FD", "JMP table": "R R A L R FD"},
}

# the rest, as microcycles (the same for every front end)
RECIPES = {
    "AND r1, r2": "R", "ADD r1, r2": "R", "CMP r1, #5": "R", "MOV r1, #0x12345678": "R R",
    "LEA r1, [r2 + 100]": "R", "ADD r1, [r2 + 8]": "A LA", "MOV r1, [r2 + 8]": "A L",
    "MOV r1, [r2]": "M L", "MOV [abs16], r1": "A S", "MOV [r2 + 8], r1": "A S", "PUSH r1": "A S",
    "POP r1": "M L R", "MOVS r1, byte [r2]+": "M L R", "INC [r2]": "M LA S",
    "MOV r1, [r2 + r3*4 + 8]": "R R A L", "SETcc r1": "R R",
    "SAVE r8-r14": "A S S S S", "RESTORE r8-r14": "M L L L L",
}
FIXED = {"MULU r0:r1, r2 (MQ)": 165, "DIVU r0:r1, r2": 170}   # ticks, 32 MQ steps


def ticks(seq, cyc):
    t = 0
    for k in seq.split():
        t += cyc["F"] + 1 if k == "FD" else cyc[k]
    return t


def per_instruction(cycles, front):
    cyc, fe = CYCLES[cycles], FRONT[front]
    c = {k: ticks(v, cyc) for k, v in RECIPES.items()}
    c.update(FIXED)
    c["Bcc, taken"], c["Bcc, not taken"] = ticks(fe["Bcc taken"], cyc), ticks(fe["Bcc not taken"], cyc)
    c["BSR / CALL label"], c["RET (JMP r7)"] = ticks(fe["CALL"], cyc), ticks(fe["RET"], cyc)
    total = 0.0
    for name, share in N.MIX.items():
        if name in ("Bcc", "DBNZ"):
            t = N.TAKEN * c["Bcc, taken"] + (1 - N.TAKEN) * c["Bcc, not taken"]
            if name == "DBNZ":
                t += c["ADD r1, r2"]
        elif name in ("LSL", "LSR", "ASR", "ROR"):
            # a bit a microcycle: the crossbar's rotation isn't built
            t = sum(p * n for n, p in N.SHIFTS.items()) / sum(N.SHIFTS.values()) * cyc["R"]
        elif name in ("BRA", "JMP"):
            t = c["Bcc, taken"]
        else:
            k = N.KIND[name]
            t = c[k]
            if k in ("SAVE r8-r14", "RESTORE r8-r14"):
                t = t * 4 / 7
        total += share * t
    return total / sum(N.MIX.values())


def report():
    lines = [f"{'cycles':<40} {'front end':<16} {'ticks':>6} {'ns':>6}"]
    for cyc in CYCLES:
        for fe in FRONT:
            t = per_instruction(cyc, fe)
            lines.append(f"{cyc:<40} {fe:<16} {t:6.2f} {t * TICK_NS:6.0f}")
    return "\n".join(lines)


def main():
    print(report())
