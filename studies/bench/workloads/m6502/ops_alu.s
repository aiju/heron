; m6502's arithmetic and logic: ORA, AND, EOR, ADC, SBC, CMP, CPX, CPY and
; BIT. Registers, conventions and the addressing modes are in emu.s and
; ops_load.s.
;
; ORA, AND, EOR and the compares take their operand straight from the
; 6502's memory (AND r6, byte [r13 + r2]). A compare is a subtraction:
; the host's carry after SUB is "no borrow", which is the 6502's C.
; ADC and SBC fetch the operand into r1 and branch to adc or sbc, which
; check D and do the arithmetic once for all eight modes.

        .section .text.m6502_alu

; ---- ADC and SBC -------------------------------------------------------------

; adc: A = A + r1 + C. In binary, C is bit 8 of the sum, and V bit 7 of
; (A ^ sum) & (M ^ sum): set when A and M have the same sign and the sum
; has the other.
adc:    MOVS r3, byte [flag_d]
        BNE  adc_decimal
add:    MOV  r11, r6
        ADD  r6, r1
        ADD  r6, r10            ; A + M + C, 0-511
        XOR  r11, r6            ; A ^ sum
        XOR  r1, r6             ; M ^ sum
        AND  r11, r1            ; bit 7: V
        MOV  r10, r6
        LSR  r10, #8            ; C
        ZXB  r6
        SXB  r9, r6
        MOV  r1, byte [r8]+
        INC  r4
        JMP  [r14 + r1*4]

; sbc: A = A - r1 - (1 - C), which in binary is A + (255 - M) + C: the
; same addition, C meaning "no borrow" as on the 6502.
sbc:    MOVS r3, byte [flag_d]
        BNE  sbc_decimal
        NOT  r1
        ZXB  r1
        BRA  add

; Decimal mode, as the NMOS 6502 does it, digit by digit (the formulation
; of VICE's 6510 core; cpu6502.py's reference uses Bruce Clark's, and its
; self-test checks that the two agree on every input). ADC's Z comes from
; the binary sum, N and V from the sum with only its low digit adjusted,
; and C from the adjusted result.
adc_decimal:
        MOV  r2, r6
        AND  r2, #15
        MOV  r3, r1
        AND  r3, #15
        ADD  r2, r3
        ADD  r2, r10            ; the low digits and C: 0-31
        CMP  r2, #10
        BLO  .lo
        ADD  r2, #6             ; adjust the low digit...
        CMP  r2, #16
        BLO  .lo
        AND  r2, #15            ; ...and carry into the high one
        ADD  r2, #16
.lo:    MOV  r3, r6
        AND  r3, #0xF0
        ADD  r2, r3
        MOV  r3, r1
        AND  r3, #0xF0
        ADD  r2, r3             ; the high digits added: the sum so far
        MOV  r11, r6
        XOR  r11, r2            ; V: A's sign differs from the sum's...
        MOV  r3, r6
        XOR  r3, r1
        NOT  r3
        AND  r11, r3            ; ...and A and M have the same sign
        MOV  r9, r2
        LSL  r9, #24            ; N: bit 7 of the sum so far
        MOV  r3, r6
        ADD  r3, r1
        ADD  r3, r10
        ZXB  r3
        OR   r9, r3             ; Z: the binary sum's low byte
        MOV  r3, r2
        AND  r3, #0x1F0
        CMP  r3, #0x90
        BLS  .hi
        ADD  r2, #0x60          ; adjust the high digit
.hi:    MOV  r3, r2
        AND  r3, #0xFF0
        CMP  r3, #0xF0
        SETHI r10               ; C
        ZXB  r6, r2
        MOV  r1, byte [r8]+
        INC  r4
        JMP  [r14 + r1*4]

; SBC's flags are all the binary subtraction's; only A is decimal.
sbc_decimal:
        PUSH r1                 ; M, for the flags
        MOV  r2, r6
        AND  r2, #15
        MOV  r3, r1
        AND  r3, #15
        SUB  r2, r3
        ADD  r2, r10
        SUB  r2, #1             ; the low digit: -16 to 15
        MOV  r3, r6
        AND  r3, #0xF0
        AND  r1, #0xF0
        SUB  r3, r1             ; the high digit, -$F0 to $F0
        MOV  r1, r2
        AND  r1, #16
        BEQ  .lo                ; the low digit borrowed:
        SUB  r2, #6             ; adjust it, and borrow from the high one
        SUB  r3, #16
