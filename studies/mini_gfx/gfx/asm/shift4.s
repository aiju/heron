; _shift_multi(job): the shifted copy in draft 2 for three or four terms
; (L0's chunky 1 and 2 bits; shift.s has two). Each term is a source word
; (lo or hi) shifted by a constant and masked; the merge routine below has
; four slots whose source register and shift are patched in from the job,
; and the masks are in r8-r11 (0 for a slot not used). COPY only.
;
; ShiftJob: d 0, s 4, dpitch 8, spitch 12, h 16, n 20, lmask 24, rmask 28,
; rop 32, nterm 36, terms from 40 (src 0, sh 4, m 8; 12 bytes each)
; The frame: [sp] the job, [sp + 4] rows left, [sp + 8] and [sp + 12] the
; destination's and the source's row

        .global _shift_multi
        .section .text._shift_multi
_shift_multi:
        SAVE r7-r14
        SUB  sp, #16
        MOV  [sp], r1
        MOV  r0, [r1 + 16]
        MOV  [sp + 4], r0
        MOV  r0, [r1]
        MOV  [sp + 8], r0
        MOV  r0, [r1 + 4]
        MOV  [sp + 12], r0
; the slots: MOV r1, r13 (lo) or r12 (hi); LSL or LSR r1, #n
        LEA  r2, [r1 + 40]      ; r2: the term
        LEA  r3, [pc + .slots]  ; r3: the slots' patch addresses
        MOV  r4, [r1 + 36]      ; r4: terms
        CLR  r5                 ; r5: the slot
.patch: MOV  r6, [r3 + r5*8]    ; the MOV's address
        MOV  r0, #0x1D10        ; MOV r1, r13
        CMP  r5, r4
        BHS  .unused
        MOV  r7, [r2]           ; hi?
        TST  r7, r7
        BEQ  .lo
        MOV  r0, #0x1C10        ; MOV r1, r12
.lo:    MOV  half [r6], r0
        MOV  r6, [r3 + r5*8 + 4]    ; the shift's address
        MOVS r0, [r2 + 4]
        BMI  .right
        MOV  r7, #0xC0          ; LSL r1, #n
        BRA  .enc
.right: NEG  r0
        MOV  r7, #0xC4          ; LSR r1, #n
.enc:   MOV  r9, r0
        AND  r9, #1
        OR   r7, r9
        LSR  r0, #1
        OR   r0, #0x10          ; r1 in the high nibble
        LSL  r0, #8
        OR   r0, r7
        MOV  half [r6], r0
        ADD  r2, #12
        INC  r5
        CMP  r5, #4
        BLO  .patch
        BRA  .masks
.unused:
        MOV  half [r6], r0
        INC  r5
        CMP  r5, #4
        BLO  .patch
.masks: MOV  r1, [sp]
        MOV  r4, [r1 + 36]
        MOV  r8, [r1 + 48]
        MOV  r9, [r1 + 60]
        MOV  r10, #0
        MOV  r11, #0
        CMP  r4, #3
        BLO  .rows
        MOV  r10, [r1 + 72]
        CMP  r4, #4
        BLO  .rows
        MOV  r11, [r1 + 84]
        BRA  .rows

; the rows: r3 the source, r2 the destination, r4 words after this one
.rows:  MOV  r1, [sp]
        MOV  r2, [sp + 8]
        MOV  r3, [sp + 12]
        MOV  r4, [r1 + 20]
        MOV  r5, [r1 + 24]      ; r5: the edge's mask, lmask first
        MOV  r13, [r3]+         ; lo
.word:  MOV  r12, [r3]+         ; hi
        BSR  .merge             ; r14: the word
        MOV  r0, [r2]
        XOR  r14, r0
        AND  r14, r5
        XOR  r0, r14
        MOV  [r2]+, r0
        MOV  r13, r12
        MOV  r5, #-1
        MOVS r4, r4
        BEQ  .rowend
        DEC  r4
        BNE  .word
        MOV  r1, [sp]
        MOV  r5, [r1 + 28]      ; the last: rmask
        BRA  .word
.rowend:
        MOV  r1, [sp]
        MOV  r0, [r1 + 8]
        LSL  r0, #2
        ADD  r0, [sp + 8]
        MOV  [sp + 8], r0
        MOV  r0, [r1 + 12]
        LSL  r0, #2
        ADD  r0, [sp + 12]
        MOV  [sp + 12], r0
        MOV  r0, [sp + 4]
        DEC  r0
        MOV  [sp + 4], r0
        BNE  .rows
        ADD  sp, #16
        RESTORE r7-r14
        RET

; the merge: r14 = OR of the four slots, from lo (r13) and hi (r12)
.merge:
.m0:    MOV  r1, r13
.s0:    LSL  r1, #0
        AND  r1, r8
        MOV  r14, r1
.m1:    MOV  r1, r13
.s1:    LSL  r1, #0
        AND  r1, r9
        OR   r14, r1
.m2:    MOV  r1, r13
.s2:    LSL  r1, #0
        AND  r1, r10
        OR   r14, r1
.m3:    MOV  r1, r13
.s3:    LSL  r1, #0
        AND  r1, r11
        OR   r14, r1
        RET

        .align 4
.slots: .word .m0, .s0, .m1, .s1, .m2, .s2, .m3, .s3
