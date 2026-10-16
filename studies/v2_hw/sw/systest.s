; systest: RFC 0029's system architecture on the draft 2 CPU. Each test
; prints its name and "ok", or what it got instead.
;
; The harness has mapped context 0's first megabyte one to one and starts
; here in supervisor mode, bank 0. The supervisor's stack is in the window
; (physical 0x100000, as 0x8010_0000); user mode runs in bank 1 with its
; own stack at 0xF0000. Exceptions vector to 0x8000_0000 + 4n: physical 4n,
; this table, in the window.
;
;! max-cycles: 20000000

        .org 0x00
        JMP  start              ; reset
        .org 0x04
        JMP  h_irq              ; interrupt
        .org 0x08
        JMP  h_illegal          ; illegal instruction
        .org 0x10
        JMP  h_divide           ; divide error
        .org 0x14
        JMP  h_address          ; address error (misaligned, bus error)
        .org 0x18
        JMP  h_tag              ; tag trap
        .org 0x1C
        JMP  h_priv             ; privilege violation
        .org 0x20
        JMP  h_page             ; page fault
        .org 0x24
        JMP  h_trace            ; trace
        .org 0x100
        JMP  h_exit             ; SWI #0: back to the supervisor's test
        .org 0x104
        JMP  h_swi1             ; SWI #1: report the caller's r1 and r2
        .org 0x108

FAR  = 8
FSR  = 9
CTX  = 10
MAPA = 11
MAPD = 12
BANK = 13

USERPAGE = 0x90                 ; a page for user data, VA 0x90000
NOPAGE   = 0xA0                 ; a page left unmapped, VA 0xA0000
ROPAGE   = 0xB0                 ; read only
NXPAGE   = 0xC0                 ; no execute

; ---- exception handlers: record what happened, then resume ----

; the common part: r1 = the vector's number. Records it, the saved PC,
; FAR and FSR; skips `skip` bytes of the faulting instruction (0: retry it)
trapped:
        MOV  [t_vec], r1
        MOV  r1, [sp + 4]       ; the saved PC
        MOV  [t_pc], r1
        MFSR r1, FAR
        MOV  [t_far], r1
        MFSR r1, FSR
        MOV  [t_fsr], r1
        MOV  r1, [sp]           ; the saved flags word
        MOV  [t_flags], r1
        INC  [t_count]
        MOV  r1, [sp + 4]
        ADD  r1, [skip]
        MOV  [sp + 4], r1
        MOV  r1, [t_save1]
        RTI

h_illegal: MOV [t_save1], r1
        MOV  r1, #0x08
        BRA  trapped
h_divide: MOV [t_save1], r1
        MOV  r1, #0x10
        BRA  trapped
h_address: MOV [t_save1], r1
        MOV  r1, #0x14
        BRA  trapped
h_tag:  MOV  [t_save1], r1
        MOV  r1, #0x18
        BRA  trapped
h_priv: MOV  [t_save1], r1
        MOV  r1, #0x1C
        BRA  trapped

; a page fault: when fixpage is set, map the faulting page (context 0)
; with fixentry's flags onto the same physical page and retry
h_page: MOV  [t_save1], r1
        MOVS r1, [fixpage]
        BEQ  .rec
        SAVE r2-r3
        MFSR r2, FAR
        LSR  r2, #12            ; the page
        MTSR MAPA, r2
        LSL  r2, #12
        OR   r2, [fixentry]
        MTSR MAPD, r2
        RESTORE r2-r3
        CLR  [fixpage]
.rec:   MOV  r1, #0x20
        BRA  trapped

h_trace: INC [traces]
        MOV  [t_save1], r1
        MOV  r1, [sp + 4]
        MOV  [t_pc], r1
        MOV  r1, [t_save1]
        RTI

h_irq:  RTI

; SWI #0: the user's test is over. Drop the frame and go back to where
; run_user was called from.
h_exit: MFSR r1, flags
        MOV  [exit_flags], r1
        LEA  sp, [sp + 8]
        JMP  [continue]

; SWI #1: the caller's r1 and r2, read from its bank
h_swi1: SAVE r1-r2
        MFUR r1, r1
        MOV  [u_r1], r1
        MFUR r2, r2
        MOV  [u_r2], r2
        MOV  r1, [sp + 8]       ; the flags the SWI saved
        MOV  [swi_flags], r1
        RESTORE r1-r2
        RTI