.lo:    MOV  r1, r3
        AND  r1, #0x100
        BEQ  .hi                ; the high digit borrowed: adjust it
        SUB  r3, #0x60
.hi:    AND  r2, #15
        OR   r2, r3
        ZXB  r2                 ; the decimal difference
        POP  r1
        NOT  r1                 ; the flags, as sbc and add have them
        ZXB  r1
        MOV  r3, r6
        ADD  r3, r1
        ADD  r3, r10
        MOV  r11, r6
        XOR  r11, r3
        XOR  r1, r3
        AND  r11, r1            ; V
        SXB  r9, r3             ; N and Z
        MOV  r10, r3
        LSR  r10, #8            ; C
        MOV  r6, r2
        MOV  r1, byte [r8]+
        INC  r4
        JMP  [r14 + r1*4]

; ---- BIT ---------------------------------------------------------------------

; N and V are bits 7 and 6 of the operand, Z says whether A & M is zero:
; r9 holds the operand's bit 7 in bit 31 and A & M in its low byte.
op_bit_zp:
        ADD  r12, #3
        MOV  r2, byte [r8]+
        MOV  r1, byte [r13 + r2]
        BRA  bit

op_bit_abs:
        ADD  r12, #4
        MOV  r2, byte [r8 + 1]
        LSL  r2, #8
        OR   r2, byte [r8]
        ADD  r8, #2
        MOV  r1, byte [r13 + r2]
bit:    MOV  r11, r1
        LSL  r11, #1            ; bit 6 into V's bit 7
        MOV  r9, r1
        LSL  r9, #24            ; bit 7 into N's bit 31
        AND  r1, r6
        OR   r9, r1             ; and A & M in the low byte, for Z
        MOV  r1, byte [r8]+
        INC  r4
        JMP  [r14 + r1*4]

; ---- ORA, AND and EOR --------------------------------------------------------

op_ora_imm:
        ADD  r12, #2
        OR   r6, byte [r8]+     ; A |= the operand, straight from memory
        SXB  r9, r6             ; N and Z
        MOV  r1, byte [r8]+
        INC  r4
        JMP  [r14 + r1*4]

op_ora_zp:
        ADD  r12, #3
        MOV  r2, byte [r8]+
        OR   r6, byte [r13 + r2]
        SXB  r9, r6
        MOV  r1, byte [r8]+
        INC  r4
        JMP  [r14 + r1*4]

op_ora_zpx:
        ADD  r12, #4
        MOV  r2, byte [r8]+
        ADD  r2, r0
        ZXB  r2
        OR   r6, byte [r13 + r2]
        SXB  r9, r6
        MOV  r1, byte [r8]+
        INC  r4
        JMP  [r14 + r1*4]

op_ora_abs:
        ADD  r12, #4
        MOV  r2, byte [r8 + 1]
        LSL  r2, #8
        OR   r2, byte [r8]
        ADD  r8, #2
        OR   r6, byte [r13 + r2]
        SXB  r9, r6
        MOV  r1, byte [r8]+
        INC  r4
        JMP  [r14 + r1*4]

op_ora_abx:
        ADD  r12, #4
        MOV  r2, byte [r8 + 1]
        LSL  r2, #8
        MOV  r3, byte [r8]
        ADD  r8, #2
        ADD  r3, r0
        ADD  r2, r3
        ZXH  r2
        LSR  r3, #8
        ADD  r12, r3
        OR   r6, byte [r13 + r2]
        SXB  r9, r6
        MOV  r1, byte [r8]+
        INC  r4
        JMP  [r14 + r1*4]

op_ora_aby:
        ADD  r12, #4
        MOV  r2, byte [r8 + 1]
        LSL  r2, #8
        MOV  r3, byte [r8]
        ADD  r8, #2
        ADD  r3, r5
        ADD  r2, r3
        ZXH  r2
        LSR  r3, #8
        ADD  r12, r3
        OR   r6, byte [r13 + r2]
        SXB  r9, r6
        MOV  r1, byte [r8]+
        INC  r4
        JMP  [r14 + r1*4]

op_ora_izx:
        ADD  r12, #6
        MOV  r3, byte [r8]+
        ADD  r3, r0
        ZXB  r3
        MOV  r2, byte [r13 + r3]
        INC  r3
        ZXB  r3
        MOV  r3, byte [r13 + r3]
        LSL  r3, #8
        OR   r2, r3
        OR   r6, byte [r13 + r2]
        SXB  r9, r6
        MOV  r1, byte [r8]+
        INC  r4
        JMP  [r14 + r1*4]

