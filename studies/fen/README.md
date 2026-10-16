---
status: active
depends-on: [v2_isa, c_compiler, graphics]
reports: []
---

# Fen: an operating system for draft 2

Fen is an operating system for Heron's draft 2 in system mode
([RFC 0029](../../reports/0029-rfc-draft-2-system.md)), built to get
something working and to battle-test the system half of the instruction
set: modes, register banks, the window and the page map, precise faults,
vectored system calls and interrupts by level. It runs on the
instruction-level simulator, on a board of the study's own
([board/](board/)).

- **A message-passing kernel** in C and assembly, in the supervisor's
  window. Every thread has a register bank of its own and every process a
  context of the page map, so a thread switch saves nothing: it rewrites
  the trap frame and sets `bank` and `ctx`. Messages are 8 words in
  `r0`–`r7`, copied from bank to bank by `BCOPY` (a tentative instruction
  for RFC 0029's open question 3); bulk data is copied straight between
  address spaces through the window.
- **Servers in user space**, drivers included: the file server drives the
  CompactFlash card, the console server the UART, with their pages of the
  I/O card mapped into them and their interrupts as notifications.
- **A C library** with descriptors over one file protocol, stdio, a heap
  and `spawn` (there's no `fork`); **a shell** with pipelines,
  redirections, lists and background jobs; and the usual small utilities.

| Folder | What's in it |
|---|---|
| `board/` | The machine, in Rust: draft 2 in system mode, RAM, the timer, the video card, the I/O card (UART, CF card, PS/2, clock), the interrupt mask. Python uses it as `heron.native.fen` |
| `kernel/` | The kernel |
| `include/`, `lib/` | The headers and the C library |
| `srv/fs/`, `srv/cons/` | The file server and the serial console |
| `cmd/` | init, the shell, the utilities, and the kernel's test (`ktest`) |
| `syscalls.py` | The system calls' table, from which the build writes their stubs |
| `build.py`, `mkfs.py` | Building everything; the file system image |
| `run.py`, `cli.py` | Running it; the command line |

```sh
heron fen build                 # the kernel, the programs, the boot image and a disk, in build/fen
heron fen console               # the serial console in this terminal (Ctrl-] quits)
heron fen run 'ls /bin' 'ps'    # boot, run command lines, print what they print
heron fen ktest                 # the kernel's own test
heron test fen                  # the unit tests
```
