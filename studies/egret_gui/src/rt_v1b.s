; Egret's start-up code for draft 1b (studies/egret/vm/rt_v1b.s), for the
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
        .space 8
        ; 0x20 false, 0x28 nil, 0x30 true: a class word and a header word
        ; each, filled in at start-up
        .space 24

__start:
        LI   sp, #0x100000      ; top of RAM
        CALL #_main             ; a 32-bit address: main can be more than 64 KB on
        HALT

; (the handlers next to their vectors: the rest of the code may be more
; than 64 KB on)

; the timer's tick: acknowledge it, and that's all (gui_wait was waiting)
__irq:  ST   r0, [0xFFFFFF0C]
        RTI

__trap: LEA  r1, [trap_msg]
.loop:  MOV  r2, byte [r1]+
        BEQ  .done
        ST   r2, byte [0xFFFFFF00]
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

; int ejsetjmp(ejmp_buf b): b = r8-r14, sp, the return address
_ejsetjmp:
        ST   r8, [r1]
        ST   r9, [r1 + 4]
        ST   r10, [r1 + 8]
        ST   r11, [r1 + 12]
        ST   r12, [r1 + 16]
        ST   r13, [r1 + 20]
        ST   r14, [r1 + 24]
        ST   sp, [r1 + 28]
        MOV  r2, [sp]
        ST   r2, [r1 + 32]
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
        MOV  r3, [r1 + 32]
        ST   r3, [sp]
        MOV  r1, r2
        RET
