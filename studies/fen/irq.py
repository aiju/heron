"""heron fen irq: how long Fen holds interrupts off, and how often they come.

For RFC 0040 (interrupts). The simulator runs Fen one instruction at a time
and records:

- **every span with interrupts held off,** from I going clear to I set
  again, with what started it: the vector the CPU entered through (a
  system call, an interrupt, a fault) or a `DI`. Fen's kernel runs with
  interrupts off throughout, so these are its paths;
- **every interrupt taken,** by device;
- **the gaps between thread switches** (a change of register bank) and
  between returns to user mode, which bound how long an event the kernel
  only looks at then would wait.

Then it sends fast events at random moments through those spans, to see how
often the message register would be busy (RFC 0040's section 10): each
event's entry waits for interrupts to be let in, and takes the CPU for a
handler's time.

An interrupt that arrives at a random moment lands in a span of length T
with probability T over the whole time, and then waits T / 2 on average, so
its mean wait is the sum of T squared over twice the time.

Levels: the simulator numbers them as RFC 0029 does, 1-8, with level L's
vector at 0x40 + 4(L - 1). Fen's board sets mask bit L - 1 for it, and
Fen's kernel calls that level L - 1: its timer, "level 6", is RFC 0029's
level 7. The tables name devices instead.

--write puts the tables in RFC 0040's fen-latency-results.md, beside the
document that discusses them (fen-latency.md).
"""

import bisect
import collections
import os
import random
import sys

from heron import ROOT
from heron.studies.fen import syscalls
from heron.studies.fen.run import MS, Session

OUT = os.path.join(ROOT, "reports", "0040-rfc-interrupts", "fen-latency-results.md")
VEC_BASE = 0x8000_0000
EXCEPTIONS = {0x00: "reset", 0x04: "NMI", 0x08: "illegal", 0x0C: "bus error",
              0x10: "divide", 0x14: "address", 0x18: "tag", 0x1C: "privilege",
              0x20: "page fault", 0x24: "trace"}
SWI = {n: name for n, name, *_ in syscalls.SYSCALLS}
DEVICE = {7: "timer", 6: "UART", 5: "CF card", 4: "PS/2", 3: "video"}
RATES = (100, 1_000, 10_000)  # fast events a second
HANDLER_US = 10               # a message's entry and handler (an assumption)
DEPTHS = (1, 4)               # the message register, and a FIFO of four


def cause(off):
    """What the CPU entered through, from the vector's offset."""
    if off in EXCEPTIONS:
        return EXCEPTIONS[off]
    if 0x40 <= off < 0x60:
        level = (off - 0x40) // 4 + 1
        return "interrupt: " + DEVICE.get(level, f"level {level}")
    if 0x100 <= off < 0x500:
        n = (off - 0x100) // 4
        return "`" + SWI.get(n, f"swi {n}") + "`"
    return f"vector {off:#x}"


class Tracer:
    def __init__(self, c):
        self.c = c
        self.off_start = None
        self.off_cause = None
        self.spans = []                     # (cycles, cause)
        self.off = []                       # (start, end) cycles of each span
        self.taken = collections.Counter()  # device
        self.switches = []                  # cycles at each change of bank
        self.exits = []                     # cycles at each return to user mode
        self.last_bank = c.bank
        self.last_sr = c.sr
        self.instructions = 0

    def run(self, until):
        c = self.c
        status = "ok"
        while c.cycles < until:
            status = c.run(until, 1)
            self.instructions += 1
            sr, pc = c.sr, c.pc
            why = None
            if VEC_BASE <= pc < VEC_BASE + 0x500 and pc % 4 == 0:
                why = cause(pc - VEC_BASE)
                if why.startswith("interrupt"):
                    self.taken[why[len("interrupt: "):]] += 1
            on, was_on = sr >> 30 & 1, self.last_sr >> 30 & 1
            if was_on and not on:
                self.off_start, self.off_cause = c.cycles, why or "`DI`"
            elif on and not was_on and self.off_start is not None:
                self.spans.append((c.cycles - self.off_start, self.off_cause))
                self.off.append((self.off_start, c.cycles))
                self.off_start = None
            if self.last_sr >> 31 & 1 and not sr >> 31 & 1:
                self.exits.append(c.cycles)
            if c.bank != self.last_bank:
                self.switches.append(c.cycles)
                self.last_bank = c.bank
            self.last_sr = sr
            if status == "halted":
                break
        return status


