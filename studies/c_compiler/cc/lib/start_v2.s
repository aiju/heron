; C start-up code (draft 2): vectors, stack, call main, halt.
; exit() and abort() halt the machine; a trap prints "TRAP" and halts.

        .org 0x00
        JMP  __start            ; reset
        .org 0x04
        RTI                     ; IRQ (unused)
        .org 0x08
        JMP  __trap             ; illegal instruction
        .org 0x0C
        JMP  __trap             ; SWI
        .org 0x10
        JMP  __trap             ; divide error
        .org 0x14
        JMP  __trap             ; address error
        .org 0x18
        JMP  __trap             ; tag check (the tagged operations)
        .org 0x1C

__start:
        MOV  sp, #0x100000      ; top of RAM
        CALL _main
_exit:
_abort: HALT

__trap: LEA  r1, [.msg]
.loop:  MOVS r2, byte [r1]+
        BEQ  .done
        MOV  byte [0xFFFFFF00], r2
        BRA  .loop
.done:  HALT
.msg:   .asciz "TRAP\n"
        .align 2
