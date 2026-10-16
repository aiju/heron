"""What RFC 0027 estimates, measured on the model: the boot, the Forth's
speed, what the polling tick costs, the copy rates, and booting the CPU.

Times on the system bus are the model's: the CPU card's slave port takes
2 data clocks (3 a transfer, RFC 0027's assumption), its registers 1, and
the bus is granted 4 clocks after a request, with nobody else using it.
"""

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

    # ---- copies, into the CPU card's RAM through its slave port
    n = 8192
    for name, line, rfc in [
        ("fill, the CPU's RAM", "0 $10000. %05d bus-fill", "9.9 MB/s"),
        ("copy, the CPU's RAM to its RAM", "$10000. $20000. %05d bus-move", "4.9 MB/s"),
        ("copy, the shared RAM to the CPU's RAM", "0 0 $10000. %05d sr>bus", "7.6 MB/s"),
        ("copy, the CPU's RAM to the shared RAM", "$10000. 0 0 %05d bus>sr", "7.6 MB/s"),
    ]:
        t = delta_ms(s, line, n)
        rows.append((name + f", {n} halfwords", f"{2 * n / t / 1e3:.1f} MB/s", rfc))

    # ---- booting the CPU
    start = s.ms
    s.command("boot-cpu cpu-wait", 30000)
    what = "booting the CPU: " + ("the control store, the decode table and the program" if wcs
                                  else "its program (no control store)")
    hw = sum(len(h) for _, h in b.cs["runs"]) if wcs else 0
    rows.append((what, f"{s.ms - start:.1f} ms" + (f" ({2 * hw / (s.ms - start) / 1e3:.1f} MB/s)" if wcs else ""),
                 "about 35 ms (130K halfwords at 7.6 MB/s)" if wcs else "-"))
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


def table(rows):
    out = ["| | Measured | RFC 0027 |", "|---|---:|---|"]
    out += [f"| {a} | {b} | {c} |" for a, b, c in rows]
    return "\n".join(out)
