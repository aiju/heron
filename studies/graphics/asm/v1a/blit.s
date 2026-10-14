; blit_rows(job): the copy kernel, in draft 1a, for COPY; the other rops
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
; the rows left, r5 n, r6 rs, r7 M, r8 lmask, r14 rmask, r9/r10 the word
; pointers, r11/r12 rotated source words, r13 a count, or the destination
; word at the edges.

        .global _blit_rows
        .section .text._blit_rows
_blit_rows:
        LD   r2, [r1 + 52]
        BNE  _blit_rows_c       ; not COPY
        SAVE r8-r14
        LD   r2, [r1]
        LD   r3, [r1 + 4]
        LD   r4, [r1 + 16]
        BLE  .done
        LD   r5, [r1 + 20]
        LD   r8, [r1 + 24]
        LD   r14, [r1 + 28]
        LD   r6, [r1 + 32]
        MVI  r7, -1
        LSR  r7, r6
        LD   r13, [r1 + 48]
        BNE  .back
        LD   r13, [r1 + 36]
        BEQ  .arow

; ---- forward, shifted ----
.frow:  MOV  r9, r2
        MOV  r10, r3
        MVI  r11, 0
        LD   r13, [r1 + 40]     ; pre: the first source word is only lo
        BEQ  .f0
        LD   r11, [r10]
        ROR  r11, r6
        ADDI r10, 4
.f0:    MOV  r13, r5
        BEQ  .fsingle
        LD   r12, [r10]         ; the first word, under lmask
        ROR  r12, r6
        ADDI r10, 4
        XOR  r11, r12
        AND  r11, r7
        XOR  r11, r12
        LD   r13, [r9]
        XOR  r11, r13
        AND  r11, r8
        XOR  r11, r13
        ST   r11, [r9]
        ADDI r9, 4
        MOV  r11, r12
        MOV  r13, r5            ; n - 1 whole words: an odd one, then pairs
        DEC  r13
        BEQ  .flast
        MOV  r12, r13
        AND  r12, #1
        BEQ  .fpairs
        LD   r12, [r10]
        ROR  r12, r6
        XOR  r11, r12
        AND  r11, r7
        XOR  r11, r12
        ST   r11, [r9]
        ADDI r10, 4
        ADDI r9, 4
        MOV  r11, r12
.fpairs:
        LSR  r13, #1
        BEQ  .flast
.fp:    LD   r12, [r10]
        ROR  r12, r6
        XOR  r11, r12
        AND  r11, r7
        XOR  r11, r12
        ST   r11, [r9]          ; r12 is lo for the next word
        LD   r11, [r10 + 4]
        ROR  r11, r6
        XOR  r12, r11
        AND  r12, r7
        XOR  r12, r11
        ST   r12, [r9 + 4]      ; and r11 for the one after
        ADDI r10, 8
        ADDI r9, 8
        DEC  r13
        BNE  .fp
.flast: MVI  r12, 0             ; the last word, under rmask
        LD   r13, [r1 + 44]
        BEQ  .fl0
        LD   r12, [r10]
        ROR  r12, r6
.fl0:   XOR  r11, r12
        AND  r11, r7
        XOR  r11, r12
        LD   r13, [r9]
        XOR  r11, r13
        AND  r11, r14
        XOR  r11, r13
        ST   r11, [r9]
        BRA  .fnext
.fsingle:
        MVI  r12, 0             ; one word, under lmask
        LD   r13, [r1 + 44]
        BEQ  .fs0
        LD   r12, [r10]
        ROR  r12, r6
.fs0:   XOR  r11, r12
        AND  r11, r7
        XOR  r11, r12
        LD   r13, [r9]
        XOR  r11, r13
        AND  r11, r8
        XOR  r11, r13
        ST   r11, [r9]
.fnext: LD   r13, [r1 + 8]
        ADD  r2, r13
        LD   r13, [r1 + 12]
        ADD  r3, r13
        DEC  r4
        BNE  .frow
.done:  RESTORE r8-r14
        RET

; ---- forward, aligned: words as they are, four at a time ----
.arow:  MOV  r9, r2
        MOV  r10, r3
        MOV  r13, r5
        BEQ  .asingle
        LD   r12, [r10]
        LD   r13, [r9]
        XOR  r12, r13
        AND  r12, r8
        XOR  r12, r13
        ST   r12, [r9]
        ADDI r10, 4
        ADDI r9, 4
        MOV  r13, r5
        DEC  r13
        BEQ  .alast
        MOV  r11, r13
        AND  r11, #3
        BEQ  .a4
.a1:    LD   r12, [r10]
        ST   r12, [r9]
        ADDI r10, 4
        ADDI r9, 4
        DEC  r11
        BNE  .a1
