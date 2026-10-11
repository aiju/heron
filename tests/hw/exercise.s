; Hardware exercise: runs every instruction class and stores results (and
; the flags after each operation) in memory, so comparing the chip-level
; simulator against the ISA simulator (registers, memory, fetch trace,
; cycle counts) checks every microcode sequence and data path.

        .org 0
        JMP  start
        .org 4
        RTI                     ; IRQ (unused here)
        .org 8
        JMP  trap

; trap handler: count traps, record the trapping PC, return
trap:   PUSH r1
        LD   r1, [traps]
        INC  r1
        ST   r1, [traps]
        LD   r1, [sp + 4]       ; saved PC (above saved flags)
        ST   r1, [trap_pc]
        POP  r1
        RTI

start:  LI   sp, #0xF000
        LI   r13, #results      ; r13 = result pointer
        LI   r12, #values
        MVI  r11, 0             ; outer index over value pairs

; ---- two-operand ALU ops on every pair of test values -------------------
.pair:  MOV  r1, r11
        SHL  r1
        ADD  r1, r12
        LD   r2, [r1]           ; a
        LD   r3, [r1 + 2]       ; b
        MTF  r0                 ; clear flags
        MOV  r4, r2
        ADD  r4, r3
        CALL save
        MOV  r4, r2
        ADC  r4, r3
        CALL save
        MOV  r4, r2
        SUB  r4, r3
        CALL save
        MOV  r4, r2
        SBC  r4, r3
        CALL save
        MOV  r4, r2
        AND  r4, r3
        CALL save
        MOV  r4, r2
        OR   r4, r3
        CALL save
        MOV  r4, r2
        XOR  r4, r3
        CALL save
        MOV  r4, r2
        BIC  r4, r3
        CALL save
        MOV  r4, r2
        CMP  r4, r3
        CALL save
        TST  r4, r3
        CALL save
        ; unary ops on a
        NOT  r4, r2
        CALL save
        NEG  r4, r2
        CALL save
        INC  r4, r2
        CALL save
        DEC  r4, r2
        CALL save
        SHL  r4, r2
        CALL save
        SHR  r4, r2
        CALL save
        ASR  r4, r2
        CALL save
        RLC  r4, r2
        CALL save
        RRC  r4, r2
        CALL save
        SWAB r4, r2
        CALL save
        SXT  r4, r2
        CALL save
        ZXT  r4, r2
        CALL save
        ; immediates
        MOV  r4, r2
        ADD  r4, #0x1234
        CALL save
        SUB  r4, #0x8001
        CALL save
        CMP  r4, #0x7FFF
        CALL save
        ADDI r4, -3
        CALL save
        CMPI r4, 100
        CALL save
        MVI  r4, -128
        CALL save
        ADDI r11, 1
        CMPI r11, 7
        BNE  .pair

; ---- every condition code against a range of flag settings ---------------
        MVI  r5, 0              ; flags value 0..15 (V C Z N)
.flags: MVI  r6, 0              ; taken bitmask, short branches
        MVI  r7, 0              ; taken bitmask, long jumps
        MTF  r5
        BEQ  .t0
        BRA  .n0
.t0:    OR   r6, #0x0001
.n0:    MTF  r5
        BNE  .t1
        BRA  .n1
.t1:    OR   r6, #0x0002
.n1:    MTF  r5
        BHS  .t2
        BRA  .n2
.t2:    OR   r6, #0x0004
.n2:    MTF  r5
        BLO  .t3
        BRA  .n3
.t3:    OR   r6, #0x0008
.n3:    MTF  r5
        BMI  .t4
        BRA  .n4
.t4:    OR   r6, #0x0010
.n4:    MTF  r5
        BPL  .t5
        BRA  .n5
.t5:    OR   r6, #0x0020
.n5:    MTF  r5
        BVS  .t6
        BRA  .n6
.t6:    OR   r6, #0x0040
.n6:    MTF  r5
        BVC  .t7
        BRA  .n7
