; xorshift16 pseudo-random numbers (draft 2).
;
;   srand   r1 = seed (only the low 16 bits count; 0 becomes 1)  -> (nothing)   clobbers r1
;   rand                                         -> r1 = next value, 1-65535     clobbers r2
;
; The same generator as draft 0 and XorShift16 in
; studies/v1_isa/programs/reference.py, so ported programs see the same
; sequences: x ^= x << 7; x ^= x >> 9; x ^= x << 8, all on 16 bits (period
; 65535, never 0). The state is a 16-bit value kept zero-extended in a word. In 32-bit registers the left shifts
; carry bits past bit 15, so x is cut back to 16 bits after the first step,
; before x >> 9 could pull those bits down into the result. The last step
; only needs the low byte, which then can't overflow.
; Needs no other library file.

        .align 2

srand:  ZXH  r1
        BNE  .ok
        MOV  r1, #1
.ok:    MOV  [rand_state], r1
        RET

rand:   MOV  r1, [rand_state]
        MOV  r2, r1             ; x ^= x << 7
        LSL  r2, #7
        XOR  r1, r2
        ZXH  r1                 ;   back to 16 bits
        MOV  r2, r1             ; x ^= x >> 9
        LSR  r2, #9
        XOR  r1, r2
        ZXB  r2, r1             ; x ^= x << 8: only the low byte stays inside 16 bits
        LSL  r2, #8
        XOR  r1, r2
        MOV  [rand_state], r1
        RET

        .align 4
rand_state:
        .word 1