; run_user: r1 = an entry point; runs it in user mode, bank 1, until it
; does SWI #0
run_user:
        MOV  r2, #1
        MTSR BANK, r2
        MOV  r2, #0xF0000
        MTUR sp, r2
        LEA  r2, [.back]
        MOV  [continue], r2
        PUSH r1                 ; the PC
        CLR  r2
        PUSH r2                 ; the flags: user mode, interrupts off
        RTI
.back:  RET

; ---- the tests ----

start:  JMP  #0x80000000 + .win  ; run in the window, where ctx doesn't matter
.win:   MOV  sp, #0x80100000
        LEA  r1, [s_title]
        BSR  puts

        ; ---- boot state: supervisor mode, ctx 0, bank 0
        LEA  r1, [s_boot]
        BSR  puts
        MFSR r2, flags
        AND  r2, #0x70          ; S, T and I
        MFSR r3, CTX
        OR   r2, r3
        MFSR r3, BANK
        OR   r2, r3
        MOV  r1, #0x20
        BSR  expect

        ; ---- the special registers
        LEA  r1, [s_spr]
        BSR  puts
        MOV  r2, #0xFF
        MTSR CTX, r2
        MFSR r4, CTX            ; 0x7F
        CLR  r2
        MTSR CTX, r2
        MOV  r2, #0x1234
        MTSR BANK, r2
        MFSR r5, BANK           ; 0x34
        CLR  r2
        MTSR BANK, r2
        MOV  r2, #0x12345
        MTSR MAPA, r2
        MFSR r6, MAPA
        MOV  r2, #7
        MTSR 3, r2              ; reserved: ignored, reads 0
        MFSR r3, 3
        MFSR r8, 14
        MFSR r9, 15
        LSL  r4, #24
        LSL  r5, #16
        OR   r4, r5
        OR   r4, r3
        OR   r4, r8
        OR   r4, r9
        MOV  r2, r4
        MOV  r1, #0x7F340000
        BSR  expect
        LEA  r1, [s_mapa]
        BSR  puts
        MOV  r2, r6
        MOV  r1, #0x12345
        BSR  expect

        ; ---- the page map: write entries through mapd, read them back
        LEA  r1, [s_mapd]
        BSR  puts
        MOV  r2, #0x1F00        ; context 1, page 0xF00
        MTSR MAPA, r2
        MOV  r3, #0x12345007
        MTSR MAPD, r3
        MOV  r3, #0xABCDE003
        MTSR MAPD, r3           ; mapa moved on: page 0xF01
        MOV  r3, #0x55555FF5    ; bits 11-3 read as 0
        MTSR MAPD, r3
        MTSR MAPA, r2
        MFSR r4, MAPD
        MOV  r1, #0x1F01
        MTSR MAPA, r1
        MFSR r5, MAPD
        MOV  r1, #0x1F02
        MTSR MAPA, r1
        MFSR r6, MAPD
        MFSR r7, MAPA
        XOR  r4, #0x12345007
        XOR  r5, #0xABCDE003
        XOR  r6, #0x55555005
        OR   r4, r5
        OR   r4, r6
        XOR  r7, #0x1F02
        OR   r4, r7
        MOV  r2, r4
        CLR  r1
        BSR  expect

        ; set up the test pages in context 0
        MOV  r2, #USERPAGE
        MTSR MAPA, r2
        MOV  r3, #USERPAGE << 12 | 7
        MTSR MAPD, r3
        MOV  r2, #NOPAGE
        MTSR MAPA, r2
        CLR  r3
        MTSR MAPD, r3           ; invalid
        MOV  r2, #ROPAGE
        MTSR MAPA, r2
        MOV  r3, #ROPAGE << 12 | 5      ; X and V, no W
        MTSR MAPD, r3
        MOV  r2, #NXPAGE
        MTSR MAPA, r2
        MOV  r3, #NXPAGE << 12 | 3      ; W and V, no X
        MTSR MAPD, r3
        MOV  r1, #0x2468ACE0
        MOV  [USERPAGE << 12], r1       ; the user's data
        MOV  r1, #0x0FF1CE
        MOV  [0x80000000 | ROPAGE << 12], r1   ; through the window: the page has no W

        ; ---- the window: physical memory at 0x8000_0000 + pa
        LEA  r1, [s_window]
        BSR  puts
        MOV  r2, [0x80000000 | USERPAGE << 12]
        MOV  r1, #0x2468ACE0
        BSR  expect

        ; ---- user mode: bank 1, set through MTUR, read through MFUR
        LEA  r1, [s_user]
        BSR  puts
        MOV  r2, #1
        MTSR BANK, r2
        MOV  r2, #0x1111
        MTUR r1, r2
        MOV  r2, #0x2222
        MTUR r2, r2
        MOV  r1, #0x5A5A
        MOV  r9, #0x9999        ; the supervisor's r9: must survive
        MOV  r1, #u_banks
        BSR  run_user
        MOV  r2, [u_r1]         ; the user's r1 + r2 at its SWI #1
        ADD  r2, [u_r2]
        CMP  r9, #0x9999
        BEQ  .r9ok
        MOV  r2, #-1
