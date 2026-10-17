"""The IOP's card at chip level (card.py), on the chip-level simulator
(infra/hwsim), checked against the microinstruction-level model (sim/):
every E2, the microaddress uIR takes and the bus clock it takes it at,
must be the model's.

    heron iop hw run [--ms N] [--seed S]   power up, print what the console prints
    heron iop hw test [--ms N]             the same, against the model, clock for clock
    heron iop hw slave                     the slave side, against a second master on the bench
    heron iop hw window                    the window onto the I/O bus, the same way
    heron iop hw stuck                     the stuck-transfer counter, against a slave that never answers
    heron iop hw bom                       the parts
    heron iop hw schematic [--out FILE]    the schematic viewer (build/iop/schematic.html)

Both start from the microcode's quick build (build.py's `quick`: the
SRAM's self test only of its top cells), with the SRAMs holding what the
model's hold at power-up, so that a run is the model's from the first
clock.
"""

import argparse
import glob
import json
import os
import sys

from heron import BUILD, native
from heron.infra.hw import runner

from . import build as bld, card, layout
from .run import Session

OUT = os.path.join(BUILD, "iop")
HERE = os.path.dirname(os.path.abspath(__file__))
UPC = [f"UPC{i}" for i in range(16)]


def sources():
    from heron.studies.v2_hw import parts
    return runner.infra_sources() + [os.path.join(HERE, "card.py"), parts.__file__]


def netlist(master=False, watchdog=None):
    """The simulation netlist, exported (cached in build/iop); `master`:
    with the bench's second master; `watchdog`: its times, if not the
    card's."""
    name = "netlist" + ("-master" if master else "") + (f"-wd{watchdog[0]}-{watchdog[1]}" if watchdog else "")
    path = os.path.join(OUT, name + ".json")
    if not os.path.exists(path) or os.path.getmtime(path) < runner.newest(sources()):
        os.makedirs(OUT, exist_ok=True)
        nl = card.build(sim=True, bench=True, master=master, watchdog=watchdog or (card.WDOG_PS, card.WDCOLD_PS))
        tmp = f"{path}.{os.getpid()}"
        with open(tmp, "w") as f:
            json.dump(nl.export(variant=card.VARIANT, corner="max"), f)
        os.replace(tmp, path)
    with open(path) as f:
        return json.load(f)


def model(b, inp=b""):
    """The model, powered up on the same build, logging its E2s."""
    s = Session(b)
    s.s.log_start()
    if inp:
        s.s.uart_send(inp)
    return s


def preloads(b, s, inp=b""):
    """The chips' contents at the end of reset: the microcode ROMs, the
    image flash, the SRAM and the shared RAM as the model's power up, and
    what the console's terminal types."""
    pre = {}
    rom = b.ucode_bytes()
    for k in range(6):
        pre[f"U_UC{k}"] = bytes(rom[k::6])
    flash = b.flash[:2 << 17]
    pre["U_FL0"], pre["U_FL1"] = bytes(flash[0::2]), bytes(flash[1::2])
    sram = s.s.sram(0, 0x10000)
    pre["U_RAML"] = bytes(h & 0xFF for h in sram)
    pre["U_RAMH"] = bytes(h >> 8 for h in sram)
    shared = s.s.shared(0, 1 << 20)
    for k in range(2):
        half = shared[k << 19:(k + 1) << 19]
        pre[f"U_SR{k}L"] = bytes(h & 0xFF for h in half)
        pre[f"U_SR{k}H"] = bytes(h >> 8 for h in half)
    pre["U_UART"] = bytes(inp)
    ram = s.s.cpu_mem(0, 1 << 20)
    pre["X_RAML"], pre["X_RAMH"] = bytes(ram[0::2]), bytes(ram[1::2])
    return pre


def config(max_cycles, fetch_trace, seed=1, trace=None):
    cfg = {
        "seed": seed, "max_cycles": max_cycles,
        "clock_net": "BCLK", "reset_net": "RESET_n",
        "fetch_net": "E2EN", "fetch_level": 1,
        "addr_nets": UPC, "data_nets": card.ACQ,
        "fetch_trace": fetch_trace,
        "dump": ["U_UART", "U_RAML", "U_RAMH"],
        "observe": [f"LED{i}" for i in range(8)],
    }
    if trace:
        cfg.update(trace_from=trace[0], trace_to=trace[1], trace_buses={
            "UPC": UPC, "R": card.R, "T": card.T, "AC": card.ACQ, "X": card.XQ,
            "PH": ["PH", "E1EN", "E2EN", "STALL1_IO_n", "STALL2"],
            "BUS": ["DP", "STARTQ", "GNTQ", "SB_WAIT_n", "WRQ"],
            "IO": ["STB", "HLD", "IOREQ", "IODONE"], "CNT": [f"CNT{i}" for i in range(8)],
            "IOD": card.IOD})
    return cfg


