"""Reed at chip level: the whole machine's netlist (system.machine) on the
chip-level simulator's system run (infra/hwsim), with the microcode's
images (ucode.py) in the control store's and the decode table's parts, a
program in the RAM, from power-up (the IO board's TL7705A) to the
microcode's HALT; its registers and memory against the draft 2
instruction-level simulator's.

  heron reed hw smoke [--trace A:B]
"""

import json
import os

from heron import BUILD, native
from heron.infra import asm as asmcore, isas
import heron.studies.v2_isa  # noqa: F401 (registers the ISA)
from heron.infra.hw import runner

from . import parts, system, ucode

OUT = os.path.join(BUILD, "reed")
HERE = os.path.dirname(os.path.abspath(__file__))
RAM_BYTES = 4 << 20

SMOKE = """
        .org 0
        MOV  r1, #5
        MOV  r2, #100
        ADD  r1, r2             ; 105
        SUB  r2, #3             ; 97
        MOV  r3, #0x1234
        MOV  r4, #0x12345678
        MOV  [r3], r4
        MOV  r5, [r3]
        AND  r5, #0xFF          ; 0x78
        XOR  r6, r6
        OR   r6, r5             ; 0x78
        CMP  r1, #105
        BNE  fail
        BSR  sub
        LSL  r2, #1             ; 194
        LSR  r4, #1             ; 0x091A2B3C
        MOV  r7, #1
        HALT
sub:    ADD  r1, #1             ; 106
        RET
fail:   MOV  r7, #2
        HALT
"""


def sources():
    import glob
    return runner.infra_sources() + glob.glob(os.path.join(HERE, "*.py"))


# the wires at each corner (ps on a driver's pin): as sta.py's, over the
# backplane, on the clocks' traces, on a board
WIRES = {"max": {"backplane": 12000, "clock": 2500, "board": 1000},
         "min": {"backplane": 1000, "clock": 1000, "board": 0}}
FRACTION = 0.3          # a minimum where the data gives none: this of typical (RFC 0048)


def _delays(corner):
    """chips.delays_for at corner "max", or "min": the data's minimum, else
    FRACTION of typical."""
    from heron.infra.hw import chips

    def delays_for(timing, part, _corner):
        entry = timing.get(part)
        if entry is None:
            if part in chips.FIXED_PARTS.values():
                return {}
            raise KeyError(f"no timing data for {part}")
        out = {}
        for k, v in entry.get("delays", {}).items():
            if corner == "min":
                val = v.get("min", FRACTION * v.get("typ", v.get("max", 0)))
            else:
                val = v.get("max", v.get("typ"))
            out[k] = int(round(val * 1000))
        for k, v in entry.get("checks", {}).items():
            out[k] = int(round(v * 1000))
        return out
    return delays_for


def build(corner="max"):
    """The machine at a corner: its parts' delays, and its wires on the
    drivers' pins."""
    nl = system.machine(sim=True)
    bp = system.backplane_nets()
    from . import bus as BP
    slots = {BP.slot_clock(c, b) for c in BP.CLOCKS for b in BP.BOARDS}
    w = WIRES[corner]
    for inst in nl.instances:
        if inst.type.family == "passive":
            continue
        for pin, kind in inst.type.pins:
            net = inst.conn.get(pin)
            if kind not in ("out", "tri", "io") or net in (None, "GND", "VCC"):
                continue
            ps = w["clock"] if net in slots else w["backplane"] if net in bp else w["board"]
            if ps:
                inst.add_pin_delay(pin, ps)
    return nl


def netlist(corner="max"):
    """The machine's simulation netlist at a corner, exported (cached in
    build/reed)."""
    from heron.infra.hw import chips
    newest = runner.newest(sources())
    path = os.path.join(OUT, f"netlist-{corner}.json")
    if not os.path.exists(path) or os.path.getmtime(path) < newest:
        os.makedirs(OUT, exist_ok=True)
        nl = build(corner)
        saved = chips.delays_for
        chips.delays_for = _delays(corner)
        try:
            exported = nl.export(variant=parts.VARIANT, corner="max")
        finally:
            chips.delays_for = saved
        tmp = f"{path}.{os.getpid()}"
        with open(tmp, "w") as f:
            json.dump(exported, f)
        os.utime(tmp, (newest, newest))
        os.replace(tmp, path)
    with open(path) as f:
        return json.load(f)


def ram_chips(ram):
    """The RAM's eight parts' images: row by bit 21, lane by bits 1-0."""
    out = {}
    for row in range(2):
        for lane in range(4):
            base = row << 21
            out[f"MEM.U_RAM{row}{lane}"] = bytes(ram[base + lane:base + (1 << 21):4])
    return out


RF = [f"ALU.U_RF{c}{k}" for c in "AB" for k in range(4)]


def preloads(ram, prog):
    pre = dict(ucode.images(prog))
    pre.update(ram_chips(ram))
    for k in RF:
        pre[k] = bytes(1 << 16)
    pre["IO.U_BOOT"] = bytes([0xFF]) * 0x20000
    return pre


def config(prog, max_cycles, trace=None, seed=1):
    stops = [[(f"CTRL.UPC{i}", (prog.addr(lab) >> i) & 1) for i in range(14)]
             for lab in ("halted", "unimpl")]
    cfg = {
        "seed": seed, "max_cycles": max_cycles, "max_ps": int(max_cycles * 200_000) + 10_000_000,
        "clock_net": "CYC_CTRL", "reset_net": "RESET_n",
        "fetch_net": "CTRL.DECODING", "fetch_level": 1,
        "addr_nets": [], "data_nets": [f"CTRL.PD{i}" for i in range(16)],
        "fetch_trace": 2000, "stop_when": stops,
        "dump": RF + [f"MEM.U_RAM{r}{l}" for r in range(2) for l in range(4)],
        "observe": ["FN", "FZ", "FC", "FV"] + [f"CTRL.UPC{i}" for i in range(14)],
    }
    if trace:
        def b(name, n, pre=""):
            return [f"{pre}{name}{i}" for i in range(n)]
        cfg.update(trace_from=trace[0], trace_to=trace[1], trace_buses={
            "UPC": b("UPC", 14, "CTRL."), "PD": b("PD", 16, "CTRL."), "A": b("A", 32), "B": b("B", 32),
            "PC": ["CTRL.PC1", "CTRL.PC2"] + [f"CTRL.PC{i}" for i in range(3, 22)],
            "RD": b("RD", 4, "ALU."), "RS": b("RS", 4, "ALU."),
            "FL": ["FN", "FZ", "FC", "FV", "FLUSH", "FETCH", "CTRL.DECODING", "CTRL.DEC1"]})
    return cfg


def run(ram, prog=None, max_cycles=20_000, trace=None, corner="max", seed=1):
    prog = prog or ucode.build()
    nl = netlist(corner)
    hw = native.hwsim.run_system(nl, config(prog, max_cycles, trace, seed), preloads(ram, prog))
    d = hw["dumps"]
    hw["regs"] = [d["ALU.U_RFA0"][r] | d["ALU.U_RFA1"][r] << 8 | d["ALU.U_RFA2"][r] << 16
                  | d["ALU.U_RFA3"][r] << 24 for r in range(16)]
    hw["regs_b"] = [d["ALU.U_RFB0"][r] | d["ALU.U_RFB1"][r] << 8 | d["ALU.U_RFB2"][r] << 16
                    | d["ALU.U_RFB3"][r] << 24 for r in range(16)]
    out = bytearray(RAM_BYTES)
    for row in range(2):
        for lane in range(4):
            base = row << 21
            out[base + lane:base + (1 << 21):4] = d[f"MEM.U_RAM{row}{lane}"]
    hw["ram"] = bytes(out)
    upc = sum(hw["nets"][f"CTRL.UPC{i}"] << i for i in range(14))
    hw["stopped_at"] = {prog.addr("halted"): "halt", prog.addr("unimpl"): "unimpl"}.get(upc, hex(upc))
    return hw


