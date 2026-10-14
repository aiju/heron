; Switching between two user-level threads (coroutines, fibers, the tasks
; of an async runtime) N times each, with no system call (draft 1b). A
; switch saves the callee-saved registers and sp, and restores the other
; thread's. V0: the switch; V1: a plain call and return instead (the loop
; and call overhead alone).
        .include "../../v1_isa/programs/v1b/lib/start.s"
main:   SAVE r8-r14
        MOV  r10, #N
        ; the second thread's stack: its entry point, and seven registers
        MOV  r1, #0x80000
        LEA  r2, [other]
        ST   r2, -[r1]
        SUB  r1, #28
        ST   r1, [sp_other]
.loop:
.if V0
        BSR  switch
.endif
.if V1
        BSR  noswitch
.endif
        DEC  r10
        BNE  .loop
        RESTORE r8-r14
        RET
other:  ; the other thread: switch back, forever
.again: BSR  switch
        BRA  .again

; switch to the thread whose sp is in sp_other, leaving ours there
switch: SAVE r8-r14
        MOV  r1, [sp_other]
        ST   sp, [sp_other]
        MOV  sp, r1
        RESTORE r8-r14
        RET
noswitch:
        RET
        .align 4
sp_other: .word 0
