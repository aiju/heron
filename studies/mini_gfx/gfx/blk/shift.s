; shift_rows_blk(job): the shifted copy with BLIT k (RFC 0041, 2.1), in
; the linear formats whose shift is a whole number of nibbles (4 and 8
; bits a pixel): each source word rotated right by 4k bits and merged
; with the one before under r0, lo's mask; lo is r5 on entry and the last
; word rotated on exit. k is in the instruction, so it's patched in, as
; the edges' ROR #a. Everything else is shift_rows_asm's.
;
; ShiftJob: d 0, s 4, dpitch 8, spitch 12, h 16, n 20, lmask 24, rmask 28,
; rop 32, nterm 36, terms from 40 (src 0, sh 4, m 8), phase 112, bpp 116,
; fmt 120

        .global _shift_rows_blk
        .section .text._shift_rows_blk
_shift_rows_blk:
        MOVS r0, [r1 + 32]
        BNE  .asm
        MOV  r0, [r1 + 36]
        CMP  r0, #2
        BNE  .asm
        MOV  r0, [r1 + 120]
        CMP  r0, #2             ; PF_LIN4 or PF_LIN8
        BLO  .asm
        CMP  r0, #3
        BHI  .asm
        MOV  r0, [r1 + 20]
        CMP  r0, #3
        BHS  .go
.asm:   JMP  _shift_rows_asm

.go:    SAVE r7-r14
        MOV  r2, [r1 + 44]
        NEG  r2                 ; r2: a, lo's right shift
        MOV  r3, r2
        LSR  r3, #2
        LSL  r3, #8
        OR   r3, #0x10FD        ; BLIT k
        LEA  r4, [pc + .blitop]
        MOV  half [r4], r3
        MOV  r3, r2
        AND  r3, #1
        OR   r3, #0xCC
        MOV  r4, r2
        LSR  r4, #1
        LSL  r4, #8
        OR   r3, r4             ; ROR #a
        MOV  r4, r3
        OR   r4, #0xD000        ; r13
        LEA  r6, [pc + .ra1]
        MOV  half [r6], r4
        LEA  r6, [pc + .ra3]
        MOV  half [r6], r4
        OR   r3, #0xE000        ; r14
        LEA  r6, [pc + .ra2]
        MOV  half [r6], r3
        MOV  r8, [r1]           ; r8: the destination row
        MOV  r9, [r1 + 4]       ; r9: the source row
        MOV  r10, [r1 + 8]
        LSL  r10, #2
        MOV  r11, [r1 + 12]
        LSL  r11, #2
        MOV  r12, [r1 + 16]     ; r12: rows
        MOV  r6, [r1 + 24]      ; r6: lmask
        MOV  r7, [r1 + 28]      ; r7: rmask
        MOV  r4, [r1 + 20]
        DEC  r4                 ; r4: whole words
        MOV  r0, [r1 + 48]      ; r0: lo's mask
        BRA  .row

.row:   MOV  r2, r9
        MOV  r1, r8
        MOV  r13, [r2]+
.ra1:   ROR  r13, #1            ; lo
        MOV  r14, [r2]+
.ra2:   ROR  r14, #1            ; hi
        MOV  r5, r14            ; BLIT's lo
        MERGE r14, r13, r0      ; (hi & ~r0) | (lo & r0): the first word
        MOV  r13, [r1]
        XOR  r14, r13
        AND  r14, r6
        XOR  r13, r14
        MOV  [r1]+, r13
        MOV  r14, r4
.chunk: MOV  r3, r14
        CMP  r3, #256
        BLS  .blit
        MOV  r3, #256
.blit:  MOV  r13, #-1          ; CL <- 0 first (the microcode's count test
        CLZ  r13, r13          ; reads CL before it loads it: see the README)
.blitop: .half 0x10FD           ; BLIT k
        SUB  r14, r3
        BNE  .chunk
        MOV  r13, [r2]
.ra3:   ROR  r13, #1
        MERGE r13, r5, r0       ; the last word
        MOV  r14, [r1]
        XOR  r13, r14
        AND  r13, r7
        XOR  r14, r13
        MOV  [r1], r14
        ADD  r8, r10
        ADD  r9, r11
        DEC  r12
        BNE  .row
        RESTORE r7-r14
        RET
