; bignum: exact factorials up to 52!, printing 10!, 20!, 30!, 40! and 52!.
;
; The number is kept in binary, in 32-bit limbs, least significant first.
; Multiplying by k is one MULU per limb: the high half of the product, in HI,
; is the carry into the next limb. Printing divides a copy by 10^9 until
; nothing is left, with one DIVUL per limb from the top down (the remainder
; of each limb stays in HI as the top half of the next dividend); each
; division's final remainder is the next 9-digit group, least significant
; first.

        .include "lib/start.s"

LIMBS   = 8                     ; 52! < 2^226
BILLION = 1000000000

main:   SAVE r8-r10
        MVI  r1, 1
        ST   r1, [num]          ; num = 1, one limb long
        MVI  r9, 1              ; r9 = length in limbs
        MVI  r8, 2              ; r8 = k
        LEA  r10, show          ; r10 -> the next factorial to print
.fact:  MOV  r1, r8
        MOV  r2, r9
        BSR  mulsmall           ; num *= k
        MOV  r9, r1
        LDB  r1, [r10]
        CMP  r1, r8
        BNE  .next
        ADDI r10, 1
        MOV  r1, r8             ; "k! = num"
        BSR  print_u32
        LEA  r1, s_eq
        BSR  puts
        MOV  r1, r9
        BSR  printnum
        BSR  newline
.next:  ADDI r8, 1
        CMPI r8, 52
        BLS  .fact
        RESTORE r8-r10
        RET

; mulsmall: r1 = k, r2 = length -> num *= k, r1 = the new length.
; k is the multiplier (the second operand), so with k small the multiply
; stops early.
mulsmall:
        LEA  r3, num            ; r3 -> the limb
        MOV  r4, r2
        LSL  r4, #2
        ADD  r4, r3             ; r4 = end
        MVI  r5, 0              ; r5 = carry
.limb:  LD   r6, [r3]
        MULU r6, r1             ; HI:r6 = limb * k
        ADD  r6, r5             ; + carry in
        MFHI r5                 ; (MFHI leaves the flags alone)
        ADC  r5, r0             ; carry out: limb * k + carry < 2^32 * k
        ST   r6, [r3]
        ADDI r3, 4
        CMP  r3, r4
        BNE  .limb
        TST  r5, r5
        BEQ  .done
        ST   r5, [r3]           ; a carry left over: a new top limb
        ADDI r2, 1
.done:  MOV  r1, r2
        RET

; printnum: r1 = length: print num in decimal. Dividing by 10^9 < 2^32 can
; empty at most the top limb, so one check per division keeps the length up
; to date.
printnum:
        SAVE r8-r11
        LEA  r11, tmp
        MOV  r3, r1
        LSL  r3, #2             ; byte count for memcpy
        LEA  r9, [r3 + tmp]     ; r9 = end of the number in tmp
        MOV  r1, r11
        LEA  r2, num
        BSR  memcpy             ; work on a copy
        LI   r8, #BILLION
        MOV  r10, sp            ; the groups go on the stack above this
.group: MTHI r0                 ; nothing above the top limb
        MOV  r3, r9
.div:   ADDI r3, -4             ; from the top limb down:
        LD   r1, [r3]
        DIVUL r1, r8            ; (HI:limb) / 10^9, remainder to HI
        ST   r1, [r3]
        CMP  r3, r11
        BNE  .div
        MFHI r1
        PUSH r1                 ; the next 9-digit group
        LD   r1, [r9 - 4]       ; the top limb is still there?
        BNE  .group
        ADDI r9, -4             ; no: one limb shorter
        CMP  r9, r11
        BNE  .group             ; until the number is 0
        POP  r1                 ; the top group without leading zeros...
        BSR  print_u32
.print: CMP  sp, r10
        BEQ  .done
        POP  r1                 ; ...and the rest as exactly 9 digits
        MVI  r2, 9
        BSR  print_u32z
        BRA  .print
.done:  RESTORE r8-r11
        RET

show:   .byte 10, 20, 30, 40, 52, 0
s_eq:   .asciz "! = "

        .include "lib/console.s"
        .include "lib/print.s"
        .include "lib/string.s"

        .align 4
num:    .space 4 * LIMBS
tmp:    .space 4 * LIMBS
