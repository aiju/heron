; expand_rows_blk(job): 1-bit expansion with EXPAND (RFC 0041, 2.1): r3
; words from r1 up, each from a byte at r2 up through the table at r4 as
; r6 ^ (mask & r5). Opaque rows of 8 pixels a word (LIN4, PL4: their
; table is the format's); the row's bits lined up first (expand.s), the
; edges as expand_rows_asm. Everything else is expand_rows_asm's.
;
; ExpandJob: d 0, s 4, dpitch 8, spitch 12, h 16, n 20, lmask 24, rmask 28,
; soff 32, fg 36, bg 40, opaque 44, f 48, fmt 52

        .global _expand_rows_blk
        .section .text._expand_rows_blk
_expand_rows_blk:
        MOVS r0, [r1 + 44]
        BEQ  .asm
        MOV  r2, [r1 + 48]
        MOV  r3, [r2 + 4]
        CMP  r3, #3             ; 8 pixels a word
        BNE  .asm
        MOV  r3, [r1 + 20]
        CMP  r3, #2
        BLO  .asm
        CMP  r3, #250
        BLO  .go
.asm:   JMP  _expand_rows_asm

.go:    SAVE r7-r14
        SUB  sp, #8
        MOV  [sp], r1
        BSR  _xpand_patch
        MOV  r1, [sp]
        MOV  r12, [r1 + 16]     ; r12: rows
        MOV  r8, [r1]           ; r8: the destination row
        MOV  r9, [r1 + 4]       ; r9: the source row
.row:   MOV  r1, [sp]
        MOV  r2, r9
        MOV  r3, [r1 + 20]
        INC  r3
        BSR  _xpand_align       ; r3: the row's bytes
        MOV  r1, [sp]
        MOV  r2, r3             ; EXPAND's source
        MOV  r4, [r1 + 48]
        MOV  r4, [r4 + 272]     ; r4: the table
        MOV  r6, [r1 + 40]      ; r6: bg
        MOV  r5, [r1 + 36]
        XOR  r5, r6             ; r5: fg ^ bg
        MOV  r14, [r1 + 20]     ; r14: n
        MOV  r13, [r1 + 24]     ; r13: lmask
        MOV  r11, [r1 + 28]     ; r11: rmask
        MOV  r1, r8
        MOVS r0, byte [r2]+     ; the first word
        MOV  r0, [r4 + r0*4]
        AND  r0, r5
        XOR  r0, r6
        MOV  r10, [r1]
        XOR  r0, r10
        AND  r0, r13
        XOR  r10, r0
        MOV  [r1]+, r10
        DEC  r14                ; whole words
.chunk: MOV  r3, r14
        CMP  r3, #256
        BLS  .exp
        MOV  r3, #256
.exp:  MOV  r0, #-1           ; CL <- 0 first (the microcode's count test
        CLZ  r0, r0            ; reads CL before it loads it: see the README)
        .half 0x03FD            ; EXPAND
        SUB  r14, r3
        BNE  .chunk
        MOVS r0, byte [r2]      ; the last word
        MOV  r0, [r4 + r0*4]
        AND  r0, r5
        XOR  r0, r6
        MOV  r10, [r1]
        XOR  r0, r10
        AND  r0, r11
        XOR  r10, r0
        MOV  [r1], r10
        MOV  r1, [sp]
        MOV  r0, [r1 + 8]
        LSL  r0, #2
        ADD  r8, r0
        MOV  r0, [r1 + 12]
        LSL  r0, #2
        ADD  r9, r0
        DEC  r12
        BNE  .row
        ADD  sp, #8
        RESTORE r7-r14
        RET
