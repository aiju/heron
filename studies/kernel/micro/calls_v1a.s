; Calling a function N times, the ways a linker can wire it up (draft 1a).
; V0: a direct call; V1: through an import table entry (Windows' IAT): a
; load and CALL r; V2: through a PLT stub (ELF, already bound); V3:
; through a table at a library base register (AmigaOS, COM); V4: a virtual
; call, object to table to function; V5: no call (the loop alone).
        .include "../../v1_isa/programs/v1a/lib/start.s"
main:   MOV  r10, #N
        LEA  r13, lib
        LEA  r12, obj
.loop:
.if V0
        BSR  f
.endif
.if V1
        LD   r7, [iat_f]
        CALL r7
.endif
.if V2
        BSR  plt_f
.endif
.if V3
        LD   r7, [r13 + 8]
        CALL r7
.endif
.if V4
        LD   r9, [r12]
        LD   r7, [r9 + 8]
        CALL r7
.endif
        DEC  r10
        BNE  .loop
        RET
f:      RET
plt_f:  LD   r7, [got_f]
        JMP  r7
        .align 4
iat_f:  .word f
got_f:  .word f
lib:    .word 0, 0, f
obj:    .word lib
