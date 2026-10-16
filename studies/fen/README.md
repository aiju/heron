---
status: active
depends-on: [v2_isa, c_compiler, graphics]
reports: [0036]
---

# Fen: an operating system for draft 2

Fen is an operating system for Heron's draft 2 in system mode
([RFC 0029](../../reports/0029-rfc-draft-2-system.md)), built to get
something working and to battle-test the system half of the instruction
set: modes, register banks, the window and the page map, precise faults,
vectored system calls and interrupts by level. It runs on the
instruction-level simulator, on a board of the study's own
([board/](board/)). What it found is in
[report 0036](../../reports/0036-report-fen.md).

- **A message-passing kernel** in C and assembly, in the supervisor's
  window. Every thread has a register bank of its own and every process a
  context of the page map, so a thread switch saves nothing: it rewrites
  the trap frame and sets `bank` and `ctx`. Messages are 8 words in
  `r0`–`r7`, copied from bank to bank by `BCOPY` (a tentative instruction
  for RFC 0029's open question 3); bulk data is copied straight between
  address spaces through the window. A call to a waiting server and a
  reply to a waiting client switch straight from one thread to the other,
  in assembly (`kernel/fastipc.s`, its offsets generated from
  `kernel/offsets.c`).
- **Servers in user space**, drivers included: the file server drives the
  CompactFlash card, the console server the UART, the window system the
  video card, the keyboard and the mouse, each with its pages of the I/O
  card mapped into it and its interrupt as a notification.
- **A C library** with descriptors over one file protocol, stdio, a heap
  and `spawn` (there's no `fork`); **a shell** with pipelines,
  redirections, lists and background jobs; and the usual small utilities.
- **A desktop:** the window system (the Egret desktop's window manager
  over the graphics study's library), a terminal that is the file server
  of the shell it runs, and a clock.

| Folder | What's in it |
|---|---|
| `board/` | The machine, in Rust: draft 2 in system mode, RAM, the timer, the video card, the I/O card (UART, CF card, PS/2, clock), the interrupt mask. Python uses it as `heron.native.fen` |
| `kernel/` | The kernel |
| `include/`, `lib/` | The headers, the C library and the window system's client library (`gui.c`) |
| `srv/fs/`, `srv/cons/`, `srv/wsys/` | The file server, the serial console and the window system (with its fill and blit kernels in draft 2's assembly) |
| `cmd/` | init, the shell, the terminal, the clock, the utilities, the kernel's test (`ktest`) and its benchmark (`kbench`) |
| `syscalls.py` | The system calls' table, from which the build writes their stubs |
| `build.py`, `mkfs.py` | Building everything; the file system image |
| `run.py`, `cli.py` | Running it, with the keyboard, the mouse and the screen; the command line |
| `profile.py`, `bench.py` | Cycles by process and function; the measurements in report 0036 |
| `banks.py` | What fewer register banks would cost: traces of the threads that run, replayed through fewer banks ([RFC 0029's register-banks.md](../../reports/0029-rfc-draft-2-system/register-banks.md)) |
| `irq.py` | How long the kernel holds interrupts off, what holds them off and how often interrupts come, traced an instruction at a time ([RFC 0040's fen-latency.md](../../reports/0040-rfc-interrupts/fen-latency.md)) |

```sh
heron fen build                 # the kernel, the programs, the boot image and a disk, in build/fen
heron fen console               # the serial console in this terminal (Ctrl-] quits)
heron fen run 'ls /bin' 'ps'    # boot, run command lines, print what they print
heron fen shot menu:1 'click:300,300' 'type:ls\n' -o screen.png
                                # boot the desktop, do things, save the screen
heron fen ktest                 # the kernel's own test
heron fen bench [--write]       # the measurements (report 0036's performance.md)
heron fen banks [--write]       # fewer register banks (RFC 0029's register-banks-results.md)
heron fen irq [--write]         # interrupts held off (RFC 0040's fen-latency-results.md)
heron test fen                  # the unit tests
```

The desktop boots when the host leaves the boot flags' bit 0 clear
(`Session(serial=False)` in run.py): init starts the window system, which
starts a terminal. Clicking on the desktop opens a menu of the programs
in `/etc/menu`; a window moves by its title bar, grows by its bottom
right corner and closes by its box.
