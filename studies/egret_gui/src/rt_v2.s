; Egret's start-up code for draft 2 (studies/egret/vm/rt_v2.s), for the
; GUI build: the same, but the IRQ acknowledges the timer, and gui_wait
; sleeps until it ticks.

        .far _main, trap_msg

        .org 0x00
        JMP  __start            ; reset
        .org 0x04
        JMP  __irq              ; IRQ: the timer
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
        .space 4
        ; 0x20 false, 0x28 nil, 0x30 true: a class word and a header word
        ; each, filled in at start-up
        .space 24

__start:
        MOV  sp, #0x100000      ; top of RAM
        CALL #_main             ; a 32-bit address: main can be more than 64 KB on
        HALT

; (the handlers next to their vectors: the rest of the code may be more
; than 64 KB on)

; the timer's tick: acknowledge it (any write does), and that's all
; (gui_wait was waiting)
__irq:  MOV  [0xFFFFFF0C], r0
        RTI

__trap: LEA  r1, [trap_msg]
.loop:  MOVS r2, byte [r1]+
        BEQ  .done
        MOV  byte [0xFFFFFF00], r2
        BRA  .loop
.done:  HALT
trap_msg: .asciz "TRAP\n"
        .align 2

; The rest with the other code, where 16-bit calls from C reach it
        .section .text.egret_rt
_exit:
_abort: HALT

; void gui_wait(void): sleep until the next tick (the simulator skips the
; cycles in between); returns at once if a tick came while we were busy
_gui_wait:
        EI
        HALT
        DI
        RET

; int ejsetjmp(ejmp_buf b): b = r8-r14, sp, the return address (in r7, the
; link register)
_ejsetjmp:
        MOV  [r1], r8
        MOV  [r1 + 4], r9
        MOV  [r1 + 8], r10
        MOV  [r1 + 12], r11
        MOV  [r1 + 16], r12
        MOV  [r1 + 20], r13
        MOV  [r1 + 24], r14
        MOV  [r1 + 28], sp
        MOV  [r1 + 32], r7
        MOV  r1, #0
        RET

; void ejlongjmp(ejmp_buf b, int v): return v from ejsetjmp again
_ejlongjmp:
        MOV  r8, [r1]
        MOV  r9, [r1 + 4]
        MOV  r10, [r1 + 8]
        MOV  r11, [r1 + 12]
        MOV  r12, [r1 + 16]
        MOV  r13, [r1 + 20]
        MOV  r14, [r1 + 24]
        MOV  sp, [r1 + 28]
        MOV  r7, [r1 + 32]      ; setjmp's return address
        MOV  r1, r2
        RET
