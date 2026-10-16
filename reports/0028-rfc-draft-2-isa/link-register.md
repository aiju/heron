# RFC 0028: the link register, measured on 1b

The measurements behind the link register of
[RFC 0028](../0028-rfc-draft-2-isa.md#95-calls-multiple-registers-and-rows-0-and-f)
(**decided**, Emily, 2026-10-15): every call writes its return address
into r7 and pushes nothing ([5.7](../0028-rfc-draft-2-isa.md#57-jumps-and-calls)).
They were made on draft 1b, before draft 2 existed. **v1bl** is 1b with
three changes and the same encoding:

- `BSR` and `CALL`, every form, put the return address in r7;
- `RET` jumps to r7;
- `JMP [sp]+`, which 1b already has, is the return that pops.

Interrupts and traps still push the PC and the flags. The software was
ported to v1bl and both were measured on the 1b hardware's microcode and
in draft 1's timing model.

The code is `studies/link_register`, in
[pull request 39](https://github.com/aiju/heron/pull/39), which was closed
without merging: draft 2 already has what of it carries forward. It stays
at
[bee497d](https://github.com/aiju/heron/tree/bee497d10460bd2f97bac0e1a81b6de895e8fd77/studies/link_register),
and the tables here are a snapshot of its `heron link_register report`
there.

## Summary

- **On the 1b hardware it is a small gain nearly everywhere.** The worst
  measured case is +0.24% (bst in C); the worst estimated is +1.0% (the
  Lisp's compiled fib). Change in cycles, v1bl against 1b:

  | Workload | How | Mean | Range |
  |---|---|---:|---|
  | The suite by hand, 18 programs | ported; RTL model, exact | −2.3% | −6.9% to 0 |
  | The C versions, 14 programs with their library | compiler backend; RTL model, exact | −0.2% | −0.9% to +0.2% |
  | Egret, its C interpreter | ported | −0.2% | −0.7% to 0 |
  | Egret, its assembly interpreter | ported | −0.2% | −0.8% to +0.1% |
  | Egret, its JIT | ported | −0.9% | −2.3% to +0.2% |
  | Graphics, 12 scenes and depths | ported (C, and the assembly kernels) | −0.2% / −0.3% | −0.8% to +0.2% |
  | The Egret desktop and Egretica (pull request 35) | ported | −0.2% to −0.9% per action | one action +1.8%, with more work done |
  | The Lisp, 13 programs | estimated | −1.3% interpreted, −0.9% compiled | −2.5% to +1.0% |
  | The nucleus's paths | estimated | 0 for most | −3.0% to 0 |

  Means are geometric. The suites are exact. The long runs use the
  microcode's cycles for calls, returns and `SAVE`, which track the RTL
  model's change to within 0.3 points ([2](#2-what-a-call-costs)). The
  estimates are of software that wasn't ported ([3](#3-the-estimator)).
- **A leaf call gains, the rest break even.** On the 1b hardware a `BSR`
  and its `RET` take 10 cycles with a push and 5 with the link register. A
  callee that saves registers adds r7 to its `SAVE` and breaks even. One
  that calls and saves nothing pays 2 cycles and a parcel for a push.
- **Compiled C gains least,** because most of its calls go to functions
  that call. The compiler saves r7 in every function that might, as it
  doesn't shrink-wrap. With the save only on the paths that call, the
  estimator puts wordfreq at −3.7% instead of −0.9%.
- **It costs no hardware.** The link microcode is 74 microinstructions
  shorter (3,433 against 3,507). r7 is written through the register file's
  constant address, as `sp` is.
- **The cost is in the software,** and it was small in everything ported:
  - every routine that calls saves r7, usually by widening its `SAVE r8-rN`
    to `SAVE r7-rN`;
  - a leaf that uses r7 renames it, or saves it like a callee-saved
    register;
  - a trap handler that calls saves it;
  - code that keeps r7 across a call moves it (Egret's JIT, one graphics
    kernel);
  - the Lisp's calling convention, which passes argument 5 in r7, has to
    change ([report 0033](../0033-report-lisp-arguments-draft-2.md)).

  Porting the 20 programs and their library added 149 lines and removed
  122, comments included, of 3,607.
- **It matters less with a 32-bit bus.** With the wide fetch a push is
  one bus cycle that overlaps with the branch, so the link call is no
  faster, and r7's extra word in `SAVE` and `RESTORE` makes calls to
  non-leaf functions a cycle slower. In draft 1's timing model the suite
  by hand gains 0.2–0.3% there and compiled C loses 0.4%
  ([6](#6-other-microarchitectures)).

## 1. What was built

- **The simulator** (studies/v1_isa/isa): `Isa::V1bl`, with timing kinds
  for calls that link (`link`, `linkm`). The encoder is 1b's under its own
  name, so 1b and v1bl object files don't link together.
- **The microcode** (studies/v1b_hw/ucode.py, `built(link=True)`). The RTL
  model runs it, and agrees with the instruction-level simulator on every
  call mode.
  - A call puts the PC in R, loads the new PC, and writes R to r7 in the
    fetch cycle.
  - A call through memory takes the return address while the target's
    high half is read.
  - A `RET` loads the PC from r7.
  - One routine had to change: in `CALL [R]+` the base's write-back
    bridges the B bus onto the A bus, so the return address can't be
    taken in that cycle. The RTL model reported the contention.
- **The C compiler** (`codegen.v1b.V1BL`):
  - r7 is treated like a callee-saved register. A function that calls, or
    whose allocation needs r7, saves it: in its `SAVE r7-rN`, or with
    `PUSH r7` and a return by `JMP [sp]+` if it saves nothing else.
  - A leaf returns through r7.
  - Tail calls are decided before the frame is laid out, so a function
    whose only calls are tail calls is a leaf.
  - In both builds, data is aligned to 4 for the comparison. Otherwise six
    bytes more code moved sieve's `char` array onto a word boundary, and
    `memset` went 4 times as fast for reasons that have nothing to do with
    calls.
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
  - its JIT, under `__V1BL__` in jit.c: a method's prologue stores r7 into
    the frame instead of popping the return address; the stubs that call
    C keep r7 on the stack meanwhile; and a send through the method cache
    passes its bytecode in r5, not r7.
- **Graphics:** the 1b kernels, edited as they're built. Five of them save
  r7 with the registers they already save. `expand.s` uses every register
  and calls its emit routines with the depth's table in r7, so the table
  moves to its frame, and the emit routines that need it push r7 and load
  it.
- **The desktop and Egretica** (studies/egret_gui, in
  [pull request 35](https://github.com/aiju/heron/pull/35)) are built from
  the pieces above. After Egretica's eight lines both ISAs leave the same
  screen, bit for bit.
- **For the rest, an estimator** ([3](#3-the-estimator)): the Lisp and the
  kernel study's nucleus aren't ported.

Every ported program gives its expected output on v1bl: the 20 programs,
the 15 C programs, Egret's 18 on all three builds, and the 12 graphics
scenes with either kernels, which match the host's screens.

## 2. What a call costs

On the 1b hardware, in cycles, including the next instruction's fetch:

| | 1b | v1bl |
|---|---:|---:|
| `BSR` | 5 | 3 |
| `CALL label`, `CALL #label` | 5, 7 | 4, 5 |
| `CALL r9` | 5 | 3 |
| `CALL [r9 + 8]` | 9 | 6 |
| `RET` | 5 | 2 |
| `PUSH r7`; `JMP [sp]+` | | 4; 5 |
| one register more in `SAVE`, `RESTORE` | | 3, 2 |

So a `BSR` and its return change by:

| The callee | Change |
|---|---:|
| is a leaf | −5 |
| saves r8–rN: r7 joins the `SAVE` and the `RESTORE` | 0 |
| calls but saves nothing: `PUSH r7` and `JMP [sp]+` | +2 |

A push costs two bus cycles on the 16-bit bus, and so does the pop. Those
four bus cycles are what the link register saves.

**Long runs** (Egret, graphics, the desktop) are too long for the RTL
model, at about 100,000 cycles a second. They are costed from their timing
keys instead:

- calls, returns, jumps, `SAVE`, `RESTORE`, pushes and pops at their
  microcode routine's cycles;
- the rest by the timing model calibrated on the 1b hardware
  ([RFC 0024](../0024-rfc-faster-smaller.md)).

On the suites, where both can run, the result's change agrees with the
RTL model's to within 0.3 points on every program: −2.23% against −2.28%
for the suite by hand, −0.21% against −0.20% for the C versions.

## 3. The estimator

The estimator puts the costs above to a 1b run, without porting anything:

- it follows each call on a shadow stack, one per mode and address space
  for the nucleus;
- it sorts each call by what its callee did: a leaf, a callee whose
  register save r7 can join, or one that would push it;
- it adds up the costs above;
- a `SAVE` before any call keeps r7 company, as the ports do;
- an early return before any call counts as a leaf, as fib's port is
  written.

Against the ports it comes within 0.3 points on every program of the
suite by hand, and exactly on most. On compiled C it is exact for 13 of
15. The two it misses call only on a rare path (wordfreq's `before`, and a
function in bst): the compiler saves r7 every time, and the estimator only
when needed. That gap is the shrink-wrapping a compiler could add. For
Egret's interpreters it is 0.1–0.3 points optimistic. It can't follow a
JIT, whose prologues take the return address off the stack, which is why
the JIT was ported.

For the Lisp, a frame built on entry (`SAVE r3-rN` of the arguments) is
taken to save r7 too, even on a path that then returns without calling, as
a port of its compiler would.

## 4. Where it gains, and why

Calls are the whole effect. How many there are, and how many go to
leaves, decides it:

- **Hand-written code calls leaves.** Most of the suite's calls go to
  library routines that call nothing: `putc`, `puts`, `print_u32`,
  `strcmp`, `rand`. The programs that call most gain most: monitor −6.9%,
  bst −4.5%, lines −4.1%, fib −4.0%.
- **Compiled C calls functions that call.** fib and queens, both
  recursive, break even (+0.0% and +0.1%): their functions save
  registers, and r7 joins them.
- **Egret's interpreters hardly call.** A send in either interpreter is
  frames in memory and a `JMP`. `CALL` is only for C primitives and the
  allocator, 1–24 per 1,000 instructions, so their −0.2% is the VM's C.
- **Egret's JIT calls on every send,** and its prologue stored the return
  address in the frame anyway. With the link register it stores r7, so the
  pop goes as well as the push. That is −0.9% on average and −2.3% for
  Richards; [report 0017](../0017-report-egret.md) had estimated 0.7% and
  2.6%.
- **The desktop** is Egret's assembly interpreter, the graphics library
  and its C: −0.2% to −0.9% per action, and −0.55% to boot, which is
  mostly compiling the desktop's Egret source. Opening the menu is the
  exception, at +1.8%: v1bl ran 1.5% more instructions in the same time
  there, so the desktop did more work, not the same work slower.
- **The Lisp** calls through `CALL [r1 + 1]` for every call, and its
  runtime in leaves:
  - interpreted, −1.0% to −1.6%;
  - compiled, fib and tak lose (+1.0% and +0.7%), because their calls are
    almost all to functions that call;
  - the other compiled programs gain up to 2.5% (sort).
- **The nucleus** inlines its fast paths: a system call, an IPC and the
  console writes make no calls at all. A yield or a preemption makes one,
  to the ready queue, which takes 2% to 3% off them.

## 5. The desktop and Egretica

On the 1b hardware, as studies/egret_gui/bench.py measures them: an
action's cycles, less what the idle loop would have spent meanwhile.

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

Measured with the desktop at pull request 35's head
([71eb7db](https://github.com/aiju/heron/commit/71eb7db)), with the
link-register commits applied.

## 6. Other microarchitectures

The six configurations of draft 1's timing model put the same runs on a
16-bit or a 32-bit datapath, with a separate, an overlapped or a wide
fetch. Per `BSR` and its return, the change in cycles:

| The callee | 1b hardware | D16-overlap | D32-overlap | D32-wide |
|---|---:|---:|---:|---:|
| is a leaf | −5 | −3 | −3 | −1 |
| saves r8–rN, and r7 joins | 0 | +1 | +1 | +1 |
| calls and saves nothing | +2 | +3 | +3 | +2 |

And over the workloads, the geometric means:

| Workload | 1b hardware | D16-overlap | D32-overlap | D32-wide |
|---|---:|---:|---:|---:|
| The suite by hand | −2.28% | −1.16% | −1.47% | −0.31% |
| The C versions | −0.20% | +0.12% | +0.13% | +0.40% |
| Egret's JIT | −0.90% | −0.53% | −0.72% | −0.29% |

Two things make the model less kind to the link register than the 1b
hardware:

- **The model's push and pop are cheaper.** It takes 4 cycles for `BSR`
  and for `RET` where the 1b microcode takes 5. It also takes 2 cycles for
  each register in `SAVE` and `RESTORE` where the microcode takes 3 and 2.
  So even on a 16-bit bus, compiled C comes out slightly worse (+0.1%).
- **With the wide fetch,** a 32-bit bus with a prefetch buffer, recommended
  in [RFC 0007](../0007-rfc-ideas-microarchitecture.md#1-datapath-and-fetch):
  - pushing the return address is one bus cycle, and it overlaps with
    adding the offset to the PC, so `BSR` takes 3 cycles either way;
  - the link register is left with the return (3 → 2) and pays for r7's
    word in `SAVE` and `RESTORE` (+1 each);
  - so a leaf gains a cycle, and a function that calls loses one.

The model takes the 1b datapath's path for the link write: the PC reaches
the register file only through the ALU and R, so the copy and the
branch's add take the ALU one after the other. A draft 2 datapath that
can write the PC into the register file directly would make a linking
`BSR` as cheap as a branch: −2 for a leaf and about even otherwise, even
with the wide fetch. That wasn't measured.

All six configurations, for every workload, are in the
[appendix](#the-configurations).

## 7. What it costs besides cycles

- **Every routine that calls has to save r7,** in hand-written code too.
  - Widening `SAVE r8-rN` to `SAVE r7-rN` covers most of them, as r7 sits
    just below the callee-saved registers. `LDM` and `STM` need nothing
    more than their range for it.
  - Forgetting it is a bug that shows on the first return. The one mistake
    in porting the suite was a `RESTORE` left at r8 (sort's `fill`), and
    the program crashed at once.
- **Leaves lose a free register.** A leaf that needs all seven scratch
  registers saves r7, as it would a callee-saved one. The compiler does
  this itself. Before it did, sha256's block function spilled in its loop,
  and took 7% more cycles in the timing model.
- **Trap handlers that call must save r7,** since the call writes it.
  - The suite's `SWI` handler saves r1–r7 already.
  - The nucleus's page-fault handler saves r1–r6 in one variant, and
    would need r7 too.
- **Conventions move:**
  - the Lisp passes arguments 1–6 in r3–r8, so argument 5 moves
    ([report 0033](../0033-report-lisp-arguments-draft-2.md));
  - Egret's JIT passed a send's bytecode in r7 across a call, so it moved
    to r5;
  - `expand.s` kept its table in r7 across a call.
- **Some things get simpler:**
  - `setjmp` and `longjmp` keep r7, instead of reading and writing the
    stack;
  - a JIT's prologue stores the return address where it wants it;
  - a coroutine switch can start a thread with its entry point in r7.
- **Debugging:** a leaf's return address is in r7, not on the stack, so a
  backtrace from a trap has to know whether the routine saved it. The trap
  frame has the registers, so it can.
- **Code size** barely changes: +44 bytes over the suite by hand, 26 of
  them monitor's pushes, and 0–6 bytes for each C version. `SAVE r7-rN` is
  the same parcel as `SAVE r8-rN`.

## 8. What's left for draft 2

The cells and the semantics are in RFC 0028: `CALL ea` and `BSR` write r7,
and `RET` is `JMP r7`. What the measurements leave open:

- **The compiler should shrink-wrap the save of r7,** for the functions
  that call only on rare paths: wordfreq's −0.9% would be −3.7%.
- **The datapath's link write:** a direct path from the PC to the register
  file keeps the gain with a 32-bit bus ([6](#6-other-microarchitectures)).
- **A `RESTORE` that also returns** would save the `JMP r7` after
  `RESTORE r7-rN`, as ARM's `POP {..., pc}` does. That would help with or
  without a link register; it wasn't measured.

## Appendix: the tables

From `heron link_register report` at
[bee497d](https://github.com/aiju/heron/tree/bee497d10460bd2f97bac0e1a81b6de895e8fd77/studies/link_register),
on the 1b hardware unless the table says otherwise.

### The suite by hand

On the 1b hardware: the RTL model running each ISA's microcode. Estimate: the estimator on the 1b program (studies/link_register/estimate.py). Link saves per call: `SAVE r7-rN` and `PUSH r7` per call executed.

| Program | 1b cycles | v1bl cycles | Change | Estimate | Instructions | Code bytes | Calls per 1,000 instructions | Link saves per call |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| arith | 65,495 | 63,244 | -3.44% | -3.44% | +0.00% | +0 | 32.0 | 0.00 |
| bignum | 25,768 | 25,314 | -1.76% | -1.76% | +0.00% | +0 | 18.5 | 0.06 |
| bst | 33,304 | 31,805 | -4.50% | -4.79% | +0.00% | +0 | 46.9 | 0.31 |
| crc | 162,234 | 160,110 | -1.31% | -1.31% | +0.00% | +0 | 7.3 | 0.00 |
| fib | 342,190 | 328,446 | -4.02% | -4.02% | +4.43% | +4 | 91.1 | 0.49 |
| hello (not in the means) | 141 | 137 | -2.84% | -2.84% | +0.00% | +0 | 18.9 | 0.00 |
| interrupts (not in the means) | 87,610 | 87,557 | -0.06% | -0.12% | +0.00% | +0 | 1.6 | 0.12 |
| life | 598,340 | 595,285 | -0.51% | -0.51% | +0.00% | +0 | 4.0 | 0.03 |
| lines | 67,697 | 64,929 | -4.09% | -3.93% | +0.32% | +4 | 23.2 | 0.03 |
| mandel | 797,587 | 792,688 | -0.61% | -0.61% | +0.00% | +0 | 7.6 | 0.00 |
| matmul | 33,095 | 32,440 | -1.98% | -1.98% | +0.00% | +0 | 25.0 | 0.01 |
| monitor | 42,907 | 39,938 | -6.92% | -6.99% | +0.41% | +26 | 53.6 | 0.10 |
| queens | 190,067 | 188,872 | -0.63% | -0.63% | +0.00% | +0 | 36.6 | 0.89 |
| rpn | 29,013 | 28,180 | -2.87% | -2.87% | +0.00% | +0 | 19.6 | 0.00 |
| sha256 | 238,821 | 238,803 | -0.01% | -0.01% | +0.00% | +0 | 0.4 | 0.84 |
| sieve | 180,941 | 180,813 | -0.07% | -0.07% | +0.00% | +0 | 0.4 | 0.04 |
| sort | 99,644 | 98,083 | -1.57% | -1.58% | +0.01% | +6 | 17.0 | 0.38 |
| strings | 16,415 | 15,827 | -3.58% | -3.72% | +0.80% | +4 | 33.6 | 0.12 |
| vm | 2,846,603 | 2,846,524 | -0.00% | -0.00% | +0.00% | +0 | 0.0 | 0.06 |
| wordfreq | 226,579 | 220,182 | -2.82% | -2.82% | +0.00% | +0 | 23.9 | 0.00 |
| **geometric mean** |  |  | **-2.28%** | -2.30% | +0.33% | +44 in all |  |  |

### The C versions

As above, the C library included, with data objects aligned to 4 in both (the C compiler's `driver.MIN_DATA_ALIGN`).

| Program | 1b cycles | v1bl cycles | Change | Estimate | Instructions | Code bytes | Calls per 1,000 instructions | Link saves per call |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| arith | 265,085 | 265,362 | +0.10% | +0.10% | +0.12% | +2 | 2.6 | 0.90 |
| bignum | 87,353 | 87,346 | -0.01% | -0.01% | +0.26% | +2 | 8.0 | 0.66 |
| bst | 64,121 | 64,276 | +0.24% | -0.54% | +0.07% | +2 | 24.5 | 1.00 |
| crc | 233,232 | 233,238 | +0.00% | -0.00% | +0.01% | +6 | 0.1 | 0.71 |
| fib | 488,996 | 489,190 | +0.04% | +0.04% | +0.04% | +2 | 64.4 | 1.00 |
| hello (not in the means) | 633 | 640 | +1.11% | +1.11% | +0.98% | +4 | 14.6 | 1.00 |
| life | 683,036 | 680,973 | -0.30% | -0.30% | +0.01% | +2 | 3.1 | 0.13 |
| mandel | 976,805 | 972,886 | -0.40% | -0.40% | +0.00% | +0 | 4.6 | 0.00 |
| matmul | 51,068 | 50,597 | -0.92% | -0.92% | +0.08% | +2 | 12.0 | 0.14 |
| queens | 233,353 | 233,683 | +0.14% | +0.14% | +0.11% | +2 | 31.0 | 1.00 |
| sha256 | 317,052 | 317,203 | +0.05% | +0.05% | +0.04% | +2 | 1.2 | 0.89 |
| sieve | 227,809 | 227,854 | +0.02% | +0.02% | +0.01% | +2 | 0.3 | 0.96 |
| sort | 161,602 | 160,355 | -0.77% | -0.77% | +0.02% | +4 | 10.9 | 0.42 |
| strings | 50,928 | 50,865 | -0.12% | -0.12% | +0.13% | +2 | 4.6 | 0.55 |
| wordfreq | 390,440 | 386,897 | -0.91% | -3.74% | +2.44% | +4 | 50.6 | 0.49 |
| **geometric mean** |  |  | **-0.20%** | -0.47% | +0.24% | +38 in all |  |  |

### Egret

Change in cycles on the 1b hardware (studies/link_register/hw.py) for each build of the VM, the empty program's start-up taken off each program.

| Program | C interpreter | Assembly interpreter | JIT | 1b cycles with the JIT |
|---|---:|---:|---:|---:|
| start-up (the empty program) | -0.62% | -0.62% | -0.62% | 4,607,668 |
| bignum | -0.70% | -0.74% | -0.85% | 522,282 |
| bst | -0.20% | -0.30% | -1.48% | 2,583,150 |
| closures | -0.05% | -0.06% | -0.73% | 16,688,906 |
| crc | -0.03% | -0.04% | -0.90% | 7,903,276 |
| fib | -0.06% | -0.12% | -1.90% | 3,067,681 |
| json | -0.35% | -0.45% | -0.68% | 87,016,855 |
| life | -0.03% | -0.05% | -0.14% | 20,380,131 |
| mandel | -0.10% | -0.15% | -0.29% | 8,518,316 |
| matmul | -0.63% | -0.75% | -1.06% | 3,359,676 |
| queens | -0.47% | -0.68% | -0.77% | 4,099,959 |
| richards | -0.04% | -0.07% | -2.28% | 22,207,715 |
| shapes | -0.11% | -0.18% | -1.22% | 7,752,947 |
| sieve | -0.03% | -0.04% | -0.18% | 5,184,477 |
| sort | -0.15% | -0.21% | -0.64% | 4,117,869 |
| trees | -0.02% | -0.03% | -1.35% | 115,816,734 |
| wordfreq | +0.01% | +0.09% | +0.16% | 5,732,177 |
| **geometric mean** | **-0.18%** | **-0.24%** | **-0.90%** |  |

### Graphics

The graphics study's scenes, set-up phases left out, on the 1b hardware (studies/link_register/hw.py).

| Scene and depth | C kernels | Assembly kernels | 1b cycles, assembly kernels |
|---|---:|---:|---:|
| prims-0 | +0.19% | +0.04% | 18,431,062 |
| prims-1 | +0.17% | +0.07% | 19,965,245 |
| prims-2 | +0.14% | +0.06% | 22,757,050 |
| prims-3 | +0.11% | +0.06% | 23,987,863 |
| text-0 | -0.40% | -0.53% | 39,951,083 |
| text-1 | -0.37% | -0.45% | 46,341,209 |
| text-2 | -0.38% | -0.44% | 46,519,127 |
| text-3 | -0.40% | -0.45% | 45,934,276 |
| wm-0 | -0.50% | -0.79% | 12,149,370 |
| wm-1 | -0.35% | -0.48% | 17,137,071 |
| wm-2 | -0.31% | -0.44% | 18,721,162 |
| wm-3 | -0.25% | -0.44% | 18,657,567 |
| **geometric mean** | **-0.20%** | **-0.32%** |  |

### The Lisp, estimated

Not ported: the estimator, with a frame built on entry taking r7 (studies/link_register/lisp.py). Compiled: only the compiled code's running.

| Program | Interpreted | Calls | Compiled | Calls |
|---|---:|---:|---:|---:|
| boyer | -1.22% | fold 25, leaf 4,576,479, push 3,379,059 | -1.26% | fold 4, leaf 193,039, push 280,723 |
| closures | -1.40% | fold 5, leaf 823,834, push 485,134 | -1.02% | fold 1, leaf 36,436, push 66,740 |
| deriv | -1.41% | fold 8, leaf 1,448,488, push 930,755 | -1.34% | fold 2, leaf 63,588, push 82,369 |
| destruct | -1.33% | fold 5, leaf 1,112,169, push 683,948 | -0.98% | fold 1, leaf 24,519, push 10,912 |
| div | -1.01% | fold 4, leaf 728,726, push 581,717 | -0.93% | fold 2, leaf 21,771, push 30,728 |
| fib | -1.34% | fold 3, leaf 770,715, push 518,860 | +0.98% | leaf 259, push 79,297 |
| meta | -1.51% | fold 7, leaf 1,610,735, push 983,280 | -0.82% | leaf 29,655, push 48,718 |
| nqueens | -0.97% | fold 3, leaf 781,406, push 658,674 | -1.00% | fold 1, leaf 28,868, push 30,385 |
| sieve | -1.48% | fold 4, leaf 1,174,889, push 625,622 | -0.82% | fold 1, leaf 22,142, push 227 |
| sort | -1.56% | fold 24, leaf 3,975,949, push 2,364,629 | -2.46% | fold 6, leaf 282,702, push 69,678 |
| strings | -1.26% | fold 1, leaf 397,865, push 289,710 | -1.74% | leaf 40,439, push 52,198 |
| tak | -1.22% | fold 6, leaf 831,482, push 567,278 | +0.66% | leaf 125, push 50,814 |
| **geometric mean** | **-1.31%** |  | **-0.90%** |  |

### The nucleus, estimated

The kernel study's scenarios, per operation, on the 1b hardware (studies/link_register/kernel.py).

| Scenario | 1b cycles per operation (no banks) | Banks: none | Banks: half | Banks: full | Calls per operation |
|---|---:|---:|---:|---:|---:|
| null | 36 | +0.00% | +0.00% | +0.00% |  |
| yield | 241 | -2.07% | -2.67% | -2.54% | leaf 1 |
| ipc | 367 | +0.00% | +0.00% | +0.00% |  |
| fault | 4,746 | -0.11% | -0.11% | -0.11% | leaf 1 |
| preempt | 243 | -1.65% | -2.07% | -3.01% | leaf 1 |
| irqdrv | 595 | -1.34% | -1.63% | -1.82% | leaf 2 |
| wmono | 248 | +0.00% | +0.00% | +0.00% |  |
| wipc | 539 | +0.00% | +0.00% | +0.00% |  |
| wring | 379 | +0.00% | +0.00% | +0.00% |  |
| wring32 | 366 | +0.00% | +0.00% | +0.00% |  |
| wserv1 | 1,139 | -0.70% | -0.80% | -0.78% | leaf 2 |
| wserv | 418 | -0.24% | -0.25% | -0.25% | leaf 0 |
| wserv32 | 341 | -0.07% | -0.07% | -0.07% | leaf 0 |
| wmono256 | 3,128 | +0.00% | +0.00% | +0.00% |  |
| wipc256 | 3,179 | +0.00% | +0.00% | +0.00% |  |
| refill | 1,538 | +0.00% | +0.00% | +0.00% |  |

### The configurations

Geometric means of the change in cycles: on the 1b hardware, and in the six configurations of draft 1's timing model.

| Workload | 1b hardware | D16-separate | D16-overlap | D16-wide | D32-separate | D32-overlap | D32-wide |
|---|---:|---:|---:|---:|---:|---:|---:|
| the suite by hand | -2.28% | -0.96% | -1.16% | -0.23% | -1.16% | -1.47% | -0.31% |
| the C versions | -0.20% | +0.11% | +0.12% | +0.32% | +0.11% | +0.13% | +0.40% |
| Egret, C interpreter | -0.18% | -0.05% | -0.08% | +0.04% | -0.06% | -0.09% | +0.05% |
| Egret, assembly interpreter | -0.24% | -0.07% | -0.11% | +0.03% | -0.08% | -0.13% | +0.04% |
| Egret, JIT | -0.90% | -0.33% | -0.53% | -0.26% | -0.46% | -0.72% | -0.29% |
| graphics, C kernels | -0.20% | -0.05% | -0.09% | +0.03% | -0.06% | -0.11% | +0.03% |
| graphics, assembly kernels | -0.32% | -0.10% | -0.17% | -0.03% | -0.12% | -0.21% | -0.04% |
