"""heron fen banks: what Fen would pay for fewer register banks.

Fen gives every thread a bank of its own (RFC 0029 has 256, so at most
255 threads), and a switch saves nothing. With fewer banks than threads,
the banks would be a cache of the threads' registers: a thread that runs
without one takes the bank of the thread that ran least recently, whose
registers go to memory, and loads its own. With no banks at all, every
entry to the kernel saves the user's registers, as on most machines.

This measures what that costs:

- **Traces** of which thread runs, from the simulator: each return to
  user mode in another bank than the last, the kernel's marks of threads
  starting and ending (the board's trace port), and each message `BCOPY`
  copies into a bank. The traces start at power-on; the counts are taken
  over each workload alone.
- **The replay** of each trace through banks shared as an LRU cache, for
  2 to 1,024 banks (one of them the supervisor's).
- **The costs** of saving and loading a bank, and of what a kernel with
  no banks does instead, timed on the simulator in a bare system-mode
  program.

--write puts the tables in report 0037's results.md.
"""

import collections
import os

from heron import ROOT, native
from heron.infra import asm as asmcore
from heron.infra import isas
from heron.infra import link as L
from heron.studies.fen import build
from heron.studies.fen.run import Session
import heron.studies.v2_isa  # noqa: F401

REPORT = os.path.join(ROOT, "reports", "0037-report-register-banks")
BANKS = [1, 2, 4, 8, 16, 32, 64, 256, 1024]
CONFIGS = [None, "D32-separate"]          # the reference (D16-overlap), and 1b's
MSG = 0x100                               # the simulator's mark of a BCOPY into a bank
START, END = 0x01000000, 0x02000000       # kernel/kernel.h's TRACE_START, TRACE_END

# ---- what the operations cost --------------------------------------------------


def _harness(body, n):
    """A bare system-mode program: body n times, then HALT. r1 is a bank
    (5), r4 another (6), r2 a buffer, r11 and r12 r2 + 64 and r2 + 32."""
    text = f"""
        .org 0x80000000
        JMP  start
        .org 0x80000400
start:  MOV  sp, #0x80010000
        MOV  r1, #5
        MOV  r4, #6
        MOV  r2, #area
        LEA  r11, [r2 + 64]
        LEA  r12, [r2 + 32]
        MOV  r13, #{n}
loop:
{body}
        DEC  r13
        BNE  loop
        HALT
        .align 4
area:   .space 256
"""
    a = asmcore.Assembler(isas.get("v2"), relocatable=True)
    a.load("banks.s", text=text)
    img = L.link([a.assemble_object("banks.o")], [], "v2", mem_top=0x81000000)
    return build.image_bytes(img, 0x80000000, max(img.mem) + 1)


def _run(body, ref, n=1000):
    c = native.fen.Computer(reference=ref)
    c.load(0, _harness(body, n))
    status = c.run(c.cycles + 200_000_000)
    assert status == "halted", status
    return c.cycles


def _lines(*parts):
    out = []
    for p in parts:
        out += p if isinstance(p, list) else [p]
    return "\n".join("        " + x for x in out)


def _mfur(dst, src):
    return [f"MFUR r{d}, r{s}" for d, s in zip(dst, src)]


def _mtur(dst, src):
    return [f"MTUR r{d}, r{s}" for d, s in zip(dst, src)]


