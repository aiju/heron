; copy_rows_blk(job): the copy kernel with COPY (RFC 0041, 2.1): r3 words
; from r2 up to r1 up, 256 at most. Left to right, COPY's whole words; the
; edges, right to left and the other rops as copy_rows_asm.
;
; CopyJob: d 0, s 4, dpitch 8, spitch 12, h 16, n 20, lmask 24, rmask 28,
; back 32, rop 36

        .global _copy_rows_blk
        .section .text._copy_rows_blk
_copy_rows_blk:
        MOVS r0, [r1 + 36]
        BNE  .asm
        MOVS r0, [r1 + 32]
        BNE  .asm
        MOV  r0, [r1 + 20]
        CMP  r0, #3
        BHS  .go
.asm:   JMP  _copy_rows_asm

.go:    SAVE r8-r14
        MOV  r8, [r1]           ; r8: the destination row
        MOV  r9, [r1 + 4]       ; r9: the source row
        MOV  r10, [r1 + 8]
        LSL  r10, #2
        MOV  r11, [r1 + 12]
        LSL  r11, #2
        MOV  r12, [r1 + 16]     ; r12: rows
        MOV  r5, [r1 + 24]      ; r5: lmask
        MOV  r6, [r1 + 28]      ; r6: rmask
        MOV  r4, [r1 + 20]
        DEC  r4                 ; r4: whole words
.row:   MOV  r1, r8
        MOV  r2, r9
        MOV  r0, [r1]
        MOV  r13, [r2]+
        XOR  r13, r0
        AND  r13, r5
        XOR  r0, r13
        MOV  [r1]+, r0
        MOV  r14, r4
.chunk: MOV  r3, r14
        CMP  r3, #256
        BLS  .copy
        MOV  r3, #256
.copy:        .half 0x02FD            ; COPY
        SUB  r14, r3
        BNE  .chunk
        MOV  r0, [r1]
        MOV  r13, [r2]
        XOR  r13, r0
        AND  r13, r6
        XOR  r0, r13
        MOV  [r1], r0
        ADD  r8, r10
        ADD  r9, r11
        DEC  r12
        BNE  .row
        RESTORE r8-r14
        RET