.r9ok:  MOV  r1, #0x1111 + 0x2222 + 0x10
        BSR  expect
        LEA  r1, [s_swiflags]   ; SWI from user mode saved S = 0
        BSR  puts
        MOV  r2, [swi_flags]
        AND  r2, #0x20
        CLR  r1
        BSR  expect
        LEA  r1, [s_exitflags]  ; and the handler runs with S set, I clear
        BSR  puts
        MOV  r2, [exit_flags]
        AND  r2, #0x70
        MOV  r1, #0x20
        BSR  expect

        ; ---- privilege violations in user mode
        LEA  r1, [s_priv]
        BSR  puts
        CLR  [t_count]
        MOV  r1, #2
        MOV  [skip], r1
        MOV  r1, #u_priv
        BSR  run_user
        MOV  r2, [t_count]      ; EI, DI, HALT, RTI, MFSR far, MTSR ctx, MFUR, MTUR
        MOV  r1, #8
        BSR  expect
        LEA  r1, [s_privvec]
        BSR  puts
        MOV  r2, [t_vec]
        MOV  r1, #0x1C
        BSR  expect

        ; ---- MTSR flags in user mode changes only N Z C V
        LEA  r1, [s_uflags]
        BSR  puts
        MOV  r1, #u_flags
        BSR  run_user
        MOV  r2, [u_r1]         ; the user's flags after MTSR flags, #0x7F
        MOV  r1, #0x0F
        BSR  expect

        ; ---- page faults: an invalid page, retried after the handler maps it
        LEA  r1, [s_fault]
        BSR  puts
        CLR  [t_count]
        CLR  [skip]
        MOV  r1, #1
        MOV  [fixpage], r1
        MOV  r1, #7
        MOV  [fixentry], r1
        MOV  r1, #u_fault
        BSR  run_user
        MOV  r2, [t_fsr]        ; invalid entry, a user read
        MOV  r1, #0x01
        BSR  expect
        LEA  r1, [s_far]
        BSR  puts
        MOV  r2, [t_far]
        MOV  r1, #NOPAGE << 12 | 0x124
        BSR  expect
        LEA  r1, [s_retry]      ; the retried load got the value; the
        BSR  puts               ; auto-increment happened once
        MOV  r2, [u_r1]
        ADD  r2, [u_r2]
        MOV  r1, #0x99 + (NOPAGE << 12 | 0x128)
        BSR  expect

        ; unmap the page again for the next test
        MOV  r2, #NOPAGE
        MTSR MAPA, r2
        CLR  r3
        MTSR MAPD, r3

        ; ---- a store to a page without W
        LEA  r1, [s_wfault]
        BSR  puts
        CLR  [fixpage]
        MOV  r1, #4
        MOV  [skip], r1
        MOV  r1, #u_wfault
        BSR  run_user
        MOV  r2, [t_fsr]
        MOV  r1, #0x22          ; no W, a store
        BSR  expect
        LEA  r1, [s_wkept]      ; and memory, and the base register, unchanged
        BSR  puts
        MOV  r2, [ROPAGE << 12]
        ADD  r2, [u_r2]
        MOV  r1, #0x0FF1CE + (ROPAGE << 12)
        BSR  expect

        ; ---- a fetch from a page without X
        LEA  r1, [s_xfault]
        BSR  puts
        MOV  r1, #1
        MOV  [fixpage], r1
        MOV  r1, #7
        MOV  [fixentry], r1
        CLR  [skip]
        ; copy the user routine u_nx into the NX page, then run it there
        MOV  r1, #u_nx
        MOV  r2, #NXPAGE << 12
        MOV  r3, #(u_nx_end - u_nx + 3) / 4