op_ora_izy:
        ADD  r12, #5
        MOV  r3, byte [r8]+
        MOV  r2, byte [r13 + r3]
        INC  r3
        ZXB  r3
        MOV  r3, byte [r13 + r3]
        LSL  r3, #8
        ADD  r2, r5
        ADD  r3, r2
        LSR  r2, #8
        ADD  r12, r2
        ZXH  r2, r3
        OR   r6, byte [r13 + r2]
        SXB  r9, r6
        MOV  r1, byte [r8]+
        INC  r4
        JMP  [r14 + r1*4]

op_and_imm:
        ADD  r12, #2
        AND  r6, byte [r8]+
        SXB  r9, r6
        MOV  r1, byte [r8]+
        INC  r4
        JMP  [r14 + r1*4]

op_and_zp:
        ADD  r12, #3
        MOV  r2, byte [r8]+
        AND  r6, byte [r13 + r2]
        SXB  r9, r6
        MOV  r1, byte [r8]+
        INC  r4
        JMP  [r14 + r1*4]

op_and_zpx:
        ADD  r12, #4
        MOV  r2, byte [r8]+
        ADD  r2, r0
        ZXB  r2
        AND  r6, byte [r13 + r2]
        SXB  r9, r6
        MOV  r1, byte [r8]+
        INC  r4
        JMP  [r14 + r1*4]

op_and_abs:
        ADD  r12, #4
        MOV  r2, byte [r8 + 1]
        LSL  r2, #8
        OR   r2, byte [r8]
        ADD  r8, #2
        AND  r6, byte [r13 + r2]
        SXB  r9, r6
        MOV  r1, byte [r8]+
        INC  r4
        JMP  [r14 + r1*4]

op_and_abx:
        ADD  r12, #4
        MOV  r2, byte [r8 + 1]
        LSL  r2, #8
        MOV  r3, byte [r8]
        ADD  r8, #2
        ADD  r3, r0
        ADD  r2, r3
        ZXH  r2
        LSR  r3, #8
        ADD  r12, r3
        AND  r6, byte [r13 + r2]
        SXB  r9, r6
        MOV  r1, byte [r8]+
        INC  r4
        JMP  [r14 + r1*4]

op_and_aby:
        ADD  r12, #4
        MOV  r2, byte [r8 + 1]
        LSL  r2, #8
        MOV  r3, byte [r8]
        ADD  r8, #2
        ADD  r3, r5
        ADD  r2, r3
        ZXH  r2
        LSR  r3, #8
        ADD  r12, r3
        AND  r6, byte [r13 + r2]
        SXB  r9, r6
        MOV  r1, byte [r8]+
        INC  r4
        JMP  [r14 + r1*4]

op_and_izx:
        ADD  r12, #6
        MOV  r3, byte [r8]+
        ADD  r3, r0
        ZXB  r3
        MOV  r2, byte [r13 + r3]
        INC  r3
        ZXB  r3
        MOV  r3, byte [r13 + r3]
        LSL  r3, #8
        OR   r2, r3
        AND  r6, byte [r13 + r2]
        SXB  r9, r6
        MOV  r1, byte [r8]+
        INC  r4
        JMP  [r14 + r1*4]

op_and_izy:
        ADD  r12, #5
        MOV  r3, byte [r8]+
        MOV  r2, byte [r13 + r3]
        INC  r3
        ZXB  r3
        MOV  r3, byte [r13 + r3]
        LSL  r3, #8
        ADD  r2, r5
        ADD  r3, r2
        LSR  r2, #8
        ADD  r12, r2
        ZXH  r2, r3
        AND  r6, byte [r13 + r2]
        SXB  r9, r6
        MOV  r1, byte [r8]+
        INC  r4
        JMP  [r14 + r1*4]

op_eor_imm:
        ADD  r12, #2
        XOR  r6, byte [r8]+
        SXB  r9, r6
        MOV  r1, byte [r8]+
        INC  r4
        JMP  [r14 + r1*4]

op_eor_zp:
        ADD  r12, #3
        MOV  r2, byte [r8]+
        XOR  r6, byte [r13 + r2]
        SXB  r9, r6
        MOV  r1, byte [r8]+
        INC  r4
        JMP  [r14 + r1*4]

