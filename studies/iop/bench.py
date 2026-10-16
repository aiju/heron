"""What RFC 0027 estimates, measured on the model: the boot, the Forth's
speed, what the polling tick costs, the copy rates, and booting the CPU.

Times on the system bus are the model's: the CPU card's slave port takes
2 data clocks (3 a transfer, RFC 0027's assumption), its registers 1, and
the bus is granted 4 clocks after a request, with nobody else using it.
"""

import os

from heron.studies.iop import build as bld
from heron.studies.iop.run import Session


def command_ms(s, line, timeout_ms=20000):
    """Simulated ms from typing a line to its " ok"."""
    start = s.ms
    out = s.command(line, timeout_ms)
    if not out.endswith(" ok\r\n"):
        raise RuntimeError(f"{line!r}: {out!r}")
    return s.ms - start


def delta_ms(s, fmt, n):
    """The time of a line with n, less the same line with 0 (padded to the
    same length, so that typing and echoing it cost the same)."""
    return command_ms(s, fmt % n) - command_ms(s, fmt % 0)


def job_ms(s, b, line):
    """Simulated ms of the native job a line starts, from its first slice
    to its end."""
    s.s.breakpoints = [b.mc.labels["mv_start"]]
    s.s.uart_send(line.encode() + b"\r")
    if s.s.run(s.s.clock + int(1e9 / s.bclk)) != "break":
        raise RuntimeError(f"{line!r} started no job")
    start = s.s.clock
    s.s.breakpoints = [b.mc.labels["jfin"]]
    if s.s.run(s.s.clock + int(1e9 / s.bclk)) != "break":
        raise RuntimeError(f"{line!r}: its job didn't end")
    end = s.s.clock
    s.s.breakpoints = []
    s.until(b" ok\r\n", 1000)
    return (end - start) * s.bclk / 1e6


def words_run(b, counts):
    """Forth words executed, by the counts at the primitives' entries and
    nest."""
    entries = set(b.mc.prims.values()) | {b.mc.labels["nest"]}
    return sum(c for a, c in counts if a in entries)


def native_micro(b, counts):
    lo, hi = b.mc.labels["attn_next"], b.mc.labels["native_end"]
    return sum(c for a, c in counts if lo <= a < hi)


