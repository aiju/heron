; isanotes: where this CPU follows RFC 0028 and draft 2's instruction-level
; simulator doesn't (yet): MOVS of a byte or half takes N from the
; operand's own bit 7 or 15 (RFC 0028, 5.1, decided 2026-10-15); the
; simulator takes it from bit 31 of the zero-extended value. INC and DEC on
; a byte or half, which both take from the operand's top bit, for
; comparison.

        .org 0x00
        JMP  start
        .org 0x40

start:  MOV  sp, #0x100000
        LEA  r1, [s_movsb]
        BSR  puts
        MOVS r2, byte [data]            ; 0x80: N
        MFSR r2, flags
        AND  r2, #0x0C
        MOVS r3, byte [data + 1]        ; 0x7F: not N
        MFSR r3, flags
        AND  r3, #0x0C
        MOVS r4, half [data + 2]        ; 0x8000: N
        MFSR r4, flags
        AND  r4, #0x0C
        MOVS r5, byte [data + 4]        ; 0: Z
        MFSR r5, flags
        AND  r5, #0x0C
        LSL  r2, #12
        LSL  r3, #8
        LSL  r4, #4
        OR   r2, r3
        OR   r2, r4
        OR   r2, r5
        MOV  r1, #0x8084
        BSR  expect
        LEA  r1, [s_incb]
        BSR  puts
        INC  byte [data + 1]            ; 0x7F -> 0x80: N
        MFSR r2, flags
        AND  r2, #0x0C
        DEC  half [data + 6]            ; 0x0001 -> 0: Z
        MFSR r3, flags
        AND  r3, #0x0C
        LSL  r2, #4
        OR   r2, r3
        MOV  r1, #0x84
        BSR  expect
        HALT

expect: CMP  r1, r2
        BNE  .bad
        LEA  r1, [s_ok]
        BRA  puts
.bad:   LEA  r1, [s_bad]
        BRA  puts

        .align 4
data:   .byte 0x80, 0x7F, 0x00, 0x80, 0x00, 0x00, 0x01, 0x00
s_movsb: .asciz "MOVS byte and half: N from bits 7 and 15: "
s_incb:  .asciz "INC and DEC on a byte and half: "
s_ok:    .asciz "ok\n"
s_bad:   .asciz "differs\n"
        .align 2

        .include "../../v2_isa/programs/lib/console.s"
