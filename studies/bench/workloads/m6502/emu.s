; m6502: a 6502 emulator for draft 2, by hand, the way a hobbyist runs old
; 8-bit programs on a newer machine. This file has the machine around the
; CPU (loading the ROM, the I/O page, the end of the run and its report),
; the dispatch table and the status register; the instructions are in
; ops_load.s, ops_alu.s, ops_rmw.s and ops_flow.s.
;
; The emulated machine (program.a65 and cpu6502.py describe it too): 64
; KB, RAM below $C000, the I/O page at $C000 (a byte written to OUT is the
; program's output, any write to DONE ends the run), and ROM from $D000
; up, its top holding the program and the vectors; writes to ROM are
; ignored. Reads see memory everywhere, so only stores look at the
; address.
;
; Every documented NMOS opcode is emulated, with its addressing modes,
; decimal mode, the indirect JMP's page bug and the stack wrapping in
; page 1; an undocumented opcode jams the CPU (op_jam), and the run ends
; there. The cycle count is the datasheet's: each handler adds its
; opcode's cycles, a read across a page with abs,X, abs,Y or (zp),Y one
; more, a taken branch one more and one again across a page.
;
; Registers, while the 6502 runs:
;   r6   A        r0   X        r5   Y          (each 0-255)
;   r7   S, as $100 + S: the address of the next free byte of the stack
;   r8   PC, as a host address: the 6502's memory starts at a multiple
;        of 64 KB, so the PC is r8's low half and r8 = r13 | PC
;   r9   N and Z, kept lazily: N is bit 31, and Z is set when the low
;        byte is zero. An instruction that sets N and Z from a result
;        sets r9 to the result sign-extended (SXB r9, rX), one
;        instruction; BEQ and BNE test it with ZXB, BMI and BPL with TST.
;        N and Z are in different bits so that BIT and PLP can set any
;        combination of the two.
;   r10  C, 0 or 1, as ADC adds it
;   r11  V, in bit 7: ADC's overflow is (A ^ sum) & (M ^ sum), whose
;        bit 7 is V, so V costs two XORs and an AND; nothing masks it
;   r12  the cycle count
;   r4   the number of instructions emulated
;   r13  the 6502's memory: byte a is [r13 + a]
;   r14  the dispatch table
;   r1-r3 scratch: the opcode, operands, the effective address
; D and I are rarely read, so they live in memory: flag_d is D's bit (0
; or 8), and flag_bi is I's bit with B and the unused bit (P's other bits
; as PHP pushes them). There are no calls while the 6502 runs, since r7
; is S; the few subroutines here (get_p, set_p) are called with S moved
; to r2 and back.
;
; Every handler starts by adding its cycles and ends with the dispatch,
; three instructions: the next opcode, the count, and the jump through
; the table:
;
;       MOV  r1, byte [r8]+
;       INC  r4
;       JMP  [r14 + r1*4]

        .global main, io_a, io_x, io_y, io_write, get_p, set_p, flag_d, flag_bi
        .far mem6502, rom

RAM_TOP = 0xC000                ; stores from here up are I/O or ROM
OUT     = 0xC000                ; the program's output, a byte at a time
DONE    = 0xC001                ; a write ends the run
OUTMAX  = 512                   ; output kept, at most
HASH_END = 0x0600               ; the memory hashed: zero page, stack, results

        .section .farbss.m6502_mem
        .align 65536            ; so that the PC is the host address's low half
mem6502: .space 65536

        .section .bss.m6502
flag_d:  .space 1               ; D: 0 or 8
flag_bi: .space 1               ; I (0 or 4) | B | the unused bit: $30 or $34
jammed:  .space 1               ; 1 if an undocumented opcode stopped the run
        .align 4
