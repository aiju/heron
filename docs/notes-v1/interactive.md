# Notes: rpn, monitor and interrupts in draft 1a and 1b

A first-hand log of writing the three "systems" programs (parsing, command
dispatch, error handling, a timer ISR, `HALT`-based sleep and an `SWI`
system call) for both draft 1 candidates: `programs/v1a/NAME.s` and
`programs/v1b/NAME.s`. Each version was written fresh from the reference
function in `programs/reference.py` (and the draft 0 program, for the
algorithm), not translated from the other draft. I alternated which ISA came
first: **rpn 1a first, monitor 1b first, interrupts 1a first.**

Cycle counts are from `run --stats` (D16-overlap, the reference
configuration, unless I say otherwise) and from a small profiler over the
simulator's per-instruction timing keys. All numbers are from the timing
model *after* the auto-increment fix (an `[r]+` access now costs the same as
a plain `[r]` access); I re-measured everything when that changed. I hadn't
avoided `[r]+` anywhere for cycle reasons, so no code changed, but 1b's
numbers improved by 2-6%. "Own code" means the program's own
instructions, without the shared library (`console.s`, `print.s`,
`string.s`), which another agent wrote and which differs between the ISAs
too.

## Summary

- **All six programs assembled and passed on the first run.** No assembler
  errors, no wrong output, no traps, in either ISA. Extra runs against the
  Python reference with my own inputs (about 45 monitor lines and 20 rpn
  lines of edge cases) matched too, and `interrupts` gives the same output
  for timer periods from 97 to 20,000 cycles in both ISAs. The hazards I had
  to design around are listed per program below; most are ISA-specific.
- **Draft 1 removed everything that was hard in draft 0, in both ISAs
  alike.** Hardware `MULS`/`DIVS` replace rpn's `smul16`/`sdiv16`, `LSL #4`
  replaces four `SHL`s per hex digit, `SAVE r1-r7` replaces 14 `PUSH`/`POP`s
  in the trap handler, `SWI` has its own vector, and 32-bit registers make the
  16-bit semantics a matter of one `SXH` or `ZXH` at the right place.
- **1b's gain is in byte-scanning loops and nowhere else.** Own code, 1b vs
  1a: rpn -8.0% instructions and -10.0% cycles, monitor -12.4% and -8.3%,
  interrupts -0.3% and -0.1%. On D32-wide the rpn gain shrinks to -3.8%
  while the monitor's grows to -12.3%.
- **1b's code-size gain is cancelled by its 4-bit constants.** Every compare
  with a character (`' '`, `'-'`, `'0'`, `'*'`, `'b'`, `0x7E`) is one parcel
  in 1a (`CMPI`/`ADDI`, 8-bit) and two in 1b. Own code: rpn 284 bytes in 1a,
  288 in 1b; monitor 452/438; interrupts 346/336.
- **Neither ISA ran short of registers.** rpn's evaluator is a leaf in
  r1-r7, the monitor's dump uses r8-r11, interrupts uses r8-r10. 1b's memory
  operands saved a register in exactly one place (`sleep`).

## Results

Whole programs (library included), from `run --stats`:

| program | ISA | instructions | D16-overlap | D32-overlap | D32-wide | code bytes |
|---|---|---:|---:|---:|---:|---:|
| rpn | 1a | 11,569 | 34,488 | 27,272 | 24,630 | 530 |
| rpn | 1b | 10,340 | 30,698 | 25,327 | 22,677 | 532 |
| monitor | 1a | 16,689 | 50,328 | 41,327 | 36,772 | 990 |
| monitor | 1b | 14,902 | 45,820 | 38,326 | 32,864 | 912 |
| interrupts | 1a | 16,904 | 63,590 | 45,634 | 44,277 | 542 |
| interrupts | 1b | 16,684 | 63,024 | 45,244 | 43,858 | 532 |

1b vs 1a, whole programs: rpn -11.0% cycles on D16-overlap and -7.9% on
D32-wide, monitor -9.0% and -10.6%, interrupts -0.9% and -0.9%.