def trace(session):
    """Make the session run one instruction at a time through a tracer."""
    t = Tracer(session.c)

    def run(ms):
        until = session.c.cycles_at(int((session.ms + ms) * MS))
        session.status = t.run(until)
        session._collect()
        if session.status == "halted":
            raise RuntimeError("the machine halted:\n" + session.log.decode(errors="replace"))
        return session.status
    session.run = run
    return t


def desktop(s):
    s.run(1500)
    s.click(20, 20)
    s.run(300)
    s.keys("ls /bin\n")
    s.run(500)
    s.drag(200, 60, 300, 160)
    s.run(300)


# name: (a serial console, boot before tracing, what it does, what it is)
WORKLOADS = {
    "boot": (True, False, lambda s: s.boot(),
             "power-on to the shell's first prompt"),
    "commands": (True, True, lambda s: [s.command(c) for c in (
        "ls /bin", "ps", "cat /etc/menu", "echo hello | cat", "seq 200",
        "wc /bin/sh", "sort /etc/menu", "grep a /etc/menu")],
        "eight short commands at the serial shell"),
    "kbench": (True, True, lambda s: s.command("kbench", timeout_ms=600_000),
               "the kernel's benchmark (`kbench`)"),
    "idle": (True, True, lambda s: s.run(2000), "two seconds at the prompt"),
    "desktop": (False, False, desktop,
                "the desktop from power-on: a click, typing `ls /bin`, a drag"),
}


def measure(name):
    serial, boot_first, body, _ = WORKLOADS[name]
    s = Session(serial=serial)
    if boot_first:
        s.boot()
    t = trace(s)
    t.start = s.c.cycles
    body(s)
    return t, s.c.cycles - t.start, s.c.cycles_at(10**9)


def busy(t, total, hz, rate, depth, off=True, seed=1):
    """The fraction of fast events that find the message register (depth 1)
    or a FIFO of messages (depth > 1) full, for events at random moments at
    rate a second. An event waits until interrupts are let in, then its entry
    frees its place and the CPU handles it for HANDLER_US; the next waits for
    that. With off false, interrupts are never held off: the best a kernel
    following RFC 0040's convention could do."""
    spans = t.off if off else []
    ends = [e for _, e in spans]
    service = HANDLER_US * hz / 1e6

    def let_in(x):
        # the first moment at or after x outside every span
        i = bisect.bisect_right(ends, x)
        if i < len(spans) and spans[i][0] <= x:
            return spans[i][1]
        return x

    rng = random.Random(seed)
    waiting = collections.deque()
    free = t.start
    sent = dropped = 0
    x = t.start
    while True:
        x += rng.expovariate(rate) * hz
        if x >= t.start + total:
            break
        while waiting:
            go = let_in(max(free, waiting[0]))
            if go > x:
                break
            waiting.popleft()
            free = go + service
        sent += 1
        if len(waiting) < depth:
            waiting.append(x)
        else:
            dropped += 1
    return dropped / sent if sent else 0


def quantiles(xs):
    xs = sorted(xs)
    if not xs:
        return None
    n = len(xs)
    q = lambda p: xs[min(n - 1, int(p * n))]
    return {"n": n, "p50": q(0.5), "p90": q(0.9), "p99": q(0.99), "max": xs[-1]}


def gaps(times):
    return [b - a for a, b in zip(times, times[1:])]


