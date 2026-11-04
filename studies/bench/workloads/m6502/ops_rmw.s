; m6502's shifts, rotates, increments and decrements: ASL, LSR, ROL, ROR,
; INC and DEC on memory and (the shifts) on A, and INX, INY, DEX, DEY.
; Registers, conventions and the addressing modes are in emu.s and
; ops_load.s.
;
; A read-modify-write works on r1 and stores its low byte. C comes out of
; the shifts as the 6502 has it: bit 8 after a left shift, the host's
; carry (SETCS) after a right one. Only abs and abs,X can reach the I/O
; page or ROM, where io_write (emu.s) takes the value from r1; a real
; 6502 writes the old value first and then the new one, but no device
; here minds.

RAM_TOP = 0xC000

        .section .text.m6502_rmw

; ---- on A --------------------------------------------------------------------

op_asl_a:
        ADD  r12, #2
        LSL  r6, #1
        MOV  r10, r6
        LSR  r10, #8
        ZXB  r6
        SXB  r9, r6
        MOV  r1, byte [r8]+
        INC  r4
        JMP  [r14 + r1*4]

op_lsr_a:
        ADD  r12, #2
        LSR  r6, #1
        SETCS r10
        SXB  r9, r6
        MOV  r1, byte [r8]+
        INC  r4
        JMP  [r14 + r1*4]

op_rol_a:
        ADD  r12, #2
        LSL  r6, #1
        OR   r6, r10
        MOV  r10, r6
        LSR  r10, #8
        ZXB  r6
        SXB  r9, r6
        MOV  r1, byte [r8]+
        INC  r4
        JMP  [r14 + r1*4]

op_ror_a:
        ADD  r12, #2
        LSL  r10, #8
        OR   r6, r10            ; C above bit 7...
        LSR  r6, #1             ; ...shifted in, and bit 0 out
        SETCS r10
        SXB  r9, r6
        MOV  r1, byte [r8]+
        INC  r4
        JMP  [r14 + r1*4]

; ---- on X and Y --------------------------------------------------------------

op_inx: ADD  r12, #2
        INC  r0
        ZXB  r0
        SXB  r9, r0
        MOV  r1, byte [r8]+
        INC  r4
        JMP  [r14 + r1*4]

op_dex: ADD  r12, #2
        DEC  r0
        ZXB  r0
        SXB  r9, r0
        MOV  r1, byte [r8]+
        INC  r4
        JMP  [r14 + r1*4]

op_iny: ADD  r12, #2
        INC  r5
        ZXB  r5
        SXB  r9, r5
        MOV  r1, byte [r8]+
        INC  r4
        JMP  [r14 + r1*4]

op_dey: ADD  r12, #2
        DEC  r5
        ZXB  r5
        SXB  r9, r5
        MOV  r1, byte [r8]+
        INC  r4
        JMP  [r14 + r1*4]

; ---- ASL on memory -----------------------------------------------------------

op_asl_zp:
        ADD  r12, #5
        MOV  r2, byte [r8]+
        MOV  r1, byte [r13 + r2]
        LSL  r1, #1
        MOV  r10, r1
        LSR  r10, #8            ; C: bit 8
        SXB  r9, r1
        MOV  byte [r13 + r2], r1
        MOV  r1, byte [r8]+
        INC  r4
        JMP  [r14 + r1*4]

op_asl_zpx:
        ADD  r12, #6
        MOV  r2, byte [r8]+
        ADD  r2, r0
        ZXB  r2
        MOV  r1, byte [r13 + r2]
        LSL  r1, #1
        MOV  r10, r1
        LSR  r10, #8
        SXB  r9, r1
        MOV  byte [r13 + r2], r1
        MOV  r1, byte [r8]+
        INC  r4
        JMP  [r14 + r1*4]

op_asl_abs:
        ADD  r12, #6
        MOV  r2, byte [r8 + 1]
        LSL  r2, #8
        OR   r2, byte [r8]
        ADD  r8, #2
        MOV  r1, byte [r13 + r2]
        LSL  r1, #1
        MOV  r10, r1
        LSR  r10, #8
        SXB  r9, r1
        CMP  r2, #RAM_TOP       ; I/O or ROM?
        BHS  io_write
        MOV  byte [r13 + r2], r1
        MOV  r1, byte [r8]+
        INC  r4
        JMP  [r14 + r1*4]

op_asl_abx:
        ADD  r12, #7
        MOV  r2, byte [r8 + 1]
        LSL  r2, #8
        OR   r2, byte [r8]
        ADD  r8, #2
        ADD  r2, r0
        ZXH  r2
        MOV  r1, byte [r13 + r2]
        LSL  r1, #1
        MOV  r10, r1
        LSR  r10, #8
        SXB  r9, r1
        CMP  r2, #RAM_TOP
        BHS  io_write
        MOV  byte [r13 + r2], r1
        MOV  r1, byte [r8]+
        INC  r4
        JMP  [r14 + r1*4]