Own code only:

| program | ISA | instructions run | D16-overlap | D32-wide | static instructions | bytes |
|---|---|---:|---:|---:|---:|---:|
| rpn | 1a | 5,165 | 13,919 | 9,997 | 116 | 284 |
| rpn | 1b | 4,753 | 12,521 | 9,622 | 111 | 288 |
| monitor | 1a | 7,433 | 21,533 | 15,782 | 186 | 452 |
| monitor | 1b | 6,509 | 19,753 | 13,848 | 173 | 438 |
| interrupts | 1a | 15,919 | 59,754 | 41,542 | 118 | 346 |
| interrupts | 1b | 15,874 | 59,708 | 41,466 | 112 | 336 |

`interrupts` is dominated by code that is identical in both ISAs (the
`MULU` loop and a 5,000-iteration idle loop, which together are 88% of its
cycles), so it is a functional test more than a benchmark. Its `test` table
shows 95,053 / 94,849 "cycles": that number includes the time spent waiting
in `HALT`, which the per-configuration numbers above leave out.

## Log

### rpn (1a first)

**Both versions passed on the first run.** The program reads lines, echoes
them with " => ", and evaluates each with a leaf routine `eval` that uses
only r1-r7: r4 scan pointer, r5 calculator stack pointer, r1 character,
r2/r3 peek and operands, r6 number, r7 sign. `main` uses r8-r9 to print the
stack. Nine registers, the same in both ISAs.

**16-bit semantics.** The calculator stack holds 16-bit values sign-extended
to 32 bits. Then `ADD`, `SUB`, `MULS` (s16 × s16 fits in 32 bits) and
`DIVS` (-32768 / -1 = +32768 fits) are exact, and one `SXH` per result does
the wrap: `32767 1 +` gives -32768 and `-32768 -1 /` gives -32768 with no
special case. Numbers are accumulated mod 2^32 and wrapped with `SXH` at the
end, which is exact because 2^16 divides 2^32 (`70000` → 4464).

**Operator dispatch.** Instead of draft 0's two compare chains I used a
six-entry table indexed by `c - '*'` (`* + , - . /`), with 0 for `,` and
`.`, in both ISAs. 1b's `JMP [table + r]` couldn't be used: the zero entries
have to be tested before the underflow check, so it is `MOV r3, [table + r3]`
/ `BEQ` / ... / `JMP r3`, just like 1a's `LD`. Late change in both: the
`MOV r3, r1` / `ADDI r3, -'*'` pair became `LEA r3, [r1 - '*']`, a flag-free
three-operand add (1% faster in both).

**Where the ISAs differed:**

- *Scanning.* 1b's `MOV r1, byte [r4]+` does a load and the pointer step in
  one parcel. In 1a it's `LDB r1, [r4]` + `ADDI r4, 1`, and the order is
  forced: `ADDI` sets Z, so it has to come after the branch that tests the
  loaded byte:

  ```
  1a:  .skip: LDB  r1, [r4]          1b:  .skip: MOV  r1, byte [r4]+
              BEQ  .end                           BEQ  .end
              ADDI r4, 1                          CMP  r1, #' '      ; 2 parcels
              CMPI r1, ' '                        BEQ  .skip
              BEQ  .skip                          ...
  ```

  1b's catch is the opposite one: after `byte [r4]+` the pointer is already
  past the terminator. When a number ends at the NUL, the pointer has to be
  stepped back (`.nul: DEC r4; BRA .push`) or the next scan reads past the
  end of the line. I spotted this while writing, not by a failure, but it is
  an easy bug to make.
- *The calculator stack.* 1b's auto-decrement/increment is exactly a stack:

  ```
  1a:  ADDI r5, -8                   1b:  MOV  r2, -[r5]      ; b
       LD   r1, [r5]       ; a            MOV  r1, -[r5]      ; a
       LD   r2, [r5 + 4]   ; b            ...
       ...                                ST   r1, [r5]+
       ST   r1, [r5]
       ADDI r5, 4
  ```

  Five one-parcel instructions against three; 18 cycles against 12 on
  D16-overlap, 12 against 8 on D32-wide.