def tables(results):
    us = lambda c, hz: c * 1e6 / hz
    out = ["# Fen's interrupt latency: the results",
           "",
           "Generated by `heron fen irq --write`"
           " ([studies/fen/irq.py](../../studies/fen/irq.py));"
           " discussed in [fen-latency.md](fen-latency.md). Fen at 6 MHz, on the"
           " simulator's reference timing. Times in µs unless marked.",
           "",
           "## The workloads",
           "",
           "| Workload | What it is | Simulated | Instructions |",
           "|---|---|---:|---:|"]
    for name, (t, total, hz) in results.items():
        out.append(f"| {name} | {WORKLOADS[name][3]} | {total / hz * 1e3:,.0f} ms | {t.instructions:,} |")
    out += ["",
            "## Interrupts held off",
            "",
            "| Workload | Off, of the time | Spans | Median | 90% | 99% | Longest | A random arrival's mean wait |",
            "|---|---:|---:|---:|---:|---:|---:|---:|"]
    for name, (t, total, hz) in results.items():
        spans = [c for c, _ in t.spans]
        q = quantiles(spans)
        wait = sum(c * c for c in spans) / (2 * total)
        if q is None:
            out.append(f"| {name} | 0% | 0 | | | | | 0 |")
            continue
        out.append(f"| {name} | {100 * sum(spans) / total:.0f}% | {q['n']:,} | {us(q['p50'], hz):,.0f}"
                   f" | {us(q['p90'], hz):,.0f} | {us(q['p99'], hz):,.0f} | {us(q['max'], hz):,.0f}"
                   f" | {us(wait, hz):,.0f} |")
    out += ["",
            "## What holds them off longest",
            "",
            "The five causes with the most time off in each workload.",
            "",
            "| Workload | Cause | Times | Mean | Longest | Of the time |",
            "|---|---|---:|---:|---:|---:|"]
    for name, (t, total, hz) in results.items():
        by = collections.defaultdict(list)
        for c, why in t.spans:
            by[why].append(c)
        for why, cs in sorted(by.items(), key=lambda kv: -sum(kv[1]))[:5]:
            out.append(f"| {name} | {why} | {len(cs):,} | {us(sum(cs) / len(cs), hz):,.0f}"
                       f" | {us(max(cs), hz):,.0f} | {100 * sum(cs) / total:.1f}% |")
    devices = sorted({d for t, _, _ in results.values() for d in t.taken})
    out += ["",
            "## Interrupts taken, a second",
            "",
            "| Workload | " + " | ".join(devices) + " |",
            "|---|" + "---:|" * len(devices)]
    for name, (t, total, hz) in results.items():
        secs = total / hz
        out.append(f"| {name} | " + " | ".join(
            f"{t.taken.get(d, 0) / secs:,.0f}" for d in devices) + " |")
    out += ["",
            "## How long until the kernel looks again",
            "",
            "The gaps between thread switches (a change of register bank) and"
            " between returns to user mode.",
            "",
            "| Workload | Between | Gaps | Median | 90% | 99% | Longest |",
            "|---|---|---:|---:|---:|---:|---:|"]
    for name, (t, total, hz) in results.items():
        for what, times in (("thread switches", t.switches), ("returns to user mode", t.exits)):
            q = quantiles(gaps(times))
            if q is None:
                continue
            out.append(f"| {name} | {what} | {q['n']:,} | {us(q['p50'], hz):,.0f} | {us(q['p90'], hz):,.0f}"
                       f" | {us(q['p99'], hz):,.0f} | {us(q['max'], hz):,.0f} |")
    out += ["",
            "## How often the message register would be busy",
            "",
            f"Fast events at random moments, a handler of {HANDLER_US} µs each."
            " Each event's entry waits until interrupts are let in: as Fen holds"
            " them off now, or never held off, the best a kernel at `SPL #6` could"
            " do. The table gives the share of events whose claim fails, with the"
            " message register and with a FIFO of four messages.",
            "",
            "| Workload | Fast events a second | Register, as Fen is | FIFO of 4, as Fen is"
            " | Register, never held off | FIFO of 4, never held off |",
            "|---|---:|---:|---:|---:|---:|"]
    for name, (t, total, hz) in results.items():
        if not t.off:
            continue
        for rate in RATES:
            cells = [busy(t, total, hz, rate, d, off) for off in (True, False) for d in DEPTHS]
            out.append(f"| {name} | {rate:,} | " + " | ".join(f"{100 * c:.1f}%" for c in cells) + " |")
    return "\n".join(out) + "\n"


def main(write=False, names=None):
    results = {}
    for name in names or WORKLOADS:
        print(f"tracing {name}...", file=sys.stderr)
        results[name] = measure(name)
    text = tables(results)
    if write:
        os.makedirs(os.path.dirname(OUT), exist_ok=True)
        with open(OUT, "w") as f:
            f.write(text)
        print(f"wrote {os.path.relpath(OUT, ROOT)}", file=sys.stderr)
    else:
        sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    sys.exit(main("--write" in sys.argv))
