; Calling a function N times, the ways a linker can wire it up (draft 1b).
; V0: a direct call; V1: through an import table entry (Windows' IAT, one
; CALL [mem]); V2: through a PLT stub that jumps through the GOT (ELF,
; already bound); V3: through a table at a library base register (AmigaOS
; libraries, or a COM interface's table already in a register); V4: a
; virtual call, object to table to function (C++, COM); V5: no call (the
; loop alone).
        .include "../../v1_isa/programs/v1b/lib/start.s"
main:   MOV  r10, #N
        LEA  r13, [lib]
        LEA  r12, [obj]
.loop:
.if V0
        BSR  f
.endif
.if V1
        CALL [iat_f]
.endif
.if V2
        BSR  plt_f
.endif
.if V3
        CALL [r13 + 8]
.endif
.if V4
        MOV  r9, [r12]
        CALL [r9 + 8]
.endif
        DEC  r10
        BNE  .loop
        RET
f:      RET
plt_f:  JMP  [got_f]
        .align 4
iat_f:  .word f
got_f:  .word f
lib:    .word 0, 0, f
obj:    .word lib