def measure(wcs=False):
    """[(what, measured, RFC 0027's estimate)]."""
    b = bld.Build(bld.DEFAULT_PROGRAM, wcs)
    s = Session(b)
    rows = []
    bclk = s.bclk
    ms = lambda clocks: clocks * bclk / 1e6

    # ---- the boot, by breakpoints at the microcode's stages
    s.s.breakpoints = [b.mc.labels["dictcopy"], b.mc.labels["next"]]
    s.s.run(10**9)
    t_copy = s.s.clock
    s.s.run(10**9)
    t_forth = s.s.clock
    s.s.breakpoints = []
    s.boot()
    pages = (b.meta.here + 255) // 256
    rows.append(("SRAM self test (64K cells, two patterns)", f"{ms(t_copy):.1f} ms", "-"))
    rows.append((f"dictionary out of the flash ({b.meta.here} cells, {pages} pages)",
                 f"{ms(t_forth - t_copy):.1f} ms", "32K cells in ~30 ms"))
    rows.append(("power-up to the banner", f"{s.ms:.1f} ms", "-"))

    # ---- the Forth: a loop, less the same line without it
    command_ms(s, ": inc 1+ ; : w 0 ?do i inc dup + over swap - drop loop ;")
    a, z = counted(s, b, "10000 w"), counted(s, b, "00000 w")
    clocks, micro, words, nat = (x - y for x, y in zip(a, z))
    rows.append(("Forth words a second, in a loop of `i inc dup + over swap - drop`",
                 f"{words / (clocks * bclk / 1e9):,.0f}", "about 1,000,000"))
    rows.append(("microcycles a Forth word, there", f"{micro / words:.2f}",
                 "NEXT 3 (2 with its delay slot used), most primitives 5-7"))
    rows.append(("the tick's share of the IOP while Forth computes", f"{100 * nat / micro:.1f}%",
                 "5-10% (0.5-1 us a tick)"))
    a, z = counted(s, b, "words"), counted(s, b, "space")
    rows.append(("Forth words a second, `words` (the console, `emit` waiting on the UART)",
                 f"{(a[2] - z[2]) / ((a[0] - z[0]) * bclk / 1e9):,.0f}", "-"))

    # ---- copies, into the CPU card's RAM through its slave port: a job's
    # time from its first slice to its end, the ticks and the Forth's turns
    # included
    n = 8192
    for name, line, rfc in [
        ("fill, the CPU's RAM", "0 $10000. %d bus-fill", "9.9 MB/s"),
        ("copy, the CPU's RAM to its RAM", "$10000. $20000. %d bus-move", "4.9 MB/s"),
        ("copy, the shared RAM to the CPU's RAM", "0. $10000. %d sr>bus", "7.6 MB/s"),
        ("copy, the CPU's RAM to the shared RAM", "$10000. 0. %d bus>sr", "7.6 MB/s"),
    ]:
        t = job_ms(s, b, line % n)
        rows.append((name + f", {n} halfwords", f"{2 * n / t / 1e3:.1f} MB/s", rfc))

    # ---- booting the CPU
    start = s.ms
    s.command("boot-cpu cpu-wait", 30000)
    what = "booting the CPU: " + ("draft 2's control store, its decode table and the program" if wcs
                                  else "its program (no control store)")
    hw = sum(len(h) for _, h in b.cs["runs"]) if wcs else 0
    rows.append((what, f"{s.ms - start:.1f} ms" + (f" ({2 * hw / (s.ms - start) / 1e3:.1f} MB/s)" if wcs else ""),
                 "about 35 ms for the 1b's (130K halfwords at 7.6 MB/s)" if wcs else "-"))
    for what, done, irq in iop_latency():
        rows.append((f"a request, the IOP's side: {what}, from the doorbell to its completion, and to the interrupt",
                     f"{done:.1f} us, {irq:.1f} us", "~5 us on top of the transfer"))
    for what, cycles, us in request_costs():
        rows.append((f"a request from the CPU at 6 MHz: {what}, its cycles (the handler included), and the time from one to the next",
                     f"{cycles:.0f} cycles, {us:.0f} us", "200-700 cycles"))
    for what, pio, iop in fen_disk():
        rows.append((f"{what}: its own PIO driver; through the IOP", f"{pio}; {iop}",
                     "the CPU's time back"))
    rows.append(("microcode", f"{len(b.mc.words)} microinstructions, {len(b.mc.prims)} primitives",
                 "1-2K; the interpreter and primitives 500-1,000"))
    rows.append(("the Forth's dictionary", f"{b.meta.here} cells", "up to 32K"))
    return rows


def counted(s, b, line):
    """A line run: (bus clocks, microcycles, Forth words, microcycles in
    the native layer)."""
    s.s.clear_counts()
    st0, c0 = s.s.stats(), s.s.clock
    command_ms(s, line)
    counts = s.s.counts()
    return (s.s.clock - c0, s.s.stats()["micro"] - st0["micro"], words_run(b, counts), native_micro(b, counts))


RING_PROGRAM = os.path.join(bld.HERE, "sw", "ring.s")
GO, DONE, STATUS, RESULT, TABLE = 0x1000, 0x1004, 0x1008, 0x100C, 0x2000


def word(x):
    return (x & 0xFFFF_FFFF).to_bytes(4, "little")


def requests(s, reqs, timeout_ms=200):
    """The CPU (sw/ring.s, booted and waiting) makes reqs, [(op, a, b, len,
    tag)], one at a time. ({cycles, idle, done, status, result}, simulated
    ms)."""
    table = word(len(reqs)) + b"".join(word(op) + word(a) + word(b) + word(n | tag << 16)
                                       for op, a, b, n, tag in reqs)
    s.s.cpu_mem_write(TABLE, table)
    c0 = s.s.cpu()
    start = s.ms
    s.s.cpu_mem_write(GO, word(1))
    while not s.s.cpu()["halted"]:
        if s.ms - start > timeout_ms:
            raise RuntimeError("the CPU didn't finish its requests")
        s.run_ms(0.05)
    c1 = s.s.cpu()
    mem = lambda a: int.from_bytes(s.s.cpu_mem(a, 4), "little")
    return {"cycles": c1["cycles"] - c0["cycles"], "idle": c1["idle_cycles"] - c0["idle_cycles"],
            "done": mem(DONE), "status": mem(STATUS), "result": mem(RESULT)}, s.ms - start