def reference(img):
    from heron.studies.v2_isa.sim import Machine
    m = Machine(img)
    m.run(max_cycles=1_000_000)
    return m


def smoke(trace=None, text=SMOKE):
    img = asmcore.assemble_text(isas.get("v2"), text, name="smoke.s")
    ram = bytearray(RAM_BYTES)
    for a, b in img.mem.items():
        ram[a] = b
    hw = run(ram, trace=trace)
    m = reference(img)
    lines = [f"stopped at {hw['stopped_at']} ({hw['reason']}), {hw['cycles']} cycles, "
             f"{hw['time_ps'] / 1000:.0f} ns, {m.instructions} instructions"]
    bad = []
    for r in range(16):
        if hw["regs"][r] != m.r[r] or hw["regs_b"][r] != m.r[r]:
            bad.append(f"r{r}: copy A {hw['regs'][r]:08X}, B {hw['regs_b'][r]:08X}, "
                       f"the reference {m.r[r]:08X}")
    mem = m.mem
    diff = [a for a in range(0x10000) if hw["ram"][a] != mem[a]]
    if diff:
        bad.append(f"{len(diff)} RAM bytes differ below 64K, the first at {diff[0]:05X}")
    lines += bad or ["registers and the first 64K of RAM as the reference has them"]
    if hw["violation_total"]:
        lines.append(f"{hw['violation_total']} timing violations at chip level:")
        for v in hw["violation_summary"][:8]:
            lines.append(f"  {v['what']}: {v['count']}x, worst {v['worst_slack_ps'] / 1000:.1f} ns")
    c = hw["contention"]
    if c["count"]:
        lines.append(f"bus contention: {c['count']} episodes, longest {c['max_ps'] / 1000:.1f} ns")
    if trace:
        lines += hw["trace"]
    return not bad and hw["stopped_at"] == "halt", "\n".join(lines)


# ---- the gate: programs at both corners and several seeds ------------------

LOOPS = {
    "sub-bne": "SUB  r1, #1",
    "alu-loop": "ADD  r2, r1\n        XOR  r3, r2\n        SUB  r1, #1",
    "load-loop": "MOV  r5, [r4]\n        ADD  r2, r5\n        SUB  r1, #1",
}


# instructions of 2 and 3 parcels in a row: the decode pointer catching up
# with the executing instruction's parcels (the queue's AV and CONS)
QUEUE = """
        .org 0
        MOV  r1, #0x300
        MOV  r4, #0x400
.l:     MOV  r2, #0x1111
        MOV  r3, #0x22223333
        ADD  r2, r3
        MOV  r6, #0x7FFF
        XOR  r6, r2
        SUB  r1, #0x100
        BNE  .l
        HALT
"""


def programs():
    out = {"smoke": SMOKE, "queue": QUEUE}
    for name, body in LOOPS.items():
        out[name] = f"""
        .org 0
        MOV  r1, #10
        MOV  r4, #0x400
.l:     {body}
        BNE  .l
        HALT
"""
    return out


UNTIMED = ("VIDEO.", "IO.")      # boards not timed yet: their violations reported apart