.t7:    OR   r6, #0x0080
.n7:    MTF  r5
        BHI  .t8
        BRA  .n8
.t8:    OR   r6, #0x0100
.n8:    MTF  r5
        BLS  .t9
        BRA  .n9
.t9:    OR   r6, #0x0200
.n9:    MTF  r5
        BGE  .ta
        BRA  .na
.ta:    OR   r6, #0x0400
.na:    MTF  r5
        BLT  .tb
        BRA  .nb
.tb:    OR   r6, #0x0800
.nb:    MTF  r5
        BGT  .tc
        BRA  .nc
.tc:    OR   r6, #0x1000
.nc:    MTF  r5
        BLE  .td
        BRA  .nd
.td:    OR   r6, #0x2000
.nd:    MTF  r5
        JEQ  .u0
        JMP  .m0
.u0:    OR   r7, #0x0001
.m0:    MTF  r5
        JLT  .u1
        JMP  .m1
.u1:    OR   r7, #0x0002
.m1:    MTF  r5
        JHI  .u2
        JMP  .m2
.u2:    OR   r7, #0x0004
.m2:    ST   r6, [r13]
        ST   r7, [r13 + 2]
        ADDI r13, 4
        ADDI r5, 1
        CMPI r5, 16
        JNE  .flags

; ---- memory: words, bytes, short and long forms, odd addresses ----------
        LI   r1, #buf
        LI   r2, #0xA55A
        ST   r2, [r1]
        ST   r2, [r1 + 30]
        ST   r2, [r1 + 100]
        MVI  r3, 0x12
        STB  r3, [r1 + 1]
        STB  r3, [r1 + 4]
        STB  r3, [r1 + 15]
        STB  r3, [r1 + 201]
        LDB  r4, [r1 + 1]
        CALL save
        LDB  r4, [r1]
        CALL save
        LD   r4, [r1 + 30]
        CALL save
        LD   r4, [r1 + 100]
        CALL save
        LDB  r4, [r1 + 201]
        CALL save
        LD   r4, [r1 + 1]       ; odd word address: bit 0 ignored
        CALL save
        LEA  r4, [r1 + 0x1234]
        CALL save
        LD   r4, [buf + 4]
        CALL save

; ---- calls and jumps ------------------------------------------------------
        CALL sub1
        LI   r1, #sub2
        CALL r1
        LI   r1, #.after
        JMP  r1
        HALT                    ; skipped
.after: PUSH r2
        PUSH sp
        POP  r4
        CALL save
        POP  r4
        CALL save
        MFF  r4
        CALL save

; ---- traps: SWI, reserved opcodes and functions -------------------------
        SWI
        .word 0xB000            ; op B (reserved)
        .word 0xF123            ; op F (reserved)
        .word 0x100F            ; ALU fn F
        .word 0x200C            ; unary fn C
        .word 0x000E            ; system fn E
        .word 0xA015, 0x0001    ; long memory fn 5 (traps after one word; 0001 = NOP)
        LD   r4, [traps]
        CALL save
        LD   r4, [trap_pc]
        CALL save

; ---- I/O ---------------------------------------------------------------
        LI   r1, #msg
.out:   LDB  r2, [r1]
        BEQ  .done
        STB  r2, [0xFF00]
        ADDI r1, 1
        BRA  .out
.done:  LD   r4, [0xFF00]       ; no input: FFFF
        CALL save
        LD   r4, [0xFF02]
        CALL save
        HALT

sub1:   MVI  r4, 77
        CALL save
        RET
sub2:   MVI  r4, 88
        CALL save
        RET

; save r4 and the current flags at r13
save:   PUSH r1
        MFF  r1
        ST   r4, [r13]
        ST   r1, [r13 + 2]
        ADDI r13, 4
        POP  r1
        RET


        .org $
values: .word 0, 1, 0x7FFF, 0x8000, 0xFFFF, 0x1234, 0x00FF, 0xFF00
traps:  .word 0
trap_pc: .word 0
msg:    .asciz "exercise done\n"
        .align 2
buf:    .space 256
results:
