; Fills and copies with SAVE and RESTORE: the stack pointer borrowed as the
; address (interrupts off meanwhile), because the mini's microcode moves a
; register a cycle for them, with none of LDM's and STM's check of the
; range first (studies/mini/ucode.py). An experiment: how close plain
; draft 2 code comes to the block instructions FILL and COPY.
;
;   void sch_fill_save(unsigned *p, unsigned v, int n)
;       n words of v from p: the odd ones a word at a time, then 12 a SAVE
;   void sch_copy_rs(unsigned *d, const unsigned *s, int n)
;       n words from s to d: the odd ones a word at a time, then 12 a
;       RESTORE and a SAVE

        .global _sch_fill_save, _sch_copy_rs

        .section .text._sch_fill_save
_sch_fill_save:
        SAVE r7-r14
        MOV  r9, #0
.f12:   CMP  r3, #12            ; r9: groups of 12, r3: the rest
        BLO  .f1
        SUB  r3, #12
        INC  r9
        BRA  .f12
.f1:    TST  r3, r3
        BEQ  .fg
.f1l:   MOV  [r1]+, r2
        DBNZ r3, .f1l
.fg:    TST  r9, r9
        BEQ  .fd
        MOV  r12, r9
        MOV  r13, r9
        LSL  r13, #4
        LSL  r9, #2
        SUB  r13, r9            ; 12 words a group
        LSL  r13, #2
        ADD  r13, r1            ; r13: the end
        MOV  r0, r2
        MOV  r1, r2
        MOV  r3, r2
        MOV  r4, r2
        MOV  r5, r2
        MOV  r6, r2
        MOV  r7, r2
        MOV  r8, r2
        MOV  r9, r2
        MOV  r10, r2
        MOV  r11, r2
        MFSR r14, ccr
        DI
        MOV  [_sch_sp], sp
        MOV  sp, r13
.fl:    SAVE r0-r11             ; 12 words below sp, sp down by 48
        DBNZ r12, .fl
        MOV  sp, [_sch_sp]
        MTSR ccr, r14           ; interrupts as they were
.fd:    RESTORE r7-r14
        RET

        .section .text._sch_copy_rs
_sch_copy_rs:
        SAVE r7-r14
        MOV  r9, #0
.c12:   CMP  r3, #12
        BLO  .c1
        SUB  r3, #12
        INC  r9
        BRA  .c12
.c1:    TST  r3, r3
        BEQ  .cg
.c1l:   MOV  r0, [r2]+
        MOV  [r1]+, r0
        DBNZ r3, .c1l
.cg:    TST  r9, r9
        BEQ  .cd
        MOV  r12, r9            ; r12: groups
        MOV  r13, r2            ; r13: the source
        LEA  r14, [r1 + 48]     ; r14: the destination's next group's end
        MFSR r0, ccr
        MOV  [_sch_ccr], r0
        DI
        MOV  [_sch_sp], sp
.cl:    MOV  sp, r13
        RESTORE r0-r11          ; 12 words from sp up, sp up by 48
        MOV  r13, sp
        MOV  sp, r14
        SAVE r0-r11             ; 12 words below sp
        ADD  r14, #48
        DBNZ r12, .cl
        MOV  sp, [_sch_sp]
        MOV  r0, [_sch_ccr]
        MTSR ccr, r0
.cd:    RESTORE r7-r14
        RET

        .bss
        .align 4
_sch_sp:
        .space 4
_sch_ccr:
        .space 4