- *Times ten plus a digit.* 1a: `MULU r6, #10` + `ADD r6, r1` (3 parcels,
  14 cycles D16-overlap, 8 D32-wide); a shift-and-add version would be ~14
  too. 1b has no multiply by an immediate, which pushed me to the x86 trick
  with the indexed mode: `LEA r6, [r6 + r6*4]` then `LEA r6, [r1 + r6*2]`
  (4 parcels, 8 cycles on both D16-overlap and D32-wide). That is the
  biggest single 1b win in rpn on D16, and it is entirely a property of the
  timing model, which charges address adds as cheap 16-bit adds on D16. On
  D32-wide the two are equal.
- *Character constants.* 1a: `CMPI r1, ' '`, `CMPI r1, '-'`,
  `ADDI r1, -'0'` are all one parcel. 1b: `CMP r1, #' '`, `CMP r1, #'-'`,
  `SUB r1, #'0'` are all two (only 0..15 and -1..-16 are quick). Only the
  tab test (`#9`) fits. Six compares and one subtract in rpn's own code are
  two-parcel for this reason alone, which is why 1b's rpn is 4 bytes
  *bigger* despite 5 fewer instructions.

On D32-wide 1b's lead in its own code shrinks from 10.0% to 3.8% (9,622 vs
9,997 cycles): the auto-increment load still saves 2 cycles a character
(3 against 3 + 2 for `LDB` + `ADDI`), but the `LEA` pair costs the same as
`MULU` + `ADD`, `SUB #'0'` costs 3 against `ADDI`'s 2, and the 2-parcel
compares cost 1 or 2 cycles depending on alignment against 1. (Before the
auto-increment timing fix, 1b was 0.4% *slower* here.)

**Mistakes:** none. **Wished for:** in 1b, an 8-bit immediate for `CMP`/`SUB`
(character constants); in 1a, a post-incrementing byte load, or an `ADDI`
that leaves Z alone.

### monitor (1b first)

**Both versions passed on the first run.** Structure, the same in both:
`command` saves r8-r11 for the handlers, stores `sp` for a longjmp-style
`bail`, skips blanks, and dispatches on the command letter through a
22-entry table from `b` to `w` (unknown letters point at `bail`). Handlers
call `getargs`, which parses every remaining argument with `hexnum` into a
40-word array and returns the count, then check the count.

**A deliberate change from draft 0.** Draft 0's handlers parse and act
argument by argument, so `b 8000 41 4G` writes 41 to 8000 and *then* prints
"?". The reference parses the whole line first and writes nothing. I
matched the reference: all arguments are parsed before a command acts.

