; copy_rows_asm(job): the copy kernel in draft 2 (blit.c has the C one):
; h rows of n + 1 words from s to d, pitches in words, the first word
; under lmask and the last under rmask; back: each row right to left from
; its last word. COPY only; the other rops go to the C kernel.
;
; CopyJob: d 0, s 4, dpitch 8, spitch 12, h 16, n 20, lmask 24, rmask 28,
; back 32, rop 36

        .global _copy_rows_asm
        .section .text._copy_rows_asm
_copy_rows_asm:
        MOVS r0, [r1 + 36]
        BEQ  .go
        JMP  _copy_rows_c
.go:    SAVE r8-r14
        MOV  r8, [r1]           ; r8: the destination row
        MOV  r9, [r1 + 4]       ; r9: the source row
        MOV  r10, [r1 + 8]
        LSL  r10, #2            ; r10, r11: the pitches in bytes
        MOV  r11, [r1 + 12]
        LSL  r11, #2
        MOVS r12, [r1 + 16]     ; r12: rows left
        BLE  .done
        MOV  r5, [r1 + 24]      ; r5: lmask
        MOV  r6, [r1 + 28]      ; r6: rmask
        MOV  r4, [r1 + 20]      ; r4: n
        MOVS r0, [r1 + 32]
        BNE  .back

; left to right: the first word, n - 1 whole ones four a loop, the last
.frow:  MOV  r2, r8
        MOV  r3, r9
        MOV  r0, [r2]
        MOV  r1, [r3]+
        XOR  r1, r0
        AND  r1, r5
        XOR  r0, r1             ; (d & ~lmask) | (s & lmask)
        MOV  [r2]+, r0
        MOVS r13, r4
        BEQ  .fnext
        DEC  r13                ; the whole words
        MOV  r14, r13
        LSR  r14, #2
        BEQ  .f1s
.f4:    MOV  r0, [r3]+
        MOV  [r2]+, r0
        MOV  r0, [r3]+
        MOV  [r2]+, r0
        MOV  r0, [r3]+
        MOV  [r2]+, r0
        MOV  r0, [r3]+
        MOV  [r2]+, r0
        DBNZ r14, .f4
.f1s:   AND  r13, #3
        BEQ  .flast
.f1:    MOV  r0, [r3]+
        MOV  [r2]+, r0
        DBNZ r13, .f1
.flast: MOV  r0, [r2]
        MOV  r1, [r3]
        XOR  r1, r0
        AND  r1, r6
        XOR  r0, r1
        MOV  [r2], r0
.fnext: ADD  r8, r10
        ADD  r9, r11
        DEC  r12
        BNE  .frow
.done:  RESTORE r8-r14
        RET

; right to left, from the last word
.back:  TST  r4, r4
        BNE  .brow
        MOV  r6, r5             ; one word: lmask is both
.brow:  MOV  r2, r8
        MOV  r3, r9
        MOV  r0, [r2]
        MOV  r1, [r3]
        XOR  r1, r0
        AND  r1, r6
        XOR  r0, r1
        MOV  [r2], r0
        MOVS r13, r4
        BEQ  .bnext
        DEC  r13
        BEQ  .bfirst
.b1:    MOV  r0, -[r3]
        MOV  -[r2], r0
        DBNZ r13, .b1
.bfirst:
        MOV  r0, -[r2]
        MOV  r1, -[r3]
        XOR  r1, r0
        AND  r1, r5
        XOR  r0, r1
        MOV  [r2], r0
.bnext: ADD  r8, r10
        ADD  r9, r11
        DEC  r12
        BNE  .brow
        RESTORE r8-r14
        RET
