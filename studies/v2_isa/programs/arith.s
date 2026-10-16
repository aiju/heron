; arith: the hardware multiply and divide on 16-bit operands, 32-bit add,
; subtract and compare, and 32-bit division, on tables of operands that
; include the edge cases (0, 1, 7FFF, 8000, FFFF, ...).
;
; The 16-bit operands are zero-extended for the unsigned operations and
; sign-extended (SXH) for the signed ones, so the 32-bit MULU/MULS give the
; exact 16 x 16 products and DIVU/DIVS the exact quotients. The signed
; quotient is printed as a 16-bit result, so -32768 / -1 wraps to -32768
; as it would on a 16-bit machine. Division by zero would trap, so it is
; checked first.

        .include "lib/start.s"

main:   SAVE r7-r11

        ; ---- 16 x 16 multiply, 16 / 16 divide ----
        LEA  r1, [s_head16]
        CALL puts
        LEA  r8, [pairs16]
.p16:   MOV  r9, half [r8]      ; a
        MOV  r10, half [r8 + 2] ; b (there is no half auto-increment)
        LEA  r1, [s_a]
        CALL puts
        MOV  r1, r9
        MOV  r2, #4
        CALL print_hex
        LEA  r1, [s_b]
        CALL puts
        MOV  r1, r10
        MOV  r2, #4
        CALL print_hex
        LEA  r1, [s_umul]
        CALL puts
        MOV  r1, r9
        MULU r0:r1, r10
        MOV  r2, #8
        CALL print_hex
        LEA  r1, [s_smul]
        CALL puts
        SXH  r1, r9
        SXH  r2, r10
        MULS r0:r1, r2
        CALL print_s32
        TST  r10, r10
        BNE  .divide
        LEA  r1, [s_div0]
        CALL puts
        BRA  .next16
.divide:
        LEA  r1, [s_udiv]
        CALL puts
        MOV  r1, r9
        DIVU r0:r1, r10
        MOV  r11, r0            ; the remainder survives the calls in r11
        CALL print_u32
        LEA  r1, [s_r]
        CALL puts
        MOV  r1, r11
        CALL print_u32
        LEA  r1, [s_sdiv]
        CALL puts
        SXH  r1, r9
        SXH  r2, r10
        DIVS r0:r1, r2
        MOV  r11, r0
        SXH  r1                 ; the 16-bit quotient: 32768 wraps to -32768
        CALL print_s32
        LEA  r1, [s_r]
        CALL puts
        MOV  r1, r11
        CALL print_s32
.next16:
        CALL newline
        ADD  r8, #4
        CMP  r8, #pairs16_end
        BLO  .p16

        ; ---- 32-bit add, subtract, compare ----
        LEA  r1, [s_head32]
        CALL puts
        LEA  r8, [pairs32]
.p32:   MOV  r9, [r8]+          ; a
        MOV  r10, [r8]+         ; b
        MOV  r1, r9
        MOV  r2, #8
        CALL print_hex
        CALL space
        MOV  r1, r10
        MOV  r2, #8
        CALL print_hex
        LEA  r1, [s_sum]
        CALL puts
        MOV  r1, r9
        ADD  r1, r10
        MOV  r2, #8
        CALL print_hex
        LEA  r1, [s_diff]
        CALL puts
        MOV  r1, r9
        SUB  r1, r10
        MOV  r2, #8
        CALL print_hex
        LEA  r1, [s_u]
        CALL puts
        CMP  r9, r10            ; (a > b) - (a < b) = 1, 0 or -1 picks the
        SETHI r1                ; character from "<=>"
        SETLO r2
        SUB  r1, r2
        MOV  r1, byte [s_cmpchars + 1 + r1]
        CALL putc
        LEA  r1, [s_s]
        CALL puts
        CMP  r9, r10            ; the same with the signed conditions
        SETGT r1
        SETLT r2
        SUB  r1, r2
        MOV  r1, byte [s_cmpchars + 1 + r1]
        CALL putc
        CALL newline
        CMP  r8, #pairs32_end
        BLO  .p32

        ; ---- 32-bit divide ----
        LEA  r1, [s_headdiv]
        CALL puts
        LEA  r8, [divs]
.pdiv:  MOV  r9, [r8]+          ; dividend
        MOV  r10, [r8]+         ; divisor
        MOV  r1, r9
        CALL print_u32
        LEA  r1, [s_slash]
        CALL puts
        MOV  r1, r10
        CALL print_u32
        LEA  r1, [s_eq]
        CALL puts
        MOV  r1, r9
        DIVU r0:r1, r10         ; 32 / 32: quotients above 16 bits are no problem
        MOV  r11, r0
        CALL print_u32
        LEA  r1, [s_r]
        CALL puts
        MOV  r1, r11
        CALL print_u32
        CALL newline
        CMP  r8, #divs_end
        BLO  .pdiv

        RESTORE r7-r11
        RET

; ---- data ----
        .align 4
pairs16:                        ; a, b (16 bits each)
        .half 0, 0
        .half 0, 1
        .half 1, 1
        .half 1, 0xFFFF
        .half 0xFFFF, 0xFFFF
        .half 0x8000, 0xFFFF    ; -32768 * -1 and -32768 / -1 (wraps in 16 bits)
        .half 0x8000, 0x8000
        .half 0x8000, 1
        .half 0x7FFF, 0x7FFF
        .half 0x7FFF, 0x8000
        .half 0xFFFF, 0x8000
        .half 0xFFFF, 0x8001
        .half 0xFFFE, 0xFFFF
        .half 1234, 567
        .half -1234, 77
        .half 100, -7
        .half -100, -7
        .half -100, 7
        .half 12345, 10
        .half 0x8001, 0x7FFF
        .half 40000, 3
        .half 0xFFFF, 0         ; divide by zero
pairs16_end:

        .align 4
pairs32:                        ; a, b
        .word 0x0000FFFF, 0x00000001
        .word 0xFFFFFFFF, 0x00000001
        .word 0x80000000, 0xFFFFFFFF
        .word 0x7FFFFFFF, 0x80000000
        .word 0x12345678, 0x12345678
        .word 0x00010000, 0x0000FFFF
        .word 123456789, 987654321
        .word 0, 0xFFFFFFFF
        .word 0xFFFF0000, 0xFFFEFFFF
        .word 5, 0xFFFFFFFB
pairs32_end:

divs:                           ; dividend, divisor
        .word 0xFFFFFFFF, 0xFFFF
        .word 0xFFFFFFFF, 1
        .word 123456789, 10
        .word 1000000, 7
        .word 0x12345678, 0x1234
        .word 0, 5
        .word 0x80000000, 0x8000
        .word 0xFFFFFFFE, 0x8001
        .word 3000000000, 60000
        .word 1, 0xFFFF
divs_end:

s_head16:   .asciz "16-bit multiply and divide\n"
s_head32:   .asciz "32-bit add, subtract, compare\n"
s_headdiv:  .asciz "32/16 divide\n"
s_a:        .asciz "a="
s_b:        .asciz " b="
s_umul:     .asciz "\n  umul "
s_smul:     .asciz "  smul "
s_udiv:     .asciz "\n  udiv "
s_sdiv:     .asciz "  sdiv "
s_r:        .asciz " r "
s_div0:     .asciz "\n  divide by zero"
s_sum:      .asciz "  sum "
s_diff:     .asciz "  diff "
s_u:        .asciz "  u"
s_s:        .asciz " s"
s_slash:    .asciz " / "
s_eq:       .asciz " = "
s_cmpchars: .ascii "<=>"

        .include "lib/console.s"
        .include "lib/print.s"
