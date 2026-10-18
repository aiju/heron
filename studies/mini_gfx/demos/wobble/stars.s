; The stars in draft 2 (wobble.c has the C version and the Star): each
; erased from where it was drawn, moved `speed` nearer, projected through
; the table of reciprocals rz (two multiplies), and drawn through the
; table of row addresses and the format's pixel masks (the reciprocals
; have 8 fraction bits and the coordinates 10, so that MULS, with both
; operands in 16 bits, takes 16 steps rather than 32); a star that comes
; too near or leaves the screen starts again far away at a random place
; (a xorshift in stars_seed) and is drawn from the next frame.
;
;   void stars_move_asm(Star *s, int n, const int *rz, const unsigned *zcol,
;                       unsigned **rows, const unsigned *pmask, int h, int speed)
;
; Star: x 0, y 4, z 8, p 12, m 16 (20 bytes)

        .global _stars_move_asm
        .section .text._stars_move_asm
_stars_move_asm:
        SAVE r7-r14
        MOV  r5, [sp + 32]      ; rows
        MOV  r6, [sp + 36]      ; pmask
        MOV  r7, [sp + 40]      ; h
        MOV  r8, [sp + 44]      ; speed
        MOV  r9, [_stars_seed]
        MOV  r14, r7
        LSR  r14, #1            ; r14: h / 2
.star:  MOV  r10, [r1 + 12]     ; erase: *p &= ~m
        MOV  r11, [r1 + 16]
        MOV  r12, [r10]
        BIC  r12, r11
        MOV  [r10], r12
        MOV  r12, [r1 + 8]      ; z -= speed
        SUB  r12, r8
        CMP  r12, #16
        BLT  .new
        MOV  [r1 + 8], r12
        MOV  r13, [r3 + r12*4]  ; rz[z]
        MOV  r10, [r1]
        MULS r0:r10, r13
        ASR  r10, #8
        ADD  r10, #320          ; sx
        CMP  r10, #640
        BHS  .new
        MOV  r11, [r1 + 4]
        MULS r0:r11, r13
        ASR  r11, #8
        ADD  r11, r14           ; sy
        CMP  r11, r7
        BHS  .new
        MOV  r12, [r5 + r11*4]  ; the row
        MOV  r0, r10
        LSR  r0, #3
        LEA  r12, [r12 + r0*4]  ; p
        AND  r10, #7
        MOV  r11, [r6 + r10*4]  ; m
        MOV  r10, [r1 + 8]
        LSR  r10, #6
        MOV  r10, [r4 + r10*4]  ; the colour's word
        AND  r10, r11
        MOV  r0, [r12]
        BIC  r0, r11
        OR   r0, r10
        MOV  [r12], r0
        MOV  [r1 + 12], r12
        MOV  [r1 + 16], r11
.next:  ADD  r1, #20
        DEC  r2
        BNE  .star
        MOV  [_stars_seed], r9
        RESTORE r7-r14
        RET

; a new star, far away: x -512..511, y -256..255, z 1023, not drawn
.new:   MOV  r0, r9             ; xorshift: << 13, >> 17, << 5
        LSL  r0, #13
        XOR  r9, r0
        MOV  r0, r9
        LSR  r0, #17
        XOR  r9, r0
        MOV  r0, r9
        LSL  r0, #5
        XOR  r9, r0
        MOV  r0, r9
        AND  r0, #1023
        SUB  r0, #512
        MOV  [r1], r0
        MOV  r0, r9
        LSR  r0, #10
        AND  r0, #511
        SUB  r0, #256
        MOV  [r1 + 4], r0
        MOV  r0, #1023
        MOV  [r1 + 8], r0
        CLR  [r1 + 16]
        BRA  .next