op_eor_zpx:
        ADD  r12, #4
        MOV  r2, byte [r8]+
        ADD  r2, r0
        ZXB  r2
        XOR  r6, byte [r13 + r2]
        SXB  r9, r6
        MOV  r1, byte [r8]+
        INC  r4
        JMP  [r14 + r1*4]

op_eor_abs:
        ADD  r12, #4
        MOV  r2, byte [r8 + 1]
        LSL  r2, #8
        OR   r2, byte [r8]
        ADD  r8, #2
        XOR  r6, byte [r13 + r2]
        SXB  r9, r6
        MOV  r1, byte [r8]+
        INC  r4
        JMP  [r14 + r1*4]

op_eor_abx:
        ADD  r12, #4
        MOV  r2, byte [r8 + 1]
        LSL  r2, #8
        MOV  r3, byte [r8]
        ADD  r8, #2
        ADD  r3, r0
        ADD  r2, r3
        ZXH  r2
        LSR  r3, #8
        ADD  r12, r3
        XOR  r6, byte [r13 + r2]
        SXB  r9, r6
        MOV  r1, byte [r8]+
        INC  r4
        JMP  [r14 + r1*4]

op_eor_aby:
        ADD  r12, #4
        MOV  r2, byte [r8 + 1]
        LSL  r2, #8
        MOV  r3, byte [r8]
        ADD  r8, #2
        ADD  r3, r5
        ADD  r2, r3
        ZXH  r2
        LSR  r3, #8
        ADD  r12, r3
        XOR  r6, byte [r13 + r2]
        SXB  r9, r6
        MOV  r1, byte [r8]+
        INC  r4
        JMP  [r14 + r1*4]

op_eor_izx:
        ADD  r12, #6
        MOV  r3, byte [r8]+
        ADD  r3, r0
        ZXB  r3
        MOV  r2, byte [r13 + r3]
        INC  r3
        ZXB  r3
        MOV  r3, byte [r13 + r3]
        LSL  r3, #8
        OR   r2, r3
        XOR  r6, byte [r13 + r2]
        SXB  r9, r6
        MOV  r1, byte [r8]+
        INC  r4
        JMP  [r14 + r1*4]

op_eor_izy:
        ADD  r12, #5
        MOV  r3, byte [r8]+
        MOV  r2, byte [r13 + r3]
        INC  r3
        ZXB  r3
        MOV  r3, byte [r13 + r3]
        LSL  r3, #8
        ADD  r2, r5
        ADD  r3, r2
        LSR  r2, #8
        ADD  r12, r2
        ZXH  r2, r3
        XOR  r6, byte [r13 + r2]
        SXB  r9, r6
        MOV  r1, byte [r8]+
        INC  r4
        JMP  [r14 + r1*4]

; ---- ADC and SBC's addressing modes ------------------------------------------

op_adc_imm:
        ADD  r12, #2
        MOV  r1, byte [r8]+     ; the operand, for adc
        BRA  adc

op_adc_zp:
        ADD  r12, #3
        MOV  r2, byte [r8]+
        MOV  r1, byte [r13 + r2]
        BRA  adc

op_adc_zpx:
        ADD  r12, #4
        MOV  r2, byte [r8]+
        ADD  r2, r0
        ZXB  r2
        MOV  r1, byte [r13 + r2]
        BRA  adc

op_adc_abs:
        ADD  r12, #4
        MOV  r2, byte [r8 + 1]
        LSL  r2, #8
        OR   r2, byte [r8]
        ADD  r8, #2
        MOV  r1, byte [r13 + r2]
        BRA  adc

op_adc_abx:
        ADD  r12, #4
        MOV  r2, byte [r8 + 1]
        LSL  r2, #8
        MOV  r3, byte [r8]
        ADD  r8, #2
        ADD  r3, r0
        ADD  r2, r3
        ZXH  r2
        LSR  r3, #8
        ADD  r12, r3
        MOV  r1, byte [r13 + r2]
        BRA  adc

op_adc_aby:
        ADD  r12, #4
        MOV  r2, byte [r8 + 1]
        LSL  r2, #8
        MOV  r3, byte [r8]
        ADD  r8, #2
        ADD  r3, r5
        ADD  r2, r3
        ZXH  r2
        LSR  r3, #8
        ADD  r12, r3
        MOV  r1, byte [r13 + r2]
        BRA  adc

