; m6502's control flow, stack and flags: the branches, JMP, JSR, RTS, BRK,
; RTI, PHA, PLA, PHP, PLP, the flag instructions and NOP. Registers and
; conventions are in emu.s.
;
; The PC is a host address (r8 = r13 | PC), so a jump to a 6502 address
; is MOV r8, address / OR r8, r13, and the 6502's PC is ZXH of r8.
;
; S is kept as $100 + S, the address of the stack's next free byte, so a
; push is a store to [r13 + r7] and a decrement. The stack wraps around in
; page 1 as the 6502's does: a push ORs $100 back in after the decrement,
; and a pull takes the low byte after the increment and ORs it back.

        .section .text.m6502_flow

; ---- branches ----------------------------------------------------------------

; A branch not taken costs two cycles and skips its offset; a taken one
; goes to taken, three cycles and a fourth when it lands on another page.
op_bpl: TST  r9, r9
        BPL  taken
        ADD  r12, #2
        ADD  r8, #1
        MOV  r1, byte [r8]+
        INC  r4
        JMP  [r14 + r1*4]

op_bmi: TST  r9, r9
        BMI  taken
        ADD  r12, #2
        ADD  r8, #1
        MOV  r1, byte [r8]+
        INC  r4
        JMP  [r14 + r1*4]

op_bne: ZXB  r3, r9             ; Z is a zero low byte
        BNE  taken
        ADD  r12, #2
        ADD  r8, #1
        MOV  r1, byte [r8]+
        INC  r4
        JMP  [r14 + r1*4]

op_beq: ZXB  r3, r9
        BEQ  taken
        ADD  r12, #2
        ADD  r8, #1
        MOV  r1, byte [r8]+
        INC  r4
        JMP  [r14 + r1*4]

op_bcc: TST  r10, r10
        BEQ  taken
        ADD  r12, #2
        ADD  r8, #1
        MOV  r1, byte [r8]+
        INC  r4
        JMP  [r14 + r1*4]

op_bcs: TST  r10, r10
        BNE  taken
        ADD  r12, #2
        ADD  r8, #1
        MOV  r1, byte [r8]+
        INC  r4
        JMP  [r14 + r1*4]

op_bvc: SXB  r3, r11            ; V is bit 7
        BPL  taken
        ADD  r12, #2
        ADD  r8, #1
        MOV  r1, byte [r8]+
        INC  r4
        JMP  [r14 + r1*4]

op_bvs: SXB  r3, r11
        BMI  taken
        ADD  r12, #2
        ADD  r8, #1
        MOV  r1, byte [r8]+
        INC  r4
        JMP  [r14 + r1*4]

taken:  MOV  r1, byte [r8]+     ; the offset
        SXB  r1
        MOV  r2, r8             ; the next instruction's address...
        ADD  r8, r1
        XOR  r2, r8
        LSR  r2, #8             ; ...and the target's: on the same page?
        BNE  .page
        ADD  r12, #3
        MOV  r1, byte [r8]+
        INC  r4
        JMP  [r14 + r1*4]
.page:  ADD  r12, #4            ; another page, and maybe past either end
        ZXH  r8                 ; of memory: wrap the target to 64 KB
        OR   r8, r13
        MOV  r1, byte [r8]+
        INC  r4
        JMP  [r14 + r1*4]

; ---- jumps and subroutines ---------------------------------------------------

op_jmp_abs:
        ADD  r12, #3
        MOV  r2, byte [r8 + 1]
        LSL  r2, #8
        OR   r2, byte [r8]
        MOV  r8, r2
        OR   r8, r13
        MOV  r1, byte [r8]+
        INC  r4
        JMP  [r14 + r1*4]

; JMP (vector): the NMOS 6502 takes the vector's high byte from the same
; page as its low byte, so JMP ($12FF) reads $12FF and $1200.
op_jmp_ind:
        ADD  r12, #5
        MOV  r2, byte [r8 + 1]
        LSL  r2, #8
        OR   r2, byte [r8]      ; the vector's address
        MOV  r1, byte [r13 + r2] ; the target's low byte
        INC  r3, r2
        ZXB  r3                 ; the next byte's offset in the page...
        LSR  r2, #8
        LSL  r2, #8
        OR   r3, r2             ; ...in the same page
        MOV  r3, byte [r13 + r3] ; the target's high byte
        LSL  r3, #8
        OR   r1, r3
        MOV  r8, r1
        OR   r8, r13
        MOV  r1, byte [r8]+
        INC  r4
        JMP  [r14 + r1*4]

; JSR pushes the address of its own last byte, high byte first.
op_jsr: ADD  r12, #6
        MOV  r2, byte [r8 + 1]
        LSL  r2, #8
        OR   r2, byte [r8]      ; the subroutine
        ADD  r8, #1
        ZXH  r3, r8             ; the return address minus one
        MOV  r1, r3
        LSR  r1, #8
        MOV  byte [r13 + r7], r1
        DEC  r7
        OR   r7, #0x100
        MOV  byte [r13 + r7], r3
        DEC  r7
        OR   r7, #0x100
        MOV  r8, r2
        OR   r8, r13
        MOV  r1, byte [r8]+
        INC  r4
        JMP  [r14 + r1*4]

