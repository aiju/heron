---
status: active
depends-on: [v1_isa, v1b_hw, v1b_tradeoffs, c_compiler, egret, graphics, lisp, kernel]
reports: [30]
---

# CALL with a link register

Should draft 2's `CALL` leave the return address in a register (r7)
instead of pushing it? This study makes that machine, v1bl, out of
draft 1b, ports the software to it, and measures it against 1b on the 1b
hardware and in draft 1's timing model. The findings are
[report 0030](../../reports/0030-report-link-register.md).

**v1bl** is draft 1b with three changes, and the encoding unchanged:

- `BSR` and `CALL`, every form, put the return address in r7 instead of
  pushing it;
- `RET` jumps to r7 (`JMP r7` does the same);
- `JMP [sp]+` is the return that pops, for a routine that pushed r7.

Interrupts and traps still push the PC and the flags. r7 is the last of
the caller-saved registers, next to r8–r14, so a routine that saves
registers saves the return address in the same `SAVE r7-rN`.

| File | What's in it |
|---|---|
| `v1bl.py` | The ISA module; the simulator is Rust (`Isa::V1bl` in studies/v1_isa/isa), and so is the encoder, 1b's under its own name |
| `programs/` | The 20 programs of the suite by hand, ported from studies/v1_isa/programs/v1b, with their library |
| `egret.py`, `vm/` | Egret's VM for v1bl: its start code, its assembly interpreter and its JIT (studies/egret/vm/jit.c has the JIT's changes under `__V1BL__`) |
| `graphics.py` | The graphics library's 1b kernels, edited for v1bl as they're built |
| `hw.py` | Cycles on the 1b hardware for runs too long for its RTL model: calls, returns, jumps, `SAVE` and `RESTORE` from the microcode, the rest from the calibrated model |
| `estimate.py` | What v1bl would do to a 1b run, from a shadow stack of its calls, for software that isn't ported |
| `lisp.py`, `kernel.py` | The Lisp and the kernel study's nucleus under the estimator |
| `gui.py` | The Egret desktop and Egretica (studies/egret_gui, pull request 35) on both, when that study is there |
| `measure.py` | Every workload on both ISAs, cached in build/link_register/ |
| `report.py` | The report's generated tables, [results.md](../../reports/0030-report-link-register/results.md) |

Elsewhere, with the study's name in the comments:

- studies/v1b_hw/ucode.py builds v1bl's microcode with `built(link=True)`:
  a `BSR` takes 3 cycles instead of 5, `RET` 2 instead of 5.
- The C compiler has a v1bl backend (`codegen.v1b.V1BL`): it saves r7
  like a callee-saved register, in the prologue's `SAVE r7-rN` or with a
  push, in a function that calls or needs the register; a leaf returns
  through r7. `driver.MIN_DATA_ALIGN` aligns data so that a comparison
  isn't moved by the code before it.

```sh
heron link_register test                  # the ported suite on v1bl
heron link_register run studies/link_register/programs/fib.s --stats   # a program (--isa v1b for 1b's)
heron link_register cc studies/c_compiler/programs/fib.c --run   # C for v1bl
heron link_register report [--write]      # the report's tables (half an hour the first time)
heron test link_register                  # the unit tests
```