# The bodies. HI and LO: RFC 0029 has no way for the supervisor to reach
# another bank's (MFUR and MTUR name r0-r15), so they stand in as two more
# MFURs or MTURs, the cost such an instruction would most likely have.
R8 = list(range(3, 11))
OPS = {
    # a bank's 18 registers to memory, and back
    "save18": _lines("MTSR bank, r1", _mfur(R8, range(8)), "STM  r2, r3-r10",
                     _mfur(R8, range(8, 16)), "STM  r12, r3-r10",
                     _mfur([3, 4], [0, 0]), "STM  r11, r3-r4"),
    "load18": _lines("MTSR bank, r1", "LDM  r2, r3-r10", _mtur(range(8), R8),
                     "LDM  r12, r3-r10", _mtur(range(8, 16), R8),
                     "LDM  r11, r3-r4", _mtur([0, 0], [3, 4])),
    # without r0-r7, which a message makes dead (the sender's) or brings
    "save10": _lines("MTSR bank, r1", _mfur(R8, range(8, 16)), "STM  r12, r3-r10",
                     _mfur([3, 4], [0, 0]), "STM  r11, r3-r4"),
    "load10": _lines("MTSR bank, r1", "LDM  r12, r3-r10", _mtur(range(8, 16), R8),
                     "LDM  r11, r3-r4", _mtur([0, 0], [3, 4])),
    # a message as Fen copies it, and memory to memory
    "bcopy": _lines("BCOPY r1, r4"),
    "msgmem": _lines("LDM  r2, r3-r10", "STM  r12, r3-r10"),
    # no banks: an entry saves and restores what C may change (r0-r7, HI,
    # LO), and a switch the rest (r8-r14; sp goes with the stack)
    "entry": _lines("SAVE r0-r7", "MFSR r0, hi", "MFSR r1, lo", "SAVE r0-r1",
                    "RESTORE r0-r1", "MTSR hi, r0", "MTSR lo, r1", "RESTORE r0-r7"),
    "switch7": _lines("SAVE r8-r14", "RESTORE r8-r14"),
    # a user register through MFUR, or from a frame in memory
    "mfur": _lines(_mfur([3], [5])),
    "load": _lines("MOV  r3, [r2 + 20]"),
}


def costs():
    """{config: {op: cycles}}"""
    out = {}
    for ref in CONFIGS:
        base = _run("", ref)
        out[ref] = {op: (_run(body, ref) - base) / 1000 for op, body in OPS.items()}
    return out


# ---- the workloads ---------------------------------------------------------------

SHELL = [
    "ls -l /bin",
    "cat /etc/hello.txt | wc -w",
    "seq 300 | sort -rn | head -3",
    "grep -c e /etc/motd /etc/hello.txt",
    "cp /etc/hello.txt /tmp/a; cat /tmp/a /tmp/a > /tmp/b; wc -c /tmp/b; rm /tmp/a /tmp/b",
    "ps; df; free; uptime",
    "xd /bin/true | tail -2",
    "sleep 1 & seq 100 | uniq | wc -l; wait",
]


def _settle(s, quiet=300, limit_ms=60_000):
    """Run until the machine has been idle for `quiet` ms (at most
    limit_ms)."""
    from heron.studies.fen.bench import busy
    hz = s.c.cycles_at(1_000_000_000)
    start, idle_for = s.ms, 0
    while idle_for < quiet and s.ms - start < limit_ms:
        b = busy(s)
        s.run(10)
        idle_for = idle_for + 10 if busy(s) - b < 0.05 * hz / 100 else 0


def _menu(s, item, items=2):
    top = 480 - (items * 18 + 4)
    s.mouse_to(20, 470)
    s.c.mouse(0, 0, 1)
    s.run(100)
    s.mouse_to(30, top + 2 + 18 * item + 9, 1)
    s.c.mouse(0, 0, 0)
    _settle(s)


def w_ipc(s):
    s.command("kbench ipc_process", timeout_ms=120_000)


def w_shell(s):
    for line in SHELL:
        s.command(line, timeout_ms=120_000)


def w_pipeline(s):
    s.command("cat /bin/sh /bin/term | xd | sort | uniq | wc -l", timeout_ms=300_000)


def w_desktop(s):
    _menu(s, 1)                         # the clock
    s.click(400, 300)                   # the terminal
    for line in ("ls -l /bin", "seq 200", "cat /etc/hello.txt"):
        s.keys(line + "\n")
        _settle(s)
    s.drag(200, 33, 300, 93)
    _settle(s)
    s.run(2000)                         # the clock ticks