outlen:  .space 4
outbuf:  .space OUTMAX
res_pc:  .space 4               ; the state at the end, for the report
res_a:   .space 4
res_x:   .space 4
res_y:   .space 4
res_p:   .space 4
res_s:   .space 4
res_cyc: .space 4
res_ins: .space 4
res_mem: .space 4
res_jam: .space 4

        .section .text.m6502

; ---- start-up ----------------------------------------------------------------

main:   SAVE r7-r14
        MOV  r13, #mem6502
        ; the ROM image (workload.py: a multiple of 32 bytes) at the top of
        ; the 6502's memory, 32 bytes at a time
        MOV  r1, #rom
        MOV  r3, [rom_len]
        MOV  r2, r13
        ADD  r2, #0x10000
        SUB  r2, r3
        LSR  r3, #5
.copy:  LDM  r1, r4-r11
        STM  r2, r4-r11
        ADD  r1, #32
        ADD  r2, #32
        DBNZ r3, .copy
        ; the CPU as reset leaves it: S = $FD, I set, seven cycles gone
        MOV  r1, #0x34
        MOV  byte [flag_bi], r1
        CLR  byte [flag_d]
        MOV  r6, #0
        MOV  r0, #0
        MOV  r5, #0
        MOV  r7, #0x1FD
        MOV  r9, #1             ; neither N nor Z
        MOV  r10, #0
        MOV  r11, #0
        MOV  r12, #7
        MOV  r4, #0
        MOV  r14, #optable
        MOV  r3, #0xFFFC        ; the reset vector
        MOV  r8, byte [r13 + r3 + 1]
        LSL  r8, #8
        OR   r8, byte [r13 + r3]
        OR   r8, r13
        MOV  r1, byte [r8]+     ; and the first instruction
        JMP  [r14 + r1*4]

; ---- the I/O page ------------------------------------------------------------

; A store at RAM_TOP or above: the store handlers come here with the
; address in r2, from io_a, io_x and io_y with the register stored, and
; the read-modify-write ones with the value in r1.
io_a:   MOV  r1, r6
        BRA  io_write
io_x:   MOV  r1, r0
        BRA  io_write
io_y:   MOV  r1, r5
io_write:
        CMP  r2, #OUT
        BEQ  .out
        CMP  r2, #DONE
        BEQ  stop
        MOV  r1, byte [r8]+     ; anything else is ignored: ROM, or no device
        INC  r4
        JMP  [r14 + r1*4]
.out:   MOV  r3, [outlen]
        CMP  r3, #OUTMAX
        BHS  .full
        MOV  byte [outbuf + r3], r1
        INC  r3
        MOV  [outlen], r3
.full:  MOV  r1, byte [r8]+
        INC  r4
        JMP  [r14 + r1*4]

; ---- undocumented opcodes ----------------------------------------------------

; The CPU jams: the run ends with the PC at the opcode, which doesn't
; count as an instruction.
op_jam: SUB  r8, #1
        MOV  r1, #1
        MOV  byte [jammed], r1
        BRA  finish

; ---- the end of the run ------------------------------------------------------

stop:   INC  r4                 ; the store to DONE was an instruction too
finish: ZXH  r8                 ; the PC, as the 6502's address
        MOV  [res_pc], r8
        MOV  [res_a], r6
        MOV  [res_x], r0
        MOV  [res_y], r5
        ZXB  r7
        MOV  [res_s], r7
        BSR  get_p
        BIC  r1, #0x10          ; B exists only on the stack
        MOV  [res_p], r1
        MOV  [res_cyc], r12
        MOV  [res_ins], r4
        MOV  r1, byte [jammed]
        MOV  [res_jam], r1
        MOV  r1, #5381          ; a hash of the RAM the program keeps its results in
        MOV  r2, r13
        MOV  r3, #HASH_END
        CALL bench_hash
        MOV  [res_mem], r1
        ; the program's output, as it wrote it
        MOV  r8, #outbuf
        MOV  r9, [outlen]
        TST  r9, r9
        BEQ  .rep
