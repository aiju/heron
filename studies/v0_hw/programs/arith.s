; arith: multiply, divide and 32-bit add/subtract/compare on a table of
; operands, including the edge cases (0, 1, 7FFF, 8000, FFFF).

        .include "lib/start.s"

main:   PUSH r8
        PUSH r9

        ; ---- 16 x 16 multiply, 16 / 16 divide ----
        LI   r1, #s_head16
        CALL puts
        LI   r8, #pairs16
.p16:   LI   r1, #s_a
        CALL puts
        LD   r1, [r8]
        CALL print_hex16
        LI   r1, #s_b
        CALL puts
        LD   r1, [r8 + 2]
        CALL print_hex16
        LI   r1, #s_umul
        CALL puts
        LD   r1, [r8]
        LD   r2, [r8 + 2]
        CALL umul16
        CALL print_hex32
        LI   r1, #s_smul
        CALL puts
        LD   r1, [r8]
        LD   r2, [r8 + 2]
        CALL smul16
        CALL print_s32
        LD   r2, [r8 + 2]
        BNE  .divide
        LI   r1, #s_div0
        CALL puts
        BRA  .next16
.divide:
        LI   r1, #s_udiv
        CALL puts
        LD   r1, [r8]
        LD   r2, [r8 + 2]
        CALL udiv16
        MOV  r9, r2             ; remainder survives the print call in r9
        CALL print_u16
        LI   r1, #s_r
        CALL puts
        MOV  r1, r9
        CALL print_u16
        LI   r1, #s_sdiv
        CALL puts
        LD   r1, [r8]
        LD   r2, [r8 + 2]
        CALL sdiv16
        MOV  r9, r2
        CALL print_s16
        LI   r1, #s_r
        CALL puts
        MOV  r1, r9
        CALL print_s16
.next16:
        CALL newline
        ADDI r8, 4
        CMP  r8, #pairs16_end
        BLO  .p16

        ; ---- 32-bit add, subtract, compare ----
        LI   r1, #s_head32
        CALL puts
        LI   r8, #pairs32
.p32:   LD   r1, [r8]
        LD   r2, [r8 + 2]
        CALL print_hex32
        CALL space
        LD   r1, [r8 + 4]
        LD   r2, [r8 + 6]
        CALL print_hex32
        LI   r1, #s_sum
        CALL puts
        LD   r1, [r8]
        LD   r2, [r8 + 2]
        LD   r3, [r8 + 4]
        LD   r4, [r8 + 6]
        ADD  r1, r3
        ADC  r2, r4
        CALL print_hex32
        LI   r1, #s_diff
        CALL puts
        LD   r1, [r8]
        LD   r2, [r8 + 2]
        LD   r3, [r8 + 4]
        LD   r4, [r8 + 6]
        SUB  r1, r3
        SBC  r2, r4
        CALL print_hex32
        LI   r1, #s_u
        CALL puts
        LD   r1, [r8]
        LD   r2, [r8 + 2]
        LD   r3, [r8 + 4]
        LD   r4, [r8 + 6]
        BSR  ucmp32
        LDB  r1, [s_cmpchars + 1 + r1]
        CALL putc
        LI   r1, #s_s
        CALL puts
        LD   r1, [r8]
        LD   r2, [r8 + 2]
        LD   r3, [r8 + 4]
        LD   r4, [r8 + 6]
        BSR  scmp32
        LDB  r1, [s_cmpchars + 1 + r1]
        CALL putc
        CALL newline
        ADDI r8, 8
        CMP  r8, #pairs32_end
        BLO  .p32

        ; ---- 32 / 16 divide ----
        LI   r1, #s_headdiv
        CALL puts
        LI   r8, #divs
