; Heron Mini's start code for C programs: the vectors, the stack at the
; top of bank 0, the interrupt into C (rt.c's rt_irq), and a trap's report
; on the console. Calls write the return address into r7 (RFC 0028, 5.7).
;
; Waiting for an interrupt (rt_wait_frame_after) is EI then HALT: an
; interrupt taken between the two would return to the HALT and wait for
; another, so the interrupt entry steps a saved PC that is the HALT past
; it.

        .org 0x00
        JMP  __start            ; reset
        .org 0x04
        JMP  __irq              ; the interrupt
        .org 0x08
        JMP  __trap_ill         ; an illegal instruction
        .org 0x0C
        JMP  __trap_swi         ; SWI
        .org 0x10
        JMP  __trap_div         ; a divide error
        .org 0x14
        JMP  __trap_addr        ; an address error
        .org 0x18
        JMP  __trap_tag         ; a tag check
        .org 0x1C

__start:
        MOV  sp, #0x200000      ; the top of bank 0
        CALL _rt_init
        CALL _main
_exit:
_abort: DI
        HALT

; the interrupt: the scratch registers and the link register saved; the
; flags word is at [sp], the PC at [sp + 4] as it comes
        .text
__irq:  SAVE r0-r7
        CALL _rt_irq
        MOV  r1, [sp + 36]      ; the saved PC
        LEA  r2, [pc + __halt]
        CMP  r1, r2
        BNE  .back
        ADD  r1, #2             ; past the HALT
        MOV  [sp + 36], r1
.back:  RESTORE r0-r7
        RTI

        .global _rt_ei, _rt_di, _rt_wait_frame_after, _exit, _abort
_rt_ei: EI
        RET
_rt_di: DI
        RET

; void rt_wait_frame_after(unsigned seen): until rt_frames != seen
_rt_wait_frame_after:
        DI
__waitl:
        MOV  r2, [_rt_frames]
        CMP  r2, r1
        BNE  __waitd
        EI
__halt: HALT
        DI
        BRA  __waitl
__waitd:
        EI
        RET

; a trap: its name, the saved PC and flags, and halt
__trap_ill:
        MOV  r1, #'I'
        BRA  __trap
__trap_swi:
        MOV  r1, #'S'
        BRA  __trap
__trap_div:
        MOV  r1, #'D'
        BRA  __trap
__trap_addr:
        MOV  r1, #'A'
        BRA  __trap
__trap_tag:
        MOV  r1, #'T'
__trap: DI
        LEA  r3, [pc + .msg]
.m:     MOVS r2, byte [r3]+
        BEQ  .m1
        MOV  byte [0xFFFFFF00], r2
        BRA  .m
.m1:    MOV  byte [0xFFFFFF00], r1
        MOV  r2, #' '
        MOV  byte [0xFFFFFF00], r2
        MOV  r1, [sp + 4]       ; the PC
        CALL __hex
        MOV  r2, #' '
        MOV  byte [0xFFFFFF00], r2
        MOV  r1, [sp]           ; the flags word
        CALL __hex
        MOV  r2, #10
        MOV  byte [0xFFFFFF00], r2
        HALT
.msg:   .asciz "@trap "
        .align 2

; r1 as eight hex digits (r2, r3, r4 scratch)
__hex:  MOV  r3, #28
.h:     MOV  r2, r1
        LSR  r2, r3
        AND  r2, #15
        CMP  r2, #10
        BLO  .d
        ADD  r2, #'A' - '0' - 10
.d:     ADD  r2, #'0'
        MOV  byte [0xFFFFFF00], r2
        SUB  r3, #4
        BPL  .h
        RET