.a4:    LSR  r13, #2
        BEQ  .alast
.a4l:   LD   r12, [r10]
        ST   r12, [r9]
        LD   r12, [r10 + 4]
        ST   r12, [r9 + 4]
        LD   r12, [r10 + 8]
        ST   r12, [r9 + 8]
        LD   r12, [r10 + 12]
        ST   r12, [r9 + 12]
        ADDI r10, 16
        ADDI r9, 16
        DEC  r13
        BNE  .a4l
.alast: LD   r12, [r10]
        LD   r13, [r9]
        XOR  r12, r13
        AND  r12, r14
        XOR  r12, r13
        ST   r12, [r9]
        BRA  .anext
.asingle:
        LD   r12, [r10]
        LD   r13, [r9]
        XOR  r12, r13
        AND  r12, r8
        XOR  r12, r13
        ST   r12, [r9]
.anext: LD   r13, [r1 + 8]
        ADD  r2, r13
        LD   r13, [r1 + 12]
        ADD  r3, r13
        DEC  r4
        BNE  .arow
        BRA  .done

; ---- backward: from the last word down, with the pointers at it ----
.back:  LD   r13, [r1 + 36]
        BEQ  .barow
.brow:  MOV  r9, r2
        MOV  r10, r3
        MVI  r11, 0             ; hi of the last word
        LD   r13, [r1 + 44]
        BEQ  .b0
        LD   r11, [r10]
        ROR  r11, r6
.b0:    MOV  r13, r5
        BEQ  .bsingle
        ADDI r10, -4            ; the last word, under rmask
        LD   r12, [r10]
        ROR  r12, r6
        XOR  r11, r12           ; out = lo' ^ ((lo' ^ hi') & ~M)
        BIC  r11, r7
        XOR  r11, r12
        LD   r13, [r9]
        XOR  r11, r13
        AND  r11, r14
        XOR  r11, r13
        ST   r11, [r9]
        MOV  r11, r12
        MOV  r13, r5
        DEC  r13
        BEQ  .bfirst
.bmid:  ADDI r10, -4
        LD   r12, [r10]
        ROR  r12, r6
        XOR  r11, r12
        BIC  r11, r7
        XOR  r11, r12
        ADDI r9, -4
        ST   r11, [r9]
        MOV  r11, r12
        DEC  r13
        BNE  .bmid
.bfirst:
        MVI  r12, 0             ; the first word, under lmask
        LD   r13, [r1 + 40]
        BEQ  .bf0
        ADDI r10, -4
        LD   r12, [r10]
        ROR  r12, r6
.bf0:   XOR  r11, r12
        BIC  r11, r7
        XOR  r11, r12
        ADDI r9, -4
        LD   r13, [r9]
        XOR  r11, r13
        AND  r11, r8
        XOR  r11, r13
        ST   r11, [r9]
        BRA  .bnext
.bsingle:
        MVI  r12, 0
        LD   r13, [r1 + 40]
        BEQ  .bs0
        ADDI r10, -4
        LD   r12, [r10]
        ROR  r12, r6
.bs0:   XOR  r11, r12
        BIC  r11, r7
        XOR  r11, r12
        LD   r13, [r9]
        XOR  r11, r13
        AND  r11, r8
        XOR  r11, r13
        ST   r11, [r9]
.bnext: LD   r13, [r1 + 8]
        ADD  r2, r13
        LD   r13, [r1 + 12]
        ADD  r3, r13
        DEC  r4
        BNE  .brow
        BRA  .done

.barow: MOV  r9, r2
        MOV  r10, r3
        MOV  r13, r5
        BEQ  .basingle
        LD   r12, [r10]         ; the last word, under rmask
        LD   r13, [r9]
        XOR  r12, r13
        AND  r12, r14
        XOR  r12, r13
        ST   r12, [r9]
        MOV  r13, r5
        DEC  r13
        BEQ  .bafirst
.bam:   ADDI r10, -4
        LD   r12, [r10]
        ADDI r9, -4
        ST   r12, [r9]
        DEC  r13
        BNE  .bam
.bafirst:
        ADDI r10, -4
        LD   r12, [r10]
        ADDI r9, -4
        LD   r13, [r9]
        XOR  r12, r13
        AND  r12, r8
        XOR  r12, r13
        ST   r12, [r9]
        BRA  .banext
.basingle:
        LD   r12, [r10]
        LD   r13, [r9]
        XOR  r12, r13
        AND  r12, r8
        XOR  r12, r13
        ST   r12, [r9]
.banext:
        LD   r13, [r1 + 8]
        ADD  r2, r13
        LD   r13, [r1 + 12]
        ADD  r3, r13
        DEC  r4
        BNE  .barow
        BRA  .done