def run(b, ms, inp=b"", seed=1, fetch_trace=0, s=None, trace=None):
    """Power up the card and run it for `ms` of simulated time."""
    s = s or model(b, inp)
    cycles = int(ms * 1e9 / card.BCLK_PS)
    hw = native.hwsim.run_system(netlist(), config(cycles, fetch_trace, seed, trace),
                                 preloads(b, s, inp))
    hw["output"] = bytes(hw["dumps"]["U_UART"])
    return hw


def compare(hw, ref):
    """The first E2 where the card and the model differ, or None: (index,
    the card's (clock, address, AC), the model's), clocks from the first
    E2. The card's AC is the one before the edge, so the model's from the
    E2 before."""
    got = hw["fetches"]
    if not got or not ref:
        return (0, got[:1], ref[:1])
    c0, r0 = got[0][0], ref[0][0]
    same = False                # AC powers up anything: from when it first agrees
    for i, ((c, a, ac), (rc, ra, _)) in enumerate(zip(got, ref)):
        rac = ref[i - 1][2] if i else None
        same = same or ac == rac
        if (c - c0, a) != (rc - r0, ra) or (same and ac != rac):
            return (i, (c - c0, a, hex(ac)), (rc - r0, ra, rac and hex(rac)))
    return None


def check(ms=2.0, inp=b"", seed=1, quiet=False):
    """Run the card and the model for `ms`; (the outcome, the first
    difference or None, E2s compared)."""
    b = bld.Build(bld.DEFAULT_PROGRAM, quick=True)
    s = model(b, inp)
    hw = run(b, ms, inp, seed, fetch_trace=10_000_000, s=s)
    s.run_ms(ms)
    ref = s.s.log_take()
    n = min(len(hw["fetches"]), len(ref))
    hw["model_output"] = s.out
    return hw, compare(hw, ref[:n]), n


class Program:
    """A build with a microcode program of its own (ucode/hwtest.uc) in
    place of the firmware's, over the firmware's image flash."""

    def __init__(self, name="hwtest.uc"):
        from . import uasm
        base = bld.Build(bld.DEFAULT_PROGRAM, quick=True)
        self.mc = uasm.assemble([(name, bld.read("ucode", name))])
        self.flash = base.flash

    def ucode_bytes(self):
        return self.mc.rom_bytes()


def check_ucode(name="hwtest.uc", clocks=2000, seed=1):
    """Run a microcode program on the card and the model to its end (a
    goto to itself); (the outcome, the first difference or None, E2s
    compared, the model's registers and CPU RAM, the card's)."""
    b = Program(name)
    s = model(b)
    cfg = config(clocks, 1_000_000, seed)
    cfg["dump"] += ["X_RAML", "X_RAMH"]
    hw = native.hwsim.run_system(netlist(), cfg, preloads(b, s))
    s.s.run(s.s.clock + clocks)
    ref = s.s.log_take()
    n = min(len(hw["fetches"]), len(ref))
    d = hw["dumps"]
    card_ram = bytes(x for pair in zip(d["X_RAML"][:0x800], d["X_RAMH"][:0x800]) for x in pair)
    card_regs = [l | h << 8 for l, h in zip(d["U_RAML"][0xC000:0xC010], d["U_RAMH"][0xC000:0xC010])]
    got = {"regs": card_regs, "ram": card_ram}
    want = {"regs": s.s.sram(0xC000, 16), "ram": s.s.cpu_mem(0, 0x1000)}
    return hw, compare(hw, ref[:n]), n, b, want, got


