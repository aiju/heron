; The bobs' kernels with the block instructions (the blk variant): COPY
; (RFC 0041, 2.1: r3 words from r2 up to r1 up, both ending past them)
; for the restores and saves a row at a time, and for a sprite row's
; opaque run when it's long enough to pay for COPY's set-up. Each COPY
; follows MOV rX, #-1; CLZ rX, rX, which clears the condition latch the
; microcode tests (studies/mini_gfx/README.md).
;
;   Blt: d 0, s 4, w 8, h 12 (16 bytes)

        .global _draw_spans_blk, _restore_blk, _save_blk, _unsave_blk

        .equ COPYMIN, 3         ; opaque runs this long or longer go to COPY

; draw_spans_blk(list, n): as draw_spans_asm (draw.s)
        .section .text._draw_spans_blk
_draw_spans_blk:
        SAVE r8-r14
        MOVS r9, r2
        BLE  .done
        MOV  r8, r1
        MOV  r10, [_bob_pitch]
        LSL  r10, #2
.bob:   MOV  r11, [r8]
        MOV  r2, [r8 + 4]
        MOV  r12, [r8 + 12]
        ADD  r8, #16
.row:   MOV  r1, byte [r2]
        ADD  r1, r11
        MOV  r4, byte [r2 + 2]
        MOV  r5, byte [r2 + 3]
        MOVS r3, byte [r2 + 1]
        LEA  r2, [r2 + 4]
        BEQ  .o
.l:     MOV  r0, [r1]
        AND  r0, [r2]+
        OR   r0, [r2]+
        MOV  [r1]+, r0
        DBNZ r3, .l
.o:     CMP  r4, #COPYMIN
        BHS  .copy
        TST  r4, r4
        BEQ  .r
.ol:    MOV  r0, [r2]+
        MOV  [r1]+, r0
        DBNZ r4, .ol
        BRA  .r
.copy:  MOV  r3, r4
        MOV  r0, #-1
        CLZ  r0, r0
        .half 0x02FD            ; COPY
.r:     TST  r5, r5
        BEQ  .next
.rl:    MOV  r0, [r1]
        AND  r0, [r2]+
        OR   r0, [r2]+
        MOV  [r1]+, r0
        DBNZ r5, .rl
.next:  ADD  r11, r10
        DEC  r12
        BNE  .row
        DEC  r9
        BNE  .bob
.done:  RESTORE r8-r14
        RET

; restore_blk(list, n): a COPY a row
        .section .text._restore_blk
_restore_blk:
        SAVE r8-r14
        MOVS r9, r2
        BLE  .done
        MOV  r8, r1
        MOV  r10, [_bob_pitch]
        LSL  r10, #2
.bob:   MOV  r1, [r8]
        MOV  r2, [r8 + 4]
        MOV  r3, [r8 + 8]       ; r3: words a row, for every COPY
        MOV  r12, [r8 + 12]
        ADD  r8, #16
        MOV  r13, r3
        LSL  r13, #2
        NEG  r13
        ADD  r13, r10
.row:   MOV  r0, #-1
        CLZ  r0, r0
        .half 0x02FD            ; COPY
        ADD  r1, r13
        ADD  r2, r13
        DBNZ r12, .row
        DEC  r9
        BNE  .bob
.done:  RESTORE r8-r14
        RET

; save_blk(list, n): the screen's rows at d packed into s
        .section .text._save_blk
_save_blk:
        SAVE r8-r14
        MOVS r9, r2
        BLE  .done
        MOV  r8, r1
        MOV  r10, [_bob_pitch]
        LSL  r10, #2
.bob:   MOV  r2, [r8]
        MOV  r1, [r8 + 4]
        MOV  r3, [r8 + 8]
        MOV  r12, [r8 + 12]
        ADD  r8, #16
        MOV  r13, r3
        LSL  r13, #2
        NEG  r13
        ADD  r13, r10
.row:   MOV  r0, #-1
        CLZ  r0, r0
        .half 0x02FD            ; COPY
        ADD  r2, r13
        DBNZ r12, .row
        DEC  r9
        BNE  .bob
.done:  RESTORE r8-r14
        RET

; unsave_blk(list, n): the saves back, the last first
        .section .text._unsave_blk
_unsave_blk:
        SAVE r8-r14
        MOVS r9, r2
        BLE  .done
        MOV  r8, r2
        LSL  r8, #4
        ADD  r8, r1
        MOV  r10, [_bob_pitch]
        LSL  r10, #2
.bob:   SUB  r8, #16
        MOV  r1, [r8]
        MOV  r2, [r8 + 4]
        MOV  r3, [r8 + 8]
        MOV  r12, [r8 + 12]
        MOV  r13, r3
        LSL  r13, #2
        NEG  r13
        ADD  r13, r10
.row:   MOV  r0, #-1
        CLZ  r0, r0
        .half 0x02FD            ; COPY
        ADD  r1, r13
        DBNZ r12, .row
        DEC  r9
        BNE  .bob
.done:  RESTORE r8-r14
        RET