def check(corners=("max", "min"), seeds=(1, 2, 3)):
    """Every program at every corner and seed, against the draft 2
    simulator: (all good, report lines). A run is good when it halts with
    the reference's registers and memory and has no timing violation on
    CTRL, ALU, MEM or the clock card."""
    prog = ucode.build()
    good, lines = True, []
    for name, text in programs().items():
        img = asmcore.assemble_text(isas.get("v2"), text, name=f"{name}.s")
        ram = bytearray(RAM_BYTES)
        for a, b in img.mem.items():
            ram[a] = b
        m = reference(img)
        for corner in corners:
            for seed in seeds:
                hw = run(ram, prog, corner=corner, seed=seed)
                bad = [f"r{r}" for r in range(16) if hw["regs"][r] != m.r[r] or hw["regs_b"][r] != m.r[r]]
                if any(hw["ram"][a] != m.mem[a] for a in range(0x10000)):
                    bad.append("RAM")
                if hw["stopped_at"] != "halt":
                    bad.append(f"stopped at {hw['stopped_at']}")
                v = [x for x in hw["violation_summary"] if not x["what"].startswith(UNTIMED)]
                vu = sum(x["count"] for x in hw["violation_summary"] if x["what"].startswith(UNTIMED))
                ok = not bad and not v
                good &= ok
                lines.append(f"{name:<10} {corner} seed {seed}: {'ok ' if ok else 'BAD'} "
                             f"{hw['cycles']} cycles, {hw['time_ps'] / 1000:.0f} ns"
                             + (f"; {', '.join(bad)}" if bad else "")
                             + (f"; violations: " + "; ".join(f"{x['what']} {x['count']}x {x['worst_slack_ps'] / 1000:.1f} ns"
                                                            for x in v[:4]) if v else "")
                             + (f" (untimed boards: {vu})" if vu else "")
                             + f"; contention {hw['contention']['count']}x, longest "
                               f"{hw['contention']['max_ps'] / 1000:.1f} ns")
    return good, lines


# ---- the model against the chip level, cycle by cycle -------------------------

def lockstep_image(ram, cycles, prog=None):
    """A RAM image on the chip-level simulator and on the model, their µPC
    and PC compared every cycle: (cycles compared, the first that differs
    or None), from the model's cycle where the chip level's trace (from its
    first decode) begins."""
    import re
    from . import model
    prog = prog or ucode.build()
    r = run(ram, prog, max_cycles=cycles + 200, trace=(0, cycles))
    seq = []
    for line in r["trace"]:
        d = dict(re.findall(r"(\w+)=([0-9A-Fa-f]+)", line))
        seq.append((int(d["UPC"], 16), int(d["PC"], 16)))
    m = model.Model(bytes(ram), prog=prog)
    ms = []
    for _ in range(len(seq) + 1000):
        m.step()
        ms.append((m.upc, (m.pc >> 1) & 0x1FFFFF))
    k = min(6, len(seq))
    off = next((o for o in range(len(ms) - len(seq)) if ms[o:o + k] == seq[:k]), None)
    if off is None:
        return len(seq), 0
    return len(seq), next((i for i, h in enumerate(seq) if ms[i + off] != h), None)


def lockstep(names=None, cycles=400):
    """Each program on the chip-level simulator and on the model (model.py),
    their µPC and PC compared every cycle: [(name, cycles compared,
    mismatches)], from the model's cycle where the chip level's trace
    (which starts at its first decode) begins."""
    import re
    from . import model
    progs = programs()
    out = []
    for name in names or progs:
        img = asmcore.assemble_text(isas.get("v2"), progs[name], name=f"{name}.s")
        ram = bytearray(RAM_BYTES)
        for a, b in img.mem.items():
            ram[a] = b
        r = run(ram, trace=(0, cycles))
        seq = []
        for line in r["trace"]:
            d = dict(re.findall(r"(\w+)=([0-9A-Fa-f]+)", line))
            seq.append((int(d["UPC"], 16), int(d["PC"], 16)))
        m = model.Model(ram)
        ms = []
        for _ in range(len(seq) + 1000):
            m.step()
            ms.append((m.upc, m.pc >> 1))
        # the chip level's trace starts at its first decode: the model's
        # cycle that matches its first few
        k = min(6, len(seq))
        off = next((o for o in range(len(ms) - len(seq)) if ms[o:o + k] == seq[:k]), None)
        bad = list(range(len(seq))) if off is None else [i for i, h in enumerate(seq) if ms[i + off] != h]
        out.append((name, len(seq), bad))
    return out
