; Number printing. Writes straight to the console, so it needs no other file.
;
;   print_u16    r1 = value                      unsigned decimal
;   print_u16z   r1 = value, r2 = digits (1-5)   unsigned decimal, zero-padded to r2 digits
;   print_s16    r1 = value                      signed decimal
;   print_u32    r1 = low, r2 = high             unsigned decimal
;   print_s32    r1 = low, r2 = high             signed decimal
;   print_hex32  r1 = low, r2 = high             8 hex digits
;   print_hex16  r1 = value                      4 hex digits (keeps r1)
;   print_hex8   r1 = value                      2 hex digits of the low byte (keeps r1)
;
; There is no divide instruction, so decimal digits come from repeated
; subtraction of powers of ten (at most 9 subtractions per digit), which is
; much cheaper than a 16- or 32-step software division per digit.
; All of them clobber r1-r7 at most and leave r8-r14 alone.

PR_OUT = 0xFF00

        .align 2

print_s16:
        TST  r1, r1
        BPL  print_u16
        MVI  r2, '-'
        STB  r2, [PR_OUT]
        NEG  r1                 ; -32768 becomes 32768 unsigned, which is right
print_u16:
        MVI  r2, 1
print_u16z:
        LI   r3, #__pr_pow16
        MVI  r4, 5              ; digit positions left
.digit: LD   r5, [r3]           ; 10000, 1000, 100, 10, 1
        MVI  r6, '0' - 1
.sub:   INC  r6                 ; subtract until it borrows...
        SUB  r1, r5
        BHS  .sub
        ADD  r1, r5             ; ...then add the last one back
        CMPI r6, '0'
        BNE  .print
        CMP  r4, r2             ; a leading zero: print it only inside the width
        BHI  .skip
.print: STB  r6, [PR_OUT]
        MVI  r2, 5              ; once a digit is out, print all the rest
.skip:  ADDI r3, 2
        DEC  r4
        BNE  .digit
        RET

print_s32:
        TST  r2, r2
        BPL  print_u32
        MVI  r3, '-'
        STB  r3, [PR_OUT]
        NEG  r1                 ; negate r2:r1. NEG sets C exactly when r1 was 0,
        NOT  r2                 ; which is the carry into the high half of ~x + 1
        ADC  r2, r0
print_u32:
        LI   r3, #__pr_pow32
        MVI  r4, 10             ; powers left
        ; skip powers greater than the value (leading zeros), but always
        ; keep the last one so that 0 prints as "0"
.lead:  CMPI r4, 1
        BEQ  .digit
        LD   r6, [r3 + 2]       ; 32-bit compare: high halves first...
        CMP  r2, r6
        BHI  .digit
        BLO  .next
        LD   r5, [r3]           ; ...and the low halves only if those are equal
        CMP  r1, r5
        BHS  .digit
.next:  ADDI r3, 4
        DEC  r4
        BRA  .lead
.digit: LD   r5, [r3]
        LD   r6, [r3 + 2]
        MVI  r7, '0' - 1
.sub:   INC  r7
        SUB  r1, r5
        SBC  r2, r6
        BHS  .sub
        ADD  r1, r5
        ADC  r2, r6
        STB  r7, [PR_OUT]
        ADDI r3, 4
        DEC  r4
        BNE  .digit
        RET

print_hex32:
        PUSH r1
        MOV  r1, r2
        BSR  print_hex16
        POP  r1
print_hex16:                    ; shifts are one bit at a time, so SWAB does
        SWAB r2, r1             ; the first 8 bits of every 12- or 8-bit shift
        SHR  r2
        SHR  r2
        SHR  r2
        SHR  r2
        BSR  __pr_hexdig        ; bits 15-12
        SWAB r2, r1
        BSR  __pr_hexdig        ; bits 11-8
print_hex8:
        MOV  r2, r1
        SHR  r2
        SHR  r2
        SHR  r2
        SHR  r2
        BSR  __pr_hexdig        ; bits 7-4
        MOV  r2, r1             ; bits 3-0, and return through __pr_hexdig
__pr_hexdig:                    ; print the low nibble of r2
        AND  r2, #15
        LDB  r2, [__pr_hexchars + r2]
        STB  r2, [PR_OUT]
        RET

__pr_pow16:
        .word 10000, 1000, 100, 10, 1
__pr_pow32:                     ; low word first (lo()/hi() are bytes, so mask by hand)
        .word 1000000000 & 0xFFFF, 1000000000 >> 16
        .word 100000000 & 0xFFFF, 100000000 >> 16
        .word 10000000 & 0xFFFF, 10000000 >> 16
        .word 1000000 & 0xFFFF, 1000000 >> 16
        .word 100000 & 0xFFFF, 100000 >> 16
        .word 10000, 0
        .word 1000, 0
        .word 100, 0
        .word 10, 0
        .word 1, 0
__pr_hexchars:
        .ascii "0123456789ABCDEF"
        .align 2
