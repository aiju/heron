; blit_rows(job): the copy kernel, in draft 2, for COPY; the other rops
; go to the C version (src/blit.c, which explains the job).
;
; BlitJob: d 0, s 4, dpitch 8, spitch 12, h 16, n 20, lmask 24, rmask 28,
;          rs 32, ls 36, pre 40, last 44, back 48, rop 52
;
; A destination word put together from two source words, lo and hi, is
; (lo >> rs) | (hi << ls). Shifts take a step per bit (and per byte and
; half), so instead each source word is rotated right by rs once, and
; neighbouring rotated words are merged under M = ~0 >> rs:
;
;     out = hi' ^ ((lo' ^ hi') & M)     (x' = x rotated right by rs)
;
; Registers in the row loops: r2/r3 the destination and source rows, r4
; the rows left, r5 n, r6 rs, r0 M, r8 lmask, r14 rmask, r9/r10 the word
; pointers, r11/r12 rotated source words, r13 a count.

        .global _blit_rows
        .section .text._blit_rows
_blit_rows:
        MOVS r2, [r1 + 52]
        BNE  _blit_rows_c       ; not COPY
        SAVE r8-r14
        MOV  r2, [r1]
        MOV  r3, [r1 + 4]
        MOVS r4, [r1 + 16]
        BLE  .done
        MOV  r5, [r1 + 20]
        MOV  r8, [r1 + 24]
        MOV  r14, [r1 + 28]
        MOV  r6, [r1 + 32]
        MOV  r0, #-1
        LSR  r0, r6
        MOVS r13, [r1 + 48]
        BNE  .back
        MOVS r13, [r1 + 36]
        BEQ  .arow

; ---- forward, shifted ----
.frow:  MOV  r9, r2
        MOV  r10, r3
        MOV  r11, #0
        MOVS r13, [r1 + 40]     ; pre: the first source word is only lo
        BEQ  .f0
        MOV  r11, [r10]+
        ROR  r11, r6
.f0:    MOVS r13, r5
        BEQ  .fsingle
        MOV  r12, [r10]+        ; the first word, under lmask
        ROR  r12, r6
        XOR  r11, r12
        AND  r11, r0
        XOR  r11, r12
        XOR  r11, [r9]
        AND  r11, r8
        XOR  r11, [r9]
        MOV  [r9]+, r11
        MOV  r11, r12
        DEC  r13                ; n - 1 whole words: an odd one, then pairs
        BEQ  .flast
        MOV  r12, r13
        AND  r12, #1
        BEQ  .fpairs
        MOV  r12, [r10]+
        ROR  r12, r6
        XOR  r11, r12
        AND  r11, r0
        XOR  r11, r12
        MOV  [r9]+, r11
        MOV  r11, r12
.fpairs:
        LSR  r13, #1
        BEQ  .flast
.fp:    MOV  r12, [r10]+
        ROR  r12, r6
        XOR  r11, r12
        AND  r11, r0
        XOR  r11, r12
        MOV  [r9]+, r11         ; r12 is lo for the next word
        MOV  r11, [r10]+
        ROR  r11, r6
        XOR  r12, r11
        AND  r12, r0
        XOR  r12, r11
        MOV  [r9]+, r12         ; and r11 for the one after
        DEC  r13
        BNE  .fp
.flast: MOV  r12, #0            ; the last word, under rmask
        MOVS r13, [r1 + 44]
        BEQ  .fl0
        MOV  r12, [r10]+
        ROR  r12, r6
.fl0:   XOR  r11, r12
        AND  r11, r0
        XOR  r11, r12
        XOR  r11, [r9]
        AND  r11, r14
        XOR  r11, [r9]
        MOV  [r9], r11
        BRA  .fnext
.fsingle:
        MOV  r12, #0            ; one word, under lmask
        MOVS r13, [r1 + 44]
        BEQ  .fs0
        MOV  r12, [r10]+
        ROR  r12, r6
.fs0:   XOR  r11, r12
        AND  r11, r0
        XOR  r11, r12
        XOR  r11, [r9]
        AND  r11, r8
        XOR  r11, [r9]
        MOV  [r9], r11
.fnext: ADD  r2, [r1 + 8]
        ADD  r3, [r1 + 12]
        DEC  r4
        BNE  .frow
.done:  RESTORE r8-r14
        RET

