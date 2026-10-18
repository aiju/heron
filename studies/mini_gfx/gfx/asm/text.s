; text_or_asm(dst, dpitch, src, spitch, bit, rows): a glyph's rows (at
; most 32 pixels each, starting on a word of the strike) ORed into a 1-bit
; buffer from bit `bit` of word dst on (font.c has the C one). The shifts
; are constants patched in: a shift by a register costs a cycle a bit.
;
; Arguments: r1 dst, r2 dpitch (words), r3 src, r4 spitch (words),
; [sp] bit, [sp + 4] rows

        .global _text_or_asm
        .section .text._text_or_asm
_text_or_asm:
        MOV  r5, [sp]           ; r5: bit
        MOV  r6, [sp + 4]       ; r6: rows
        LSL  r2, #2
        LSL  r4, #2             ; the pitches in bytes
        TST  r6, r6
        BEQ  .done
        TST  r5, r5
        BEQ  .aligned
        SAVE r8-r9
        ; LSL r0, #bit: C0 | bit & 1, then the register byte r0, bit >> 1
        MOV  r0, r5
        AND  r0, #1
        OR   r0, #0xC0
        MOV  r8, r5
        LSR  r8, #1
        LSL  r8, #8
        OR   r0, r8
        LEA  r8, [pc + .lsl]
        MOV  half [r8], r0
        ; LSR r9, #32 - bit: C4 | m & 1, then the register byte r9, m >> 1
        MOV  r9, #32
        SUB  r9, r5
        MOV  r0, r9
        AND  r0, #1
        OR   r0, #0xC4
        LSR  r9, #1
        OR   r9, #0x90
        LSL  r9, #8
        OR   r0, r9
        LEA  r8, [pc + .lsr]
        MOV  half [r8], r0
        BRA  .rows              ; a jump: the prefetch queue holds no old copy
.rows:  MOV  r0, [r3]
        MOV  r9, r0
.lsl:   LSL  r0, #1
        OR   r0, [r1]
        MOV  [r1], r0
.lsr:   LSR  r9, #1
        OR   r9, [r1 + 4]
        MOV  [r1 + 4], r9
        ADD  r1, r2
        ADD  r3, r4
        DBNZ r6, .rows
        RESTORE r8-r9
.done:  RET
.aligned:
        MOV  r0, [r3]
        OR   r0, [r1]
        MOV  [r1], r0
        ADD  r1, r2
        ADD  r3, r4
        DBNZ r6, .aligned
        RET
