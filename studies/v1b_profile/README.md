---
status: active
depends-on: [v1_isa, v1b_hw, c_compiler, lisp, graphics, kernel, egret]
reports: []
---

# Instruction profiles of draft 1b

What every program that runs on draft 1b executes, instruction by
instruction, in an SQLite database for quick investigations: which
instructions each program runs and how often, what each costs on the
draft 1b hardware and in the six configurations of the timing model,
control flow, which results and flags are ever read, and where the time
goes by function.

A profile is an observer of the instruction-level simulator: it sees every
instruction whoever runs the machine executes, so each study's programs run
exactly as the study runs them (the graphics scenes with their marks, the
Lisp compiling on the machine, the desktop with its scripted input). Code a
program makes for itself (the Lisp's compiler, Egret's JIT) is profiled as
it runs, with a new version whenever code at an address changes.

**Hardware cycles are exact.** The register-transfer model of the draft 1b
hardware is in Rust now ([`../v1b_hw/rtl`](../v1b_hw/rtl/src/lib.rs)), and
it follows the simulator as a *shadow*. Before each instruction it takes the
architectural state, runs the real microcode for that instruction, and counts
the cycles from its fetch to the next. It matches rtl.py cycle for cycle on all
20 programs and the exercise program: totals, output, the register file, flags,
all of RAM, and cycles per instruction address (`studies/v1b_hw/tests/test_rtl_native.py`).
The shadow's per-instruction costs match the whole machine's
(`tests/test_v1b_profile.py`). After every instruction it also compares its
registers, flags and next fetch with the simulator's. The database records
any difference; there have been none.

| File | What's in it |
|---|---|
| `collect/` | The profile, in Rust (heron.native.v1b_profile): counts, keys, the shadow, control flow, def-use chains, the call stack |
| `collect.py` | Attaching profiles, symbols and source lines, the schema and the database |
| `traces.py` | The catalogue: every program of every study, in its variants, and how to run it |
| `runner.py` | Collecting traces in worker processes |

```sh
heron v1b_profile list                       # the traces, * for those in the database
heron v1b_profile collect                    # all of them, into build/v1b_profile/profile.db (about 6 minutes on 4 cores)
heron v1b_profile collect lisp egret/fib     # some: names, prefixes or globs ("*/compiled")
heron v1b_profile collect --missing          # the ones the database doesn't have yet
heron v1b_profile summary                    # what's in the database
heron v1b_profile sql "SELECT * FROM mix WHERE trace = 'v1_isa/life' ORDER BY count DESC"
heron v1b_profile merge other.db             # copy another database's traces into this one
```

Or open the database in any SQLite client: `sqlite3 build/v1b_profile/profile.db`.

The database isn't committed: `collect` makes it again in minutes. It is
about 250 MB, a third of it indexes; a copy without them gets them back
the first time `heron v1b_profile sql` or `summary` opens it.

## The traces

199 traces, 2.3 billion instructions:

| Study | Traces | What |
|---|---:|---|
| `v1_isa` | 20 | The program suite in assembly |
| `v1b_hw` | 1 | The exercise program: every instruction class, mode and trap |
| `c_compiler` | 28 | The suite's 15 C versions at `-O1`, 5 of them at `-O0` too, and the compiler's 8 tests |
| `lisp` | 28 | The 12 programs interpreted, and compiled on the machine then run; 4 compiled with v1bx's tagged mode |
| `graphics` | 16 | The three scenes at 1, 2, 4 and 8 bits per pixel with the assembly kernels, at 8 bits all in C, and the store-multiple experiment |
| `kernel` | 42 | The nucleus's 16 scenarios with full register banks and 5 without (v1bs), and the 21 micro-benchmark variants |
| `egret` | 54 | Each program and an empty one, on the assembly interpreter, the C interpreter and the JIT |
| `egret_gui` | 10 | The desktop: booting; idle, with and without the clock; typing and Print it in the Workspace; the menu and moving windows; opening the Transcript, Paint and About; the Browser; Life, Mandel and Gadgets running |

The `egret_gui` study is on its own branch for now
(`claude/wizardly-carson-62xnr4`). Its traces are listed when the study is
in the tree: collect them from a merge of that branch, and `merge` the
database into the main one. Every other trace with an expected output
produced it exactly.

Not included: draft 1a, and the system study's programs, which need its
bus devices and live on another unmerged branch.

## The database