; ---- LSR on memory -----------------------------------------------------------

op_lsr_zp:
        ADD  r12, #5
        MOV  r2, byte [r8]+
        MOV  r1, byte [r13 + r2]
        LSR  r1, #1
        SETCS r10
        SXB  r9, r1
        MOV  byte [r13 + r2], r1
        MOV  r1, byte [r8]+
        INC  r4
        JMP  [r14 + r1*4]

op_lsr_zpx:
        ADD  r12, #6
        MOV  r2, byte [r8]+
        ADD  r2, r0
        ZXB  r2
        MOV  r1, byte [r13 + r2]
        LSR  r1, #1
        SETCS r10
        SXB  r9, r1
        MOV  byte [r13 + r2], r1
        MOV  r1, byte [r8]+
        INC  r4
        JMP  [r14 + r1*4]

op_lsr_abs:
        ADD  r12, #6
        MOV  r2, byte [r8 + 1]
        LSL  r2, #8
        OR   r2, byte [r8]
        ADD  r8, #2
        MOV  r1, byte [r13 + r2]
        LSR  r1, #1
        SETCS r10
        SXB  r9, r1
        CMP  r2, #RAM_TOP
        BHS  io_write
        MOV  byte [r13 + r2], r1
        MOV  r1, byte [r8]+
        INC  r4
        JMP  [r14 + r1*4]

op_lsr_abx:
        ADD  r12, #7
        MOV  r2, byte [r8 + 1]
        LSL  r2, #8
        OR   r2, byte [r8]
        ADD  r8, #2
        ADD  r2, r0
        ZXH  r2
        MOV  r1, byte [r13 + r2]
        LSR  r1, #1
        SETCS r10
        SXB  r9, r1
        CMP  r2, #RAM_TOP
        BHS  io_write
        MOV  byte [r13 + r2], r1
        MOV  r1, byte [r8]+
        INC  r4
        JMP  [r14 + r1*4]

; ---- ROL on memory -----------------------------------------------------------

op_rol_zp:
        ADD  r12, #5
        MOV  r2, byte [r8]+
        MOV  r1, byte [r13 + r2]
        LSL  r1, #1
        OR   r1, r10
        MOV  r10, r1
        LSR  r10, #8
        SXB  r9, r1
        MOV  byte [r13 + r2], r1
        MOV  r1, byte [r8]+
        INC  r4
        JMP  [r14 + r1*4]

op_rol_zpx:
        ADD  r12, #6
        MOV  r2, byte [r8]+
        ADD  r2, r0
        ZXB  r2
        MOV  r1, byte [r13 + r2]
        LSL  r1, #1
        OR   r1, r10
        MOV  r10, r1
        LSR  r10, #8
        SXB  r9, r1
        MOV  byte [r13 + r2], r1
        MOV  r1, byte [r8]+
        INC  r4
        JMP  [r14 + r1*4]

op_rol_abs:
        ADD  r12, #6
        MOV  r2, byte [r8 + 1]
        LSL  r2, #8
        OR   r2, byte [r8]
        ADD  r8, #2
        MOV  r1, byte [r13 + r2]
        LSL  r1, #1
        OR   r1, r10
        MOV  r10, r1
        LSR  r10, #8
        SXB  r9, r1
        CMP  r2, #RAM_TOP
        BHS  io_write
        MOV  byte [r13 + r2], r1
        MOV  r1, byte [r8]+
        INC  r4
        JMP  [r14 + r1*4]

op_rol_abx:
        ADD  r12, #7
        MOV  r2, byte [r8 + 1]
        LSL  r2, #8
        OR   r2, byte [r8]
        ADD  r8, #2
        ADD  r2, r0
        ZXH  r2
        MOV  r1, byte [r13 + r2]
        LSL  r1, #1
        OR   r1, r10
        MOV  r10, r1
        LSR  r10, #8
        SXB  r9, r1
        CMP  r2, #RAM_TOP
        BHS  io_write
        MOV  byte [r13 + r2], r1
        MOV  r1, byte [r8]+
        INC  r4
        JMP  [r14 + r1*4]

; ---- ROR on memory -----------------------------------------------------------

op_ror_zp:
        ADD  r12, #5
        MOV  r2, byte [r8]+
        MOV  r1, byte [r13 + r2]
        LSL  r10, #8
        OR   r1, r10
        LSR  r1, #1
        SETCS r10
        SXB  r9, r1
        MOV  byte [r13 + r2], r1
        MOV  r1, byte [r8]+
        INC  r4
        JMP  [r14 + r1*4]

op_ror_zpx:
        ADD  r12, #6
        MOV  r2, byte [r8]+
        ADD  r2, r0
        ZXB  r2
        MOV  r1, byte [r13 + r2]
        LSL  r10, #8
        OR   r1, r10
        LSR  r1, #1
        SETCS r10
        SXB  r9, r1
        MOV  byte [r13 + r2], r1
        MOV  r1, byte [r8]+
        INC  r4
        JMP  [r14 + r1*4]