.cp:    MOV  r4, [r1]+
        MOV  [r2]+, r4
        DBNZ r3, .cp
        MOV  r1, #NXPAGE << 12
        BSR  run_user
        MOV  r2, [t_fsr]
        MOV  r1, #0x44          ; no X, a fetch
        BSR  expect
        LEA  r1, [s_xpc]        ; the saved PC is the instruction's own
        BSR  puts
        MOV  r2, [t_pc]
        MOV  r1, #NXPAGE << 12
        BSR  expect

        ; ---- the user's bit 31, and the gap between 16 MB and 2 GB
        LEA  r1, [s_range]
        BSR  puts
        CLR  [fixpage]
        MOV  r1, #6
        MOV  [skip], r1
        CLR  [t_fsr]
        MOV  r1, #u_high
        BSR  run_user
        MOV  r2, [u_r1]         ; the two faults' FSRs, as the user saw them
        MOV  r1, #0x1008
        BSR  expect

        ; ---- the supervisor's own faults: bit 7, a translated address
        LEA  r1, [s_sfault]
        BSR  puts
        CLR  [fixpage]
        MOV  r1, #6
        MOV  [skip], r1
        MOV  r1, [NOPAGE << 12]
        MOV  r2, [t_fsr]
        MOV  r1, #0x81          ; invalid, in supervisor mode
        BSR  expect

        ; ---- misaligned accesses: the address error vector, FAR
        LEA  r1, [s_mis]
        BSR  puts
        MOV  r1, #2
        MOV  [skip], r1
        MOV  r3, #USERPAGE << 12 | 2
        MOV  r4, [r3]+          ; a word at an address of 2: r3 unchanged
        MOV  r2, [t_vec]
        LSL  r2, #24
        OR   r2, [t_far]
        SUB  r2, r3             ; ... + (FAR - r3) = 0x14000000 + 0
        MOV  r1, #0x14000000
        BSR  expect

        ; ---- an empty slot: a bus error, through the address error vector
        LEA  r1, [s_buserr]
        BSR  puts
        MOV  r1, #6
        MOV  [skip], r1
        CLR  [t_vec]
        MOV  r2, [0xA8000000]   ; slot 5 (the window, physical 0x2800_0000)
        MOV  r2, [t_vec]
        LSL  r2, #24
        MOV  r3, [t_far]
        LSR  r3, #24
        OR   r2, r3
        MOV  r1, #0x140000A8
        BSR  expect

        ; ---- divide error, illegal instruction, tag trap
        LEA  r1, [s_traps]
        BSR  puts
        MOV  r1, #2
        MOV  [skip], r1
        CLR  r2
        MOV  r3, #5
        DIVU r3, r2
        MOV  r5, [t_vec]
        .align 4
        .word 0x00FF00FF        ; two ILLEGAL parcels
        MOV  r6, [t_vec]
        MOV  r3, #3
        TADD r3, r3
        MOV  r7, [t_vec]
        LSL  r5, #16
        LSL  r6, #8
        OR   r5, r6
        OR   r5, r7
        MOV  r2, r5
        MOV  r1, #0x100818
        BSR  expect

        ; ---- trace: a trap after every instruction while T is set
        LEA  r1, [s_trace]
        BSR  puts
        CLR  [traces]
        MOV  r1, #u_trace
        BSR  run_user_traced
        MOV  r2, [traces]       ; the four instructions before the SWI (one
        MOV  r1, #4             ; that traps doesn't trace: the trap clears T)
        BSR  expect

        ; ---- interrupts in user mode come back to the user's bank
        LEA  r1, [s_done]
        BSR  puts
        HALT

; run_user_traced: as run_user, with T set in the flags RTI restores
run_user_traced:
        MOV  r2, #1
        MTSR BANK, r2
        MOV  r2, #0xF0000
        MTUR sp, r2
        LEA  r2, [.back]
        MOV  [continue], r2
        PUSH r1
        MOV  r2, #0x40          ; T
        PUSH r2
        RTI
.back:  RET

; expect: r1 = the value wanted, r2 = the value got: prints "ok" or both
expect: CMP  r1, r2
        BNE  .bad
        LEA  r1, [s_ok]
        BRA  puts
.bad:   SAVE r7-r8
        MOV  r8, r2
        MOV  r7, r1
        LEA  r1, [s_want]
        BSR  puts
        MOV  r1, r7
        MOV  r2, #8
        BSR  print_hex
        LEA  r1, [s_got]
        BSR  puts
        MOV  r1, r8
        MOV  r2, #8
        BSR  print_hex
        BSR  newline
        RESTORE r7-r8
        RET

; ---- user routines: they end with SWI #0 ----

u_banks:
        ADD  r1, #0x10          ; the user's own r1 (0x1111, set through MTUR)
        SWI  #1
        SWI  #0

u_priv: EI
        DI
        HALT
        RTI
        MFSR r1, FAR
        MTSR CTX, r1
        MFUR r1, r2
        MTUR r1, r2
        SWI  #0

u_flags:
        MOV  r1, #0x7F
        MTSR flags, r1
        MFSR r1, flags
        SWI  #1
        SWI  #0

u_fault:
        MOV  r2, #NOPAGE << 12 | 0x124
        MOV  r1, [r2]+          ; faults, is retried
        ADD  r1, #0x99
        SWI  #1
        SWI  #0

u_wfault:
        MOV  r2, #ROPAGE << 12
        MOV  [r2]+, r2          ; no W: skipped, r2 unchanged
        NOP
        SWI  #1
        SWI  #0

        .align 4
u_nx:   ADD  r1, #0             ; fetching this faults, until mapped with X
        SWI  #0
u_nx_end:

u_high: MOV  r2, [0x80001000]   ; bit 31 in user mode
        MOV  r1, [t_fsr]
        AND  r1, #0x1F
        LSL  r1, #8
        MOV  r2, [0x01000000]   ; 16 MB
        MOV  r3, [t_fsr]
        AND  r3, #0x1F
        OR   r1, r3
        SWI  #1
        SWI  #0

u_trace:
        NOP
        NOP
        NOP
        NOP
        SWI  #0

; ---- data ----

        .align 4
t_vec:     .word 0
t_pc:      .word 0
t_far:     .word 0
t_fsr:     .word 0
t_flags:   .word 0
t_count:   .word 0
t_save1:   .word 0
skip:      .word 0
fixpage:   .word 0
fixentry:  .word 0
traces:    .word 0
continue:  .word 0
exit_flags: .word 0
swi_flags: .word 0
u_r1:      .word 0
u_r2:      .word 0

s_title:   .asciz "RFC 0029 on the draft 2 CPU\n"
s_boot:    .asciz "boot state: "
s_spr:     .asciz "special registers: "
s_mapa:    .asciz "mapa: "
s_mapd:    .asciz "map through mapd: "
s_window:  .asciz "the window: "
s_user:    .asciz "user mode, banks, MTUR, MFUR: "
s_swiflags: .asciz "SWI saves S = 0: "
s_exitflags: .asciz "handlers run with S, without I: "
s_priv:    .asciz "privileged instructions trap: "
s_privvec: .asciz "privilege violation vector: "
s_uflags:  .asciz "user MTSR flags: "
s_fault:   .asciz "page fault, FSR: "
s_far:     .asciz "page fault, FAR: "
s_retry:   .asciz "retried after mapping: "
s_wfault:  .asciz "store without W, FSR: "
s_wkept:   .asciz "store without W changed nothing: "
s_xfault:  .asciz "fetch without X, FSR: "
s_xpc:     .asciz "fetch fault saves its PC: "
s_range:   .asciz "user bit 31, and 16 MB-2 GB: "
s_sfault:  .asciz "supervisor page fault: "
s_mis:     .asciz "misaligned word, FAR, base kept: "
s_buserr:  .asciz "empty slot: "
s_traps:   .asciz "divide, illegal, tag vectors: "
s_trace:   .asciz "trace: "
s_done:    .asciz "done\n"
s_ok:      .asciz "ok\n"
s_want:    .asciz "want "
s_got:     .asciz " got "
        .align 2

        .include "../../v2_isa/programs/lib/console.s"
        .include "../../v2_isa/programs/lib/print.s"
