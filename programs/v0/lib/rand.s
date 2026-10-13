; xorshift16 pseudo-random numbers (shifts 7, 9, 8: period 65535, never 0).
;
;   srand   r1 = seed (0 is replaced by 1)
;   rand    -> r1 = next value (1-65535), clobbers r2
;
; Shifts are one bit per instruction, so each shift starts with SWAB (a free
; shift by 8) and corrects by one bit.

        .align 2

srand:  TST  r1, r1
        BNE  .ok
        MVI  r1, 1
.ok:    ST   r1, [rand_state]
        RET

rand:   LD   r1, [rand_state]
        SWAB r2, r1             ; x ^= x << 7: rotate the swapped word right
        SHR  r0, r2             ; by one (C = x bit 8 goes to the top) and
        RRC  r2                 ; drop the bits that came from the high byte
        AND  r2, #0xFF80
        XOR  r1, r2
        SWAB r2, r1             ; x ^= x >> 9
        ZXT  r2
        SHR  r2
        XOR  r1, r2
        ZXT  r2, r1             ; x ^= x << 8
        SWAB r2
        XOR  r1, r2
        ST   r1, [rand_state]
        RET

rand_state:
        .word 1
