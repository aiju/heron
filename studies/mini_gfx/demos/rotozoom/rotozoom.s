; The rotozoomer's rows in draft 2 (rotozoom.c has the C ones and the
; packing): u and v as two 8.8 halves of one register, uv = u << 16 | v,
; one ADD stepping both; the texel at (uv >> 24) | (uv & 0xFF00), u's
; whole part and v's.
;
;   void roto_row2_asm(unsigned *d, unsigned uv, unsigned duv, int n,
;                      const unsigned short *tex)
;       n words of two texels each, each texel two pixels (tex holds it
;       doubled, a half): 160 texels a row in M1
;   void roto_row4_asm(unsigned *d, unsigned uv, unsigned duv, int n,
;                      const unsigned *tex)
;       n words of one texel (tex holds it four times): 80 a row

        .global _roto_row2_asm, _roto_row4_asm

        .section .text._roto_row2_asm
_roto_row2_asm:
        SAVE r8-r9
        MOV  r5, [sp + 8]       ; tex
        MOV  r6, #0xFF00
.l:     MOV  r8, r2
        AND  r8, r6
        MOV  r9, r2
        LSR  r9, #24
        OR   r8, r9
        MOV  r0, half [r5 + r8*2]       ; the first texel
        ADD  r2, r3
        MOV  r8, r2
        AND  r8, r6
        MOV  r9, r2
        LSR  r9, #24
        OR   r8, r9
        MOV  r9, half [r5 + r8*2]       ; the second
        ADD  r2, r3
        SWAP r9
        OR   r0, r9
        MOV  [r1]+, r0
        DEC  r4
        BNE  .l
        RESTORE r8-r9
        RET

        .section .text._roto_row4_asm
_roto_row4_asm:
        SAVE r8-r9
        MOV  r5, [sp + 8]
        MOV  r6, #0xFF00
.l:     MOV  r8, r2
        AND  r8, r6
        MOV  r9, r2
        LSR  r9, #24
        OR   r8, r9
        MOV  r0, [r5 + r8*4]
        MOV  [r1]+, r0
        ADD  r2, r3
        DEC  r4
        BNE  .l
        RESTORE r8-r9
        RET

;   void roto_row2_l1_asm(unsigned *d, unsigned uv, unsigned duv, int n,
;                         const unsigned *tex)
;       roto_row2 for L1, where M1's four pixels of a word are spread over
;       its bits (pixel p's bit i at 8i + 2p, or 8(i - 4) + 2p + 1): tex
;       holds each texel as pixels 0 and 1 of a word, and the second texel
;       of a word is the same shifted to pixels 2 and 3, by 4
        .global _roto_row2_l1_asm
        .section .text._roto_row2_l1_asm
_roto_row2_l1_asm:
        SAVE r8-r9
        MOV  r5, [sp + 8]
        MOV  r6, #0xFF00
.l:     MOV  r8, r2
        AND  r8, r6
        MOV  r9, r2
        LSR  r9, #24
        OR   r8, r9
        MOV  r0, [r5 + r8*4]
        ADD  r2, r3
        MOV  r8, r2
        AND  r8, r6
        MOV  r9, r2
        LSR  r9, #24
        OR   r8, r9
        MOV  r9, [r5 + r8*4]
        ADD  r2, r3
        LSL  r9, #4
        OR   r0, r9
        MOV  [r1]+, r0
        DEC  r4
        BNE  .l
        RESTORE r8-r9
        RET
