; fill_rows_asm(job): the fill kernel in draft 2 (gfx.h has the job, and
; gfx.c the C kernel): h rows of words from p, pitch words apart; in each
; the first word under lmask, n whole words, then one under rmask (none
; if rmask is 0). COPY stores the whole words eight a loop; XOR reads,
; changes and writes them. Patterns, OR and AND go to the C kernel.
;
; FillJob: p 0, pitch 4, h 8, lmask 12, n 16, rmask 20, pat 24, rop 28,
; pats 32, row0 36

        .global _fill_rows_asm
        .section .text._fill_rows_asm
_fill_rows_asm:
        MOVS r0, [r1 + 32]      ; a pattern: C
        BNE  .c
        MOVS r0, [r1 + 28]      ; the rop
        BEQ  .copy
        CMP  r0, #1
        BEQ  .xor
.c:     JMP  _fill_rows_c

.copy:  SAVE r8-r14
        MOV  r2, [r1]           ; r2: the row
        MOVS r4, [r1 + 8]       ; r4: rows left
        BLE  .done
        MOV  r8, [r1 + 24]      ; r8: the pattern
        MOV  r5, [r1 + 12]      ; r5: lmask
        MOV  r6, [r1 + 20]      ; r6: rmask
        MOV  r3, [r1 + 16]      ; r3: whole words
        MOV  r12, [r1 + 4]
        LSL  r12, #2            ; r12: the pitch in bytes
        MOV  r9, r8
        AND  r9, r5             ; r9: pat & lmask
        MOV  r10, r8
        AND  r10, r6            ; r10: pat & rmask
        MOV  r11, r3
        LSR  r11, #3            ; r11: groups of 8
        AND  r3, #7             ; r3: and single words
.crow:  MOV  r13, r2
        MOV  r0, [r13]
        BIC  r0, r5
        OR   r0, r9
        MOV  [r13]+, r0
        MOVS r14, r11
        BEQ  .crem
.c8:    MOV  [r13]+, r8
        MOV  [r13]+, r8
        MOV  [r13]+, r8
        MOV  [r13]+, r8
        MOV  [r13]+, r8
        MOV  [r13]+, r8
        MOV  [r13]+, r8
        MOV  [r13]+, r8
        DBNZ r14, .c8
.crem:  MOVS r14, r3
        BEQ  .clast
.c1:    MOV  [r13]+, r8
        DBNZ r14, .c1
.clast: TST  r6, r6
        BEQ  .cnext
        MOV  r0, [r13]
        BIC  r0, r6
        OR   r0, r10
        MOV  [r13], r0
.cnext: ADD  r2, r12
        DEC  r4
        BNE  .crow
.done:  RESTORE r8-r14
        RET

.xor:   SAVE r8-r14
        MOV  r2, [r1]
        MOVS r4, [r1 + 8]
        BLE  .xdone
        MOV  r8, [r1 + 24]
        MOV  r9, [r1 + 12]
        AND  r9, r8             ; r9: pat & lmask
        MOV  r6, [r1 + 20]      ; r6: rmask
        MOV  r10, r6
        AND  r10, r8            ; r10: pat & rmask
        MOV  r3, [r1 + 16]
        MOV  r12, [r1 + 4]
        LSL  r12, #2
.xrow:  MOV  r13, r2
        MOV  r0, [r13]
        XOR  r0, r9
        MOV  [r13]+, r0
        MOVS r14, r3
        BEQ  .xlast
.x1:    MOV  r0, [r13]
        XOR  r0, r8
        MOV  [r13]+, r0
        DBNZ r14, .x1
.xlast: TST  r6, r6
        BEQ  .xnext
        MOV  r0, [r13]
        XOR  r0, r10
        MOV  [r13], r0
.xnext: ADD  r2, r12
        DEC  r4
        BNE  .xrow
.xdone: RESTORE r8-r14
        RET
