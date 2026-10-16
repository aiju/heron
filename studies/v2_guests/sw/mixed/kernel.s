; A kernel in draft 2 code whose user processes run other instruction
; sets (studies/v2_guests/mixed.py): round-robin on the timer, a process
; to each context and bank, its pages mapped as it touches them, SWI #0
; to exit. It doesn't know how a process's instructions are encoded: the
; status word's ISA bits, which RTI loads, pick the decode table page. It
; reads them only to say what each process was.
;
; The harness, as a boot loader would, has put each process's image in
; physical memory and mapped it from VA 0 in the process's context, mapped
; the process's console card at VA 0xFFF000, and filled in nproc and
; procs. The kernel is linked at 0x8000_0000, in the supervisor's window,
; so its code and data are where they are whatever context is current.
;

P_CTX    = 0
P_BANK   = 4
P_PC     = 8
P_FLAGS  = 12                   ; the status word RTI loads: ISA << 8, I
P_ALIVE  = 16
P_SLICES = 20
P_FAULTS = 24
P_END    = 28                   ; 0 after SWI #0, else the vector it died by
PSIZE    = 32

TIMER    = 0xFFFFFF08
TFLAG    = 0xFFFFFF0C
USER_TOP = 0x100000             ; pages below this are mapped when touched

FAR  = 8
FSR  = 9
CTX  = 10
MAPA = 11
MAPD = 12
BANK = 13

        .org 0x80000000
        JMP  start              ; reset
        .org 0x80000004
        JMP  h_irq              ; interrupt
        .org 0x80000008
        JMP  h_illegal
        .org 0x80000010
        JMP  h_divide
        .org 0x80000014
        JMP  h_address
        .org 0x80000018
        JMP  h_tag
        .org 0x8000001C
        JMP  h_priv
        .org 0x80000020
        JMP  h_page
        .org 0x80000024
        JMP  h_trace
        .org 0x80000100
        JMP  h_exit             ; SWI #0: the process is done
        .org 0x80000104

start:  MOV  sp, #0x80200000    ; the top of the CPU card's 2 MB
        LEA  r1, [s_title]
        BSR  puts
        MOV  r1, [period]
        MOV  [TIMER], r1
        CLR  r1

; run: r1 = the process to run: its context and bank, then RTI to it
run:    MOV  [cur], r1
        BSR  entry
        MOV  r2, [r1 + P_CTX]
        MTSR CTX, r2
        MOV  r2, [r1 + P_BANK]
        MTSR BANK, r2
        MOV  r2, [r1 + P_SLICES]
        INC  r2
        MOV  [r1 + P_SLICES], r2
        MOV  r2, [r1 + P_PC]
        PUSH r2
        MOV  r2, [r1 + P_FLAGS]
        PUSH r2
        RTI

; entry: r1 = process r1's entry in procs. Clobbers r2
entry:  LSL  r1, #5
        MOV  r2, #procs
        ADD  r1, r2
        RET

; the timer: keep the process's PC and status word, run the next one
h_irq:  MOV  [TFLAG], r1        ; acknowledge
        MOV  r1, [cur]
        BSR  entry
        MOV  r2, [sp]           ; the frame: the status word, then the PC
        MOV  [r1 + P_FLAGS], r2
        MOV  r2, [sp + 4]
        MOV  [r1 + P_PC], r2
        LEA  sp, [sp + 8]

; next: the next live process after cur, round robin; when none is left,
; the summary
next:   MOV  r3, [cur]
        MOV  r4, [nproc]
        MOV  r5, r4
.try:   INC  r3
        CMP  r3, r4
        BLO  .in
        CLR  r3
.in:    MOV  r1, r3
        BSR  entry
        MOV  r2, [r1 + P_ALIVE]
        TST  r2, r2
        BNE  .go
        DBNZ r5, .try
        LEA  r1, [s_done]
        BSR  puts
        HALT
.go:    MOV  r1, r3
        BRA  run

; a page fault: below USER_TOP, a user access to an invalid entry gets a
; fresh page (bss, heap and stack are made this way), and the instruction
; runs again. Anything else ends the process.
h_page: MFSR r1, FAR
        CMP  r1, #USER_TOP
        BHS  .bad
        MFSR r2, FSR
        AND  r2, #0x8F          ; S and the reason: a user's, invalid entry
        CMP  r2, #0x01
        BNE  .bad
        LSR  r1, #12
        MFSR r2, CTX
        LSL  r2, #12
        OR   r1, r2
        MTSR MAPA, r1           ; context << 12 | page
        MOV  r3, [freepage]
        MOV  r2, r3
        ADD  r2, #0x1000
        MOV  [freepage], r2
        OR   r3, #7             ; valid, writable, executable
        MTSR MAPD, r3
        MOV  r1, [cur]
        BSR  entry
        MOV  r2, [r1 + P_FAULTS]
        INC  r2
        MOV  [r1 + P_FAULTS], r2
        RTI
