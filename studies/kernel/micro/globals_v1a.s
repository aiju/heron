; Loading a global variable N times, the ways code can find it (draft 1a).
; V0: an absolute address; V1: PC-relative (LEA, then the load); V2:
; through the GOT; V3: from a base register; V4: no load.
        .include "../../v1_isa/programs/v1a/lib/start.s"
main:   MOV  r10, #N
        LEA  r13, data
.loop:
.if V0
        LD   r1, [var]
.endif
.if V1
        LEA  r7, var
        LD   r1, [r7]
.endif
.if V2
        LEA  r7, got_var
        LD   r7, [r7]
        LD   r1, [r7]
.endif
.if V3
        LD   r1, [r13 + 4]
.endif
        DEC  r10
        BNE  .loop
        RET
        .align 4
got_var: .word var
data:   .word 0
var:    .word 42