**16-bit semantics.** `hexnum` accumulates with `LSL r1, #4` / `OR` in 32
bits and ends with `ZXH`, which is exactly `int(tok, 16) & 0xFFFF`
(`w 8070 10000 BEEF` writes 0000). Word accesses ignore bit 0 in the
reference (and in draft 0's hardware), but in draft 1 a misaligned half
access *traps*, so `w` and `r` need an explicit `AND r3, #-2`; the test
input has `r 8011`, which would otherwise trap. Monitor address A is RAM
address A; a range past FFFF runs on into RAM above 64 KB rather than
wrapping to 0000, where the program itself is (the printed addresses do wrap
because `print_hex` prints 4 digits). This is documented in the header. The
only differences from the reference I could provoke were reads of low
memory (`r 0` shows the vector table), which no layout can avoid.

**Where the ISAs differed:**

- *Dispatch.* 1b: `LSL r2, #2` / `CALL [cmdtab + r2]`. 1a: `LSL r2, #2` /
  `LD r2, [cmdtab + r2]` / `CALL r2`. One parcel and one instruction less in
  1b (8 vs 9 cycles D16-overlap, 5 vs 7 D32-wide). Neither ISA has a scaled
  index with a 16-bit displacement, so both need the `LSL`.
- *Parsing primitives.* The same split as rpn. 1b's `skipblanks` is four
  instructions with `byte [r8]+` and leaves r8 after the character; 1a's
  leaves r8 *on* the character, because `ADDI` would destroy the Z flag the
  caller wants (Z = end of line). So the two versions of `hexnum`,
  `getargs` and `cmd_s` have different pointer conventions: 1a's
  `hexnum` ends with r8 on the terminator, 1b's ends after a blank or on a
  NUL (`.nul: DEC r8`, again).
- *Halfwords.* 1a's `LDH`/`STH` exist only as long forms, so `STH r4, [r3]`
  and `LDH r1, [r8]` are two parcels with a zero displacement; in 1b
  `ST r4, half [r3]` and `MOV r1, half [r8]` are one. 1a's `AND r3, #-2` is
  two parcels (op 8; there is no short AND), 1b's is one (quick -2).
- *Reading the argument array.* 1a: `LD r1, [r2]` / `LD r3, [r2 + 4]` /
  `LD r2, [r2 + 8]` (one parcel each, any order). 1b: `MOV r1, [r2]+` /
  `MOV r3, [r2]+` / `MOV r2, [r2]` (one parcel each, but the order is fixed
  by the increments). A tie: this is where 1a's short `[reg + 4o]` form pays.
- *The dump.* Both walk a pointer r11 from the line start r8 to the line end
  r10 (draft 0 did the same for lack of register+register addressing; in 1b
  I could have used `byte [r8 + r11]`, but that is 2 parcels and two adds
  where `byte [r11]+` is one parcel). 1b saves the `ADDI` in both inner
  loops. `cmd_d` is 5,693 vs 6,097 cycles on D16-overlap and 3,991 vs
  4,626 on D32-wide.
- *Character constants* again: `'b'`, `'w' - 'b'` (21), `'0'`, `'a' - '0'`,
  `' '`, `0x7E` are all 2 parcels in 1b; 5 compares and 3 subtracts.

`LSL r1, #4` costs 9 cycles on D16-overlap (four 1-bit steps of two cycles
each, no barrel shifter): 24-25% of `hexnum` in both ISAs.

**Mistakes:** none. Hazards I designed around: the `byte [r]+` overshoot at
the NUL (1b), `ADDI` clobbering Z (1a), misaligned half accesses (both), and
`cmd_s` must not use `strcpy` because the reference doesn't write the NUL.
**Wished for:** both: `CALL [table + r*4]` with a 16-bit table address;
1a: short `LDH`/`STH` and a short `AND #imm`; 1b: 8-bit compare constants.

### interrupts (1a first)

**Both versions passed on the first run**, and both gave identical output
for timer periods 97, 150, 333, 1000, 2500, 7919 and 20,000 cycles. The
structure follows draft 0: own vector table, an ISR that counts ticks, the
sum of i² with interrupts firing, two exact sleeps (`DI` around the
measurement, `EI; HALT` relying on the EI shadow), stopping the timer and
checking that no more ticks arrive, then a system call.

**What draft 1 changed:**

- *Vectors.* Six vectors, 4 bytes apart, each a two-parcel relative `JMP`.
  `SWI` has its own vector, so the handler no longer has to tell it from an
  illegal instruction as in draft 0. Illegal instruction, divide error and
  address error go to a `fatal` handler that prints "TRAP" and halts (I
  checked both: a bad `SWI` number and a `DIVU` by zero print TRAP).
- *System calls with numbers.* `SWI #n` carries 8 bits, so the handler is a
  real dispatcher: `SWI #0` = putc, `SWI #1` = puts, anything else is fatal.
  The program now prints "swi: hello from a system call" with `SWI #1` and
  the newline with `SWI #0`. The decode folds the ×4 for the table into the
  shift: `(w >> 4) & 0xFF` times 4 is `LSR #2` / `AND #0x3FC`.

  ```
  1a:  SAVE r1-r7                      1b:  SAVE r1-r7
       LD   r5, [sp + 32]                   MOV  r5, [sp + 32]       ; stack slot
       LDH  r5, [r5 - 2]   ; 2 parcels      MOV  r5, half [r5 - 2]   ; 2 parcels
       LSR  r5, #2                          LSR  r5, #2
       AND  r5, #0xFF << 2                  AND  r5, #0xFF << 2
       CMP  r5, #4 * NSYS                   CMP  r5, #4 * NSYS
       BHS  fatal                           BHS  fatal
       LD   r5, [systab + r5]               CALL [systab + r5]
       CALL r5                              RESTORE r1-r7
       RESTORE r1-r7                        RTI
       RTI
  ```

  `SAVE`/`RESTORE r1-r7` cost 16 cycles each on D16-overlap; draft 0's 14
  `PUSH`/`POP`s cost 49.
- *The work.* With `MULU` the sum of squares is `MOV`, `MULU`, `ADD`, `DEC`,
  `BNE` per i (counting down so `DEC` sets Z), and fits in 32 bits. The
  register (r1, live from `MOV` to `ADD`) and flag (`DEC` to `BNE`)
  dependencies the comment points at are what a broken ISR would corrupt.
  This loop is identical in both ISAs.

**Where the ISAs differed:**

- *The ISR is the same code in both.* Neither ISA has a read-modify-write memory
  instruction, so `ticks++` needs a register in both:
  `PUSH r1; LD/MOV r1, [ticks]; ADDI/INC r1; ST r1, [ticks]; ST r0, [ack];
  POP r1; RTI`: 7 instructions, 32 cycles on D16-overlap plus 6 for the
  interrupt entry, in both. On D32-wide it's 21 against 20: 1a's `POP` is
  `RESTORE r1-r1` (4 cycles there), 1b's is `MOV r1, [sp]+` (3). An
  `INC [mem]` would make it `INC [ticks]; ST r0, [ack]; RTI`.
- *Memory operands in the sleep loop.* 1b compares with the tick counter in
  memory directly, and needs no temporary:

  ```
  1a:  .wait: LD   r2, [ticks]         1b:  .wait: CMP  r1, [ticks]
              CMP  r2, r1                          BLS  .done
              BHS  .done
  ```

  6 vs 7 cycles D16-overlap, 4 vs 4 D32-wide. `timed_sleep` similarly uses
  `NEG r9; ADD r9, [ticks]` and `main` uses `CMP r8, [ticks]`. These four
  are the only ALU memory operands in all three 1b programs; `ADD r9, [r2]`
  in the monitor's dump is the fifth.
- Everything else (`EI`/`DI`/`HALT`, the timer registers as 16-bit absolute
  addresses `[0xFFFFFF08]`, `SAVE`) is the same in both.

**Mistakes:** none. **Wished for:** both: an increment-memory instruction
for the ISR.

## Comparison

Costs of the idioms that mattered (cycles D16-overlap / D32-wide, from the
profiles):

| idiom | 1a | 1b |
|---|---|---|
| next byte and advance | `LDB` + `ADDI`: 2 parcels, 6 / 5 | `MOV r, byte [p]+`: 1 parcel, 3 / 3 |
| next word and advance | `ADDI` + `LD`: 2 parcels, 7 / 5 | `MOV r, [p]+`: 1 parcel, 4 / 3 |
| compare with `' '` | `CMPI`: 1 parcel, 2 / 1 | `CMP #' '`: 2 parcels, 3 / 1-2 |
| subtract `'0'` | `ADDI`: 1 parcel, 3 / 2 | `SUB #'0'`: 2 parcels, 4 / 3 |
| x × 10 + d | `MULU #10` + `ADD`: 3 parcels, 14 / 8 | 2 × indexed `LEA`: 4 parcels, 8 / 8 |
| pop two, push one | 5 instructions, 5 parcels, 18 / 12 | 3 instructions, 3 parcels, 12 / 8 |
| call through a table | `LD` + `CALL r`: 3 parcels, 9 / 7 | `CALL [t + r]`: 2 parcels, 8 / 5 |
| compare with a word in memory | `LD` + `CMP`: 3 parcels, 7 / 4 | `CMP r, [abs]`: 2 parcels, 6 / 4 |
| halfword store `[r]` | `STH` long: 2 parcels | `ST r, half [r]`: 1 parcel |

What I'd tell someone choosing:

1. **For parsers, 1b's auto-increment is the real advantage**: 8-12% fewer
   instructions in the programs' own code, 8-10% fewer cycles on
   D16-overlap and 4-12% on D32-wide. A byte load with the pointer step costs
   3 cycles against 1a's 5-6 for `LDB` + `ADDI`. (With the old timing model,
   where `[r]+` cost a cycle more, D32-wide ranged from 1b 0.4% slower
   (rpn) to 7.8% faster (monitor), so this conclusion depends on that
   microcode detail being achievable.) It is also where 1b's one new pitfall
   lives: the pointer is already past the terminator when the loop sees it.
