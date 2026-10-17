; addrerr: draft 2's address error (RFC 0028, 2; RFC 0029, 6). A half at
; an odd address, or a word at one that isn't a multiple of 4, traps to
; 0x14 with the flags word and the faulting instruction's own address on
; the stack, and the instruction changes nothing. Each case sets r1-r6
; and the flags, runs one instruction, and prints where the trap was taken
; (from the instruction's address, or "-" for none), the flags word it
; saved and r1-r7, and the two words it might have stored to. The last
; cases are accesses that mustn't trap. Heron Mini (RFC 0041) must print
; what draft 2's simulator does.
;
; A call writes the return address into r7 (RFC 0028, 5.7).
;
;! input: "x"

        .org 0x00
        JMP  start              ; reset
        .org 0x04
        JMP  fatal              ; IRQ
        .org 0x08
        JMP  fatal              ; illegal instruction
        .org 0x0C
        JMP  fatal              ; SWI
        .org 0x10
        JMP  fatal              ; divide error
        .org 0x14
        JMP  addr_err           ; address error
        .org 0x18
        JMP  fatal              ; tag check
        .org 0x1C

start:  MOV  sp, #0x100000
        CALL main
        HALT

; the address error: the saved PC into r10, the flags word into r11, and
; on at r9
addr_err:
        MOV  r10, [sp + 4]
        MOV  r11, [sp]
        MOV  [sp + 4], r9
        RTI

fatal:  LEA  r1, [s_fatal]
        BSR  puts
        HALT

; setup: r1 = 0x11111111, r2 = buf (aligned), r3 = buf + 1, r4 = buf + 2,
; r5 = 0x55555555, r6 = 1, r10 = r11 = -1; buf's two words 0xB0B0B0B0 and
; 0xB4B4B4B4, the jump table's word; Z set, the other flags clear
setup:  MOV  r1, #0xB0B0B0B0
        MOV  [buf], r1
        MOV  r1, #0xB4B4B4B4
        MOV  [buf + 4], r1
        MOV  r1, #0x11111111
        LEA  r2, [buf]
        LEA  r3, [buf + 1]
        LEA  r4, [buf + 2]
        MOV  r5, #0x55555555
        MOV  r6, #1
        MOV  r10, #-1
        MOV  r11, #-1
        CMP  r6, r6
        RET

; report: the case's results, r8 = the instruction's address: the trap's
; offset from it, the saved flags word, r1-r7, buf's words
report: MOV  [save], r1
        MOV  [save + 4], r2
        MOV  [save + 8], r3
        MOV  [save + 12], r4
        MOV  [save + 16], r5
        MOV  [save + 20], r6
        MOV  [save + 24], r7
        MOV  r6, r7             ; the return address
        CMP  r10, #-1
        BEQ  .none
        MOV  r1, r10
        SUB  r1, r8
        MOV  r2, #2
        BSR  print_hex
        BRA  .flags
.none:  MOV  r1, #'-'
        BSR  putc
.flags: BSR  space
        MOV  r1, r11
        MOV  r2, #2
        BSR  print_hex
        LEA  r5, [save]
        MOV  r0, #7
.reg:   BSR  space
        MOV  r1, [r5]+
        MOV  r2, #8
        BSR  print_hex
        DBNZ r0, .reg
        BSR  space
        MOV  r1, [buf]
        MOV  r2, #8
        BSR  print_hex
        BSR  space
        MOV  r1, [buf + 4]
        MOV  r2, #8
        BSR  print_hex
        BSR  newline
        JMP  r6

main:   PUSH r7
        LEA  r1, [s_title]
        BSR  puts

        ; word loads
        LEA  r8, [.i1]
        LEA  r9, [.n1]
        BSR  setup
.i1:    MOV  r1, [r2 - 1]
.n1:    BSR  report
        LEA  r8, [.i2]
        LEA  r9, [.n2]
        BSR  setup
.i2:    MOV  r1, [r2 + 3]
.n2:    BSR  report
        LEA  r8, [.i3]
        LEA  r9, [.n3]
        BSR  setup
.i3:    MOV  r1, [r4]
.n3:    BSR  report
        LEA  r8, [.i4]
        LEA  r9, [.n4]
        BSR  setup
.i4:    MOVS r1, [r3]
.n4:    BSR  report
        ; a half load
        LEA  r8, [.i5]
        LEA  r9, [.n5]
        BSR  setup
.i5:    MOV  r1, half [r3]
.n5:    BSR  report
        ; stores
        LEA  r8, [.i6]
        LEA  r9, [.n6]
        BSR  setup
.i6:    MOV  [r3], r5
.n6:    BSR  report
        LEA  r8, [.i7]
        LEA  r9, [.n7]
        BSR  setup
.i7:    MOV  half [r3], r5
.n7:    BSR  report
        LEA  r8, [.i8]
        LEA  r9, [.n8]
        BSR  setup
.i8:    MOV  [r4 + 0x100], r5
.n8:    BSR  report
        ; post-increment and pre-decrement: the register doesn't change
        LEA  r8, [.i9]
        LEA  r9, [.n9]
        BSR  setup
.i9:    MOV  r1, [r3]+
.n9:    BSR  report
        LEA  r8, [.i10]
        LEA  r9, [.n10]
        BSR  setup
.i10:   MOV  -[r4], r5
.n10:   BSR  report
        ; arithmetic with a memory operand, and on memory (DEC, INC)
        LEA  r8, [.i11]
        LEA  r9, [.n11]
        BSR  setup
.i11:   ADD  r1, [r3]
.n11:   BSR  report
        LEA  r8, [.i12]
        LEA  r9, [.n12]
        BSR  setup
.i12:   DEC  [r4]
.n12:   BSR  report
        LEA  r8, [.i13]
        LEA  r9, [.n13]
        BSR  setup
.i13:   INC  [r3]
.n13:   BSR  report
        ; absolute and indexed addresses: longer instructions
        LEA  r8, [.i14]
        LEA  r9, [.n14]
        BSR  setup
.i14:   MOV  r1, [buf + 2]
.n14:   BSR  report
        LEA  r8, [.i15]
        LEA  r9, [.n15]
        BSR  setup
.i15:   MOV  r1, [r2 + r6*4 + 1]
.n15:   BSR  report
        LEA  r8, [.i16]
        LEA  r9, [.n16]
        BSR  setup
.i16:   MOV  [buf + 0x10001], r5
.n16:   BSR  report
        ; jumps and calls through memory: r7 doesn't change
        LEA  r8, [.i17]
        LEA  r9, [.n17]
        BSR  setup
.i17:   JMP  [r2 + 1]
.n17:   BSR  report
        LEA  r8, [.i18]
        LEA  r9, [.n18]
        BSR  setup
.i18:   CALL [r2 + 1]
.n18:   BSR  report
        ; LDM and STM from a misaligned base
        LEA  r8, [.i19]
        LEA  r9, [.n19]
        BSR  setup
.i19:   LDM  r3, r4-r5
.n19:   BSR  report
        LEA  r8, [.i20]
        LEA  r9, [.n20]
        BSR  setup
.i20:   STM  r4, r5-r6
.n20:   BSR  report
        ; the console, misaligned: no character read or written
        LEA  r8, [.i21]
        LEA  r9, [.n21]
        BSR  setup
.i21:   MOV  r1, [CONSOLE + 1]
.n21:   BSR  report
        LEA  r8, [.i22]
        LEA  r9, [.n22]
        BSR  setup
.i22:   MOV  half [CONSOLE + 1], r5
.n22:   BSR  report
        ; no trap: a byte at an odd address, a half at buf + 2
        LEA  r8, [.i23]
        LEA  r9, [.n23]
        BSR  setup
.i23:   MOV  r1, byte [r3]
.n23:   BSR  report
        LEA  r8, [.i24]
        LEA  r9, [.n24]
        BSR  setup
.i24:   MOV  half [r4], r5
.n24:   BSR  report

        ; the console's input is still all there
        BSR  getc
        BSR  putc
        BSR  newline
        POP  r7
        RET

        .align 4
buf:    .word 0, 0, 0, 0
save:   .space 28
s_title: .asciz "address errors\n"
s_fatal: .asciz "TRAP\n"
        .align 2

        .include "../../../v2_isa/programs/lib/console.s"
        .include "../../../v2_isa/programs/lib/print.s"
