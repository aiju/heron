; Switching between two user-level threads N times each, with no system
; call (draft 1a). V0: the switch; V1: a plain call and return instead.
        .include "../../v1_isa/programs/v1a/lib/start.s"
main:   SAVE r8-r14
        MOV  r10, #N
        LI   r1, #0x80000
        LEA  r2, other
        ST   r2, [r1 + -4]
        ADD  r1, #-32
        ST   r1, [r0 + sp_other]
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
other:
.again: BSR  switch
        BRA  .again

switch: SAVE r8-r14
        LD   r1, [r0 + sp_other]
        ST   sp, [r0 + sp_other]
        MOV  sp, r1
        RESTORE r8-r14
        RET
noswitch:
        RET
        .align 4
sp_other: .word 0
