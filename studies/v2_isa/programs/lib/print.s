; Number printing (draft 2). Writes straight to the console, so it needs no
; other library file.
;
;   print_u32    r1 = value                          unsigned decimal
;   print_s32    r1 = value                          signed decimal
;   print_u32z   r1 = value, r2 = minimum digits     unsigned decimal, zero-padded
;   print_u64    r1 = low word, r2 = high word       unsigned decimal
;   print_hex    r1 = value, r2 = digits (1-8)       the low r2 hex digits, uppercase
;
; The decimal routines clobber r0-r6, print_hex r1-r4; r7-r14 are left
; alone. The decimal routines use at most 80 bytes of stack (one word
; per digit).
;
; Decimal digits come from the hardware divide: DIVU by 10 leaves the next
; digit (least significant first) in r0. The digits are pushed on the stack
; and popped back in printing order. print_u64 divides the 64-bit value by
; 10 with a DIVU/DIVUL pair (the remainder of the high word is the top half
; of the low word's dividend) until the high word is 0, then carries on with
; the 32-bit loop.

PR_OUT = 0xFFFFFF00             ; console data register

        .align 2

print_s32:
        TST  r1, r1
        BPL  print_u32
        MOV  r2, #'-'
        MOV  byte [PR_OUT], r2
        NEG  r1                 ; -2^31 stays 0x80000000 = 2147483648 unsigned: right
print_u32:
        MOV  r2, #1
print_u32z:
        MOV  r4, sp             ; r4 = the stack pointer before the digits
        MOV  r5, #10
__pr_digits:                    ; print_u64 joins here, with r4 and r5 set up
.div:   DEC  r2                 ; count down the minimum width
        DIVU r0:r1, r5          ; r1 /= 10, r0 = digit; Z = nothing left
        PUSH r0                 ; (stores leave the flags alone)
        BNE  .div
        MOV  r3, #'0'
        MOV  r6, #PR_OUT
.pad:   DEC  r2                 ; r2 = width - digits: print that many zeros
        BMI  .out
        MOV  byte [r6], r3
        BRA  .pad
.out:   POP  r1                 ; most significant digit first
        ADD  r1, r3
        MOV  byte [r6], r1
        CMP  sp, r4
        BNE  .out
        RET

print_u64:
        TST  r2, r2
        BEQ  print_u32          ; the high word is 0: a 32-bit number
        MOV  r4, sp
        MOV  r5, #10
.div:   DIVU  r0:r2, r5         ; high word / 10, remainder in r0...
        DIVUL r0:r1, r5         ; ...on top of the low word: (r0:low) / 10, r0 = digit
        PUSH  r0
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
        MOV  r4, #PR_OUT
.loop:  ROR  r1, #28            ; rotate left 4: the next digit to bits 3-0
        MOV  r3, r1
        AND  r3, #15
        MOV  r3, byte [__pr_hexdigits + r3]
        MOV  byte [r4], r3
        DBNZ r2, .loop
        RET

__pr_hexdigits:
        .ascii "0123456789ABCDEF"
