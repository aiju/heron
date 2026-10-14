; Loading a global variable N times, the ways code can find it (draft 1b).
; V0: an absolute address (code linked for one place); V1: PC-relative
; (position-independent, with the data at a fixed distance from the
; code); V2: through the GOT (ELF shared libraries: PC-relative to the
; GOT, then the variable); V3: from a base register (a library or
; per-instance data pointer, AmigaOS's A6, a "global pointer"); V4: no
; load (the loop alone).
        .include "../../v1_isa/programs/v1b/lib/start.s"
main:   MOV  r10, #N
        LEA  r13, [data]
.loop:
.if V0
        MOV  r1, [var]
.endif
.if V1
        MOV  r1, [pc + var]
.endif
.if V2
        MOV  r7, [pc + got_var]
        MOV  r1, [r7]
.endif
.if V3
        MOV  r1, [r13 + 4]
.endif
        DEC  r10
        BNE  .loop
        RET
        .align 4
got_var: .word var
data:   .word 0
var:    .word 42