def ring_session():
    """The system with sw/ring.s booted, waiting for its requests."""
    s = Session(bld.Build(RING_PROGRAM))
    s.boot()
    s.command("boot-cpu", 5000)
    s.run_ms(2)
    return s


def request_costs():
    """[(what, CPU cycles a request, us a request)]: the CPU making the
    same request n times, each waiting for its completion's interrupt."""
    import heron.studies.iop.layout as L
    n = 16
    out = []
    for what, req in [
        ("fill 64 bytes", (L.OP_FILL, 0x10000, 0x5555, 64, 1)),
        ("copy a 4 KB page", (L.OP_COPY, 0x20000, 0x10000, 4096, 2)),
        ("a request to the Forth's server (OP_NOP)", (L.OP_NOP, 0, 0, 0, 3)),
    ]:
        s = ring_session()
        got, ms = requests(s, [req] * n)
        assert got["done"] == n and got["status"] == 0, got
        out.append((what, (got["cycles"] - got["idle"]) / n, 1000 * ms / n))
    return out


def iop_latency():
    """[(what, us from the doorbell to the completion in the ring, to the
    interrupt's bit on the bus)]: the IOP's side of a request, the test
    playing the client (tests/test_rings.py)."""
    import heron.studies.iop.layout as L
    from heron.studies.iop.tests.test_rings import kernel
    s = Session(bld.Build(bld.DEFAULT_PROGRAM))
    s.boot()
    k = kernel(s)
    k.do((L.OP_NOTIFY, 0, 3 << 16, 0, 0))
    out = []
    for what, req in [("fill 64 bytes", (L.OP_FILL, 0x10000, 0x5555, 64, 1)),
                      ("copy a 4 KB page", (L.OP_COPY, 0x20000, 0x10000, 4096, 2)),
                      ("OP_NOP, through the Forth's server", (L.OP_NOP, 0, 0, 0, 3))]:
        s.run_ms(0.1)
        k.put(*req)
        s.s.breakpoints = [s.b.mc.labels["cpost"]]
        start = s.s.clock
        k.ring()
        times = []
        for label in ["cpost", "po_now"]:
            s.s.breakpoints = [s.b.mc.labels[label]]
            if s.s.run(s.s.clock + int(20e6 / s.bclk)) != "break":
                raise RuntimeError(f"{what}: no {label}")
            times.append((s.s.clock - start) * s.bclk / 1e3)
        s.s.breakpoints = []
        s.run_ms(0.5)
        k.completions()
        out.append((what, *times))
    return out


def fen_disk(kb=256):
    """[(what, PIO's result, the IOP's)]: Fen (studies/fen) reading and
    copying a file bigger than its file server's cache, with its own PIO
    driver for the I/O card's CF card, and with the disk behind the IOP
    (srv/fs/ide_iop.c): the time, the CPU's busy share, and its busy
    cycles a KB."""
    from heron.studies.fen import build as fen_build
    from heron.studies.fen.run import Session as FenSession
    data = bytes((i * 7 + (i >> 9)) & 0xFF for i in range(kb * 1024))
    disk = fen_build.disk(extra={"/tmp/big": data})
    got = {}
    for iop in (False, True):
        s = FenSession(iop=iop, disk=disk)
        s.boot(timeout_ms=5000)
        s.command("true")
        for cmd in ("cat /tmp/big > /dev/null", "cp /tmp/big /tmp/copy"):
            c0, i0, t0 = s.c.cycles, s.c.idle_cycles, s.ms
            s.type(cmd + "\n")
            s.wait_for("% ", step_ms=0.2)
            c1, i1, t1 = s.c.cycles, s.c.idle_cycles, s.ms
            busy = (c1 - c0) - (i1 - i0)
            got[cmd, iop] = f"{t1 - t0:.0f} ms, {100 * busy / (c1 - c0):.0f}% busy, {busy / kb:,.0f} cycles a KB"
    return [(f"Fen: `{cmd}`, {kb} KB", got[cmd, False], got[cmd, True])
            for cmd in ("cat /tmp/big > /dev/null", "cp /tmp/big /tmp/copy")]


def table(rows):
    out = ["| | Measured | RFC 0027 |", "|---|---:|---|"]
    out += [f"| {a} | {b} | {c} |" for a, b, c in rows]
    return "\n".join(out)
