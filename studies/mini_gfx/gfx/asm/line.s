; line_run_asm(job): a line's pixels in draft 2 (line.c has the job and
; the C kernel): n pixels from word p, pixel i, each v = (v & ~(m & ka))
; ^ (m & kx) with m from the format's pixel masks; Bresenham's steps.
;
; LineJob: p 0, i 4, ppw 8, masks 12, ka 16, kx 20, n 24, e 28, inc 32,
; dec 36, ystep 40, dir 44

        .global _line_run_asm
        .section .text._line_run_asm
_line_run_asm:
        SAVE r7-r14
        MOV  r2, [r1]           ; r2: the word
        MOV  r3, [r1 + 12]      ; the masks
        MOV  r0, [r1 + 4]
        LEA  r3, [r3 + r0*4]    ; r3: this pixel's mask
        MOV  r4, [r1 + 16]      ; r4: ka
        MOV  r5, [r1 + 20]      ; r5: kx
        MOVS r6, [r1 + 24]      ; r6: pixels left
        BLE  .done
        MOV  r7, [r1 + 28]      ; r7: e
        MOV  r8, [r1 + 32]      ; r8: inc
        MOV  r9, [r1 + 36]      ; r9: dec
        MOV  r10, [r1 + 40]
        LSL  r10, #2            ; r10: the minor (or major) step, bytes
        MOV  r11, [r1 + 12]     ; r11: the first mask
        MOV  r12, [r1 + 8]
        LEA  r12, [r11 + r12*4] ; r12: past the last
        MOVS r13, [r1 + 44]
        BNE  .down

; mostly across: a pixel right a step, the minor step when e >= 0
.x:     MOV  r0, [r3]+
        MOV  r1, r0
        AND  r1, r4
        MOV  r14, [r2]
        BIC  r14, r1
        AND  r0, r5
        XOR  r14, r0
        MOV  [r2], r14
        CMP  r3, r12
        BLO  .x1
        MOV  r3, r11
        ADD  r2, #4
.x1:    TST  r7, r7
        BMI  .x2
        ADD  r2, r10
        SUB  r7, r9
.x2:    ADD  r7, r8
        DEC  r6
        BNE  .x
.done:  RESTORE r7-r14
        RET

; mostly down: ystep a step, a pixel left or right (r13) when e >= 0
.down:  MOV  r0, [r3]
        MOV  r1, r0
        AND  r1, r4
        MOV  r14, [r2]
        BIC  r14, r1
        AND  r0, r5
        XOR  r14, r0
        MOV  [r2], r14
        ADD  r2, r10
        TST  r7, r7
        BMI  .d2
        SUB  r7, r9
        TST  r13, r13
        BMI  .left
        ADD  r3, #4
        CMP  r3, r12
        BLO  .d2
        MOV  r3, r11
        ADD  r2, #4
        BRA  .d2
.left:  CMP  r3, r11
        BHI  .l1
        MOV  r3, r12
        SUB  r2, #4
.l1:    SUB  r3, #4
.d2:    ADD  r7, r8
        DEC  r6
        BNE  .down
        RESTORE r7-r14
        RET
