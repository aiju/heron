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


def netlist():
    """The machine's simulation netlist, exported (cached in build/reed)."""
    newest = runner.newest(sources())
    path = os.path.join(OUT, "netlist.json")
    if not os.path.exists(path) or os.path.getmtime(path) < newest:
        os.makedirs(OUT, exist_ok=True)
        nl = system.machine(sim=True)
        tmp = f"{path}.{os.getpid()}"
        with open(tmp, "w") as f:
            json.dump(nl.export(variant=parts.VARIANT, corner="max"), f)
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


def config(prog, max_cycles, trace=None):
    stops = [[(f"CTRL.UPC{i}", (prog.addr(lab) >> i) & 1) for i in range(14)]
             for lab in ("halted", "unimpl")]
    cfg = {
        "seed": 1, "max_cycles": max_cycles, "max_ps": int(max_cycles * 200_000) + 10_000_000,
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


def run(ram, prog=None, max_cycles=20_000, trace=None):
    prog = prog or ucode.build()
    nl = netlist()
    hw = native.hwsim.run_system(nl, config(prog, max_cycles, trace), preloads(ram, prog))
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
