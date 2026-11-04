; The benchmark's start code for hand-written workloads (draft 2): the
; vectors at 0, the stack at the top of the first megabyte, a call to
; `main`, and HALT when it returns. A trap prints "TRAP" and halts, which
; the harness reports as a failure. The C workloads use the C compiler's
; start code (studies/c_compiler/cc/lib/start_v2.s), which is the same
; apart from calling `_main`.

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
        MOV  sp, #0x100000      ; the top of the first megabyte
        CALL main
        HALT

__trap: LEA  r1, [.msg]
.loop:  MOVS r2, byte [r1]+
        BEQ  .done
        MOV  byte [0xFFFFFF00], r2
        BRA  .loop
.done:  HALT
.msg:   .asciz "TRAP\n"
        .align 2