class MasterScript:
    """The bench's second master's script (card.M_OUT, card.M_IN): RFC
    0037 transfers, each an address clock and a data phase that ends at
    the first edge it sees WAIT inactive."""

    Z = None

    def __init__(self):
        self.steps = []
        self.drive = {n: self.Z for n in card.M_OUT}
        self.reads = []         # the steps whose end has read data

    def step(self, until=None, **drive):
        self.drive.update(drive)
        conds = [1 + 2 * card.M_IN.index(n) + v for n, v in (until or {}).items()]
        self.steps.append(([2 if self.drive[n] is self.Z else self.drive[n] for n in card.M_OUT],
                           conds + [0] * (card.M_CONDS - len(conds))))

    def idle(self, n=1):
        d = {"SB_START_n": 1, "SB_WRITE_n": 1, "SB_BE0_n": 1, "SB_BE1_n": 1}
        d.update({a: 0 for a in card.SBA[1:32]})
        d.update({x: self.Z for x in card.SBD})
        for _ in range(n):
            self.step(**d)

    def transfer(self, addr, write=False, data=0, size=2):
        be = (0, 0) if size == 2 else ((addr & 1), (addr & 1) ^ 1)
        d = {"SB_START_n": 0, "SB_WRITE_n": 0 if write else 1, "SB_BE0_n": be[0], "SB_BE1_n": be[1]}
        d.update({card.SBA[i]: (addr >> i) & 1 for i in range(1, 32)})
        self.step(**d)
        dd = {x: ((data >> i) & 1 if write else self.Z) for i, x in enumerate(card.SBD)}
        if not write:
            self.reads.append(len(self.steps))
        self.step(until={"SB_WAIT_n": 1}, SB_START_n=1, **dd)
        self.drive.update({x: self.Z for x in card.SBD})

    def write(self, addr, data, size=2):
        self.transfer(addr, True, data, size)

    def read(self, addr):
        self.transfer(addr)

    def image(self):
        return bytes(b for outs, conds in self.steps for b in outs + conds)

    def results(self, log):
        """The read data, from what the master saw at each edge."""
        n = len(card.M_IN)
        seen = [log[i:i + n] for i in range(0, len(log), n)]
        k, out = 0, []
        for e in seen:
            if k >= len(self.steps):
                break
            conds = self.steps[k][1]
            if all(b == 0 or e[(b - 1) // 2] == (b - 1) % 2 for b in conds):
                if k in self.reads:
                    out.append(sum(e[2 + i] << i for i in range(16)))
                k += 1
        return out


def check_slave(clocks=3000, seed=1):
    """The slave side against a second master on the bench: it writes two
    halfwords into the shared RAM and rings doorbell 3; ucode/hwslave.uc
    answers with their sum; the master reads that back, and makes more
    accesses while the core reads and writes the shared RAM in a loop.
    (the outcome, the master's reads, the IOP's registers 8-11)."""
    m = MasterScript()
    m.step(until={"RESET_n": 1})
    m.idle(20)
    m.write(0x4000_0100, 0x1111)
    m.write(0x4000_0102, 0x2222)
    m.write(0x7400_000C, 0)
    m.idle(60)
    m.read(0x4000_0200)
    m.read(0x4000_0100)
    m.write(0x4000_0104, 0x1234)
    m.write(0x4000_0105, 0xAB00, size=1)
    m.read(0x4000_0104)
    for i in range(8):
        m.write(0x4000_0300 + 2 * i, 0x100 + i)
    for i in range(8):
        m.read(0x4000_0300 + 2 * i)
    m.idle(2)
    b = Program("hwslave.uc")
    s = model(b)
    pre = preloads(b, s)
    pre["X_M"] = m.image()
    cfg = config(clocks, 0, seed)
    cfg["dump"] += ["X_M"]
    hw = native.hwsim.run_system(netlist(master=True), cfg, pre)
    d = hw["dumps"]
    regs = [l | h << 8 for l, h in zip(d["U_RAML"][0xC008:0xC00C], d["U_RAMH"][0xC008:0xC00C])]
    return hw, m.results(d["X_M"]), regs


def check_window(clocks=4000, seed=1):
    """The window against a second master on the bench, while
    ucode/hwwin.uc reads the flash and writes the LEDs in a loop: posted
    writes to the UART's scratch register, one after another and before a
    read, read back; the flash's header; the shared RAM between. (the
    outcome, the master's reads, what they should be, the IOP's registers
    8-15, the model's, which runs the program without the window)."""
    b = Program("hwwin.uc")
    fl = lambda i: b.flash[2 * i] | b.flash[2 * i + 1] << 8
    win = lambda dev, r: 0x7F00_0000 | dev << 16 | 4 * r
    m = MasterScript()
    m.step(until={"RESET_n": 1})
    m.idle(40)                                  # the timing table's filled in
    m.write(win(12, 7), 0x5A)
    m.write(win(12, 7), 0xC3)                   # waits for the first
    m.read(win(12, 7))
    m.read(win(13, layout.FL_MAGIC))
    m.write(0x4000_0100, 0x1234)
    m.read(win(13, layout.FL_PAGES))
    m.read(0x4000_0100)
    m.write(win(12, 7), 0x11)
    m.read(win(13, layout.FL_MAGIC))            # after the write's done
    m.read(win(12, 7))
    m.idle(2)
    want = [0xC3, fl(layout.FL_MAGIC), fl(layout.FL_PAGES), 0x1234, fl(layout.FL_MAGIC), 0x11]
    uart = [0, 5]                               # its D8-D15 are nobody's
    s = model(b)
    pre = preloads(b, s)
    pre["X_M"] = m.image()
    cfg = config(clocks, 0, seed)
    cfg["dump"] += ["X_M"]
    hw = native.hwsim.run_system(netlist(master=True), cfg, pre)
    s.s.run(s.s.clock + clocks)
    d = hw["dumps"]
    regs = [l | h << 8 for l, h in zip(d["U_RAML"][0xC008:0xC010], d["U_RAMH"][0xC008:0xC010])]
    reads = [x & 0xFF if i in uart else x for i, x in enumerate(m.results(d["X_M"]))]
    return hw, reads, want, regs, s.s.sram(0xC008, 8)


def check_watchdog(clocks=6000, seed=1, wait_ps=20_000_000, cold_ps=2_000_000):
    """The watchdog, with its times shortened to `wait_ps` and `cold_ps`:
    ucode/hwwdog.uc counts its starts in register 8 and kicks it a few
    times. (the outcome, the starts, the clocks at which uIR took
    microaddress 0 after a reset.)"""
    b = Program("hwwdog.uc")
    s = model(b)
    pre = preloads(b, s)
    first = s.s.sram(0xC008, 1)[0]
    cfg = config(clocks, 1_000_000, seed)
    hw = native.hwsim.run_system(netlist(watchdog=(wait_ps, cold_ps)), cfg, pre)
    d = hw["dumps"]
    a = d["U_RAML"][0xC008] | d["U_RAMH"][0xC008] << 8
    starts = [f[0] for f in hw["fetches"] if f[1] == 0]
    return hw, (a - first) & 0xFFFF, starts


def check_stuck(clocks=1500, seed=1):
    """The stuck-transfer counter: ucode/hwstuck.uc reads from the bench's
    stuck slave, which holds WAIT until RESET. (the outcome, the IOP's
    registers 8-10, the longest wait between two E2s in clocks.)"""
    b = Program("hwstuck.uc")
    s = model(b)
    cfg = config(clocks, 1_000_000, seed)
    hw = native.hwsim.run_system(netlist(), cfg, preloads(b, s))
    d = hw["dumps"]
    regs = [l | h << 8 for l, h in zip(d["U_RAML"][0xC008:0xC00B], d["U_RAMH"][0xC008:0xC00B])]
    f = hw["fetches"]
    return hw, regs, max(b_[0] - a_[0] for a_, b_ in zip(f, f[1:]))


def where(b, a):
    return b.mc.where(a)


def bom():
    """{part: packages} on the card: the bench's (X_...) left out, the
    halves of 16-bit parts paired."""
    nl = card.build(bench=True)
    per, refs = {}, {}
    for inst in nl.instances:
        if inst.ref.startswith("X_") or inst.type.family in ("fixture", "passive"):
            continue
        p = inst.part_number(card.VARIANT)
        per[p] = inst.type.per_package
        refs[p] = refs.get(p, 0) + 1
    return {p: -(-n // per[p]) for p, n in refs.items()}


def report(hw):
    print(f"{hw['cycles']:,} clocks, {hw['fetch_count']:,} microinstructions, {hw['events']:,} events, "
          f"{hw['wall_seconds']:.1f} s ({hw['reason']})")
    print(f"timing violations: {hw['violation_total']}")
    for v in hw["violation_summary"][:12]:
        print(f"  {v['count']:6} x {v['what']} (worst slack {v['worst_slack_ps']} ps)")
    c = hw["contention"]
    print(f"bus contention: {c['count']} episodes, the longest {c['max_ps']} ps")


def main(argv):
    p = argparse.ArgumentParser(prog="heron iop hw")
    sub = p.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--ms", type=float, default=30.0)
    r.add_argument("--seed", type=int, default=1)
    r.add_argument("--type", default="", help="what the console's terminal types")
    t = sub.add_parser("test")
    t.add_argument("--ms", type=float, default=2.0)
    t.add_argument("--seed", type=int, default=1)
    t.add_argument("--ucode", help="a microcode program of its own (ucode/NAME) instead of the firmware")
    sub.add_parser("bom")
    sub.add_parser("slave")
    sub.add_parser("window")
    sub.add_parser("stuck")
    sc = sub.add_parser("schematic")
    sc.add_argument("--out", help="where to write it (default build/iop/schematic.html)")
    a = p.parse_args(argv)
    if a.cmd == "run":
        b = bld.Build(bld.DEFAULT_PROGRAM, quick=True)
        hw = run(b, a.ms, a.type.encode().replace(b"\\r", b"\r"), a.seed)
        sys.stdout.write(hw["output"].decode("latin-1"))
        print()
        report(hw)
    elif a.cmd == "test" and a.ucode:
        hw, diff, n, b, want, got = check_ucode(a.ucode, seed=a.seed)
        report(hw)
        if diff:
            i, g_, w_ = diff
            print(f"E2 {i} of {n}: the card {g_}, the model {w_}")
            return 1
        print(f"the same as the model for {n:,} microinstructions")
        print("registers 8-15: card ", [hex(x) for x in got["regs"][8:16]])
        print("               model", [hex(x) for x in want["regs"][8:16]])
        same = got["ram"] == want["ram"]
        print(f"the CPU card's RAM, 4 KB: {'the same' if same else 'different'}")
        return 0 if same and got["regs"][8:16] == want["regs"][8:16] else 1
    elif a.cmd == "test":
        hw, diff, n = check(a.ms, seed=a.seed)
        report(hw)
        b = bld.Build(bld.DEFAULT_PROGRAM, quick=True)
        if diff:
            i, got, want = diff
            print(f"E2 {i} of {n}: the card {got}, the model {want}")
            if got and want:
                print(f"  the card at {where(b, got[1])}, the model at {where(b, want[1])}")
            return 1
        print(f"the same as the model for {n:,} microinstructions")
        print(f"console: card {hw['output']!r}, model {hw['model_output']!r}")
        return 0
    elif a.cmd == "slave":
        hw, reads, regs = check_slave()
        report(hw)
        print("the master read:", [hex(x) for x in reads])
        print("the IOP's registers 8-11:", [hex(x) for x in regs])
        want = [0x3333, 0x1111, 0xAB34] + [0x100 + i for i in range(8)]
        ok = reads == want and regs[:3] == [8, 0x1111, 0x2222]
        print("as expected" if ok else f"expected {[hex(x) for x in want]}")
        return 0 if ok else 1
    elif a.cmd == "window":
        hw, reads, want, regs, mregs = check_window()
        report(hw)
        print("the master read:", [hex(x) for x in reads])
        print("the IOP's registers 8-15: card ", [hex(x) for x in regs])
        print("                          model", [hex(x) for x in mregs])
        ok = reads == want and regs == mregs
        print("as expected" if ok else f"expected {[hex(x) for x in want]}")
        return 0 if ok else 1
    elif a.cmd == "stuck":
        hw, regs, wait = check_stuck()
        report(hw)
        print(f"the read waited {wait} clocks; the event port's register 1 then {regs[0]:#06x}, "
              f"cleared {regs[1]:#06x}; the bus after it read {regs[2]:#06x}")
        ok = regs == [0x6000, 0, 0x1234] and 256 < wait < 300
        print("as expected" if ok else "expected 0x6000, 0, 0x1234 and a wait of 256 clocks and a little")
        return 0 if ok else 1
    elif a.cmd == "schematic":
        from heron.infra.hw import schematic
        out = a.out or os.path.join(OUT, "schematic.html")
        os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
        html = schematic.page(card.build(bench=True), "The I/O processor's card", variant=card.VARIANT,
                              standalone=True)
        with open(out, "w") as f:
            f.write(html)
        print(f"{out}: {len(html) // 1024} KB")
    elif a.cmd == "bom":
        for part, n in sorted(bom().items()):
            print(f"{n:4}  {part}")
        print(f"{sum(bom().values()):4}  in all")
        print("substitutes:")
        for want, used in card.SUBSTITUTES:
            print(f"  {want}: {used}")
    return 0