2. **1b's 4-bit quick constants are the wrong size for text.** Parsers
   compare with ASCII all the time; 1a's 8-bit `CMPI`/`ADDI`/`MVI` cover
   them in one parcel and 1b doesn't. This alone erased 1b's code-size
   advantage in rpn and halved it elsewhere. A one-parcel `CMP rd, #imm8`
   in 1b (or a 0-127 quick range for `CMP`) would fix most of it.
3. **1a's `ADDI` setting Z is a constant small nuisance in byte loops**: it
   dictates the order load → branch → increment and made the two versions'
   pointer conventions differ. An `ADDI` that leaves all flags alone (as
   `LEA` does, but in one parcel) would help.
4. **Memory operands mattered less than expected.** In three programs, five
   ALU instructions used a memory operand, all of them `CMP`/`ADD` with a
   global or an array element. Systems code like this is dominated by
   calls, branches and byte loads, and neither ISA has the read-modify-write
   form (`INC [ticks]`) that an ISR would want.
5. **Dispatch tables are slightly nicer in 1b** (`CALL [table + r]`), but
   both need a `LSL #2` first, and the 1b form couldn't be used in rpn
   where the table has holes that must be tested before jumping.

## Spec and tool notes

- **HALT with interrupts enabled and no interrupt source** isn't covered by
  `isa-v1.md` ("wait for an interrupt"). The simulator stops, like draft 0's.
  My programs `DI` before `main` returns so `HALT` really stops.
