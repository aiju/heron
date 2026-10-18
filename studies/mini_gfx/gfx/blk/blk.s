; The block instructions from C (the blk variant only: with GFX_BLK), each
; a call's arguments in its registers, any count (256 at a time). gfx.h
; declares them.
;
;   void blk_fill(unsigned *d, unsigned v, int n)
;   void blk_copy(unsigned *d, const unsigned *s, int n)
;   void blk_expand(unsigned *d, const unsigned char *s, int n,
;                   const unsigned *table, unsigned fg_xor_bg, unsigned bg)
;   unsigned blk_blit(unsigned *d, const unsigned *s, int n, int k,
;                     unsigned lo, unsigned mask)
;       BLIT k: returns the last word rotated (the next call's lo)

        .global _blk_fill, _blk_copy, _blk_expand, _blk_blit

        .section .text._blk_fill
_blk_fill:
        MOV  r4, r3
.l:     MOV  r3, r4
        CMP  r3, #256
        BLS  .go
        MOV  r3, #256
.go:    TST  r3, r3
        BEQ  .done
        .half 0x01FD            ; FILL
        SUB  r4, r3
        BNE  .l
.done:  RET

        .section .text._blk_copy
_blk_copy:
        MOV  r4, r3
.l:     MOV  r3, r4
        CMP  r3, #256
        BLS  .go
        MOV  r3, #256
.go:    TST  r3, r3
        BEQ  .done
        .half 0x02FD            ; COPY
        SUB  r4, r3
        BNE  .l
.done:  RET

        .section .text._blk_expand
_blk_expand:
        MOV  r5, [sp]           ; the fifth and sixth arguments
        MOV  r6, [sp + 4]
        MOV  r0, r3
.l:     MOV  r3, r0
        CMP  r3, #256
        BLS  .go
        MOV  r3, #256
.go:    TST  r3, r3
        BEQ  .done
        .half 0x03FD            ; EXPAND
        SUB  r0, r3
        BNE  .l
.done:  RET

; BLIT k for k = 0-7 (r4): through a table of the eight encodings, patched
; into the instruction (a jump between: the prefetch queue holds no old copy)
        .section .text._blk_blit
_blk_blit:
        SAVE r7-r8
        MOV  r8, r4
        AND  r8, #7
        LSL  r8, #8
        OR   r8, #0x10FD
        LEA  r0, [pc + .op]
        MOV  half [r0], r8
        MOV  r5, [sp + 8]       ; lo
        MOV  r0, [sp + 12]      ; the mask
        MOV  r8, r0
        MOV  r4, r3
        BRA  .l
.l:     MOV  r3, r4
        CMP  r3, #256
        BLS  .go
        MOV  r3, #256
.go:    TST  r3, r3
        BEQ  .done
        MOV  r0, r8
.op:    .half 0x10FD            ; BLIT k
        SUB  r4, r3
        BNE  .l
.done:  MOV  r1, r5
        RESTORE r7-r8
        RET
