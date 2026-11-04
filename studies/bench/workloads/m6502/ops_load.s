; m6502's loads, stores and transfers: LDA, LDX, LDY, STA, STX, STY, and
; TAX, TAY, TXA, TYA, TSX, TXS. Registers and conventions are in emu.s.
;
; The addressing modes are written out in each handler, as a fast
; emulator has them; they compute the 6502 address in r2 and read [r13 +
; r2]:
;
;   zp      MOV  r2, byte [r8]+
;   zp,X    the same, + X, wrapped in the zero page (ZXB)
;   abs     MOV  r2, byte [r8 + 1] / LSL r2, #8 / OR r2, byte [r8] / ADD r8, #2
;   abs,X   the same, + X, wrapped at 64 KB (ZXH); a read adds the page
;           crossing to the cycles: bit 8 of the low byte + X
;   (zp,X)  the pointer at zp + X, both bytes in the zero page
;   (zp),Y  the pointer at zp, + Y; a read adds the page crossing
;
; Loads set N and Z with SXB r9. Stores to the zero page are always RAM;
; the others go to io_a, io_x or io_y (emu.s) from RAM_TOP up.

RAM_TOP = 0xC000

        .section .text.m6502_load

; ---- LDA ---------------------------------------------------------------------

op_lda_imm:
        ADD  r12, #2
        MOV  r6, byte [r8]+
        SXB  r9, r6
        MOV  r1, byte [r8]+
        INC  r4
        JMP  [r14 + r1*4]

op_lda_zp:
        ADD  r12, #3
        MOV  r2, byte [r8]+
        MOV  r6, byte [r13 + r2]
        SXB  r9, r6
        MOV  r1, byte [r8]+
        INC  r4
        JMP  [r14 + r1*4]

op_lda_zpx:
        ADD  r12, #4
        MOV  r2, byte [r8]+
        ADD  r2, r0
        ZXB  r2
        MOV  r6, byte [r13 + r2]
        SXB  r9, r6
        MOV  r1, byte [r8]+
        INC  r4
        JMP  [r14 + r1*4]

op_lda_abs:
        ADD  r12, #4
        MOV  r2, byte [r8 + 1]
        LSL  r2, #8
        OR   r2, byte [r8]
        ADD  r8, #2
        MOV  r6, byte [r13 + r2]
        SXB  r9, r6
        MOV  r1, byte [r8]+
        INC  r4
        JMP  [r14 + r1*4]

op_lda_abx:
        ADD  r12, #4
        MOV  r2, byte [r8 + 1]
        LSL  r2, #8
        MOV  r3, byte [r8]
        ADD  r8, #2
        ADD  r3, r0             ; the low byte + X: bit 8 is a page crossed
        ADD  r2, r3
        ZXH  r2
        LSR  r3, #8
        ADD  r12, r3
        MOV  r6, byte [r13 + r2]
        SXB  r9, r6
        MOV  r1, byte [r8]+
        INC  r4
        JMP  [r14 + r1*4]

op_lda_aby:
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
        MOV  r6, byte [r13 + r2]
        SXB  r9, r6
        MOV  r1, byte [r8]+
        INC  r4
        JMP  [r14 + r1*4]

op_lda_izx:
        ADD  r12, #6
        MOV  r3, byte [r8]+
        ADD  r3, r0
        ZXB  r3                 ; the pointer's address, in the zero page
        MOV  r2, byte [r13 + r3]
        INC  r3
        ZXB  r3                 ; its high byte wraps in the zero page too
        MOV  r3, byte [r13 + r3]
        LSL  r3, #8
        OR   r2, r3
        MOV  r6, byte [r13 + r2]
        SXB  r9, r6
        MOV  r1, byte [r8]+
        INC  r4
        JMP  [r14 + r1*4]

op_lda_izy:
        ADD  r12, #5
        MOV  r3, byte [r8]+
        MOV  r2, byte [r13 + r3] ; the pointer's low byte
        INC  r3
        ZXB  r3
        MOV  r3, byte [r13 + r3] ; and its high byte
        LSL  r3, #8
        ADD  r2, r5             ; the low byte + Y: bit 8 is a page crossed
        ADD  r3, r2
        LSR  r2, #8
        ADD  r12, r2
        ZXH  r2, r3
        MOV  r6, byte [r13 + r2]
        SXB  r9, r6
        MOV  r1, byte [r8]+
        INC  r4
        JMP  [r14 + r1*4]

