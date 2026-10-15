---
number: 30
type: report
title: CALL with a link register, measured on draft 1b
status: draft
date: 2026-10-15
context:
  studies: [link_register, v1_isa, v1b_hw, c_compiler, egret, graphics, lisp, kernel]
  commit: 9012aff
---

# Report 0030: CALL with a link register, measured on draft 1b

Should draft 2's `CALL` leave the return address in a register instead of
pushing it ([RFC 0006, 5](0006-rfc-ideas-isa.md#5-more-instruction-ideas),
reopened by Emily on 2026-10-15)? This report builds that machine out of
draft 1b, ports the software to it, and measures the two against each
other on the 1b hardware's microcode and in draft 1's timing model. The
work is [studies/link_register](../studies/link_register/README.md); the
generated tables are [results.md](0030-report-link-register/results.md).

The link register is r7, the last caller-saved register, next to r8–r14.
The variant, **v1bl**, is draft 1b with three changes and the same
encoding:

- `BSR` and `CALL`, every form, put the return address in r7;
- `RET` jumps to r7;
- `JMP [sp]+`, which 1b already has, is the return that pops.

Interrupts and traps still push the PC and the flags.

## Summary

- **On the 1b hardware it is a small gain nearly everywhere.** The worst
  measured case is +0.24% (bst in C), the worst estimated +1.0% (the
  Lisp's compiled fib). Change in cycles, v1bl against 1b:

  | Workload | How | Mean | Range |
  |---|---|---:|---|
  | The suite by hand, 18 programs | ported; RTL model, exact | −2.3% | −6.9% to 0 |
  | The C versions, 14 programs with their library | compiler backend; RTL model, exact | −0.2% | −0.9% to +0.2% |
  | Egret, its C interpreter | ported | −0.2% | −0.7% to 0 |
  | Egret, its assembly interpreter | ported | −0.2% | −0.8% to +0.1% |
  | Egret, its JIT | ported | −0.9% | −2.3% to +0.2% |
  | Graphics, 12 scenes and depths | ported (C, and the assembly kernels) | −0.2% / −0.3% | −0.8% to +0.2% |
  | The Egret desktop and Egretica (PR 35) | ported | −0.2% to −0.9% | one action +1.8%, with more work done |
  | The Lisp, 13 programs | estimated | −1.3% interpreted, −0.9% compiled | −2.5% to +1.0% |
  | The nucleus's paths | estimated | 0 for most | −3.0% to 0 |

  Means are geometric. The suites are exact; the long runs use the
  microcode's cycles for calls, returns and `SAVE`, which track the RTL
  model's change to within 0.3 points (section 2). The estimates are of
  software not ported.
- **A leaf call gains, the rest break even.** A `BSR` and its `RET` take 10
  cycles on the 1b hardware and 5 with the link register. A callee that
  saves registers adds r7 to its `SAVE` and breaks even; one that calls
  and saves nothing pays 2 cycles and a parcel for a push.
- **Compiled C gains least,** because most of its calls go to functions
  that call: the compiler saves r7 in every function that might, as it
  doesn't shrink-wrap. With the save only on the paths that call, the
  estimator puts wordfreq at −3.7% instead of −0.9%.
- **It costs no hardware.** The link microcode is 74 microinstructions
  shorter (3,433 against 3,507); r7 is written through the register file's
  constant address, as `sp` is.
- **The cost is in the software,** and it was small in everything ported:
  - every routine that calls saves r7, usually by widening its `SAVE r8-rN`
    to `SAVE r7-rN`;
  - a leaf that uses r7 renames it, or saves it like a callee-saved
    register;
  - a trap handler that calls saves it;
  - code that keeps r7 across a call moves it (Egret's JIT, one graphics
    kernel);
  - the Lisp's calling convention, which passes argument 5 in r7, would
    have to change.

  Porting the 20 programs and their library added 149 lines and removed
  122, comments included, of 3,607.
- **It matters less with a 32-bit bus.** In draft 1's timing model, which
  costs a push a cycle less than the 1b microcode does, the suite by hand
  gains 1.0–1.5% with a 16-bit bus and 0.2–0.3% with the wide fetch, and
  compiled C loses 0.1–0.4% (section 6).

## 1. What was built

- **The simulator** (studies/v1_isa/isa): `Isa::V1bl`, with timing kinds
  for calls that link (`link`, `linkm`). The encoder is 1b's under its own
  name, so 1b and v1bl object files don't link together.
- **The microcode** (studies/v1b_hw/ucode.py, `built(link=True)`): the RTL
  model runs it, and agrees with the instruction-level simulator on every
  call mode. A call puts the PC in R, loads the new PC, and writes R to r7
  in the fetch cycle. A call through memory takes the return address while
  the target's high half is read. A `RET` loads the PC from r7. One routine
  had to change: in `CALL [R]+` the base's write-back bridges the B bus
  onto the A bus, so the return address can't be taken in that cycle (the
  RTL model reported the contention).
- **The C compiler** (`codegen.v1b.V1BL`):
  - r7 is treated like a callee-saved register. A function that calls, or
    whose allocation needs r7, saves it: in its `SAVE r7-rN`, or with
    `PUSH r7` and a return by `JMP [sp]+` if it saves nothing else.
  - A leaf returns through r7.
  - Tail calls are decided before the frame is laid out, so a function
    whose only calls are tail calls is a leaf.
  - In both builds, data is aligned to 4 for the comparison
    (`driver.MIN_DATA_ALIGN`). Otherwise six bytes more code moved sieve's
    `char` array onto a word boundary, and `memset` went 4 times as fast
    for reasons that have nothing to do with calls.
- **The suite by hand,** ported as a programmer would write it for v1bl:
  - a routine that calls saves r7 with its other registers;
  - fib saves r7 only on its recursive path, so fib(0) and fib(1) return
    through it;
  - lines.s's `plot4` keeps the return address in a free register;
  - leaves that used r7 for data use another register (crc, rpn, the
    string library) or save it (isort, sha256's block).
- **Egret:**
  - its start code: `setjmp` stores r7 and `longjmp` reloads it;
  - its assembly interpreter: one change, since sends don't use `CALL`;
  - its JIT, under `__V1BL__` in jit.c: a method's prologue stores r7
    into the frame instead of popping the return address, the stubs that
    call C keep r7 on the stack meanwhile, and a send through the method
    cache passes its bytecode in r5 instead of r7.
- **Graphics:** the 1b kernels edited as they're built. Five save r7 with
  the registers they already save. `expand.s` uses every register and calls
  its emit routines with the depth's table in r7, so the table moves to
  its frame, and the emit routines that need it push r7 and load it.
- **The desktop and Egretica** (studies/egret_gui, in
  [pull request 35](https://github.com/aiju/heron/pull/35)): built from the
  pieces above. They were measured on that branch with this one's commits
  applied: `gui.py` runs when the study is there. After Egretica's eight
  lines both ISAs leave the same screen, bit for bit.
- **For the rest, an estimator** (section 2): the Lisp and the kernel
  study's nucleus aren't ported.

Every ported program gives its expected output on v1bl: the 20 programs,
the 15 C programs, Egret's 18 on all three builds, and the 12 graphics
scenes with either kernels, which match the host's screens.

## 2. What a call costs, and the estimator

On the 1b hardware, in cycles, the next instruction's fetch included:

| | 1b | v1bl |
|---|---:|---:|
| `BSR` | 5 | 3 |
| `CALL label`, `CALL #label` | 5, 7 | 4, 5 |
| `CALL r9` | 5 | 3 |
| `CALL [r9 + 8]` | 9 | 6 |
| `RET` | 5 | 2 |
| `PUSH r7`; `JMP [sp]+` | | 4; 5 |
| one register more in `SAVE` and `RESTORE` | | 3 + 2 |

So a `BSR` and its return:

| The callee | Change |
|---|---:|
| is a leaf | −5 |
| saves r8–rN: r7 joins the `SAVE` and the `RESTORE` | 0 |
| calls but saves nothing: `PUSH r7` and `JMP [sp]+` | +2 |

A push costs two bus cycles on the 16-bit bus, and so does the pop:
those are what the link register saves.

**Long runs** (Egret, graphics, the desktop) are too long for the RTL
model, at about 100,000 cycles a second. They are costed from their timing
keys instead (hw.py): calls, returns, jumps, `SAVE`, `RESTORE`, pushes
and pops at their microcode routine's cycles, the rest by the timing
model calibrated on the 1b hardware
([RFC 0024](0024-rfc-faster-smaller.md)). On the suites, where both can
run, its change agrees with the RTL model's to within 0.3 points on every
program: −2.23% against −2.28% for the suite by hand, −0.21% against
−0.20% for the C versions.

**The estimator** (estimate.py) puts this to a 1b run without porting
anything:

- it follows each call on a shadow stack, and sorts it by what its callee
  did: a leaf, a callee whose register save r7 can join, or one that would
  push it;
- it adds up the costs above;
- a `SAVE` before any call keeps r7 company, as the ports do;
- an early return before any call counts as a leaf, as fib's port is
  written.

Against the ports it comes within 0.3 points on every program of the
suite by hand, and exactly on most. On compiled C it is exact for 13 of
15. The two it misses call only on a rare path (wordfreq's `before`,
and a function in bst), where the compiler saves r7 every time and the
estimator saves it only when needed. That is the shrink-wrapping a
compiler could add. For Egret's interpreters it is 0.1–0.3 points
optimistic. It can't follow a JIT, whose prologues take the return
address off the stack, which is why the JIT is ported.

## 3. Where it gains, and why

Calls are the whole effect. How many there are, and how many go to
leaves, decides it:

- **Hand-written code calls leaves.** Of the suite's calls, most go to
  library routines that call nothing: `putc`, `puts`, `print_u32`,
  `strcmp`, `rand`. The programs that call most gain most: monitor
  −6.9%, bst −4.5%, lines −4.1%, fib −4.0%.
- **Compiled C calls functions that call.** fib and queens, recursive,
  break even (+0.0%, +0.1%): their functions save registers, and r7
  joins them.
- **Egret's interpreters hardly call.** A send in either interpreter is
  frames in memory and a `JMP`; `CALL` is only for C primitives and the
  allocator, 1–24 per 1,000 instructions. Their −0.2% is the VM's C.
- **Egret's JIT calls on every send,** and its prologue stored the return
  address in the frame anyway. With the link register it stores r7, so
  the pop goes as well as the push: −0.9% on average, −2.3% for Richards,
  against report 0017's estimate of 0.7% and 2.6%.
- **The desktop** is Egret's assembly interpreter, the graphics library
  and its C: −0.2% to −0.9% per action, −0.55% to boot (compiling the
  desktop's Egret source). Opening the menu is the exception, at +1.8%.
  There v1bl ran 1.5% more instructions in the same time: the desktop did
  more work, not the same work slower.
- **The Lisp** calls through `CALL [r1 + 1]` for every call and its runtime
  in leaves. Interpreted, it is −1.0% to −1.6%. Compiled, fib and tak,
  whose calls are almost all to functions that call, lose (+1.0%,
  +0.7%), and the rest gain up to 2.5% (sort). That assumes a port that
  saves r7 in each frame as it is built.
- **The nucleus** inlines its fast paths: a system call, an IPC and the
  console writes make no calls at all. A yield or a preemption makes one,
  to the ready queue: −2% to −3% of them.

The full tables are in [results.md](0030-report-link-register/results.md).

## 4. The desktop and Egretica

On the 1b hardware, an action's cycles less what the idle loop would have
spent meanwhile, as studies/egret_gui/bench.py measures them:

| What | 1b | v1bl | Change |
|---|---:|---:|---:|
| Boot: start the VM, the splash, the prelude | 11,079,955 | 11,024,306 | −0.50% |
| Boot: to ready, compiling the desktop | 174,079,419 | 173,120,886 | −0.55% |
| Workspace: type a character | 62,063 | 61,889 | −0.28% |
| Workspace: Return, with the lines below redrawn | 549,013 | 546,737 | −0.41% |
| Workspace: print `2 ** 100` | 232,735 | 230,707 | −0.87% |
| Windows: open the menu and close it | 595,819 | 606,777 | +1.84% |
| Windows: drag the Workspace | 810,958 | 810,976 | +0.00% |
| Windows: raise the Transcript | 633,910 | 631,246 | −0.42% |
| Open: Transcript | 358,005 | 356,249 | −0.49% |
| Open: Browser | 2,680,212 | 2,670,915 | −0.35% |
| Open: Egretica | 1,305,175 | 1,301,360 | −0.29% |
| Open: About | 6,080,323 | 6,029,979 | −0.83% |
| Egretica: `D[x^2 Sin[x], x]` | 2,215,697 | 2,212,315 | −0.15% |
| Egretica: `Integrate[x^2 Exp[x], x]` | 5,930,853 | 5,910,675 | −0.34% |
| Egretica: `Integrate[1/(x^3 + 1), x]` | 8,857,133 | 8,836,491 | −0.23% |
| Egretica: `Solve[x^3 - 6 x^2 + 11 x - 6 == 0, x]` | 5,062,466 | 5,054,492 | −0.16% |
| Egretica: `Factor[x^6 - 1]` | 4,962,885 | 4,951,456 | −0.23% |
| Egretica: `Series[Tan[x], {x, 0, 7}]` | 15,605,413 | 15,555,709 | −0.32% |
| Egretica: `N[Pi, 50]` | 2,860,537 | 2,841,660 | −0.66% |
| Egretica: `Plot[{Sin[x], Cos[x]}, {x, 0, 2 Pi}]` | 13,871,973 | 13,851,767 | −0.15% |
| Gadgets: a frame, on average over 20 s | 107,875 | 107,160 | −0.66% |

These were measured with the desktop at
[71eb7db](https://github.com/aiju/heron/commit/71eb7db), PR 35's head,
and this branch's commits applied; they aren't in results.md, which is
made from main.

## 5. What it costs besides cycles

- **Every routine that calls has to save r7,** in hand-written code too.
  - Widening `SAVE r8-rN` to `SAVE r7-rN` covers most of them, as r7 sits
    just below the callee-saved registers. A range does it, and
    [RFC 0006](0006-rfc-ideas-isa.md#5-more-instruction-ideas)'s "a range
    plus a bit" for `LDM`/`STM` isn't needed.
  - Forgetting it is a bug that shows on the first return: the one
    mistake in porting the suite was a `RESTORE` left at r8 (sort's
    `fill`), and the program crashed at once.
- **Leaves lose a free register.** One that needs all seven scratch
  registers saves r7, like a callee-saved one. The compiler does this
  itself: sha256's block function would otherwise have spilled in its
  loop (7% more cycles in the timing model before the compiler did).
- **Trap handlers that call must save r7,** since the call writes it.
  - The suite's `SWI` handler saves r1–r7 already.
  - The nucleus's page-fault handler saves r1–r6 in one variant and would
    need r7 too.
- **Conventions move:**
  - The Lisp passes arguments 1–6 in r3–r8, so argument 5 would move.
  - Egret's JIT passed a send's bytecode in r7 across a call; it moved
    to r5.
  - `expand.s` kept its table in r7 across a call.
- **Some things get simpler:**
  - `setjmp` and `longjmp` keep r7 instead of reading and writing the
    stack;
  - a JIT's prologue stores the return address where it wants it;
  - a coroutine switch can start a thread with its entry point in r7.
- **Debugging:** a leaf's return address is in r7, not on the stack, so
  a backtrace from a trap has to know whether the routine saved it. The
  trap frame has the registers, so it can.
- **Code size** barely changes: +44 bytes over the suite by hand, 26 of
  them monitor's pushes, and 0–6 bytes for each C version. `SAVE r7-rN` is
  the same parcel as `SAVE r8-rN`.

## 6. Other microarchitectures

The six configurations of draft 1's timing model put the same runs on a
16-bit or 32-bit datapath, with a separate, overlapped or wide fetch.
Its call costs a cycle less than the 1b microcode, and a register in
`SAVE` a cycle less too, so the push it saves is cheaper:

| Workload | 1b hardware | D16-overlap | D32-overlap | D32-wide |
|---|---:|---:|---:|---:|
| The suite by hand | −2.28% | −1.16% | −1.47% | −0.31% |
| The C versions | −0.20% | +0.12% | +0.13% | +0.40% |

With the wide fetch (a 32-bit bus with a prefetch buffer, recommended
in [RFC 0007](0007-rfc-ideas-microarchitecture.md#1-datapath-and-fetch))
a push is one bus cycle, and the link register is worth about nothing for
hand-written code and a little less than nothing for compiled C. Every
workload's means in all six are in results.md.

## 7. For draft 2

If draft 2 takes the link register:

- **The encoding doesn't change:** `CALL ea` (`F1`) and `BSR` (`B` row,
  condition F) keep their cells, and only what they do changes.
- **`RET` becomes `JMP r7`,** already a one-parcel `JMP ea`, so `FD 00`
  could go back to the free list, with `RET` an assembler alias. `JMP [sp]+`
  is the return that pops.
- **r7 stays caller-saved** in the C convention: every call writes it.
- **The compiler should shrink-wrap the save of r7,** for the functions
  that call on rare paths (wordfreq's −0.9% would be −3.7%).
- **Orthogonal, not measured:** a `RESTORE` that also returns would save
  the `JMP r7` after `RESTORE r7-rN`, and on 1b the `RET` after
  `RESTORE r8-rN`, as ARM's `POP {..., pc}` does.

Whether to take it is Emily's decision. On a 16-bit memory path like the
1b hardware's it is a free, small gain, largest in hand-written code and
the JIT. With the wide fetch it is about even. In either case the cost is
the conventions above.

## 8. Reproducing it

```sh
heron link_register test                 # the ported suite on v1bl
heron link_register report --write       # results.md (half an hour, then cached)
heron test link_register                 # the unit tests
```

The desktop's table needs studies/egret_gui (PR 35): `gui.measure("v1b")`
and `gui.measure("v1bl")` in studies/link_register/gui.py, a few minutes
each.
