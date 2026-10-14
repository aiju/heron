; Copy a 4 KB page N times (draft 1a), from PG to PG2. V0: a loop of word
; loads and stores; V1: unrolled by 8; V2: RESTORE and SAVE r1-r8 as load-
; and store-multiple through sp (8 words a go); V3: r1-r12 (12 words a go).
        .include "../../v1_isa/programs/v1a/lib/start.s"
PG = 0x40000
PG2 = 0x50000
main:   MOV  r10, #N
.again:
.if V0
        MOV  r1, #PG
        MOV  r2, #PG2
        MOV  r4, #PG + 4096
.loop:  LD   r3, [r1]
        ST   r3, [r2]
        ADDI r1, 4
        ADDI r2, 4
        CMP  r1, r4
        BNE  .loop
.endif
.if V1
        MOV  r1, #PG
        MOV  r2, #PG2
        MOV  r4, #PG + 4096
.loop:  LD   r3, [r1]
        LD   r5, [r1 + 4]
        LD   r6, [r1 + 8]
        LD   r7, [r1 + 12]
        ST   r3, [r2]
        ST   r5, [r2 + 4]
        ST   r6, [r2 + 8]
        ST   r7, [r2 + 12]
        LD   r3, [r1 + 16]
        LD   r5, [r1 + 20]
        LD   r6, [r1 + 24]
        LD   r7, [r1 + 28]
        ST   r3, [r2 + 16]
        ST   r5, [r2 + 20]
        ST   r6, [r2 + 24]
        ST   r7, [r2 + 28]
        ADDI r1, 32
        ADDI r2, 32
        CMP  r1, r4
        BNE  .loop
.endif
.if V2
        ST   sp, [r0 + saved]
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
        LD   sp, [r0 + saved]
.endif
.if V3
        ST   sp, [r0 + saved]
        ST   r10, [r0 + count]
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
        LEA  sp, [r14 + -32]
        SAVE r1-r4
        LD   sp, [r0 + saved]
        LD   r10, [r0 + count]
.endif
        DEC  r10
        BNE  .again
        RET
        .align 4
saved:  .word 0
count:  .word 0
