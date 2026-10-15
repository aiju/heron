---
status: active
depends-on: [v1_isa, c_compiler, lisp, egret, graphics]
reports: [20]
---

# An operating system for Heron

What an operating system would want from Heron's hardware, and what kind
of operating system would suit it. The study measures the hot paths an
operating system has, on draft 1b with proposed system extensions, so
the proposals come with numbers. The findings, and the survey of what
the operating system could be, are
[report 0020](../../reports/0020-report-operating-system.md).

It depends on `v1_isa` for the ISA, the simulator (which it extends) and
the timing model; on `c_compiler` for one comparison; and on `lisp`,
`egret` and `graphics` for their programs, whose page references it
counts.

- **v1bs** ([report 0020's appendix](../../reports/0020-report-operating-system.md#appendix-v1bs-draft-1b-with-system-extensions)): draft 1b with a supervisor mode,
  register banks in the spare register-file SRAM (three policies), the
  flat page map of RFC 0010, loads and stores across modes, and precise
  page faults. It's an ISA variant of the draft 1 simulator
  ([sys.rs](../v1_isa/isa/src/sys.rs)), as the Lisp's v1bx is.
- **The benchmark nucleus** ([nucleus/nucleus.s](nucleus/nucleus.s)): a
  small message-passing kernel in 1b assembly, in the style of L4 and
  QNX, written once for each banking policy: threads in their own
  address spaces, system calls, synchronous calls with the message in
  registers, notifications, an io_uring-style ring, a timer that
  preempts, interrupts handed to a user-level driver, demand-zero pages
  and, optionally, the map as a cache refilled from page tables.
- **User programs** ([user/](user/)) that exercise it: null system
  calls, yields, a client and a server, page touching, a user-level
  console driver, and four ways to write to the console.
- **Small routines on plain 1a and 1b** ([micro/](micro/)): zeroing and
  copying a page, calls and globals the ways a dynamic linker wires them
  up, switching user-level threads, and the ready queue in C against
  assembly.
- **Page statistics** ([pages.py](pages.py)): how many pages the other
  studies' bigger programs touch, and how often translation caches of
  each size would miss (the simulator's page counters,
  [pages.rs](../v1_isa/isa/src/pages.rs)).

| File | What's in it |
|---|---|
| `system.md` | v1bs, the system extensions as simulated |
| `v1bs.py` | v1bs's disassembler (the decoder, simulator and encoder are Rust, in `v1_isa`) |
| `nucleus/nucleus.s` | the nucleus, with `.if none`, `.if half`, `.if full` and `.if softtlb` blocks |
| `user/*.s`, `user/sys.inc` | the user programs, and the system calls and address space they see |
| `build.py` | assembling the nucleus's variants and the programs, and a boot image of both |
| `bench.py` | the nucleus's scenarios: cycles per operation and by routine |
| `micro.py`, `micro/` | the small routines |
| `pages.py` | page statistics of the bigger programs |
| `report.py` | report 0020's tables |

```sh
heron kernel run hello hello null:10 --banks half --stats   # boot the nucleus with three processes
heron kernel run conserver wipc:5:16 --io 1 --shared 1 --shared 2   # a user-level driver and its client
heron kernel bench [ipc yield ...] [--banks full]   # the hot paths, by routine
heron kernel micro                # page zero and copy, linkage, coroutines on 1a and 1b
heron kernel pages                # the other studies' programs' page references (about 30 s)
heron kernel report [--write]     # report 0020's tables (--write: its performance.md)
heron test kernel                 # the unit tests
```

## How the measurements work

- **Every scenario runs twice,** with n and 2n iterations, on the
  instruction-level simulator. The difference over n is one operation,
  with booting and ending cancelled out. Cycles come from the draft 1
  timing model, for D32-separate (the configuration of the draft 1b
  hardware) unless a table says otherwise.
- **By routine:** each executed instruction's cycles go to the nucleus
  symbol it is in, or to the user program; taking a trap or an interrupt
  goes to "(trap entry)". Scenarios that only keep the nucleus busy
  (preemption, interrupts to a driver, refills) count only the nucleus's
  cycles.
- **The nucleus is written for speed but not tuned to the last cycle,**
  and the same way in each variant except where the policy changes what
  has to be saved and where results go.
- **Checked:** the write scenarios compare the console output with what
  they should print, the client checks every reply, and no thread may
  end by a fault.