.pdiv:  LD   r1, [r8]
        LD   r2, [r8 + 2]
        CALL print_u32
        LI   r1, #s_slash
        CALL puts
        LD   r1, [r8 + 4]
        CALL print_u16
        LI   r1, #s_eq
        CALL puts
        LD   r1, [r8]
        LD   r2, [r8 + 2]
        LD   r3, [r8 + 4]
        CALL udiv32
        MOV  r9, r3
        CALL print_u32
        LI   r1, #s_r
        CALL puts
        MOV  r1, r9
        CALL print_u16
        CALL newline
        ADDI r8, 6
        CMP  r8, #divs_end
        BLO  .pdiv

        POP  r9
        POP  r8
        RET

; Compare r2:r1 with r4:r3 -> r1 = -1, 0 or 1. SBC doesn't combine Z across
; the halves, so a 32-bit compare is two compares and a branch.
ucmp32: CMP  r2, r4
        BNE  .decide            ; high halves differ: they decide (unsigned)
        CMP  r1, r3
        BEQ  .eq
.decide:
        BLO  .lt
        MVI  r1, 1
        RET
.lt:    MVI  r1, -1
        RET
.eq:    MVI  r1, 0
        RET

scmp32: CMP  r2, r4
        BEQ  .low
        BLT  .lt                ; high halves are signed...
        MVI  r1, 1
        RET
.low:   CMP  r1, r3             ; ...the low halves unsigned
        BEQ  .eq
        BLO  .lt
        MVI  r1, 1
        RET
.lt:    MVI  r1, -1
        RET
.eq:    MVI  r1, 0
        RET

; ---- data ----
pairs16:
        .word 0, 0
        .word 0, 1
        .word 1, 1
        .word 1, 0xFFFF
        .word 0xFFFF, 0xFFFF
        .word 0x8000, 0xFFFF    ; -32768 * -1 and -32768 / -1 (wraps)
        .word 0x8000, 0x8000
        .word 0x8000, 1
        .word 0x7FFF, 0x7FFF
        .word 0x7FFF, 0x8000
        .word 0xFFFF, 0x8000
        .word 0xFFFF, 0x8001    ; divisor > 8000: partial remainder reaches 17 bits
        .word 0xFFFE, 0xFFFF
        .word 1234, 567
        .word -1234, 77
        .word 100, -7
        .word -100, -7
        .word -100, 7
        .word 12345, 10
        .word 0x8001, 0x7FFF
        .word 40000, 3
        .word 0xFFFF, 0
pairs16_end:

pairs32:                        ; A low, A high, B low, B high
        .word 0xFFFF, 0x0000, 0x0001, 0x0000
        .word 0xFFFF, 0xFFFF, 0x0001, 0x0000
        .word 0x0000, 0x8000, 0xFFFF, 0xFFFF
        .word 0xFFFF, 0x7FFF, 0x0000, 0x8000
        .word 0x5678, 0x1234, 0x5678, 0x1234
        .word 0x0000, 0x0001, 0xFFFF, 0x0000
        .word 123456789 & 0xFFFF, 123456789 >> 16, 987654321 & 0xFFFF, 987654321 >> 16
        .word 0x0000, 0x0000, 0xFFFF, 0xFFFF
        .word 0x0000, 0xFFFF, 0xFFFF, 0xFFFE
        .word 0x0005, 0x0000, 0xFFFB, 0xFFFF
pairs32_end:

divs:                           ; dividend low, high, divisor
        .word 0xFFFF, 0xFFFF, 0xFFFF
        .word 0xFFFF, 0xFFFF, 1
        .word 123456789 & 0xFFFF, 123456789 >> 16, 10
        .word 1000000 & 0xFFFF, 1000000 >> 16, 7
        .word 0x5678, 0x1234, 0x1234
        .word 0, 0, 5
        .word 0x0000, 0x8000, 0x8000
        .word 0xFFFE, 0xFFFF, 0x8001
        .word 3000000000 & 0xFFFF, 3000000000 >> 16, 60000
        .word 1, 0, 0xFFFF
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
        .include "lib/mul.s"
        .include "lib/div.s"