; ---- LDX ---------------------------------------------------------------------

op_ldx_imm:
        ADD  r12, #2
        MOV  r0, byte [r8]+
        SXB  r9, r0
        MOV  r1, byte [r8]+
        INC  r4
        JMP  [r14 + r1*4]

op_ldx_zp:
        ADD  r12, #3
        MOV  r2, byte [r8]+
        MOV  r0, byte [r13 + r2]
        SXB  r9, r0
        MOV  r1, byte [r8]+
        INC  r4
        JMP  [r14 + r1*4]

op_ldx_zpy:
        ADD  r12, #4
        MOV  r2, byte [r8]+
        ADD  r2, r5
        ZXB  r2
        MOV  r0, byte [r13 + r2]
        SXB  r9, r0
        MOV  r1, byte [r8]+
        INC  r4
        JMP  [r14 + r1*4]

op_ldx_abs:
        ADD  r12, #4
        MOV  r2, byte [r8 + 1]
        LSL  r2, #8
        OR   r2, byte [r8]
        ADD  r8, #2
        MOV  r0, byte [r13 + r2]
        SXB  r9, r0
        MOV  r1, byte [r8]+
        INC  r4
        JMP  [r14 + r1*4]

op_ldx_aby:
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
        MOV  r0, byte [r13 + r2]
        SXB  r9, r0
        MOV  r1, byte [r8]+
        INC  r4
        JMP  [r14 + r1*4]

; ---- LDY ---------------------------------------------------------------------

op_ldy_imm:
        ADD  r12, #2
        MOV  r5, byte [r8]+
        SXB  r9, r5
        MOV  r1, byte [r8]+
        INC  r4
        JMP  [r14 + r1*4]

op_ldy_zp:
        ADD  r12, #3
        MOV  r2, byte [r8]+
        MOV  r5, byte [r13 + r2]
        SXB  r9, r5
        MOV  r1, byte [r8]+
        INC  r4
        JMP  [r14 + r1*4]

op_ldy_zpx:
        ADD  r12, #4
        MOV  r2, byte [r8]+
        ADD  r2, r0
        ZXB  r2
        MOV  r5, byte [r13 + r2]
        SXB  r9, r5
        MOV  r1, byte [r8]+
        INC  r4
        JMP  [r14 + r1*4]

op_ldy_abs:
        ADD  r12, #4
        MOV  r2, byte [r8 + 1]
        LSL  r2, #8
        OR   r2, byte [r8]
        ADD  r8, #2
        MOV  r5, byte [r13 + r2]
        SXB  r9, r5
        MOV  r1, byte [r8]+
        INC  r4
        JMP  [r14 + r1*4]

op_ldy_abx:
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
        MOV  r5, byte [r13 + r2]
        SXB  r9, r5
        MOV  r1, byte [r8]+
        INC  r4
        JMP  [r14 + r1*4]

; ---- STA ---------------------------------------------------------------------

op_sta_zp:
        ADD  r12, #3
        MOV  r2, byte [r8]+
        MOV  byte [r13 + r2], r6
        MOV  r1, byte [r8]+
        INC  r4
        JMP  [r14 + r1*4]

op_sta_zpx:
        ADD  r12, #4
        MOV  r2, byte [r8]+
        ADD  r2, r0
        ZXB  r2
        MOV  byte [r13 + r2], r6
        MOV  r1, byte [r8]+
        INC  r4
        JMP  [r14 + r1*4]

op_sta_abs:
        ADD  r12, #4
        MOV  r2, byte [r8 + 1]
        LSL  r2, #8
        OR   r2, byte [r8]
        ADD  r8, #2
        CMP  r2, #RAM_TOP
        BHS  io_a
        MOV  byte [r13 + r2], r6
        MOV  r1, byte [r8]+
        INC  r4
        JMP  [r14 + r1*4]

op_sta_abx:
        ADD  r12, #5
        MOV  r2, byte [r8 + 1]
        LSL  r2, #8
        OR   r2, byte [r8]
        ADD  r8, #2
        ADD  r2, r0
        ZXH  r2
        CMP  r2, #RAM_TOP
        BHS  io_a
        MOV  byte [r13 + r2], r6
        MOV  r1, byte [r8]+
        INC  r4
        JMP  [r14 + r1*4]

