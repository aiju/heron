"""Reed's nucleus (sw/kernel.s) on the model, and at chip level.

  heron reed kernel           the model: its console, and what each process did
  heron reed kernel --chip    the chip level too (about ten minutes), console
                              into RAM: the same results as the model's

On the model the console is UART 0. At chip level the UART takes its baud
rate's time and the timer's interrupts come when the 82C54 says, so the
two runs part at the first character: the kernel's console goes into RAM
for both instead ([outmode] 0), and what is compared is what doesn't
depend on when the timer comes: each process's state, how it ended, its
exit code or why it was killed, its page faults; the end's flag; and the
console's bytes, sorted.
"""

import os

from . import hw, model, systest, ucode

HERE = os.path.dirname(os.path.abspath(__file__))
PROGRAM = os.path.join(HERE, "sw", "kernel.s")
FIELDS = ("state", "pc", "sr", "ticks", "faults", "how", "code")
KEPT = ("state", "faults", "how", "code")       # those that don't depend on the timer


def image(outmode=1):
    img, ram = systest.image(PROGRAM)
    sym = img.symbols
    a = sym["outmode"] & 0x7FFFFFFF
    ram[a:a + 4] = outmode.to_bytes(4, "little")
    return sym, ram


def word(mem, a):
    a &= 0x7FFFFFFF
    return int.from_bytes(bytes(mem[a:a + 4]), "little")


def results(sym, mem):
    """{"procs": [{field: value}], "done": flag, "out": the RAM console's bytes}"""
    n = sym["NPROC"]
    procs = []
    for k in range(n):
        base = sym["procs"] + sym["P_SIZE"] * k
        procs.append({f: word(mem, base + 4 * i) for i, f in enumerate(FIELDS)})
    outp = word(mem, sym["outp"])
    start = sym["OUTBUF"] & 0x7FFFFFFF
    out = bytes(mem[start:start + ((outp & 0x7FFFFFFF) - start)]) if outp else b""
    return {"procs": procs, "done": word(mem, sym["done"]), "out": out}


def run_model(outmode=1, max_cycles=20_000_000, prog=None):
    sym, ram = image(outmode)
    m = model.Model(bytes(ram), prog=prog or ucode.build())
    m.stopped = m.run(max_cycles)
    return sym, m


def kept(res):
    return ([{f: p[f] for f in KEPT} for p in res["procs"]], res["done"], sorted(res["out"]))


def main(chip=False):
    prog = ucode.build()
    sym, m = run_model(1, prog=prog)
    print(f"the model: {m.stopped}, {m.instructions:,} instructions, {m.cycles:,} cycles, "
          f"{m.ticks * model.TICK_PS / 1e9:.1f} ms as built")
    print(bytes(m.out).decode(errors="replace").rstrip())
    res = results(sym, m.ram)
    for k, p in enumerate(res["procs"]):
        print(f"  process {k}: " + ", ".join(f"{f} {p[f]:#x}" for f in KEPT))
    if not chip:
        return 0 if m.stopped == "halt" and res["done"] else 1
    sym, m0 = run_model(0, prog=prog)
    sym, ram = image(0)
    hwr = hw.run(bytearray(ram), prog, max_cycles=4 * m0.cycles)
    hres = results(sym, hwr["ram"])
    mres = results(sym, m0.ram)
    # (the clock card's WAIT_IO input is the IO board's timing, untimed
    # yet: reported apart)
    io_wait = [x for x in hwr["violation_summary"] if x["what"].startswith("CLK.U_CGA.I3")]
    v = [x for x in hwr["violation_summary"] if not x["what"].startswith(hw.UNTIMED) and x not in io_wait]
    print(f"chip level: {hwr['stopped_at']} after {hwr['cycles']:,} cycles, {hwr['time_ps'] / 1e9:.1f} ms; "
          f"the model (console in RAM) {m0.cycles:,} cycles")
    same = kept(hres) == kept(mres)
    print("the same results as the model's" if same else f"differ:\n  chip  {kept(hres)}\n  model {kept(mres)}")
    print(f"timing violations on CTRL, ALU, MEM and the clock card: {sum(x['count'] for x in v)}"
          + "".join(f"\n  {x['what']}: {x['count']}x, worst {x['worst_slack_ps'] / 1000:.1f} ns" for x in v[:8]))
    for x in io_wait:
        print(f"and WAIT_IO at the clock card (the IO board's): {x['count']}x, worst "
              f"{x['worst_slack_ps'] / 1000:.1f} ns")
    return 0 if same and not v and hwr["stopped_at"] == "halt" else 1