op_adc_izx:
        ADD  r12, #6
        MOV  r3, byte [r8]+
        ADD  r3, r0
        ZXB  r3
        MOV  r2, byte [r13 + r3]
        INC  r3
        ZXB  r3
        MOV  r3, byte [r13 + r3]
        LSL  r3, #8
        OR   r2, r3
        MOV  r1, byte [r13 + r2]
        BRA  adc

op_adc_izy:
        ADD  r12, #5
        MOV  r3, byte [r8]+
        MOV  r2, byte [r13 + r3]
        INC  r3
        ZXB  r3
        MOV  r3, byte [r13 + r3]
        LSL  r3, #8
        ADD  r2, r5
        ADD  r3, r2
        LSR  r2, #8
        ADD  r12, r2
        ZXH  r2, r3
        MOV  r1, byte [r13 + r2]
        BRA  adc

op_sbc_imm:
        ADD  r12, #2
        MOV  r1, byte [r8]+
        BRA  sbc

op_sbc_zp:
        ADD  r12, #3
        MOV  r2, byte [r8]+
        MOV  r1, byte [r13 + r2]
        BRA  sbc

op_sbc_zpx:
        ADD  r12, #4
        MOV  r2, byte [r8]+
        ADD  r2, r0
        ZXB  r2
        MOV  r1, byte [r13 + r2]
        BRA  sbc

op_sbc_abs:
        ADD  r12, #4
        MOV  r2, byte [r8 + 1]
        LSL  r2, #8
        OR   r2, byte [r8]
        ADD  r8, #2
        MOV  r1, byte [r13 + r2]
        BRA  sbc

op_sbc_abx:
        ADD  r12, #4
        MOV  r2, byte [r8 + 1]
        LSL  r2, #8
        MOV  r3, byte [r8]
        ADD  r8, #2
        ADD  r3, r0
        ADD  r2, r3
        ZXH  r2
        LSR  r3, #8
        ADD  r12, r3
        MOV  r1, byte [r13 + r2]
        BRA  sbc

op_sbc_aby:
        ADD  r12, #4
        MOV  r2, byte [r8 + 1]
        LSL  r2, #8
        MOV  r3, byte [r8]
        ADD  r8, #2
        ADD  r3, r5
        ADD  r2, r3
        ZXH  r2
        LSR  r3, #8
        ADD  r12, r3
        MOV  r1, byte [r13 + r2]
        BRA  sbc

op_sbc_izx:
        ADD  r12, #6
        MOV  r3, byte [r8]+
        ADD  r3, r0
        ZXB  r3
        MOV  r2, byte [r13 + r3]
        INC  r3
        ZXB  r3
        MOV  r3, byte [r13 + r3]
        LSL  r3, #8
        OR   r2, r3
        MOV  r1, byte [r13 + r2]
        BRA  sbc

op_sbc_izy:
        ADD  r12, #5
        MOV  r3, byte [r8]+
        MOV  r2, byte [r13 + r3]
        INC  r3
        ZXB  r3
        MOV  r3, byte [r13 + r3]
        LSL  r3, #8
        ADD  r2, r5
        ADD  r3, r2
        LSR  r2, #8
        ADD  r12, r2
        ZXH  r2, r3
        MOV  r1, byte [r13 + r2]
        BRA  sbc

; ---- CMP, CPX and CPY --------------------------------------------------------

op_cmp_imm:
        ADD  r12, #2
        MOV  r9, r6
        SUB  r9, byte [r8]+     ; A - M...
        SETHS r10               ; ...C if there was no borrow
        SXB  r9                 ; N and Z from the difference's low byte
        MOV  r1, byte [r8]+
        INC  r4
        JMP  [r14 + r1*4]

op_cmp_zp:
        ADD  r12, #3
        MOV  r2, byte [r8]+
        MOV  r9, r6
        SUB  r9, byte [r13 + r2]
        SETHS r10
        SXB  r9
        MOV  r1, byte [r8]+
        INC  r4
        JMP  [r14 + r1*4]

op_cmp_zpx:
        ADD  r12, #4
        MOV  r2, byte [r8]+
        ADD  r2, r0
        ZXB  r2
        MOV  r9, r6
        SUB  r9, byte [r13 + r2]
        SETHS r10
        SXB  r9
        MOV  r1, byte [r8]+
        INC  r4
        JMP  [r14 + r1*4]

