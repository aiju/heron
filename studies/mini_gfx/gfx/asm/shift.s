; shift_rows_asm(job): the shifted copy in draft 2 (blit.c has the job
; and the C kernel). COPY with two terms, lo shifted right by a and hi
; left by b, the second's mask m1; anything else goes to the C kernel.
;
; Draft 2's shifts by a register take a cycle a bit, and by a constant at
; most 10 (a rotation at most 4), so the loops' shifts are constants,
; patched in before the rows. A linear format (a + b = 32) rotates each
; source word once and merges it with the one before under m1 (MERGE);
; the planes (a + b = 8 or 16) shift each word both ways.
;
; ShiftJob: d 0, s 4, dpitch 8, spitch 12, h 16, n 20, lmask 24, rmask 28,
; rop 32, nterm 36, terms from 40 (src 0, sh 4, m 8; 12 bytes each). Three or
; four terms go to shift4.s.

        .global _shift_rows_asm
        .section .text._shift_rows_asm
_shift_rows_asm:
        MOVS r0, [r1 + 32]      ; COPY only
        BNE  .c
        MOV  r0, [r1 + 36]
        CMP  r0, #2
        BEQ  .two
        CMP  r0, #4             ; three or four terms: shift4.s
        BHI  .c
        JMP  _shift_multi
.two:
        MOVS r0, [r1 + 44]      ; lo shifted right
        BPL  .c
        MOVS r0, [r1 + 52]      ; then hi
        BNE  .go
.c:     JMP  _shift_rows_c

.go:    SAVE r7-r14
        MOV  r2, [r1 + 44]
        NEG  r2                 ; r2: a
        MOV  r3, [r1 + 56]      ; r3: b
        MOV  r4, r2
        ADD  r4, r3
        CMP  r4, #32
        BEQ  .lin

; ---- the planes: patch LSR #a and LSL #b
        MOV  r4, r2
        AND  r4, #1
        OR   r4, #0xC4          ; LSR: C4 | a & 1
        MOV  r5, r2
        LSR  r5, #1
        LSL  r5, #8
        OR   r4, r5             ; with a >> 1 in the register byte
        LEA  r5, [pc + .pa1]
        MOV  r6, r4
        OR   r6, #0xE000        ; r14
        MOV  half [r5], r6
        LEA  r5, [pc + .pa2]
        MOV  r6, r4
        OR   r6, #0xD000        ; r13
        MOV  half [r5], r6
        LEA  r5, [pc + .pa3]
        MOV  half [r5], r6
        MOV  r4, r3
        AND  r4, #1
        OR   r4, #0xC0          ; LSL: C0 | b & 1
        MOV  r5, r3
        LSR  r5, #1
        LSL  r5, #8
        OR   r4, r5
        LEA  r5, [pc + .pb1]
        MOV  r6, r4
        OR   r6, #0x1000        ; r1
        MOV  half [r5], r6
        LEA  r5, [pc + .pb2]
        MOV  half [r5], r6
        LEA  r5, [pc + .pb3]
        MOV  r6, r4
        OR   r6, #0xD000        ; r13
        MOV  half [r5], r6
        BSR  .setup
        BRA  .prow              ; a jump: the prefetch queue holds no old copy

.prow:  MOV  r2, r8
        MOV  r3, r9
        MOV  r14, [r3]+
.pa1:   LSR  r14, #1            ; r14: L(s0) = s0 >> a
        MOV  r13, [r3]+
        MOV  r1, r13
.pb1:   LSL  r1, #1             ; H(s1)
        MERGE r14, r1, r0       ; the first word
.pa2:   LSR  r13, #1            ; L(s1)
        MOV  r1, [r2]
        XOR  r14, r1
        AND  r14, r5
        XOR  r1, r14            ; under lmask
        MOV  [r2]+, r1
        MOV  r14, r13
        MOVS r7, r4
        BEQ  .pnext
        DEC  r7
        BEQ  .plast
.pmid:  MOV  r13, [r3]+
        MOV  r1, r13
.pb2:   LSL  r1, #1
        MERGE r14, r1, r0
        MOV  [r2]+, r14
.pa3:   LSR  r13, #1
        MOV  r14, r13
        DBNZ r7, .pmid
.plast: MOV  r13, [r3]+
.pb3:   LSL  r13, #1
        MERGE r14, r13, r0
        MOV  r1, [r2]
        XOR  r14, r1
        AND  r14, r6
        XOR  r1, r14            ; under rmask
        MOV  [r2], r1
.pnext: ADD  r8, r10
        ADD  r9, r11
        DEC  r12
        BNE  .prow
        RESTORE r7-r14
        RET

; ---- linear: patch ROR #a
.lin:   MOV  r4, r2
        AND  r4, #1
        OR   r4, #0xCC          ; ROR: CC | a & 1
        MOV  r5, r2
        LSR  r5, #1
        LSL  r5, #8
        OR   r4, r5
        LEA  r5, [pc + .ra1]
        MOV  r6, r4
        OR   r6, #0xE000        ; r14
        MOV  half [r5], r6
        MOV  r6, r4
        OR   r6, #0xD000        ; r13
        LEA  r5, [pc + .ra2]
        MOV  half [r5], r6
        LEA  r5, [pc + .ra3]
        MOV  half [r5], r6
        LEA  r5, [pc + .ra4]
        MOV  half [r5], r6
        BSR  .setup
        BRA  .rrow

.rrow:  MOV  r2, r8
        MOV  r3, r9
        MOV  r14, [r3]+
.ra1:   ROR  r14, #1            ; the words rotated: lo's bits low, hi's high
        MOV  r13, [r3]+
.ra2:   ROR  r13, #1
        MOV  r1, r14
        MERGE r1, r13, r0       ; the first word
        MOV  r14, [r2]
        XOR  r1, r14
        AND  r1, r5
        XOR  r14, r1
        MOV  [r2]+, r14
        MOV  r14, r13
        MOVS r7, r4
        BEQ  .rnext
        DEC  r7
        BEQ  .rlast
.rmid:  MOV  r13, [r3]+
.ra3:   ROR  r13, #1
        MOV  r1, r14
        MERGE r1, r13, r0
        MOV  [r2]+, r1
        MOV  r14, r13
        DBNZ r7, .rmid
.rlast: MOV  r13, [r3]+
.ra4:   ROR  r13, #1
        MOV  r1, r14
        MERGE r1, r13, r0
        MOV  r14, [r2]
        XOR  r1, r14
        AND  r1, r6
        XOR  r14, r1
        MOV  [r2], r14
.rnext: ADD  r8, r10
        ADD  r9, r11
        DEC  r12
        BNE  .rrow
        RESTORE r7-r14
        RET

; the rows' registers from the job (r1); returns through r7, which the
; caller has saved
.setup: MOV  r8, [r1]           ; r8: the destination row
        MOV  r9, [r1 + 4]       ; r9: the source row
        MOV  r10, [r1 + 8]
        LSL  r10, #2            ; r10, r11: the pitches in bytes
        MOV  r11, [r1 + 12]
        LSL  r11, #2
        MOV  r12, [r1 + 16]     ; r12: rows
        MOV  r4, [r1 + 20]      ; r4: n
        MOV  r5, [r1 + 24]      ; r5: lmask
        MOV  r6, [r1 + 28]      ; r6: rmask
        MOV  r0, [r1 + 60]      ; r0: hi's mask
        RET