op_rts: ADD  r12, #6
        INC  r7
        ZXB  r7
        OR   r7, #0x100
        MOV  r2, byte [r13 + r7] ; the low byte
        INC  r7
        ZXB  r7
        OR   r7, #0x100
        MOV  r3, byte [r13 + r7] ; the high byte
        LSL  r3, #8
        OR   r2, r3
        INC  r2                 ; one past JSR's last byte
        ZXH  r2
        MOV  r8, r2
        OR   r8, r13
        MOV  r1, byte [r8]+
        INC  r4
        JMP  [r14 + r1*4]

; BRK pushes the address two past itself (it skips a signature byte) and
; P with B set, sets I, and goes through the vector at $FFFE.
op_brk: ADD  r12, #7
        ADD  r8, #1
        ZXH  r3, r8
        MOV  r1, r3
        LSR  r1, #8
        MOV  byte [r13 + r7], r1
        DEC  r7
        OR   r7, #0x100
        MOV  byte [r13 + r7], r3
        DEC  r7
        OR   r7, #0x100
        MOV  r2, r7
        BSR  get_p
        MOV  r7, r2
        MOV  byte [r13 + r7], r1
        DEC  r7
        OR   r7, #0x100
        MOV  r1, #0x34          ; I set
        MOV  byte [flag_bi], r1
        MOV  r3, #0xFFFE
        MOV  r8, byte [r13 + r3 + 1]
        LSL  r8, #8
        OR   r8, byte [r13 + r3]
        OR   r8, r13
        MOV  r1, byte [r8]+
        INC  r4
        JMP  [r14 + r1*4]

; RTI pulls P, then the PC as it was pushed.
op_rti: ADD  r12, #6
        INC  r7
        ZXB  r7
        OR   r7, #0x100
        MOV  r1, byte [r13 + r7]
        MOV  r2, r7
        BSR  set_p
        MOV  r7, r2
        INC  r7
        ZXB  r7
        OR   r7, #0x100
        MOV  r2, byte [r13 + r7]
        INC  r7
        ZXB  r7
        OR   r7, #0x100
        MOV  r3, byte [r13 + r7]
        LSL  r3, #8
        OR   r2, r3
        MOV  r8, r2
        OR   r8, r13
        MOV  r1, byte [r8]+
        INC  r4
        JMP  [r14 + r1*4]

; ---- the stack ---------------------------------------------------------------

op_pha: ADD  r12, #3
        MOV  byte [r13 + r7], r6
        DEC  r7
        OR   r7, #0x100
        MOV  r1, byte [r8]+
        INC  r4
        JMP  [r14 + r1*4]

op_pla: ADD  r12, #4
        INC  r7
        ZXB  r7
        OR   r7, #0x100
        MOV  r6, byte [r13 + r7]
        SXB  r9, r6
        MOV  r1, byte [r8]+
        INC  r4
        JMP  [r14 + r1*4]

op_php: ADD  r12, #3
        MOV  r2, r7
        BSR  get_p
        MOV  r7, r2
        MOV  byte [r13 + r7], r1
        DEC  r7
        OR   r7, #0x100
        MOV  r1, byte [r8]+
        INC  r4
        JMP  [r14 + r1*4]

op_plp: ADD  r12, #4
        INC  r7
        ZXB  r7
        OR   r7, #0x100
        MOV  r1, byte [r13 + r7]
        MOV  r2, r7
        BSR  set_p
        MOV  r7, r2
        MOV  r1, byte [r8]+
        INC  r4
        JMP  [r14 + r1*4]

; ---- flags -------------------------------------------------------------------

op_clc: ADD  r12, #2
        MOV  r10, #0
        MOV  r1, byte [r8]+
        INC  r4
        JMP  [r14 + r1*4]

op_sec: ADD  r12, #2
        MOV  r10, #1
        MOV  r1, byte [r8]+
        INC  r4
        JMP  [r14 + r1*4]

op_clv: ADD  r12, #2
        MOV  r11, #0
        MOV  r1, byte [r8]+
        INC  r4
        JMP  [r14 + r1*4]

op_cld: ADD  r12, #2
        CLR  byte [flag_d]
        MOV  r1, byte [r8]+
        INC  r4
        JMP  [r14 + r1*4]

op_sed: ADD  r12, #2
        MOV  r1, #8
        MOV  byte [flag_d], r1
        MOV  r1, byte [r8]+
        INC  r4
        JMP  [r14 + r1*4]

op_cli: ADD  r12, #2
        MOV  r1, #0x30
        MOV  byte [flag_bi], r1
        MOV  r1, byte [r8]+
        INC  r4
        JMP  [r14 + r1*4]

op_sei: ADD  r12, #2
        MOV  r1, #0x34
        MOV  byte [flag_bi], r1
        MOV  r1, byte [r8]+
        INC  r4
        JMP  [r14 + r1*4]

op_nop: ADD  r12, #2
        MOV  r1, byte [r8]+
        INC  r4
        JMP  [r14 + r1*4]
