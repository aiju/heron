; The CF card's data register, moved a sector at a time: 256 halfword
; accesses to the one register, two at a time into a word of the buffer.

        .global _ide_in, _ide_out

; ide_in(reg, buf, words): words 32-bit words from the 16-bit register
        .section .text._ide_in
_ide_in:
.in:    MOV  r4, half [r1]
        MOV  r5, half [r1]
        LSL  r5, #16
        OR   r4, r5
        MOV  [r2]+, r4
        DBNZ r3, .in
        RET

; ide_out(reg, buf, words)
        .section .text._ide_out
_ide_out:
.out:   MOV  r4, [r2]+
        MOV  half [r1], r4
        LSR  r4, #16
        MOV  half [r1], r4
        DBNZ r3, .out
        RET