def w_busy(s):
    s.keys("seq 2000 | sort -n | tail -1 &\n")
    s.run(300)
    _menu(s, 0)                         # a second terminal, on top
    s.keys("ls -l /bin; ps\n")
    s.run(300)
    _menu(s, 0)                         # a third
    s.keys("xd /bin/sh | wc -l\n")
    s.run(300)
    _menu(s, 1)                         # and the clock
    _settle(s)
    s.run(3000)


WORKLOADS = [
    ("ipc", "kbench: 2,000 calls and replies between two processes", True, w_ipc),
    ("shell", "eight command lines on the serial console (ls -l, pipelines, cp, ps, ...)", True, w_shell),
    ("pipeline", "a five-process pipeline over 44 KB: cat, xd, sort, uniq, wc", True, w_pipeline),
    ("desktop", "the desktop: the clock, three commands in the terminal, a window moved, 2 s idle", False, w_desktop),
    ("busy", "three terminals running at once, and the clock", False, w_busy),
]


def _opcodes(c, pcs):
    """{physical pc: opcode byte} for kernel PCs."""
    out = {}
    for pc in pcs:
        b = c.read_phys(pc, 2)
        out[pc] = b[0]
    return out


def trace(name, serial, fn):
    """Run a workload from power-on with tracing: its counts and events."""
    s = Session(serial=serial)
    s.c.trace_banks()
    if serial:
        s.boot()
    else:
        _settle(s)
    events = []

    def collect():
        for cyc, v in s.c.bank_runs():
            events.append((cyc, "msg" if v & MSG else "run", v & 0xFF))
        for cyc, v in s.c.trace_port():
            events.append((cyc, "start" if v & START else "end", v & 0xFF))
    collect()
    t0, busy0, ent0 = s.c.cycles, s.c.cycles - s.c.idle_cycles, s.c.user_entries
    keys0 = collections.Counter()
    for pc, k, n in s.c.pc_keys():
        keys0[pc] += n
    fn(s)
    collect()
    kend = s.kernel.symbols["__end"] & 0x7FFFFFFF
    execs = collections.Counter()
    for pc, k, n in s.c.pc_keys():
        if pc is not None and pc < kend:
            execs[pc] += n
    for pc in execs:
        execs[pc] -= keys0[pc]
    ops = _opcodes(s.c, [pc for pc, n in execs.items() if n > 0])
    count = collections.Counter()
    for pc, n in execs.items():
        if n > 0:
            count[{0x31: "mfur", 0x3D: "mtur", 0xF9: "bcopy"}.get(ops[pc], "other")] += n
    events.sort(key=lambda e: e[0])
    return {
        "name": name, "t0": t0, "events": events,
        "busy": s.c.cycles - s.c.idle_cycles - busy0,
        "entries": s.c.user_entries - ent0,
        "mfur": count["mfur"], "mtur": count["mtur"], "bcopy": count["bcopy"],
        "ms": (s.c.cycles - t0) / 6000,
    }


# ---- the replay -------------------------------------------------------------------


def replay(tr, user_banks):
    """The trace through user_banks banks shared by LRU (None: one each,
    as Fen has them). Counts over the workload: switches, misses (and of
    them, those that run a thread a message just came to), saves of all a
    bank's registers, and saves without r0-r7 (the victim is the thread
    whose message it is, so they're dead)."""
    lru = collections.OrderedDict()     # thread -> None, the least recent first
    ident, gen = {}, collections.Counter()
    live, max_live = set(), 0
    c = collections.Counter()
    last_run = None
    msg_from = None                     # (the bank a message went to, the thread it came from)
    started = False
    for cyc, kind, b in tr["events"]:
        counting = cyc >= tr["t0"]
        if counting and not started:
            started, max_live = True, len(live)
        if kind == "start":
            gen[b] += 1
            t = ident[b] = (b, gen[b])
            live.add(t)
            if counting:
                max_live = max(max_live, len(live))
            if user_banks is None or len(lru) < user_banks:
                lru[t] = None           # a free bank: started in it, as Fen does
            continue
        if kind == "end":
            t = ident.get(b)
            live.discard(t)
            lru.pop(t, None)            # its bank is free, nothing saved
            continue
        if kind == "msg":
            msg_from = (b, last_run)
            continue
        t = ident.get(b, (b, 0))
        if counting:
            c["switches"] += 1
        ipc = msg_from is not None and msg_from[0] == b
        sender = msg_from[1] if ipc else None
        msg_from = None
        last_run = t
        if t in lru:
            lru.move_to_end(t)
            continue
        if counting:
            c["misses"] += 1
            c["ipc_misses"] += ipc
        if user_banks is not None and len(lru) >= user_banks:
            victim, _ = lru.popitem(last=False)
            if counting:
                c["saves10" if victim == sender else "saves18"] += 1
        lru[t] = None
    c["max_live"] = max_live
    c["threads"] = len({(b, g) for b in gen for g in range(1, gen[b] + 1)})
    return c