.out:   MOV  r1, byte [r8]+
        CALL bench_putc
        DBNZ r9, .out
        ; then the CPU's state
.rep:   MOV  r8, #reports
        MOV  r9, #(reports_end - reports) / 8
.line:  MOV  r1, [r8]+
        MOV  r2, [r8]+
        MOV  r2, [r2]
        CALL bench_report
        DBNZ r9, .line
        RESTORE r7-r14
        RET

        .section .rodata.m6502_reports
        .align 4
reports:
        .word lab_pc, res_pc, lab_a, res_a, lab_x, res_x, lab_y, res_y
        .word lab_p, res_p, lab_s, res_s, lab_cyc, res_cyc, lab_ins, res_ins
        .word lab_mem, res_mem, lab_jam, res_jam
reports_end:
lab_pc:  .asciz "pc"
lab_a:   .asciz "a"
lab_x:   .asciz "x"
lab_y:   .asciz "y"
lab_p:   .asciz "p"
lab_s:   .asciz "s"
lab_cyc: .asciz "cycles"
lab_ins: .asciz "instructions"
lab_mem: .asciz "memory"
lab_jam: .asciz "jammed"

        .section .text.m6502_flags

; ---- the status register -----------------------------------------------------

; get_p: r1 = P as PHP pushes it (B and the unused bit set). Uses r3.
get_p:  MOV  r1, byte [flag_bi] ; B, the unused bit and I
        OR   r1, byte [flag_d]
        OR   r1, r10            ; C
        TST  r9, r9
        BPL  .n
        OR   r1, #0x80          ; N
.n:     ZXB  r3, r9
        BNE  .z
        OR   r1, #2             ; Z
.z:     MOV  r3, r11
        LSR  r3, #1
        AND  r3, #0x40
        OR   r1, r3             ; V
        RET

