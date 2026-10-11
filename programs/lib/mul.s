; 16 x 16 -> 32 bit multiplication (shift and add; there is no MUL instruction).
;
;   umul16   r1, r2  -> r2:r1 = r1 * r2, unsigned     clobbers r3-r5, keeps r6/r7
;   smul16   r1, r2  -> r2:r1 = r1 * r2, signed       clobbers r3-r6
;
; Cost is about 10 cycles per bit of the smaller operand plus 4 per 1 bit,
; so 1000 * 7 is much cheaper than 1000 * 1000.

        .align 2

umul16: MOV  r3, r2             ; r3 = multiplier, consumed from bit 0 up
        MOV  r4, r1             ; r5:r4 = multiplicand, shifted left each step
        CMP  r1, r2
        BHS  .go
        MOV  r3, r1             ; multiply by the smaller operand: the loop
        MOV  r4, r2             ; stops as soon as the multiplier runs out of 1s
.go:    MVI  r5, 0
        MVI  r1, 0              ; r2:r1 = product
        MVI  r2, 0
        SHR  r3                 ; C = this bit, Z = no 1 bits left after it
        BEQ  .last
.loop:  BCC  .skip
        ADD  r1, r4
        ADC  r2, r5
.skip:  SHL  r4
        RLC  r5
        SHR  r3
        BNE  .loop
.last:  BCC  .done              ; the top 1 bit (C still from the SHR)
        ADD  r1, r4
        ADC  r2, r5
.done:  RET

; Signed: multiply the magnitudes (small magnitudes stay cheap) and fix the sign.
smul16: MOV  r6, r1
        XOR  r6, r2             ; r6 bit 15 = sign of the product
        TST  r1, r1
        BPL  .1
        NEG  r1                 ; -32768 -> 32768 unsigned, which is fine
.1:     TST  r2, r2
        BPL  .2
        NEG  r2
.2:     BSR  umul16             ; leaves r6 alone
        TST  r6, r6
        BPL  .3
        NEG  r1                 ; negate r2:r1 (NEG sets C only if r1 was 0)
        NOT  r2
        ADC  r2, r0
.3:     RET
