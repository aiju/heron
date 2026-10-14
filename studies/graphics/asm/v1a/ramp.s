; ramp_rows(job): anti-aliased coverage through a ramp of pixel values,
; in draft 1a (src/expand.c has the C version; src/gfx.h the job).
; Pixels with coverage 0 are left alone.
;
; RampJob: d 0, c 4, dpitch 8, cpitch 12, h 16, n 20, lead 24, w 28,
;          ramp 32, depth 36
;
; At 8 bits per pixel a pixel is a byte: load the coverage, look it up,
; store it. Below that, the destination word rotates through the pixels
; (see below). Rotating by bpp is 1, 2 or 4 steps; shifting each value up
; to its place instead would be up to 8. The C version builds the pixels
; and a mask, and merges them.

        .global _ramp_rows
        .section .text._ramp_rows
_ramp_rows:
        LD   r2, [r1 + 36]
        CMPI r2, 3
        BNE  .packed
; 8 bits: r2 the destination row (from the first pixel), r3 the coverage
        SAVE r8-r12
        LD   r2, [r1]
        LD   r6, [r1 + 24]
        ADD  r2, r6
        LD   r3, [r1 + 4]
        LD   r7, [r1 + 32]
        LD   r11, [r1 + 8]
        LD   r12, [r1 + 12]
        LD   r4, [r1 + 16]
        BLE  .bout
.brow:  MOV  r8, r2
        MOV  r9, r3
        LD   r6, [r1 + 28]
.bpx:   LDB  r10, [r9]          ; (sets Z)
        BEQ  .bz
        ADD  r10, r7
        LDB  r10, [r10]
        STB  r10, [r8]
.bz:    INC  r9
        INC  r8
        DEC  r6
        BNE  .bpx
        ADD  r2, r11
        ADD  r3, r12
        DEC  r4
        BNE  .brow
.bout:  RESTORE r8-r12
        RET

; 1, 2 and 4 bits: the destination word itself rotates right by bpp a
; pixel at a time, so that each pixel in turn is at the bottom, where it is
; replaced (BIC, OR) if it has coverage; after 32/bpp rotations the word
; is back in place. The first word starts lead pixels in (a rotation by
; lead * bpp first), and the row's last word owes the rotations of the
; pixels after its end.
;
; r5 the pixels of this word, r6 the row's pixels left, r7 the ramp, r8
; bpp, r9 the destination word, r10 the coverage, r11 a pixel's mask, r12
; the word, r13 a rotation. The frame: the pixels per word, the rotation
; owed at the end of this word (in pixels), the depth.
PPW     = 0
OWED    = 4
DEPTH   = 8

.packed:
        SAVE r8-r14
        ADDI sp, -12
        ST   r2, [sp + DEPTH]
        MVI  r8, 1
        LSL  r8, r2             ; bpp
        MVI  r5, 32
        LSR  r5, r2
        ST   r5, [sp + PPW]
        MVI  r11, 1
        LSL  r11, r8
        DEC  r11                ; the mask of one pixel
        LD   r7, [r1 + 32]
        LD   r2, [r1]
        LD   r3, [r1 + 4]
        LD   r4, [r1 + 16]
        BLE  .pout
.row:   MOV  r9, r2
        MOV  r10, r3
        LD   r6, [r1 + 28]
        LD   r12, [r9]          ; the first word, turned past its lead pixels
        LD   r13, [r1 + 24]
        LD   r5, [sp + PPW]
        SUB  r5, r13            ; it holds ppw - lead of them
        LD   r14, [sp + DEPTH]
        LSL  r13, r14
        ROR  r12, r13
.word:  MOV  r14, r5            ; its room
        CMP  r5, r6
        BLS  .w1
        MOV  r5, r6
.w1:    SUB  r14, r5            ; the rotations owed if the row ends in it
        ST   r14, [sp + OWED]
        SUB  r6, r5
.px:    LDB  r14, [r10]
        BEQ  .pz
        ADD  r14, r7
        LDB  r14, [r14]
        BIC  r12, r11
        OR   r12, r14
.pz:    INC  r10
        ROR  r12, r8
        DEC  r5
        BNE  .px
        LD   r13, [sp + OWED]
        BEQ  .put
        LD   r14, [sp + DEPTH]
        LSL  r13, r14
        ROR  r12, r13
.put:   ST   r12, [r9]
        ADDI r9, 4
        TST  r6, r6
        BEQ  .rend
        LD   r12, [r9]
        LD   r5, [sp + PPW]
        BRA  .word
.rend:  LD   r14, [r1 + 8]
        ADD  r2, r14
        LD   r14, [r1 + 12]
        ADD  r3, r14
        DEC  r4
        BNE  .row
.pout:  ADDI sp, 12
        RESTORE r8-r14
        RET
