; bignum: exact factorials up to 52! with base-10000 limbs (four decimal
; digits per word), so printing needs no big division: every limb below the
; top one is just printed as four digits.

        .include "lib/start.s"

LIMBS = 20                      ; 52! has 68 digits = 17 limbs
BASE  = 10000

main:   PUSH r8
        MVI  r1, 1              ; num = 1
        ST   r1, [num]
        ST   r1, [len]
        MVI  r8, 2
.fact:  MOV  r1, r8
        BSR  mulsmall           ; num *= k
        LI   r1, #show          ; print the ones listed in `show`
.find:  LDB  r2, [r1]
        BEQ  .next
        INC  r1
        CMP  r2, r8
        BNE  .find
        MOV  r1, r8
        CALL print_u16
        LI   r1, #s_eq
        CALL puts
        BSR  printnum
        CALL newline
.next:  INC  r8
        CMPI r8, 52
        BLS  .fact
        POP  r8
        RET

; mulsmall: num *= r1 (r1 < BASE).
; limb * k + carry < 10000 * 10000, so its high word is below BASE and one
; 32/16 division (udiv32_16) gives both the new limb and the carry.
mulsmall:
        PUSH r8
        PUSH r9
        PUSH r10
        PUSH r11
        MOV  r8, r1             ; r8 = k
        MVI  r9, 0              ; r9 = carry
        LI   r10, #num          ; r10 = limb pointer
        LD   r11, [len]         ; r11 = limbs left
.limb:  LD   r1, [r10]
        MOV  r2, r8
        CALL umul16             ; r2:r1 = limb * k
        ADD  r1, r9             ; + carry
        ADC  r2, r0
        LI   r3, #BASE
        CALL udiv32_16          ; r1 = carry out, r2 = new limb
        ST   r2, [r10]
        MOV  r9, r1
        ADDI r10, 2
        DEC  r11
        BNE  .limb
.grow:  TST  r9, r9             ; carry left over: new limbs on top
        BEQ  .done
        MOV  r1, r9
        MVI  r2, 0
        LI   r3, #BASE
        CALL udiv32_16
        ST   r2, [r10]
        MOV  r9, r1
        ADDI r10, 2
        LD   r1, [len]
        INC  r1
        ST   r1, [len]
        BRA  .grow
.done:  POP  r11
        POP  r10
        POP  r9
        POP  r8
        RET

; printnum: print num in decimal.
printnum:
        PUSH r8
        LD   r8, [len]          ; r8 = byte offset of the top limb
        DEC  r8
        SHL  r8
        LD   r1, [num + r8]     ; the top limb without leading zeros...
        CALL print_u16
.limb:  ADDI r8, -2
        BMI  .done
        LD   r1, [num + r8]     ; ...the rest as exactly four digits
        MVI  r2, 4
        CALL print_u16z
        BRA  .limb
.done:  POP  r8
        RET

show:   .byte 10, 20, 30, 40, 52, 0
s_eq:   .asciz "! = "
        .align 2
len:    .word 0
num:    .space 2 * LIMBS

        .include "lib/console.s"
        .include "lib/print.s"
        .include "lib/mul.s"
        .include "lib/div.s"