op_ror_abs:
        ADD  r12, #6
        MOV  r2, byte [r8 + 1]
        LSL  r2, #8
        OR   r2, byte [r8]
        ADD  r8, #2
        MOV  r1, byte [r13 + r2]
        LSL  r10, #8
        OR   r1, r10
        LSR  r1, #1
        SETCS r10
        SXB  r9, r1
        CMP  r2, #RAM_TOP
        BHS  io_write
        MOV  byte [r13 + r2], r1
        MOV  r1, byte [r8]+
        INC  r4
        JMP  [r14 + r1*4]

op_ror_abx:
        ADD  r12, #7
        MOV  r2, byte [r8 + 1]
        LSL  r2, #8
        OR   r2, byte [r8]
        ADD  r8, #2
        ADD  r2, r0
        ZXH  r2
        MOV  r1, byte [r13 + r2]
        LSL  r10, #8
        OR   r1, r10
        LSR  r1, #1
        SETCS r10
        SXB  r9, r1
        CMP  r2, #RAM_TOP
        BHS  io_write
        MOV  byte [r13 + r2], r1
        MOV  r1, byte [r8]+
        INC  r4
        JMP  [r14 + r1*4]

; ---- INC on memory -----------------------------------------------------------

op_inc_zp:
        ADD  r12, #5
        MOV  r2, byte [r8]+
        MOV  r1, byte [r13 + r2]
        INC  r1
        SXB  r9, r1
        MOV  byte [r13 + r2], r1
        MOV  r1, byte [r8]+
        INC  r4
        JMP  [r14 + r1*4]

op_inc_zpx:
        ADD  r12, #6
        MOV  r2, byte [r8]+
        ADD  r2, r0
        ZXB  r2
        MOV  r1, byte [r13 + r2]
        INC  r1
        SXB  r9, r1
        MOV  byte [r13 + r2], r1
        MOV  r1, byte [r8]+
        INC  r4
        JMP  [r14 + r1*4]

op_inc_abs:
        ADD  r12, #6
        MOV  r2, byte [r8 + 1]
        LSL  r2, #8
        OR   r2, byte [r8]
        ADD  r8, #2
        MOV  r1, byte [r13 + r2]
        INC  r1
        SXB  r9, r1
        CMP  r2, #RAM_TOP
        BHS  io_write
        MOV  byte [r13 + r2], r1
        MOV  r1, byte [r8]+
        INC  r4
        JMP  [r14 + r1*4]

op_inc_abx:
        ADD  r12, #7
        MOV  r2, byte [r8 + 1]
        LSL  r2, #8
        OR   r2, byte [r8]
        ADD  r8, #2
        ADD  r2, r0
        ZXH  r2
        MOV  r1, byte [r13 + r2]
        INC  r1
        SXB  r9, r1
        CMP  r2, #RAM_TOP
        BHS  io_write
        MOV  byte [r13 + r2], r1
        MOV  r1, byte [r8]+
        INC  r4
        JMP  [r14 + r1*4]

; ---- DEC on memory -----------------------------------------------------------

op_dec_zp:
        ADD  r12, #5
        MOV  r2, byte [r8]+
        MOV  r1, byte [r13 + r2]
        DEC  r1
        SXB  r9, r1
        MOV  byte [r13 + r2], r1
        MOV  r1, byte [r8]+
        INC  r4
        JMP  [r14 + r1*4]

op_dec_zpx:
        ADD  r12, #6
        MOV  r2, byte [r8]+
        ADD  r2, r0
        ZXB  r2
        MOV  r1, byte [r13 + r2]
        DEC  r1
        SXB  r9, r1
        MOV  byte [r13 + r2], r1
        MOV  r1, byte [r8]+
        INC  r4
        JMP  [r14 + r1*4]

op_dec_abs:
        ADD  r12, #6
        MOV  r2, byte [r8 + 1]
        LSL  r2, #8
        OR   r2, byte [r8]
        ADD  r8, #2
        MOV  r1, byte [r13 + r2]
        DEC  r1
        SXB  r9, r1
        CMP  r2, #RAM_TOP
        BHS  io_write
        MOV  byte [r13 + r2], r1
        MOV  r1, byte [r8]+
        INC  r4
        JMP  [r14 + r1*4]

op_dec_abx:
        ADD  r12, #7
        MOV  r2, byte [r8 + 1]
        LSL  r2, #8
        OR   r2, byte [r8]
        ADD  r8, #2
        ADD  r2, r0
        ZXH  r2
        MOV  r1, byte [r13 + r2]
        DEC  r1
        SXB  r9, r1
        CMP  r2, #RAM_TOP
        BHS  io_write
        MOV  byte [r13 + r2], r1
        MOV  r1, byte [r8]+
        INC  r4
        JMP  [r14 + r1*4]