def extra_cycles(tr, banks, cost):
    """What a workload would take more with `banks` banks, by the model."""
    if banks == 1:
        # no banks: every entry from user mode saves and restores r0-r7,
        # HI and LO; every switch r8-r14; messages move memory to memory;
        # the user's registers are in a frame, not reached with MFUR/MTUR
        r = replay(tr, None)
        return (tr["entries"] * cost["entry"] + r["switches"] * cost["switch7"]
                + tr["bcopy"] * (cost["msgmem"] - cost["bcopy"])
                + (tr["mfur"] + tr["mtur"]) * (cost["load"] - cost["mfur"]))
    r = replay(tr, banks - 1)
    loads18 = r["misses"] - r["ipc_misses"]
    keep = BOOKKEEPING_ONE if banks == 2 else BOOKKEEPING
    return (r["saves18"] * cost["save18"] + r["saves10"] * cost["save10"]
            + loads18 * cost["load18"] + r["ipc_misses"] * cost["load10"]
            + r["misses"] * keep + r["switches"] * HIT)


# Estimates of what a kernel that shares banks does besides moving
# registers: on a miss, picking the victim and updating which thread has
# which bank (about 15 instructions; with one user bank, 4: there's no
# choosing); on every switch, marking the bank used, for the victim's
# choice (one store, as for a clock policy).
BOOKKEEPING = 50
BOOKKEEPING_ONE = 15
HIT = 5

# The hardware, as Emily costed it (2026-10-16): chips for the banks as the
# register file is built, and with one bank address shared by its ports.
CHIPS = {1: (0, 0), 2: (8, 7), 4: (11, 7), 8: (14, 8), 16: (16, 8), 32: (20, 11),
         64: (23, 12), 256: (29, 13), 1024: (37, 18)}


# ---- the tables -------------------------------------------------------------------


