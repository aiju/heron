; Copy a 4 KB page N times (draft 1b), from PG to PG2. V0: a loop of word
; loads and stores; V1: unrolled by 8; V2: RESTORE and SAVE r1-r8 as load-
; and store-multiple through sp (8 words a go); V3: r1-r12 (12 words a go).
        .include "../../v1_isa/programs/v1b/lib/start.s"
PG = 0x40000
PG2 = 0x50000
main:   MOV  r10, #N
.again:
.if V0
        MOV  r1, #PG
        MOV  r2, #PG2
        MOV  r4, #PG + 4096
.loop:  MOV  r3, [r1]+
        ST   r3, [r2]+
        CMP  r1, r4
        BNE  .loop
.endif
.if V1
        MOV  r1, #PG
        MOV  r2, #PG2
        MOV  r4, #PG + 4096
.loop:  MOV  r3, [r1]+
        MOV  r5, [r1]+
        MOV  r6, [r1]+
        MOV  r7, [r1]+
        ST   r3, [r2]+
        ST   r5, [r2]+
        ST   r6, [r2]+
        ST   r7, [r2]+
        MOV  r3, [r1]+
        MOV  r5, [r1]+
        MOV  r6, [r1]+
        MOV  r7, [r1]+
        ST   r3, [r2]+
        ST   r5, [r2]+
        ST   r6, [r2]+
        ST   r7, [r2]+
        CMP  r1, r4
        BNE  .loop
.endif
.if V2
        ST   sp, [saved]
        MOV  r9, #PG
        MOV  r11, #PG2 + 32
.loop:  MOV  sp, r9
        RESTORE r1-r8
        MOV  r9, sp
        MOV  sp, r11
        SAVE r1-r8
        ADD  r11, #32
        CMP  r9, #PG + 4096
        BNE  .loop
        MOV  sp, [saved]
.endif
.if V3
        ST   sp, [saved]
        ST   r10, [count]
        MOV  r13, #PG
        MOV  r14, #PG2 + 48
.loop:  MOV  sp, r13
        RESTORE r1-r12          ; 85 times 48 bytes...
        MOV  r13, sp
        MOV  sp, r14
        SAVE r1-r12
        ADD  r14, #48
        CMP  r13, #PG + 4096 - 16
        BNE  .loop
        MOV  sp, r13            ; ...and 16 more
        RESTORE r1-r4
        LEA  sp, [r14 - 32]
        SAVE r1-r4
        MOV  sp, [saved]
        MOV  r10, [count]
.endif
        DEC  r10
        BNE  .again
        RET
        .align 4
saved:  .word 0
count:  .word 0
