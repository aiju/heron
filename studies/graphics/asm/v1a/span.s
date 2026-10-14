; gfx_span(s, y, x0, x1, pat, rop): one row of a polygon or an ellipse,
; in draft 1a (src/gfx.c has the C version, gfx_span_c, and src/gfx.h the
; Surface). All of it here: the clipping, the row's address, the masks of
; the first and last words, from tables (a shift by up to 31 is up to 9
; steps), and the words. COPY, XOR and OR; AND goes to the C version.
;
; Surface: bits 0, w 4, h 8, pitch 12, depth 16, cx0 20, cy0 24, cx1 28,
;          cy1 32
; r1 s, r2 y, r3 x0, r4 x1; on the stack pat, then rop

        .global _gfx_span
        .section .text._gfx_span
_gfx_span:
        LD   r5, [r1 + 24]
        CMP  r2, r5
        BLT  .out
        LD   r5, [r1 + 32]
        CMP  r2, r5
        BGE  .out
        LD   r5, [r1 + 20]
        CMP  r3, r5
        BGE  .x0
        MOV  r3, r5
.x0:    LD   r5, [r1 + 28]
        CMP  r4, r5
        BLE  .x1
        MOV  r4, r5
.x1:    CMP  r3, r4
        BGE  .out
        LD   r5, [sp + 8]       ; the rop
        CMPI r5, 3
        BEQ  _gfx_span_c        ; AND
        SAVE r8-r10
        LD   r6, [r1 + 16]      ; the depth
        LD   r7, [r1 + 12]
        MULS r2, r7
        LD   r7, [r1]
        ADD  r2, r7             ; r2: the row
        LSL  r3, r6             ; the first bit
        LSL  r4, r6
        DEC  r4                 ; and the last
        MOV  r8, r3
        AND  r8, #31
        LSL  r8, #2
        LEA  r9, .lmask
        ADD  r8, r9
        LD   r8, [r8]           ; r8: the first word's mask
        MOV  r9, r4
        AND  r9, #31
        LSL  r9, #2
        LEA  r10, .rmask
        ADD  r9, r10
        LD   r9, [r9]           ; r9: the last word's
        LSR  r3, #5
        LSR  r4, #5
        SUB  r4, r3             ; r4: words after the first
        LSL  r3, #2
        ADD  r2, r3             ; r2: the first word
        TST  r4, r4
        BNE  .multi
        AND  r8, r9             ; one word, under both masks
.multi: LD   r10, [sp + 16]     ; r10: the pattern
        CMPI r5, 1
        BEQ  .xor
        BHI  .or
        LD   r3, [r2]           ; COPY: the first word
        BIC  r3, r8
        AND  r8, r10
        OR   r3, r8
        ST   r3, [r2]
        ADDI r2, 4
        TST  r4, r4
        BEQ  .done
        DEC  r4                 ; the whole words: some singly, then fours
        MOV  r5, r4
        AND  r5, #3
        BEQ  .c4
.c1:    ST   r10, [r2]
        ADDI r2, 4
        DEC  r5
        BNE  .c1
.c4:    LSR  r4, #2
        BEQ  .clast
.c4l:   ST   r10, [r2]
        ST   r10, [r2 + 4]
        ST   r10, [r2 + 8]
        ST   r10, [r2 + 12]
        ADDI r2, 16
        DEC  r4
        BNE  .c4l
.clast: LD   r3, [r2]           ; the last word
        BIC  r3, r9
        AND  r9, r10
        OR   r3, r9
        ST   r3, [r2]
.done:  RESTORE r8-r10
.out:   RET

.xor:   AND  r8, r10
        LD   r3, [r2]
        XOR  r8, r3
        ST   r8, [r2]
        ADDI r2, 4
        TST  r4, r4
        BEQ  .done
        DEC  r4
        BEQ  .xlast
.x1l:   LD   r3, [r2]
        XOR  r3, r10
        ST   r3, [r2]
        ADDI r2, 4
        DEC  r4
        BNE  .x1l
.xlast: AND  r9, r10
        LD   r3, [r2]
        XOR  r9, r3
        ST   r9, [r2]
        BRA  .done

.or:    AND  r8, r10
        LD   r3, [r2]
        OR   r8, r3
        ST   r8, [r2]
        ADDI r2, 4
        TST  r4, r4
        BEQ  .done
        DEC  r4
        BEQ  .olast
.o1l:   LD   r3, [r2]
        OR   r3, r10
        ST   r3, [r2]
        ADDI r2, 4
        DEC  r4
        BNE  .o1l
.olast: AND  r9, r10
        LD   r3, [r2]
        OR   r9, r3
        ST   r9, [r2]
        BRA  .done

        .align 4
.lmask:
        .word 0xFFFFFFFF, 0xFFFFFFFE, 0xFFFFFFFC, 0xFFFFFFF8
        .word 0xFFFFFFF0, 0xFFFFFFE0, 0xFFFFFFC0, 0xFFFFFF80
        .word 0xFFFFFF00, 0xFFFFFE00, 0xFFFFFC00, 0xFFFFF800
        .word 0xFFFFF000, 0xFFFFE000, 0xFFFFC000, 0xFFFF8000
        .word 0xFFFF0000, 0xFFFE0000, 0xFFFC0000, 0xFFF80000
        .word 0xFFF00000, 0xFFE00000, 0xFFC00000, 0xFF800000
        .word 0xFF000000, 0xFE000000, 0xFC000000, 0xF8000000
        .word 0xF0000000, 0xE0000000, 0xC0000000, 0x80000000
.rmask:
        .word 0x00000001, 0x00000003, 0x00000007, 0x0000000F
        .word 0x0000001F, 0x0000003F, 0x0000007F, 0x000000FF
        .word 0x000001FF, 0x000003FF, 0x000007FF, 0x00000FFF
        .word 0x00001FFF, 0x00003FFF, 0x00007FFF, 0x0000FFFF
        .word 0x0001FFFF, 0x0003FFFF, 0x0007FFFF, 0x000FFFFF
        .word 0x001FFFFF, 0x003FFFFF, 0x007FFFFF, 0x00FFFFFF
        .word 0x01FFFFFF, 0x03FFFFFF, 0x07FFFFFF, 0x0FFFFFFF
        .word 0x1FFFFFFF, 0x3FFFFFFF, 0x7FFFFFFF, 0xFFFFFFFF
