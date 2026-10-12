; Startup code and vector table (draft 1a). Include this first; define `main`.
; main returns -> HALT. IRQs are ignored (RTI); traps print "TRAP" and halt.

        .org 0x00
        JMP  __start            ; reset
        .org 0x04
        RTI                     ; IRQ (unused by default)
        .org 0x08
        JMP  __trap             ; illegal instruction
        .org 0x0C
        JMP  __trap             ; SWI
        .org 0x10
        JMP  __trap             ; divide error
        .org 0x14
        JMP  __trap             ; address error
        .org 0x18

__start:
        LI   sp, #0x100000      ; top of RAM
        CALL main
        HALT

__trap: LEA  r1, .msg
.loop:  LDB  r2, [r1]
        BEQ  .done
        STB  r2, [0xFFFFFF00]
        ADDI r1, 1
        BRA  .loop
.done:  HALT
.msg:   .asciz "TRAP\n"
        .align 2