; ---- forward, aligned: words as they are, four at a time ----
.arow:  MOV  r9, r2
        MOV  r10, r3
        MOVS r13, r5
        BEQ  .asingle
        MOV  r12, [r10]+
        XOR  r12, [r9]
        AND  r12, r8
        XOR  r12, [r9]
        MOV  [r9]+, r12
        DEC  r13
        BEQ  .alast
        MOV  r11, r13
        AND  r11, #3
        BEQ  .a4
.a1:    MOV  r12, [r10]+
        MOV  [r9]+, r12
        DEC  r11
        BNE  .a1
.a4:    LSR  r13, #2
        BEQ  .alast
.a4l:   MOV  r12, [r10]+
        MOV  [r9]+, r12
        MOV  r12, [r10]+
        MOV  [r9]+, r12
        MOV  r12, [r10]+
        MOV  [r9]+, r12
        MOV  r12, [r10]+
        MOV  [r9]+, r12
        DEC  r13
        BNE  .a4l
.alast: MOV  r12, [r10]
        XOR  r12, [r9]
        AND  r12, r14
        XOR  r12, [r9]
        MOV  [r9], r12
        BRA  .anext
.asingle:
        MOV  r12, [r10]
        XOR  r12, [r9]
        AND  r12, r8
        XOR  r12, [r9]
        MOV  [r9], r12
.anext: ADD  r2, [r1 + 8]
        ADD  r3, [r1 + 12]
        DEC  r4
        BNE  .arow
        BRA  .done

; ---- backward: from the last word down, with the pointers at it ----
.back:  MOVS r13, [r1 + 36]
        BEQ  .barow
.brow:  MOV  r9, r2
        MOV  r10, r3
        MOV  r11, #0            ; hi of the last word
        MOVS r13, [r1 + 44]
        BEQ  .b0
        MOV  r11, [r10]
        ROR  r11, r6
.b0:    MOVS r13, r5
        BEQ  .bsingle
        MOV  r12, -[r10]        ; the last word, under rmask
        ROR  r12, r6
        XOR  r11, r12           ; out = lo' ^ ((lo' ^ hi') & ~M)
        BIC  r11, r0
        XOR  r11, r12
        XOR  r11, [r9]
        AND  r11, r14
        XOR  r11, [r9]
        MOV  [r9], r11
        MOV  r11, r12
        DEC  r13
        BEQ  .bfirst
.bmid:  MOV  r12, -[r10]
        ROR  r12, r6
        XOR  r11, r12
        BIC  r11, r0
        XOR  r11, r12
        MOV  -[r9], r11
        MOV  r11, r12
        DEC  r13
        BNE  .bmid
.bfirst:
        MOV  r12, #0            ; the first word, under lmask
        MOVS r13, [r1 + 40]
        BEQ  .bf0
        MOV  r12, -[r10]
        ROR  r12, r6
.bf0:   XOR  r11, r12
        BIC  r11, r0
        XOR  r11, r12
        SUB  r9, #4
        XOR  r11, [r9]
        AND  r11, r8
        XOR  r11, [r9]
        MOV  [r9], r11
        BRA  .bnext
.bsingle:
        MOV  r12, #0
        MOVS r13, [r1 + 40]
        BEQ  .bs0
        MOV  r12, -[r10]
        ROR  r12, r6
.bs0:   XOR  r11, r12
        BIC  r11, r0
        XOR  r11, r12
        XOR  r11, [r9]
        AND  r11, r8
        XOR  r11, [r9]
        MOV  [r9], r11
.bnext: ADD  r2, [r1 + 8]
        ADD  r3, [r1 + 12]
        DEC  r4
        BNE  .brow
        BRA  .done

.barow: MOV  r9, r2
        MOV  r10, r3
        MOVS r13, r5
        BEQ  .basingle
        MOV  r12, [r10]         ; the last word, under rmask
        XOR  r12, [r9]
        AND  r12, r14
        XOR  r12, [r9]
        MOV  [r9], r12
        DEC  r13
        BEQ  .bafirst
.bam:   MOV  r12, -[r10]
        MOV  -[r9], r12
        DEC  r13
        BNE  .bam
.bafirst:
        MOV  r12, -[r10]
        SUB  r9, #4
        XOR  r12, [r9]
        AND  r12, r8
        XOR  r12, [r9]
        MOV  [r9], r12
        BRA  .banext
.basingle:
        MOV  r12, [r10]
        XOR  r12, [r9]
        AND  r12, r8
        XOR  r12, [r9]
        MOV  [r9], r12
.banext:
        ADD  r2, [r1 + 8]
        ADD  r3, [r1 + 12]
        DEC  r4
        BNE  .barow
        BRA  .done
