; Zero a 4 KB page N times (draft 1a). V0: a loop of word stores; V1: the
; same unrolled by 8; V2: SAVE r1-r8 as a store-multiple through sp (8
; words a go); V3: SAVE r1-r14 (14 words a go). Interrupts are off.
        .include "../../v1_isa/programs/v1a/lib/start.s"
PG = 0x40000
main:   MOV  r10, #N
.again:
.if V0
        MOV  r1, #PG
        MOV  r2, #PG + 4096
.loop:  ST   r0, [r1]
        ADDI r1, 4
        CMP  r1, r2
        BNE  .loop
.endif
.if V1
        MOV  r1, #PG
        MOV  r2, #PG + 4096
.loop:  ST   r0, [r1]
        ST   r0, [r1 + 4]
        ST   r0, [r1 + 8]
        ST   r0, [r1 + 12]
        ST   r0, [r1 + 16]
        ST   r0, [r1 + 20]
        ST   r0, [r1 + 24]
        ST   r0, [r1 + 28]
        ADDI r1, 32
        CMP  r1, r2
        BNE  .loop
.endif
.if V2
        ST   sp, [r0 + saved]
        MOV  r1, #0
        MOV  r2, #0
        MOV  r3, #0
        MOV  r4, #0
        MOV  r5, #0
        MOV  r6, #0
        MOV  r7, #0
        MOV  r8, #0
        MOV  r9, #PG
        MOV  sp, #PG + 4096
.loop:  SAVE r1-r8
        CMP  sp, r9
        BNE  .loop
        LD   sp, [r0 + saved]
.endif
.if V3
        ST   sp, [r0 + saved]
        ST   r10, [r0 + count]
        MOV  r1, #0
        MOV  r2, #0
        MOV  r3, #0
        MOV  r4, #0
        MOV  r5, #0
        MOV  r6, #0
        MOV  r7, #0
        MOV  r8, #0
        MOV  r9, #0
        MOV  r10, #0
        MOV  r11, #0
        MOV  r12, #0
        MOV  r13, #0
        MOV  r14, #0
        MOV  sp, #PG + 4096
.loop:  SAVE r1-r14             ; 73 times 56 bytes...
        CMP  sp, #PG + 56
        BHS  .loop
        SAVE r1-r2              ; ...and 8 more
        LD   sp, [r0 + saved]
        LD   r10, [r0 + count]
.endif
        DEC  r10
        BNE  .again
        RET
        .align 4
saved:  .word 0
count:  .word 0