def report():
    cost = costs()
    traces = [trace(name, serial, fn) for name, _, serial, fn in WORKLOADS]
    ref = cost[None]
    lines = ["# Register banks: results", "",
             "Generated by `heron fen banks --write` (studies/fen/banks.py); what the",
             "numbers say is in [report 0037](../0037-report-register-banks.md).", "",
             "## What the operations cost", "",
             "Cycles, timed in a bare system-mode program on the simulator.", "",
             "| Operation | D16-overlap | D32-separate |", "|---|---:|---:|"]
    what = {
        "save18": "save a bank's 18 registers to memory (MFUR, STM)",
        "load18": "load a bank's 18 registers from memory (LDM, MTUR)",
        "save10": "save r8-r15, HI and LO",
        "load10": "load r8-r15, HI and LO",
        "bcopy": "BCOPY a message (r0-r7) between banks",
        "msgmem": "copy a message memory to memory (LDM, STM)",
        "entry": "no banks: save and restore r0-r7, HI and LO on the stack",
        "switch7": "no banks: save and restore r8-r14 on a switch",
        "mfur": "MFUR a user register",
        "load": "load a user register from a frame in memory",
    }
    for op, w in what.items():
        lines.append(f"| {w} | {cost[None][op]:.0f} | {cost['D32-separate'][op]:.0f} |")
    lines += ["", f"Besides moving registers, a kernel that shares banks would spend about "
              f"{BOOKKEEPING} cycles a miss", f"choosing the victim ({BOOKKEEPING_ONE} with one user "
              f"bank) and {HIT} a switch marking the bank used", "(estimates).", "",
              "## The workloads", "",
              "| Workload | What | busy cycles | threads | most live at once | switches | "
              "kernel entries | BCOPYs |", "|---|---|---:|---:|---:|---:|---:|---:|"]
    for (name, w, _, _), tr in zip(WORKLOADS, traces):
        r = replay(tr, None)
        lines.append(f"| {name} | {w} | {tr['busy']:,} | {r['threads']} | {r['max_live']} | "
                     f"{r['switches']:,} | {tr['entries']:,} | {tr['bcopy']:,} |")
    lines += ["", "## Misses", "",
              "Threads run without a bank of their own, over each workload (LRU; the",
              "supervisor has one of the banks).", "",
              "| Banks | " + " | ".join(n for n, *_ in WORKLOADS) + " |",
              "|---:|" + "---:|" * len(WORKLOADS)]
    for banks in BANKS[1:]:
        row = []
        for tr in traces:
            r = replay(tr, banks - 1)
            row.append(f"{r['misses']:,}")
        lines.append(f"| {banks} | " + " | ".join(row) + " |")
    lines += ["", "## What it would cost", "",
              "Extra cycles over each workload by the model, as a share of its busy",
              "cycles (D16-overlap), with the banks shared as a cache of the threads'",
              "registers; 1 is no banks at all. Fen as it is gives each thread a bank,",
              "which costs nothing while there are fewer threads than banks.", "",
              "| Banks | chips | shared address | threads, a bank each | "
              + " | ".join(n for n, *_ in WORKLOADS) + " |",
              "|---:|---:|---:|---:|" + "---:|" * len(WORKLOADS)]
    for banks in BANKS:
        row = []
        for tr in traces:
            x = extra_cycles(tr, banks, ref)
            row.append(f"{100 * x / tr['busy']:.1f}%")
        chips, shared = CHIPS[banks]
        limit = "–" if banks == 1 else f"{banks - 1:,}"
        lines.append(f"| {banks} | {chips} | {shared} | {limit} | " + " | ".join(row) + " |")
    lines += ["", "## Per IPC round trip", "",
              "The ipc workload's extra cycles per call and reply, on top of Fen's 734",
              "(D16-overlap; the workload includes starting kbench's server).", "",
              "| Banks | extra cycles |", "|---:|---:|"]
    ipc = traces[0]
    for banks in BANKS:
        lines.append(f"| {banks} | {extra_cycles(ipc, banks, ref) / 2000:.0f} |")
    lines += ["", "## A slower MFUR, MTUR or BCOPY", "",
              "If the banks shared one address, so that an instruction that reads one",
              "bank and writes another took a step more: the cycles one more cycle on",
              "each MFUR and MTUR would add, and eight more on each BCOPY, as a share of",
              "the workload.", "",
              "| Workload | MFURs | MTURs | BCOPYs | +1 on MFUR, MTUR | +8 on BCOPY |",
              "|---|---:|---:|---:|---:|---:|"]
    for tr in traces:
        a = 100 * (tr["mfur"] + tr["mtur"]) / tr["busy"]
        b = 100 * 8 * tr["bcopy"] / tr["busy"]
        lines.append(f"| {tr['name']} | {tr['mfur']:,} | {tr['mtur']:,} | {tr['bcopy']:,} | "
                     f"{a:.2f}% | {b:.2f}% |")
    lines.append("")
    return "\n".join(lines), cost, traces


def main(write=False):
    text, _, _ = report()
    print(text)
    if write:
        os.makedirs(REPORT, exist_ok=True)
        path = os.path.join(REPORT, "results.md")
        with open(path, "w") as f:
            f.write(text)
        print(f"wrote {os.path.relpath(path, ROOT)}")
    return 0
