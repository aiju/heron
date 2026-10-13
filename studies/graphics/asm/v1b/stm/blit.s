; blit_rows_stm(job): an experiment for report 0019, what a load- and
; store-multiple through any base register would do for copies, in draft
; 1b. RESTORE and SAVE are those, through sp: RESTORE r1-r8 loads eight
; words upwards from sp and leaves sp after them, SAVE r1-r8 stores them
; upwards from sp - 32. Interrupts must be off; they are in the scenes.
;
; Forward COPY rows that are aligned (no shift) with at least 16 whole
; words are done here, 8 words at a time; anything else goes to
; blit_rows (blit.s).
;
; BlitJob: d 0, s 4, dpitch 8, spitch 12, h 16, n 20, lmask 24, rmask 28,
;          rs 32, ls 36, pre 40, last 44, back 48, rop 52
;
; r1-r8 the words, r9 the job, r10/r11 the source and destination, r13
; the stack, which holds the rows and the rows left, r14 a count.

        .global _blit_rows_stm
        .section .text._blit_rows_stm
_blit_rows_stm:
        MOV  r2, [r1 + 52]
        BNE  _blit_rows         ; not COPY
        MOV  r2, [r1 + 48]
        BNE  _blit_rows         ; backward
        MOV  r2, [r1 + 36]
        BNE  _blit_rows         ; shifted
        MOV  r2, [r1 + 20]
        CMP  r2, #17
        BLO  _blit_rows         ; fewer than 16 whole words
        SAVE r8-r14
        SUB  sp, #12
        MOV  r9, r1
        MOV  r2, [r9]
        ST   r2, [sp]
        MOV  r2, [r9 + 4]
        ST   r2, [sp + 4]
        MOV  r2, [r9 + 16]
        ST   r2, [sp + 8]
        BLE  .done
        MOV  r13, sp
.row:   MOV  r11, [r13]
        MOV  r10, [r13 + 4]
        MOV  r1, [r10]+         ; the first word, under lmask
        MOV  r2, [r11]
        XOR  r1, r2
        AND  r1, [r9 + 24]
        XOR  r1, r2
        ST   r1, [r11]+
        MOV  r14, [r9 + 20]     ; n - 1 whole words, 8 at a time
        DEC  r14
        LSR  r14, #3
.g:     MOV  sp, r10
        RESTORE r1-r8
        MOV  r10, sp
        LEA  sp, [r11 + 32]
        SAVE r1-r8
        LEA  r11, [r11 + 32]
        DEC  r14
        BNE  .g
        MOV  r14, [r9 + 20]     ; then the rest one at a time
        DEC  r14
        AND  r14, #7
        BEQ  .last
.r:     MOV  r1, [r10]+
        ST   r1, [r11]+
        DEC  r14
        BNE  .r
.last:  MOV  r1, [r10]          ; the last word, under rmask
        MOV  r2, [r11]
        XOR  r1, r2
        AND  r1, [r9 + 28]
        XOR  r1, r2
        ST   r1, [r11]
        MOV  r2, [r13]
        ADD  r2, [r9 + 8]
        ST   r2, [r13]
        MOV  r2, [r13 + 4]
        ADD  r2, [r9 + 12]
        ST   r2, [r13 + 4]
        MOV  r2, [r13 + 8]
        DEC  r2
        ST   r2, [r13 + 8]
        BNE  .row
.done:  MOV  sp, r13
        ADD  sp, #12
        RESTORE r8-r14
        RET