- **The timer**: `isa-v1.md` doesn't say whether writing a period of 0 clears
  a pending timer flag (the simulator does), or when the first tick comes
  after writing a period (the simulator: one period later). I acknowledge
  explicitly after stopping the timer, so this doesn't matter for the
  program. The timer counts the simulator's reference configuration
  (D16-overlap) cycles, so the number of ticks during a computation depends
  on the configuration; the spec could say so.
- **`test` vs `run --stats` cycles**: for `interrupts`, the `test` table
  shows 95,053 cycles (1a) because the simulator's clock jumps forward while
  `HALT` waits, while `run --stats` reports 63,590 for D16-overlap, counting
  only executed instructions and interrupt entries. Both are reasonable,
  but the two tools disagree without saying why. For programs without `HALT`
  waits they agree.
- **Multiply operand order** (added to `isa-v1.md` while I worked: the time
  depends on the bit length of the *second* operand): my multiplies already
  had the small factor second (`MULU r6, #10`; `MULU r1, r9` squares). With
  an immediate the constant is always the second operand, so scaling by a
  constant is fast automatically. The trap is register × register: the
  result is the same in either order, so nothing reveals the slow one.
- **Draft 0's monitor doesn't match the reference** for inputs outside the
  test (`b 8000 41 4G` writes 41 before printing "?"); see the monitor log.
- No assembler or simulator bugs found, and no library bugs. `NSYS =
  ($ - systab) / 4` used before its definition, local labels in a
  `.word` table (`.optab: .word .mul, .add, ...`), and `BSR` relaxing to
  `CALL` for the far library routines all worked as documented.
- Environment: the scratchpad directory is shared between the agents running
  concurrently; another agent's `prof.py` replaced mine with the same name.
  I moved my scratch scripts to a subdirectory.
