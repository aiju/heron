; The bobs' kernels in draft 2 assembly (sprite.h has what each does and
; sprite.c the same in C). Each takes a list of blits and its length:
;
;   Blt: d 0, s 4, w 8, h 12 (16 bytes)
;
; and the buffers' pitch in words from _bob_pitch. A pre-shifted row is
; read with [r2]+ and written with [r1]+, so the loops are one-parcel
; instructions: a masked word is four (load, AND, OR, store).

        .global _draw_compiled, _restore_compiled, _draw_shifted_asm, _draw_spans_asm
        .global _restore_asm, _save_asm, _unsave_asm

; draw_compiled(list, n): each blit's code (jit.c), called with r1 its
; first word. The code clobbers r0-r6 and r8-r12; r13 and r14 are ours.
        .section .text._draw_compiled
_draw_compiled:
        SAVE r7-r14
        MOVS r14, r2
        BLE  .done
        MOV  r13, r1
.l:     MOV  r1, [r13]
        MOV  r0, [r13 + 4]
        ADD  r13, #16
        CALL r0
        DBNZ r14, .l
.done:  RESTORE r7-r14
        RET

; restore_compiled(list, n, off): each blit's restore code (jit.c), called
; with r1 its first word and r2 that plus off bytes (the background's)
        .section .text._restore_compiled
_restore_compiled:
        SAVE r7-r14
        MOVS r14, r2
        BLE  .done
        MOV  r13, r1
        MOV  r12, r3            ; the code leaves r12 alone
.l:     MOV  r1, [r13]
        MOV  r2, r1
        ADD  r2, r12
        MOV  r0, [r13 + 4]
        ADD  r13, #16
        CALL r0
        DBNZ r14, .l
.done:  RESTORE r7-r14
        RET

; draw_shifted_asm(list, n): every row w pairs (~mask, image)
        .section .text._draw_shifted_asm
_draw_shifted_asm:
        SAVE r8-r14
        MOVS r9, r2
        BLE  .done
        MOV  r8, r1
        MOV  r10, [_bob_pitch]
        LSL  r10, #2            ; r10: the pitch in bytes
.bob:   MOV  r1, [r8]           ; r1: the destination
        MOV  r2, [r8 + 4]       ; r2: the rows
        MOV  r11, [r8 + 8]      ; r11: words a row
        MOV  r12, [r8 + 12]     ; r12: rows
        ADD  r8, #16
        MOV  r13, r11
        LSL  r13, #2
        NEG  r13
        ADD  r13, r10           ; r13: from a row's end to the next one's start
.row:   MOV  r3, r11
.w:     MOV  r0, [r1]
        AND  r0, [r2]+
        OR   r0, [r2]+
        MOV  [r1]+, r0
        DBNZ r3, .w
        ADD  r1, r13
        DBNZ r12, .row
        DEC  r9
        BNE  .bob
.done:  RESTORE r8-r14
        RET

; draw_spans_asm(list, n): each row a header (its first word's offset in
; bytes, then the counts of masked, opaque and masked words, a byte each),
; then its words: pairs for the masked ones, images for the opaque ones
        .section .text._draw_spans_asm
_draw_spans_asm:
        SAVE r8-r14
        MOVS r9, r2
        BLE  .done
        MOV  r8, r1
        MOV  r10, [_bob_pitch]
        LSL  r10, #2            ; r10: the pitch in bytes
.bob:   MOV  r11, [r8]          ; r11: the row's first word
        MOV  r2, [r8 + 4]       ; r2: the rows
        MOV  r12, [r8 + 12]     ; r12: rows
        ADD  r8, #16
.row:   MOV  r1, byte [r2]
        ADD  r1, r11            ; r1: the row's first word drawn
        MOV  r4, byte [r2 + 2]  ; r4: opaque words
        MOV  r5, byte [r2 + 3]  ; r5: masked words after them
        MOVS r3, byte [r2 + 1]  ; r3: masked words before them
        LEA  r2, [r2 + 4]
        BEQ  .o
.l:     MOV  r0, [r1]
        AND  r0, [r2]+
        OR   r0, [r2]+
        MOV  [r1]+, r0
        DBNZ r3, .l
.o:     TST  r4, r4
        BEQ  .r
.ol:    MOV  r0, [r2]+
        MOV  [r1]+, r0
        DBNZ r4, .ol
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

; restore_asm(list, n): w x h words from s (the background) to d, both
; the pitch apart
        .section .text._restore_asm
_restore_asm:
        SAVE r8-r14
        MOVS r9, r2
        BLE  .done
        MOV  r8, r1
        MOV  r10, [_bob_pitch]
        LSL  r10, #2
.bob:   MOV  r1, [r8]
        MOV  r2, [r8 + 4]
        MOV  r11, [r8 + 8]
        MOV  r12, [r8 + 12]
        ADD  r8, #16
        MOV  r13, r11
        LSL  r13, #2
        NEG  r13
        ADD  r13, r10
.row:   MOV  r3, r11
.w:     MOV  r0, [r2]+
        MOV  [r1]+, r0
        DBNZ r3, .w
        ADD  r1, r13
        ADD  r2, r13
        DBNZ r12, .row
        DEC  r9
        BNE  .bob
.done:  RESTORE r8-r14
        RET

; save_asm(list, n): the screen's w x h words at d packed into s
        .section .text._save_asm
_save_asm:
        SAVE r8-r14
        MOVS r9, r2
        BLE  .done
        MOV  r8, r1
        MOV  r10, [_bob_pitch]
        LSL  r10, #2
.bob:   MOV  r2, [r8]           ; the screen
        MOV  r1, [r8 + 4]       ; the save area
        MOV  r11, [r8 + 8]
        MOV  r12, [r8 + 12]
        ADD  r8, #16
        MOV  r13, r11
        LSL  r13, #2
        NEG  r13
        ADD  r13, r10
.row:   MOV  r3, r11
.w:     MOV  r0, [r2]+
        MOV  [r1]+, r0
        DBNZ r3, .w
        ADD  r2, r13
        DBNZ r12, .row
        DEC  r9
        BNE  .bob
.done:  RESTORE r8-r14
        RET

; unsave_asm(list, n): the saves back, the last first
        .section .text._unsave_asm
_unsave_asm:
        SAVE r8-r14
        MOVS r9, r2
        BLE  .done
        MOV  r8, r2
        LSL  r8, #4
        ADD  r8, r1             ; r8: past the last blit
        MOV  r10, [_bob_pitch]
        LSL  r10, #2
.bob:   SUB  r8, #16
        MOV  r1, [r8]           ; the screen
        MOV  r2, [r8 + 4]       ; the save area
        MOV  r11, [r8 + 8]
        MOV  r12, [r8 + 12]
        MOV  r13, r11
        LSL  r13, #2
        NEG  r13
        ADD  r13, r10
.row:   MOV  r3, r11
.w:     MOV  r0, [r2]+
        MOV  [r1]+, r0
        DBNZ r3, .w
        ADD  r1, r13
        DBNZ r12, .row
        DEC  r9
        BNE  .bob
.done:  RESTORE r8-r14
        RET
