; fill_rows_blk(job): the fill kernel with FILL (RFC 0041, 2.1): r3 words
; of r2 from r1 up, 256 at most. COPY's whole words; the edges, and
; everything else, as fill_rows_asm.
;
; FillJob: p 0, pitch 4, h 8, lmask 12, n 16, rmask 20, pat 24, rop 28,
; pats 32, row0 36

        .global _fill_rows_blk
        .section .text._fill_rows_blk
_fill_rows_blk:
        MOVS r0, [r1 + 32]
        BNE  .asm
        MOVS r0, [r1 + 28]
        BNE  .asm
        MOV  r0, [r1 + 16]
        CMP  r0, #2
        BHS  .go
.asm:   JMP  _fill_rows_asm

.go:    SAVE r8-r14
        MOV  r8, [r1]           ; r8: the row
        MOV  r12, [r1 + 8]      ; r12: rows
        MOV  r10, [r1 + 24]     ; r10: the pattern
        MOV  r5, [r1 + 12]      ; r5: lmask
        MOV  r6, [r1 + 20]      ; r6: rmask
        MOV  r4, [r1 + 16]      ; r4: whole words
        MOV  r11, [r1 + 4]
        LSL  r11, #2            ; r11: the pitch in bytes
        MOV  r9, r10
        AND  r9, r5             ; r9: pat & lmask
        MOV  r13, r10
        AND  r13, r6            ; r13: pat & rmask
.row:   MOV  r1, r8
        MOV  r0, [r1]
        BIC  r0, r5
        OR   r0, r9
        MOV  [r1]+, r0
        MOV  r2, r10
        MOV  r14, r4
.chunk: MOV  r3, r14
        CMP  r3, #256
        BLS  .fill
        MOV  r3, #256
.fill:  MOV  r0, #-1           ; CL <- 0 first (the microcode's count test
        CLZ  r0, r0            ; reads CL before it loads it: see the README)
        .half 0x01FD            ; FILL
        SUB  r14, r3
        BNE  .chunk
        TST  r6, r6
        BEQ  .next
        MOV  r0, [r1]
        BIC  r0, r6
        OR   r0, r13
        MOV  [r1], r0
.next:  ADD  r8, r11
        DEC  r12
        BNE  .row
        RESTORE r8-r14
        RET
