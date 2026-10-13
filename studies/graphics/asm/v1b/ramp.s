; ramp_rows(job): anti-aliased coverage through a ramp of pixel values,
; in draft 1b (src/expand.c has the C version; src/gfx.h the job).
; Pixels with coverage 0 are left alone.
;
; RampJob: d 0, c 4, dpitch 8, cpitch 12, h 16, n 20, lead 24, w 28,
;          ramp 32, depth 36
;
; At 8 bits per pixel a pixel is a byte: load the coverage, look it up,
; store it. Below that a destination word is built a pixel at a time:
; the pixel's value goes in at the bottom of v (and its mask in m) and
; both rotate right by bpp, so that after 32/bpp rotations every pixel is
; in its place. Rotating by bpp is 1, 2 or 4 steps; shifting a value up
; to the top of the word instead would be 6 to 8.

        .global _ramp_rows
        .section .text._ramp_rows
_ramp_rows:
        MOV  r2, [r1 + 36]
        CMP  r2, #3
        BNE  .packed
; 8 bits: r2 the destination row (from the first pixel), r3 the coverage
        SAVE r8-r10
        MOV  r2, [r1]
        ADD  r2, [r1 + 24]
        MOV  r3, [r1 + 4]
        MOV  r7, [r1 + 32]
        MOV  r4, [r1 + 16]
        BLE  .bout
.brow:  MOV  r8, r2
        MOV  r9, r3
        MOV  r6, [r1 + 28]
.bpx:   MOV  r10, byte [r9]+
        BEQ  .bz
        MOV  r10, byte [r7 + r10]
        ST   r10, byte [r8]+
        DEC  r6
        BNE  .bpx
        BRA  .bnext
.bz:    INC  r8
        DEC  r6
        BNE  .bpx
.bnext: ADD  r2, [r1 + 8]
        ADD  r3, [r1 + 12]
        DEC  r4
        BNE  .brow
.bout:  RESTORE r8-r10
        RET

; 1, 2 and 4 bits. r5 the pixels of this word, r6 the row's pixels left,
; r7 the ramp, r8 bpp, r9 the destination word, r10 the coverage, r11 a
; pixel's mask, r12 v, r13 m. The frame: the pixels per word, the
; rotation still owed at the end of the row's last word, the depth.
PPW     = 0
OWED    = 4
DEPTH   = 8

.packed:
        SAVE r8-r14
        SUB  sp, #12
        ST   r2, [sp + DEPTH]
        MOV  r8, #1
        LSL  r8, r2             ; bpp
        MOV  r5, #32
        LSR  r5, r2
        ST   r5, [sp + PPW]
        MOV  r11, #1
        LSL  r11, r8
        DEC  r11                ; the mask of one pixel
        MOV  r7, [r1 + 32]
        MOV  r2, [r1]
        MOV  r3, [r1 + 4]
        MOV  r4, [r1 + 16]
        BLE  .pout
.row:   MOV  r9, r2
        MOV  r10, r3
        MOV  r6, [r1 + 28]
        MOV  r5, [sp + PPW]     ; the first word holds ppw - lead of them
        SUB  r5, [r1 + 24]
.word:  MOV  r12, #0
        MOV  r13, #0
        MOV  r14, r5            ; its room
        CMP  r5, r6
        BLS  .w1
        MOV  r5, r6
.w1:    SUB  r14, r5            ; the rotations owed if the row ends in it
        ST   r14, [sp + OWED]
        SUB  r6, r5
.px:    MOV  r14, byte [r10]+
        BEQ  .pz
        OR   r12, byte [r7 + r14]
        OR   r13, r11
.pz:    ROR  r12, r8
        ROR  r13, r8
        DEC  r5
        BNE  .px
        MOV  r14, [sp + OWED]
        BEQ  .put
        MOV  r5, [sp + DEPTH]
        LSL  r14, r5
        ROR  r12, r14
        ROR  r13, r14
.put:   TST  r13, r13
        BEQ  .skip
        MOV  r14, [r9]
        BIC  r14, r13
        AND  r12, r13
        OR   r14, r12
        ST   r14, [r9]
.skip:  ADD  r9, #4
        MOV  r5, [sp + PPW]
        TST  r6, r6
        BNE  .word
        ADD  r2, [r1 + 8]
        ADD  r3, [r1 + 12]
        DEC  r4
        BNE  .row
.pout:  ADD  sp, #12
        RESTORE r8-r14
        RET