op_cmp_abs:
        ADD  r12, #4
        MOV  r2, byte [r8 + 1]
        LSL  r2, #8
        OR   r2, byte [r8]
        ADD  r8, #2
        MOV  r9, r6
        SUB  r9, byte [r13 + r2]
        SETHS r10
        SXB  r9
        MOV  r1, byte [r8]+
        INC  r4
        JMP  [r14 + r1*4]

op_cmp_abx:
        ADD  r12, #4
        MOV  r2, byte [r8 + 1]
        LSL  r2, #8
        MOV  r3, byte [r8]
        ADD  r8, #2
        ADD  r3, r0
        ADD  r2, r3
        ZXH  r2
        LSR  r3, #8
        ADD  r12, r3
        MOV  r9, r6
        SUB  r9, byte [r13 + r2]
        SETHS r10
        SXB  r9
        MOV  r1, byte [r8]+
        INC  r4
        JMP  [r14 + r1*4]

op_cmp_aby:
        ADD  r12, #4
        MOV  r2, byte [r8 + 1]
        LSL  r2, #8
        MOV  r3, byte [r8]
        ADD  r8, #2
        ADD  r3, r5
        ADD  r2, r3
        ZXH  r2
        LSR  r3, #8
        ADD  r12, r3
        MOV  r9, r6
        SUB  r9, byte [r13 + r2]
        SETHS r10
        SXB  r9
        MOV  r1, byte [r8]+
        INC  r4
        JMP  [r14 + r1*4]

op_cmp_izx:
        ADD  r12, #6
        MOV  r3, byte [r8]+
        ADD  r3, r0
        ZXB  r3
        MOV  r2, byte [r13 + r3]
        INC  r3
        ZXB  r3
        MOV  r3, byte [r13 + r3]
        LSL  r3, #8
        OR   r2, r3
        MOV  r9, r6
        SUB  r9, byte [r13 + r2]
        SETHS r10
        SXB  r9
        MOV  r1, byte [r8]+
        INC  r4
        JMP  [r14 + r1*4]

op_cmp_izy:
        ADD  r12, #5
        MOV  r3, byte [r8]+
        MOV  r2, byte [r13 + r3]
        INC  r3
        ZXB  r3
        MOV  r3, byte [r13 + r3]
        LSL  r3, #8
        ADD  r2, r5
        ADD  r3, r2
        LSR  r2, #8
        ADD  r12, r2
        ZXH  r2, r3
        MOV  r9, r6
        SUB  r9, byte [r13 + r2]
        SETHS r10
        SXB  r9
        MOV  r1, byte [r8]+
        INC  r4
        JMP  [r14 + r1*4]

op_cpx_imm:
        ADD  r12, #2
        MOV  r9, r0
        SUB  r9, byte [r8]+
        SETHS r10
        SXB  r9
        MOV  r1, byte [r8]+
        INC  r4
        JMP  [r14 + r1*4]

op_cpx_zp:
        ADD  r12, #3
        MOV  r2, byte [r8]+
        MOV  r9, r0
        SUB  r9, byte [r13 + r2]
        SETHS r10
        SXB  r9
        MOV  r1, byte [r8]+
        INC  r4
        JMP  [r14 + r1*4]

op_cpx_abs:
        ADD  r12, #4
        MOV  r2, byte [r8 + 1]
        LSL  r2, #8
        OR   r2, byte [r8]
        ADD  r8, #2
        MOV  r9, r0
        SUB  r9, byte [r13 + r2]
        SETHS r10
        SXB  r9
        MOV  r1, byte [r8]+
        INC  r4
        JMP  [r14 + r1*4]

op_cpy_imm:
        ADD  r12, #2
        MOV  r9, r5
        SUB  r9, byte [r8]+
        SETHS r10
        SXB  r9
        MOV  r1, byte [r8]+
        INC  r4
        JMP  [r14 + r1*4]

op_cpy_zp:
        ADD  r12, #3
        MOV  r2, byte [r8]+
        MOV  r9, r5
        SUB  r9, byte [r13 + r2]
        SETHS r10
        SXB  r9
        MOV  r1, byte [r8]+
        INC  r4
        JMP  [r14 + r1*4]

op_cpy_abs:
        ADD  r12, #4
        MOV  r2, byte [r8 + 1]
        LSL  r2, #8
        OR   r2, byte [r8]
        ADD  r8, #2
        MOV  r9, r5
        SUB  r9, byte [r13 + r2]
        SETHS r10
        SXB  r9
        MOV  r1, byte [r8]+
        INC  r4
        JMP  [r14 + r1*4]
