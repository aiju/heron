; Number printing (draft 1a). Writes straight to the console, so it needs no
; other library file.
;
;   print_u32    r1 = value                          unsigned decimal
;   print_s32    r1 = value                          signed decimal
;   print_u32z   r1 = value, r2 = minimum digits     unsigned decimal, zero-padded
;   print_u64    r1 = low word, r2 = high word       unsigned decimal
;   print_hex    r1 = value, r2 = digits (1-8)       the low r2 hex digits, uppercase
;
; The decimal routines clobber r1-r6 and HI, print_hex r1-r4; r7-r14 are
; left alone. The decimal routines use at most 80 bytes of stack (one word
; per digit) below the return address.
;
; Decimal digits come from the hardware divide: DIVU by 10 leaves the next
; digit (least significant first) in HI. The digits are pushed on the stack
; and popped back in printing order. print_u64 divides the 64-bit value by
; 10 with a DIVU/DIVUL pair (the remainder of the high word is the top half
; of the low word's dividend) until the high word is 0, then carries on with
; the 32-bit loop.

PR_OUT = 0xFFFFFF00             ; console data register

        .align 2

print_s32:
        TST  r1, r1
        BPL  print_u32
        MVI  r2, '-'
        STB  r2, [PR_OUT]
        NEG  r1                 ; -2^31 stays 0x80000000 = 2147483648 unsigned: right
print_u32:
        MVI  r2, 1
print_u32z:
        MOV  r4, sp             ; r4 = the stack pointer before the digits
        MVI  r5, 10
__pr_digits:                    ; print_u64 joins here, with r4 and r5 set up
.div:   DEC  r2                 ; count down the minimum width
        DIVU r1, r5             ; r1 /= 10, HI = digit; Z = nothing left
        MFHI r3
        PUSH r3                 ; (MFHI and SAVE leave the flags alone)
        BNE  .div
        MVI  r3, '0'
        LI   r6, #PR_OUT
.pad:   DEC  r2                 ; r2 = width - digits: print that many zeros
        BMI  .out
        STB  r3, [r6]
        BRA  .pad
.out:   POP  r1                 ; most significant digit first
        ADD  r1, r3
        STB  r1, [r6]
        CMP  sp, r4
        BNE  .out
        RET

print_u64:
        TST  r2, r2
        BEQ  print_u32          ; the high word is 0: a 32-bit number
        MOV  r4, sp
        MVI  r5, 10
.div:   DIVU  r2, r5            ; high word / 10, remainder in HI...
        DIVUL r1, r5            ; ...on top of the low word: (HI:low) / 10, HI = digit
        MFHI  r3
        PUSH  r3
        TST   r2, r2
        BNE   .div
        ; The quotient now fits in 32 bits and isn't 0 (the value was at least
        ; 2^32), so the 32-bit loop can take over. r2 = 0: no padding.
        BRA   __pr_digits

; Rotate the first wanted digit to the top, then rotate left 4 bits per digit.
print_hex:
        MOV  r3, r2
        LSL  r3, #2             ; 4 bits per digit; a count of 32 is taken as 0,
        ROR  r1, r3             ; which is right for 8 digits
        LI   r4, #PR_OUT
.loop:  ROR  r1, #28            ; rotate left 4: the next digit to bits 3-0
        MOV  r3, r1
        AND  r3, #15
        LDB  r3, [__pr_hexdigits + r3]
        STB  r3, [r4]
        DEC  r2
        BNE  .loop
        RET

__pr_hexdigits:
        .ascii "0123456789ABCDEF"