| Table | One row per |
|---|---|
| `trace` | Run: study, program, variant, ISA, input, totals (instructions, hardware cycles, the model's six configurations), interrupts, traps, whether the output was right, the console output, the shadow's mismatches, the commit it was collected at |
| `code` | Instruction as the program has it, shared by the traces that ran it: address, parcels, disassembly, mnemonic (`op`), operation and operand form (`kind`: `MOV [r+d]`, `Bcc`, `LSL reg`), operand mode, enclosing function and label, source file and line where the assembler kept them, the registers and flags it reads and writes |
| `insn` | Instruction a trace executed (`code` says which): executions, hardware cycles (total, min, max), the model's cycles in each configuration, branches taken, interrupts taken after it, traps, results written and read, flags written and read (N, Z, C, V), data addresses (count, I/O, range), when it first ran |
| `exec` | (instruction, timing key, hardware cost): the key's class and parameters (addressing kind, size, 64 KB carry, taken, multiplier bits, shift steps, registers saved), the hardware cycles of one execution, the model's cycles of one |
| `edge` | (instruction, next address, kind): how often one followed the other, with interrupts and traps marked |
| `flag_use` | (writer, reader, flags): reads of flags that found them set by `writer` |
| `reg_use` | (writer, reader, register): reads that found `writer`'s result, and the sum of their distances in instructions |
| `dist` | Def-use distances per trace, in powers of two |
| `func` | Function entered by a call: calls, and inclusive instructions and cycles |

Views: `insns` (every executed instruction with its code and trace name),
`mix` (instruction mix by `kind` per trace), `profile` (own and inclusive
cost per function). Columns `d16_sep` to `d32_wide` are the model's
configurations ([timing-model-v1.md](../v1_isa/timing-model-v1.md)), `hw_*`
the hardware's.

### Questions it answers

```sql
-- the hottest instructions of a run, with source lines
SELECT text, func, source, count, pct, hw_cpi FROM insns
WHERE trace_name = 'v1_isa/sha256' ORDER BY count DESC LIMIT 20;

-- which instructions' flags are read at all (RFC 0006: which MOVs set the flags)
SELECT c.op, SUM(i.count) AS execs,
       ROUND(100.0 * SUM(i.z_used) / NULLIF(SUM(i.z_defs), 0), 1) AS z_read_pct,
       ROUND(100.0 * SUM(i.c_used) / NULLIF(SUM(i.c_defs), 0), 1) AS c_read_pct
FROM insn i JOIN code c ON c.id = i.code JOIN trace t ON t.id = i.trace
WHERE t.isa = 'v1b' AND c.fwrites IS NOT NULL GROUP BY c.op ORDER BY execs DESC;

-- the hardware against the model, per timing class, on the desktop
SELECT e.class, SUM(e.count) AS execs,
       ROUND(1.0 * SUM(e.hw * e.count) / SUM(e.count), 2) AS hw_cpi,
       ROUND(1.0 * SUM(e.d32_sep * e.count) / SUM(e.count), 2) AS d32_sep_cpi
FROM exec e JOIN trace t ON t.id = e.trace
WHERE t.study = 'egret_gui' AND e.hw IS NOT NULL GROUP BY e.class ORDER BY execs DESC;

-- pairs of instructions that run one after the other (fusion candidates)
SELECT a.kind AS first, b.kind AS second, SUM(e.count) AS n
FROM edge e
JOIN insn ia ON ia.trace = e.trace AND ia.id = e.src JOIN code a ON a.id = ia.code
JOIN insn ib ON ib.trace = e.trace AND ib.id = e.dst JOIN code b ON b.id = ib.code
WHERE e.trace = (SELECT id FROM trace WHERE name = 'egret_gui/boot')
GROUP BY a.kind, b.kind ORDER BY n DESC LIMIT 20;

-- results that are never read, by kind of instruction
SELECT c.kind, SUM(i.reg_defs) AS defs, SUM(i.reg_defs) - SUM(i.reg_defs_used) AS dead
FROM insn i JOIN code c ON c.id = i.code GROUP BY c.kind ORDER BY dead DESC LIMIT 20;

-- how far a result travels: loads read within one instruction
SELECT w.kind, r.kind, u.reg, SUM(u.count) AS n, ROUND(1.0 * SUM(u.dist_sum) / SUM(u.count), 1) AS avg_dist
FROM reg_use u
JOIN insn wi ON wi.trace = u.trace AND wi.id = u.writer JOIN code w ON w.id = wi.code
JOIN insn ri ON ri.trace = u.trace AND ri.id = u.reader JOIN code r ON r.id = ri.code
WHERE w.kind LIKE 'MOV [%' GROUP BY 1, 2, 3 ORDER BY n DESC LIMIT 20;

-- where a run spends its time, by function, own and inclusive
SELECT * FROM profile WHERE trace = 'lisp/boyer/interp' ORDER BY hw_cycles DESC LIMIT 15;

-- conditional branches: taken rate, forward and backward
SELECT i.trace, SUM(i.count) AS execs, SUM(i.taken) AS taken,
       SUM(CASE WHEN e.dst_pc < i.pc THEN e.count END) AS backward
FROM insn i JOIN code c ON c.id = i.code
JOIN edge e ON e.trace = i.trace AND e.src = i.id AND e.fallthrough = 0
WHERE c.kind IN ('Bcc', 'Jcc') GROUP BY i.trace;
```

### What to know when reading it

- **Hardware cycles** count from an instruction's fetch to the next one's.
  Interrupt entries are counted apart (`trace.irq_hw_cycles`). So is HALT's
  wait for the timer, which isn't counted at all, as the simulator doesn't
  count it.
- **Unknown hardware cost.** v1bx's tagged operations and v1bs's system
  extensions aren't in the hardware, so their cost is unknown (`hw` NULL,
  `hw_unknown`). In v1bs traces the shadow reads data at virtual addresses,
  which affects nothing but the rare instruction whose microcode depends on
  a loaded value.
- **Interrupts.** They arrive when the simulator's timer says, which counts
  the reference configuration's cycles (D16-overlap), not the hardware's.
- **The model's wide fetch** is costed at the code's actual alignment, not
  the average of both alignments the reports use.
- **Def-use chains** count a register as read when an instruction reads it,
  SAVE and pushes included. An interrupt entry saves the chains and its RTI
  restores them, so a handler doesn't disturb the code it interrupted. Traps
  and system calls pass straight through. Results still unread when the
  run ends count as unread.
- **Inclusive costs** come from a call stack kept from CALL, BSR and RET,
  unwound by the stack pointer, so longjmps and the like close the frames
  they skip. A recursive function's inclusive cost counts its outermost
  calls only. The kernel's context switches confuse it.
- **Symbols.** Function and label names come from the image (`main`,
  `main.loop`; C names start with `_`). Code past the image is
  `(generated)`. Source lines are there for assembled programs (the suite,
  the kernel, the Lisp's runtime), not for linked C.
