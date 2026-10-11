; Division (restoring shift-and-subtract; there is no DIV instruction).
;
;   udiv16     r1 / r2     -> r1 = quotient, r2 = remainder
;   sdiv16     r1 / r2     -> r1 = quotient (rounded toward 0), r2 = remainder
;                             (sign of the dividend). -32768 / -1 wraps to -32768.
;   udiv32_16  r2:r1 / r3  -> r1 = quotient, r2 = remainder. Needs r2 < r3, so that
;                             the quotient fits in 16 bits (like a hardware 32/16 DIV).
;   udiv32     r2:r1 / r3  -> r2:r1 = quotient, r3 = remainder (three results, so
;                             this one breaks the r1/r2-only result convention)
;
; Dividing by zero is not trapped: the quotient comes out as all ones and the
; remainder as the dividend. Callers that care must check first.
; udiv16/udiv32_16 clobber r1-r4; sdiv16 r1-r6; udiv32 r1-r6.

        .align 2

udiv16: MOV  r3, r2             ; divisor
        MVI  r2, 0              ; a 16-bit dividend is a 32-bit one with r2 = 0
udiv32_16:
        MVI  r4, 16
.loop:  SHL  r1                 ; shift r2:r1 left; the quotient bit lands in r1 bit 0
        RLC  r2
        BCS  .sub               ; a 17-bit partial remainder is certainly >= divisor
        CMP  r2, r3
        BLO  .next
.sub:   SUB  r2, r3
        INC  r1
.next:  DEC  r4
        BNE  .loop
        RET

sdiv16: MOV  r5, r1
        XOR  r5, r2             ; r5 bit 15 = sign of the quotient
        MOV  r6, r1             ; r6 bit 15 = sign of the remainder
        BPL  .1                 ; (MOV set N)
        NEG  r1
.1:     TST  r2, r2
        BPL  .2
        NEG  r2
.2:     BSR  udiv16             ; r1-r4 only
        TST  r5, r5
        BPL  .3
        NEG  r1
.3:     TST  r6, r6
        BPL  .4
        NEG  r2
.4:     RET

; Long division in two 32/16 steps: (0:high) / d, then (remainder:low) / d.
udiv32: MOV  r5, r1             ; low half for later
        MOV  r1, r2
        MVI  r2, 0
        BSR  udiv32_16          ; r1 = quotient high, r2 = remainder (r3 kept)
        MOV  r6, r1
        MOV  r1, r5
        BSR  udiv32_16          ; r2 < r3 holds: it is a remainder
        MOV  r3, r2
        MOV  r2, r6
        RET
