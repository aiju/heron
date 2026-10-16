---
status: active
depends-on: [v2_hw, v2_isa, v1_isa, v1b_hw, c_compiler]
reports: [39]
---

# Other instruction sets in draft 2's microcode store

How hard is it to run another instruction set on the draft 2 CPU
([RFC 0031](../../reports/0031-rfc-draft-2-cpu.md)) by writing a different
microcode and decode table into its writable control store? This study
writes that microcode for four instruction sets, runs real programs on
draft 2's register-transfer model with it, checks every instruction
against a reference interpreter, and tries the design changes that make
the rest work: [report 0039](../../reports/0039-report-guest-isas.md) has
the findings, [its performance.md](../../reports/0039-report-guest-isas/performance.md)
the numbers.

| Guest | Hardware | How | Programs |
|---|---|---|---|
| RV32IM | unmodified | every register a register-file bank; fields of the second parcel through tables in the register file | the suite's C, compiled by clang |
| 6502 | unmodified | memory doubled: byte *a* is parcel *a*, with byte *a* + 1 beside it, so the byte-granular code stream is parcels | Klaus Dormann's functional test; the suite's C by cc65 |
| Draft 1b | unmodified | the decode table specialises every routine on 1b's addressing mode and register | 1b's hand-written suite and its compiled C, as 1b binaries |
| Thumb (ARMv6-M) | D1 | the decode table also gives the IR to load and an immediate | the suite's C, compiled by clang |
| Draft 2 and Thumb, as user processes | D1, D2, D3 | one control store; status-word bits pick the decode table page | a draft 2 kernel time-slicing processes in both |

The design changes are options in [rtlx.py](rtlx.py), a copy of the RTL
model's step with each marked: **D1** a wider decode table (IR translation
and an immediate), **D2** decode table pages selected by two status-word
bits, **D3** the whole 64K control store reachable. With none in use the
model is draft 2's, cycle for cycle (the unit tests check).

It depends on `v2_hw` for the CPU (its microcode assembler, placement,
timing and RTL model; the study needs that study's branch, which is
RFC 0031's), `v2_isa` for the draft 2 tools, `v1_isa` for 1b's assembler,
simulator and suite, `v1b_hw` for its shift planner, and `c_compiler` for
the C programs and library.

**Draft 2 itself moves.** The draft 2 tools in this tree follow RFC 0028
and RFC 0029 as they are on `main`; the v2_hw microcode predates two of
their changes: row 0's new cells (LEA, MFSR, MTSR) with the renumbered
special registers, and HI and LO as r0 and r1. The mixed machine's
draft 2 side copes: page 0 of its decode table maps the new row 0 onto
the microcode's routines (`mixed.native_classify`, an identity once the
microcode follows), and its draft 2 code uses no multiply or divide.

| File | What's in it |
|---|---|
| `guest.py` | What a guest is (reset, forced entries, classify, routines, state); `GuestMicrocode`, which places it as draft 2's microcode is placed; the machine it runs on |
| `rtlx.py` | The RTL model with the design changes D1-D3 |
| `rv32.py`, `rv32_ref.py` | RV32IM's microcode, and a reference interpreter |
| `thumb.py`, `thumb_ref.py` | Thumb's (needs D1), and a reference interpreter |
| `m6502.py`, `m6502_ref.py`, `m6502_progs.py` | The 6502's, a reference interpreter (decimal mode as the NMOS part), its programs |
| `v1b.py`, `v1b_progs.py` | Draft 1b's, and its programs; the reference is `v1_isa`'s simulator |
| `toolchain.py` | The C programs compiled by clang for RV32 and Thumb, linked into flat images |
| `mixed.py` | Draft 2's microcode and Thumb's in one control store (D1-D3), and the harness that plays boot loader for the kernel |
| `cli.py` | `heron v2_guests`: run, test, ucode, mixed, bench |
| `bench.py` | Every guest's programs against native draft 2 (report 0031's numbers); report 0039's performance.md |
| `sw/` | Start-up code and run-time helpers per target; `sw/mixed/`: the kernel (`kernel.s`), the draft 2 process (`sieve.s`), Thumb's user start-up and console header |
| `tests/` | Unit tests that need nothing from outside the repository; `tests/asm/`: their small guest programs, assembled once (`python3 -m heron.studies.v2_guests.tests.asm_programs` reassembles them, with clang and cc65) |

```sh
heron v2_guests test rv32 [--lockstep]       # the C programs (thumb, m6502, v1b likewise)
heron v2_guests run thumb life --profile     # one program: cycles, time, the busiest routines
heron v2_guests run m6502 functional         # the 6502 functional test (fetched into build/)
heron v2_guests ucode v1b                    # the microcode's size
heron v2_guests mixed                        # draft 2's kernel with draft 2 and Thumb processes
heron v2_guests bench [ISAS] [--write]       # report 0039's performance.md (an hour, cached)
heron test v2_guests                         # the unit tests
```

The RV32 and Thumb programs need clang, ld.lld, llvm-objcopy and llvm-nm;
the 6502's C programs need cc65; its functional test is downloaded from
GitHub the first time. Without them those programs are left out. Lockstep
runs check every register after every instruction, and take a few times
longer: the 6502's functional test in lockstep (30 million instructions)
takes about 40 minutes.