.bad:   MOV  r6, #0x20
        BRA  finish

h_illegal: MOV r6, #0x08
        BRA  finish
h_divide: MOV r6, #0x10
        BRA  finish
h_address: MOV r6, #0x14
        BRA  finish
h_tag:  MOV  r6, #0x18
        BRA  finish
h_priv: MOV  r6, #0x1C
        BRA  finish
h_trace: MOV r6, #0x24
        BRA  finish
h_exit: CLR  r6

; finish: the process is done, r6 = how (0: SWI #0, else the vector); the
; frame is on the stack. Says so, and runs the next one.
finish: MOV  r1, [cur]
        BSR  entry
        MOV  r8, r1
        CLR  r2
        MOV  [r8 + P_ALIVE], r2
        MOV  [r8 + P_END], r6
        MOV  r2, [sp]
        MOV  [r8 + P_FLAGS], r2
        MOV  r2, [sp + 4]
        MOV  [r8 + P_PC], r2
        LEA  sp, [sp + 8]
        LEA  r1, [s_proc]
        BSR  puts
        MOV  r1, [cur]
        BSR  print_u32
        LEA  r1, [s_open]
        BSR  puts
        MOV  r1, [r8 + P_FLAGS]
        LSR  r1, #8
        AND  r1, #3
        LSL  r1, #2
        MOV  r2, #isa_names
        ADD  r1, r2
        MOV  r1, [r1]
        BSR  puts
        TST  r6, r6
        BNE  .died
        LEA  r1, [s_exited]
        BSR  puts
        BRA  .counts
.died:  LEA  r1, [s_vector]
        BSR  puts
        MOV  r1, r6
        MOV  r2, #2
        BSR  print_hex
        LEA  r1, [s_at]
        BSR  puts
        MOV  r1, [r8 + P_PC]
        MOV  r2, #8
        BSR  print_hex
.counts: LEA r1, [s_slices]
        BSR  puts
        MOV  r1, [r8 + P_SLICES]
        BSR  print_u32
        LEA  r1, [s_faults]
        BSR  puts
        MOV  r1, [r8 + P_FAULTS]
        BSR  print_u32
        BSR  newline
        BRA  next

        .align 4
period:   .word 20000           ; the time slice, in cycles
freepage: .word 0x100000        ; the next free physical page
cur:      .word 0
nproc:    .word 0
procs:    .space 8 * PSIZE

isa_names: .word s_isa0, s_isa1, s_isa2, s_isa3
s_isa0:   .asciz "draft 2"
s_isa1:   .asciz "Thumb"
s_isa2:   .asciz "ISA 2"
s_isa3:   .asciz "ISA 3"
s_title:  .asciz "kernel: draft 2, user processes in other instruction sets\n"
s_proc:   .asciz "process "
s_open:   .asciz " ("
s_exited: .asciz "): exited"
s_vector: .asciz "): stopped by vector "
s_at:     .asciz " at PC "
s_slices: .asciz ", time slices "
s_faults: .asciz ", pages mapped on demand "
s_done:   .asciz "kernel: no process left\n"
        .align 2

        .include "../../../v2_isa/programs/lib/console.s"

; print_u32: r1 unsigned, in decimal. Clobbers r1-r5. By subtracting
; powers of ten: no divide, whose remainder the tools in this tree and the
; v2_hw microcode put in different places. (And the library's print.s
; indexes a table by a 24-bit address, which the window isn't.)
print_u32:
        MOV  r4, #pow10
        CLR  r5                 ; not 0 once a digit isn't
.next:  MOV  r2, [r4]+
        CLR  r3
.sub:   CMP  r1, r2
        BLO  .digit
        SUB  r1, r2
        INC  r3
        BRA  .sub
.digit: OR   r5, r3
        CMP  r2, #1
        BEQ  .out               ; the units always print
        TST  r5, r5
        BEQ  .next              ; no leading zeros
.out:   ADD  r3, #'0'
        MOV  byte [CONSOLE], r3
        CMP  r2, #1
        BNE  .next
        RET

        .align 4
pow10:  .word 1000000000, 100000000, 10000000, 1000000, 100000, 10000, 1000, 100, 10, 1

; print_hex: the low r2 hex digits of r1. Clobbers r1-r4
print_hex:
        MOV  r3, r2
        LSL  r3, #2
        ROR  r1, r3
.loop:  ROR  r1, #28            ; the next digit to bits 3-0
        MOV  r3, r1
        AND  r3, #15
        CMP  r3, #10
        BLO  .dec
        ADD  r3, #'A' - '0' - 10
.dec:   ADD  r3, #'0'
        MOV  byte [CONSOLE], r3
        DBNZ r2, .loop
        RET
