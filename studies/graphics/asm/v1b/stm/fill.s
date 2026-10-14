; fill_rows_stm(job): an experiment for report 0019, what a store-multiple
; through any base register would do for fills, in draft 1b. SAVE is one:
; it stores registers upwards from sp - 4n, so with sp pointed into the
; screen, SAVE r1-r8 writes eight words of the pattern in one instruction.
; Interrupts must be off, since they push onto sp; they are in the scenes.
;
; COPY rows with at least 24 whole words are done here, the whole words
; in groups of 8 from the end of the groups backwards, the rest one at a
; time; anything else goes to fill_rows (fill.s). Shorter rows don't pay
; for setting sp up.
;
; FillJob: p 0, pitch 4, h 8, lmask 12, n 16, rmask 20, pat 24, rop 28
;
; r1-r8 the pattern, r9 the job, r10 a count or a mask, r11 the row, r12
; the rows left, r13 the frame and stack, r14 a word.

        .global _fill_rows_stm
        .section .text._fill_rows_stm
G       = 0                     ; the frame: groups of 8 words,
EOFF    = 4                     ; the offset of their end E,
REM     = 8                     ; and the words after it
FRAME   = 12

_fill_rows_stm:
        MOV  r2, [r1 + 28]
        BNE  _fill_rows
        MOV  r2, [r1 + 16]
        CMP  r2, #24
        BLO  _fill_rows         ; fewer than 3 groups: not worth it
        SAVE r8-r14
        SUB  sp, #FRAME
        MOV  r3, r2
        LSR  r3, #3
        ST   r3, [sp + G]
        LSL  r3, #5
        ADD  r3, #4
        ST   r3, [sp + EOFF]
        AND  r2, #7
        ST   r2, [sp + REM]
        MOV  r13, sp
        MOV  r9, r1
        MOV  r11, [r9]
        MOV  r12, [r9 + 8]
        BLE  .done
        MOV  r1, [r9 + 24]
        MOV  r2, r1
        MOV  r3, r1
        MOV  r4, r1
        MOV  r5, r1
        MOV  r6, r1
        MOV  r7, r1
        MOV  r8, r1
.row:   MOV  r14, [r11]         ; the first word, under lmask
        MOV  r10, [r9 + 12]
        BIC  r14, r10
        AND  r10, r1
        OR   r14, r10
        ST   r14, [r11]
        MOV  r10, [r13 + G]     ; the groups: from their end E backwards
        MOV  sp, r11
        ADD  sp, [r13 + EOFF]
        MOV  r14, sp
.g:     SAVE r1-r8
        DEC  r10
        BNE  .g
        MOV  sp, r14            ; the rest from E
        MOV  r10, [r13 + REM]
        BEQ  .last
.r:     ST   r1, [sp]+
        DEC  r10
        BNE  .r
.last:  MOV  r10, [r9 + 20]     ; the last word, under rmask
        BEQ  .next
        MOV  r14, [sp]
        BIC  r14, r10
        AND  r10, r1
        OR   r14, r10
        ST   r14, [sp]
.next:  ADD  r11, [r9 + 4]
        DEC  r12
        BNE  .row
.done:  MOV  sp, r13
        ADD  sp, #FRAME
        RESTORE r8-r14
        RET
