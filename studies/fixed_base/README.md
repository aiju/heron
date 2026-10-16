---
status: active
depends-on: [v1_isa, egret, lisp, kernel, c_compiler]
reports: [28]
---

# A fixed-base mode for struct fields

Draft 2 might have a second fixed-base slot shaped like `[sp + 4R]`:
`[rT + 4R]`, the word at a register set aside by convention plus 4 × the
mode's register field, in one parcel, so that 16 fields of one struct
are as cheap as stack slots
([RFC 0028, 10.1](../../reports/0028-rfc-draft-2-isa.md#101-short-offsets)).
This study measures what it would save Egret, the Lisp and the kernel
study's nucleus, on draft 1b with the mode added. The findings are in
RFC 0028's folder,
[fixed-base-mode.md](../../reports/0028-rfc-draft-2-isa/fixed-base-mode.md);
draft 2 took the mode as mode E with `r14`.

**The mode on 1b.** Draft 1b reserves mode E. In the ISAs `v1b+rtN`,
`v1bx+rtN` and `v1bs+rtN` it is the word at `rN + 4R`, any of rN's 16
fields at 0–60. Every instruction that takes a memory mode takes it:
`MOV`, `ST`, `LEA`, the ALU operations, `JMP` and `CALL` through memory.
The register is part of the ISA's name, so each piece of software can be
measured with the register it already keeps a struct in. In `v1bx+rtN`
the Lisp's tagged register operations, which were mode E, are op F's
functions 9–E instead, as draft 2 would put them elsewhere too.

- The simulator decodes it (`studies/v1_isa/isa`, `Isa::parse`), and the
  timing model costs it as `[sp + 4R]`: a `[R + d16]` access one parcel
  shorter.
- The assembler picks it for `[rN + 0..60]` words, as it picks `[sp + 4R]`
  (`studies/v1_isa/isa/src/asm/mod.rs`, `WithRt`). Its objects are named
  for the base ISA, so they link with 1b's.
- Egret's JIT emits it when the VM is built with `EGRET_RT=N`
  (`studies/egret/vm/jit.c`).
- `isa()` (`__init__.py`) registers the Python side of such an ISA.

| File | What's in it |
|---|---|
| `__init__.py` | The `+rtN` ISAs for the tools: disassembly, registration |
| `scan.py` | What one-parcel forms of field accesses would save, from a baseline run's counts |
| `experiments.py` | Egret and the nucleus run with the mode; the Lisp's estimate |
| `report.py` | The findings' tables |

```sh
heron fixed_base scan egret [--variant asm|c|jit] [NAME...]   # by base register: what rT there would save
heron fixed_base scan lisp [NAME...]
heron fixed_base scan kernel [SCENARIO...]
heron fixed_base report [--write]     # the findings' tables (about 15 minutes; --write: fixed-base-mode-results.md)
heron test fixed_base                 # the unit tests
cargo test -p v1-isa --test rt        # the simulator's and the assembler's side
```

## How it measures

- **Running it:** Egret's VM and the nucleus are assembled with the mode
  and run, and checked: every Egret program prints what it should, and
  the nucleus's scenarios check their own output. Nothing in their code
  changes, so rT is a register the code already keeps a struct in:
  Egret's frame record (`r11`) or its slots (`r9`), the nucleus's other
  thread (`r6`) or current thread (`r8`, `r14`).
- **Scanning it:** the simulator counts executions per instruction, so one
  baseline run says what any choice of rT would save: every executed word
  access `[R + 4..60]` with R as rT, costed by the timing model one parcel
  shorter. The same scan prices the other short forms RFC 0028 lists:
  `MOV`/`ST [R + 4k]` with any base. Where both were done, the run saves
  what the scan says on D32-separate, or a little more: shorter code
  brings some branches into reach of the one-parcel `Bcc`.
- **Egret's programs** are counted as in report 0017: a program's run
  less a `#!check` run of it (start-up and compiling it).
- **The nucleus** is counted per operation, as in report 0020; the scans
  count the nucleus's own instructions only.
- **The Lisp** keeps no struct in a register, and its pointers are
  tagged, so its fields are at 4k ± 1. What it would gain by keeping the
  current closure in rT is an estimate from its compiled code
  (`experiments.lisp`).
- Cycles are the timing model's for D32-separate (the 1b hardware) and
  D32-wide (the likely draft 2 hardware), with Egret's averaged over the
  two code alignments as report 0017 does. The nucleus's D32-wide cycles
  move by up to ±10% with code alignment alone, so its tables give
  D32-separate.