op_sta_aby:
        ADD  r12, #5
        MOV  r2, byte [r8 + 1]
        LSL  r2, #8
        OR   r2, byte [r8]
        ADD  r8, #2
        ADD  r2, r5
        ZXH  r2
        CMP  r2, #RAM_TOP
        BHS  io_a
        MOV  byte [r13 + r2], r6
        MOV  r1, byte [r8]+
        INC  r4
        JMP  [r14 + r1*4]

op_sta_izx:
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
        CMP  r2, #RAM_TOP
        BHS  io_a
        MOV  byte [r13 + r2], r6
        MOV  r1, byte [r8]+
        INC  r4
        JMP  [r14 + r1*4]

op_sta_izy:
        ADD  r12, #6
        MOV  r3, byte [r8]+
        MOV  r2, byte [r13 + r3]
        INC  r3
        ZXB  r3
        MOV  r3, byte [r13 + r3]
        LSL  r3, #8
        ADD  r2, r5
        ADD  r2, r3
        ZXH  r2
        CMP  r2, #RAM_TOP
        BHS  io_a
        MOV  byte [r13 + r2], r6
        MOV  r1, byte [r8]+
        INC  r4
        JMP  [r14 + r1*4]

; ---- STX and STY -------------------------------------------------------------

op_stx_zp:
        ADD  r12, #3
        MOV  r2, byte [r8]+
        MOV  byte [r13 + r2], r0
        MOV  r1, byte [r8]+
        INC  r4
        JMP  [r14 + r1*4]

op_stx_zpy:
        ADD  r12, #4
        MOV  r2, byte [r8]+
        ADD  r2, r5
        ZXB  r2
        MOV  byte [r13 + r2], r0
        MOV  r1, byte [r8]+
        INC  r4
        JMP  [r14 + r1*4]

op_stx_abs:
        ADD  r12, #4
        MOV  r2, byte [r8 + 1]
        LSL  r2, #8
        OR   r2, byte [r8]
        ADD  r8, #2
        CMP  r2, #RAM_TOP
        BHS  io_x
        MOV  byte [r13 + r2], r0
        MOV  r1, byte [r8]+
        INC  r4
        JMP  [r14 + r1*4]

op_sty_zp:
        ADD  r12, #3
        MOV  r2, byte [r8]+
        MOV  byte [r13 + r2], r5
        MOV  r1, byte [r8]+
        INC  r4
        JMP  [r14 + r1*4]

op_sty_zpx:
        ADD  r12, #4
        MOV  r2, byte [r8]+
        ADD  r2, r0
        ZXB  r2
        MOV  byte [r13 + r2], r5
        MOV  r1, byte [r8]+
        INC  r4
        JMP  [r14 + r1*4]

op_sty_abs:
        ADD  r12, #4
        MOV  r2, byte [r8 + 1]
        LSL  r2, #8
        OR   r2, byte [r8]
        ADD  r8, #2
        CMP  r2, #RAM_TOP
        BHS  io_y
        MOV  byte [r13 + r2], r5
        MOV  r1, byte [r8]+
        INC  r4
        JMP  [r14 + r1*4]

; ---- transfers ---------------------------------------------------------------

op_tax: ADD  r12, #2
        MOV  r0, r6
        SXB  r9, r0
        MOV  r1, byte [r8]+
        INC  r4
        JMP  [r14 + r1*4]

op_tay: ADD  r12, #2
        MOV  r5, r6
        SXB  r9, r5
        MOV  r1, byte [r8]+
        INC  r4
        JMP  [r14 + r1*4]

op_txa: ADD  r12, #2
        MOV  r6, r0
        SXB  r9, r6
        MOV  r1, byte [r8]+
        INC  r4
        JMP  [r14 + r1*4]

op_tya: ADD  r12, #2
        MOV  r6, r5
        SXB  r9, r6
        MOV  r1, byte [r8]+
        INC  r4
        JMP  [r14 + r1*4]

op_tsx: ADD  r12, #2
        ZXB  r0, r7             ; S without page 1's $100
        SXB  r9, r0
        MOV  r1, byte [r8]+
        INC  r4
        JMP  [r14 + r1*4]

op_txs: ADD  r12, #2            ; sets no flags
        MOV  r7, r0
        OR   r7, #0x100
        MOV  r1, byte [r8]+
        INC  r4
        JMP  [r14 + r1*4]
