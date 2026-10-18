; expand_rows_asm(job): 1-bit expansion in draft 2 (blit.c has the job and
; the C kernel), for the formats of 8 pixels a word (PL4 and LIN4: a
; source byte a destination word, through the format's table of 256
; masks); the others go to the C kernel.
;
; Each row in two passes: the source's bits from soff lined up into a
; buffer, 32 at a time (two words rotated by soff, a constant patched in,
; and merged), then a byte of it per destination word: the mask from the
; table, and opaque bg ^ (mask & (fg ^ bg)), or transparent
; d ^ ((d ^ fg) & mask). The first and last words under lmask and rmask.
;
; ExpandJob: d 0, s 4, dpitch 8, spitch 12, h 16, n 20, lmask 24, rmask 28,
; soff 32, fg 36, bg 40, opaque 44, f 48, fmt 52
; Format: pshift 4, nx 268, xt 272

        .global _expand_rows_asm, _xpand_align
        .section .text._expand_rows_asm
_expand_rows_asm:
        MOV  r2, [r1 + 48]
        MOV  r3, [r2 + 4]
        CMP  r3, #3             ; 8 pixels a word
        BNE  .c
        MOV  r3, [r1 + 20]
        CMP  r3, #250           ; and the buffer holds the row
        BLO  .go
.c:     JMP  _expand_rows_c

.go:    SAVE r7-r14
        SUB  sp, #8
        MOV  [sp], r1           ; [sp]: the job
        BSR  _xpand_patch
        MOV  r12, [r1 + 16]     ; r12: rows
        MOV  r8, [r1]           ; r8: the destination row
        MOV  r9, [r1 + 4]       ; r9: the source row
.row:   MOV  r1, [sp]
        MOV  r2, r9
        MOV  r3, [r1 + 20]      ; n + 1 words: the bytes
        INC  r3
        BSR  _xpand_align       ; r3: the bytes
        MOV  r1, [sp]
        MOV  r2, r8
        MOV  r4, [r1 + 20]      ; r4: whole words after the first
        MOV  r5, [r1 + 48]
        MOV  r5, [r5 + 272]     ; r5: the table
        MOV  r6, [r1 + 36]      ; r6: fg
        MOV  r7, [r1 + 40]      ; r7: bg
        MOV  r13, [r1 + 24]     ; r13: lmask
        MOV  r14, [r1 + 28]     ; r14: rmask
        MOVS r0, [r1 + 44]
        BEQ  .trans

; opaque: r6 = fg ^ bg
        XOR  r6, r7
        MOVS r1, byte [r3]+
        MOV  r1, [r5 + r1*4]
        AND  r1, r6
        XOR  r1, r7             ; the first word's pixels
        MOV  r0, [r2]
        XOR  r1, r0
        AND  r1, r13
        XOR  r0, r1
        MOV  [r2]+, r0
        MOVS r11, r4
        BEQ  .next
        DEC  r11
        BEQ  .olast
.omid:  MOVS r1, byte [r3]+
        MOV  r1, [r5 + r1*4]
        AND  r1, r6
        XOR  r1, r7
        MOV  [r2]+, r1
        DBNZ r11, .omid
.olast: MOVS r1, byte [r3]+
        MOV  r1, [r5 + r1*4]
        AND  r1, r6
        XOR  r1, r7
        MOV  r0, [r2]
        XOR  r1, r0
        AND  r1, r14
        XOR  r0, r1
        MOV  [r2], r0
        BRA  .next

; transparent: the mask under the edges' masks, d ^= (d ^ fg) & mask
.trans: MOVS r1, byte [r3]+
        MOV  r1, [r5 + r1*4]
        AND  r1, r13
        MOV  r0, [r2]
        MOV  r10, r0
        XOR  r10, r6
        AND  r10, r1
        XOR  r0, r10
        MOV  [r2]+, r0
        MOVS r11, r4
        BEQ  .next
        DEC  r11
        BEQ  .tlast
.tmid:  MOVS r1, byte [r3]+
        BEQ  .tskip
        MOV  r1, [r5 + r1*4]
        MOV  r0, [r2]
        MOV  r10, r0
        XOR  r10, r6
        AND  r10, r1
        XOR  r0, r10
        MOV  [r2], r0
.tskip: ADD  r2, #4
        DBNZ r11, .tmid
.tlast: MOVS r1, byte [r3]+
        MOV  r1, [r5 + r1*4]
        AND  r1, r14
        MOV  r0, [r2]
        MOV  r10, r0
        XOR  r10, r6
        AND  r10, r1
        XOR  r0, r10
        MOV  [r2], r0

.next:  MOV  r1, [sp]
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

; _xpand_patch: the job in r1; ROR #soff into the aligning loop, and r0
; (for MERGE) the mask of the top soff bits. Returns through r7.
        .global _xpand_patch
_xpand_patch:
        MOV  r2, [r1 + 32]      ; soff
        MOV  r3, r2
        AND  r3, #1
        OR   r3, #0xCC
        MOV  r4, r2
        LSR  r4, #1
        LSL  r4, #8
        OR   r3, r4             ; ROR #soff
        LEA  r4, [pc + _xpand_ra]
        MOV  r5, r3
        OR   r5, #0xB000        ; r11
        MOV  half [r4], r5
        LEA  r4, [pc + _xpand_rb]
        MOV  r5, r3
        OR   r5, #0xA000        ; r10
        MOV  half [r4], r5
        MOV  r3, #0
        TST  r2, r2
        BEQ  .z
        MOV  r3, #-1
        LSR  r3, r2             ; once a job: a register shift is fine
        NOT  r3                 ; the top soff bits
.z:     LEA  r4, [pc + _xpand_m]
        MOV  [r4], r3
        RET

; _xpand_align: the r3 bytes from source bit soff of the row at r2, lined
; up at _xpand_buf; returns r3 = the buffer. Uses r0-r2, r10, r11, r13.
; Returns through r7: the caller saves it.
_xpand_align:
        MOV  r0, [pc + _xpand_m]
        TST  r0, r0
        BNE  .rot
        MOV  r3, r2             ; soff 0: the source itself
        RET
.rot:   ADD  r3, #3
        LSR  r3, #2             ; words
        LEA  r1, [_xpand_buf]
        MOV  r11, [r2]+
_xpand_ra:
        ROR  r11, #1
_xpand_loop:
        MOV  r10, [r2]+
_xpand_rb:
        ROR  r10, #1
        MOV  r13, r11
        MERGE r13, r10, r0      ; s[j] >> soff | s[j + 1] << 32 - soff
        MOV  [r1]+, r13
        MOV  r11, r10
        DBNZ r3, _xpand_loop
        LEA  r3, [_xpand_buf]
        RET

        .align 4
_xpand_m:
        .word 0

        .global _xpand_buf
        .bss
        .align 4
_xpand_buf:
        .space 256