; set_p: P = r1, as PLP and RTI pull it (B isn't kept). Uses r3.
set_p:  MOV  r3, r1
        AND  r3, #8
        MOV  byte [flag_d], r3
        MOV  r3, r1
        AND  r3, #4
        OR   r3, #0x30
        MOV  byte [flag_bi], r3
        MOV  r10, r1
        AND  r10, #1
        MOV  r11, r1
        LSL  r11, #1            ; V into bit 7
        MOV  r9, r1
        LSL  r9, #24            ; N into bit 31, and a zero low byte: Z...
        MOV  r3, r1
        LSR  r3, #1
        AND  r3, #1
        XOR  r3, #1
        OR   r9, r3             ; ...unless Z is clear
        RET

; ---- the dispatch table ------------------------------------------------------

        .section .rodata.m6502_optable
        .align 4
optable:
        .word op_brk, op_ora_izx, op_jam, op_jam, op_jam, op_ora_zp, op_asl_zp, op_jam                 ; 00-07
        .word op_php, op_ora_imm, op_asl_a, op_jam, op_jam, op_ora_abs, op_asl_abs, op_jam             ; 08-0F
        .word op_bpl, op_ora_izy, op_jam, op_jam, op_jam, op_ora_zpx, op_asl_zpx, op_jam               ; 10-17
        .word op_clc, op_ora_aby, op_jam, op_jam, op_jam, op_ora_abx, op_asl_abx, op_jam               ; 18-1F
        .word op_jsr, op_and_izx, op_jam, op_jam, op_bit_zp, op_and_zp, op_rol_zp, op_jam              ; 20-27
        .word op_plp, op_and_imm, op_rol_a, op_jam, op_bit_abs, op_and_abs, op_rol_abs, op_jam         ; 28-2F
        .word op_bmi, op_and_izy, op_jam, op_jam, op_jam, op_and_zpx, op_rol_zpx, op_jam               ; 30-37
        .word op_sec, op_and_aby, op_jam, op_jam, op_jam, op_and_abx, op_rol_abx, op_jam               ; 38-3F
        .word op_rti, op_eor_izx, op_jam, op_jam, op_jam, op_eor_zp, op_lsr_zp, op_jam                 ; 40-47
        .word op_pha, op_eor_imm, op_lsr_a, op_jam, op_jmp_abs, op_eor_abs, op_lsr_abs, op_jam         ; 48-4F
        .word op_bvc, op_eor_izy, op_jam, op_jam, op_jam, op_eor_zpx, op_lsr_zpx, op_jam               ; 50-57
        .word op_cli, op_eor_aby, op_jam, op_jam, op_jam, op_eor_abx, op_lsr_abx, op_jam               ; 58-5F
        .word op_rts, op_adc_izx, op_jam, op_jam, op_jam, op_adc_zp, op_ror_zp, op_jam                 ; 60-67
        .word op_pla, op_adc_imm, op_ror_a, op_jam, op_jmp_ind, op_adc_abs, op_ror_abs, op_jam         ; 68-6F
        .word op_bvs, op_adc_izy, op_jam, op_jam, op_jam, op_adc_zpx, op_ror_zpx, op_jam               ; 70-77
        .word op_sei, op_adc_aby, op_jam, op_jam, op_jam, op_adc_abx, op_ror_abx, op_jam               ; 78-7F
        .word op_jam, op_sta_izx, op_jam, op_jam, op_sty_zp, op_sta_zp, op_stx_zp, op_jam              ; 80-87
        .word op_dey, op_jam, op_txa, op_jam, op_sty_abs, op_sta_abs, op_stx_abs, op_jam               ; 88-8F
        .word op_bcc, op_sta_izy, op_jam, op_jam, op_sty_zpx, op_sta_zpx, op_stx_zpy, op_jam           ; 90-97
        .word op_tya, op_sta_aby, op_txs, op_jam, op_jam, op_sta_abx, op_jam, op_jam                   ; 98-9F
        .word op_ldy_imm, op_lda_izx, op_ldx_imm, op_jam, op_ldy_zp, op_lda_zp, op_ldx_zp, op_jam      ; A0-A7
        .word op_tay, op_lda_imm, op_tax, op_jam, op_ldy_abs, op_lda_abs, op_ldx_abs, op_jam           ; A8-AF
        .word op_bcs, op_lda_izy, op_jam, op_jam, op_ldy_zpx, op_lda_zpx, op_ldx_zpy, op_jam           ; B0-B7
        .word op_clv, op_lda_aby, op_tsx, op_jam, op_ldy_abx, op_lda_abx, op_ldx_aby, op_jam           ; B8-BF
        .word op_cpy_imm, op_cmp_izx, op_jam, op_jam, op_cpy_zp, op_cmp_zp, op_dec_zp, op_jam          ; C0-C7
        .word op_iny, op_cmp_imm, op_dex, op_jam, op_cpy_abs, op_cmp_abs, op_dec_abs, op_jam           ; C8-CF
        .word op_bne, op_cmp_izy, op_jam, op_jam, op_jam, op_cmp_zpx, op_dec_zpx, op_jam               ; D0-D7
        .word op_cld, op_cmp_aby, op_jam, op_jam, op_jam, op_cmp_abx, op_dec_abx, op_jam               ; D8-DF
        .word op_cpx_imm, op_sbc_izx, op_jam, op_jam, op_cpx_zp, op_sbc_zp, op_inc_zp, op_jam          ; E0-E7
        .word op_inx, op_sbc_imm, op_nop, op_jam, op_cpx_abs, op_sbc_abs, op_inc_abs, op_jam           ; E8-EF
        .word op_beq, op_sbc_izy, op_jam, op_jam, op_jam, op_sbc_zpx, op_inc_zpx, op_jam               ; F0-F7
        .word op_sed, op_sbc_aby, op_jam, op_jam, op_jam, op_sbc_abx, op_inc_abx, op_jam               ; F8-FF
